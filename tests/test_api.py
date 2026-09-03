"""Route-level tests: auth, uid-scoping, idempotency, rate limits, validation."""

import asyncio
import inspect

from tests.conftest import auth


def test_route_handlers_are_sync_so_blocking_io_is_threadpooled():
    """Regression guard for the event-loop-blocking bug: every /api handler
    must be a plain def (Starlette runs it in a worker thread)."""
    import app.main as main
    offenders = [
        r.name for r in main.app.routes
        if getattr(r, "path", "").startswith("/api")
        and asyncio.iscoroutinefunction(getattr(r, "endpoint", None))
    ]
    assert offenders == [], f"async handlers doing blocking I/O: {offenders}"


def test_current_uid_dependency_is_sync():
    from app.firebase import current_uid
    assert not inspect.iscoroutinefunction(current_uid)


def _new_case(c, uid="userA", **over):
    body = {"title": "Zomato withheld incentive", "issue_type": "incentive_dispute",
            "platform": "Zomato", "amount_claimed_inr": 2400,
            "incident_date": "2026-03-10"}
    body.update(over)
    r = c.post("/api/cases", json=body, headers=auth(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- auth ---------------------------------------------------------------
def test_no_token_is_401(app_client):
    assert app_client.get("/api/cases").status_code == 401


def test_bad_token_is_401(app_client):
    r = app_client.get("/api/cases", headers={"Authorization": "Bearer bad:x"})
    assert r.status_code == 401


def test_missing_bearer_prefix_is_401(app_client):
    r = app_client.get("/api/cases", headers={"Authorization": "Token abc"})
    assert r.status_code == 401


# ---- uid scoping ------------------------------------------------------
def test_users_cannot_see_each_others_cases(app_client):
    cid = _new_case(app_client, "userA")
    # userB sees nothing and cannot fetch userA's case
    assert app_client.get("/api/cases", headers=auth("userB")).json()["cases"] == []
    assert app_client.get(f"/api/cases/{cid}", headers=auth("userB")).status_code == 404
    assert app_client.get(f"/api/cases/{cid}", headers=auth("userA")).status_code == 200


def test_get_unknown_case_is_404(app_client):
    assert app_client.get("/api/cases/nope", headers=auth()).status_code == 404


# ---- idempotency ----------------------------------------------------
def test_create_case_idempotent_with_key(app_client):
    h = {**auth("userA"), "Idempotency-Key": "k-1"}
    body = {"title": "same case", "issue_type": "other", "platform": "X"}
    a = app_client.post("/api/cases", json=body, headers=h).json()
    b = app_client.post("/api/cases", json=body, headers=h).json()
    assert a["id"] == b["id"]
    assert len(app_client.get("/api/cases", headers=auth("userA")).json()["cases"]) == 1


def test_create_case_without_key_duplicates(app_client):
    body = {"title": "dup case", "issue_type": "other", "platform": "X"}
    app_client.post("/api/cases", json=body, headers=auth("userA"))
    app_client.post("/api/cases", json=body, headers=auth("userA"))
    assert len(app_client.get("/api/cases", headers=auth("userA")).json()["cases"]) == 2


# ---- validation ---------------------------------------------------
def test_bad_incident_date_is_422(app_client):
    r = app_client.post("/api/cases", json={"title": "bad date", "issue_type": "other",
                                            "platform": "X", "incident_date": "31-02-2026"},
                        headers=auth())
    assert r.status_code == 422


def test_deadlines_bad_date_is_422_not_500(app_client):
    cid = _new_case(app_client)
    r = app_client.post(f"/api/cases/{cid}/deadlines",
                        json={"notice_sent": "garbage"}, headers=auth())
    assert r.status_code == 422


def test_deadlines_happy_path(app_client):
    cid = _new_case(app_client)
    r = app_client.post(f"/api/cases/{cid}/deadlines",
                        json={"notice_sent": "2026-09-01", "notice_days": 15},
                        headers=auth())
    assert r.status_code == 200
    kinds = {d["kind"] for d in r.json()["deadlines"]}
    assert {"consumer_limitation", "wage_limitation", "notice_period"} <= kinds


# ---- chat --------------------------------------------------------
def test_chat_roundtrip_and_persist(app_client):
    cid = _new_case(app_client)
    r = app_client.post(f"/api/cases/{cid}/chat", json={"message": "hi"}, headers=auth())
    assert r.status_code == 200
    assert r.json()["reply"] == "MODEL DRAFT BODY"
    msgs = app_client.get(f"/api/cases/{cid}", headers=auth()).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "model"]


def test_chat_degraded_when_model_down(app_client):
    from app.gemini import GeminiResult
    app_client.gemini.result = GeminiResult(ok=False, text="fallback text", model="t")
    cid = _new_case(app_client)
    r = app_client.post(f"/api/cases/{cid}/chat", json={"message": "hi"}, headers=auth())
    assert r.json()["degraded"] is True


def test_chat_turn_cap(app_client, fs):
    from datetime import datetime, timezone
    cid = _new_case(app_client)
    # seed 40 messages (MAX_TURNS_PER_CASE*2) straight into the store
    msgs = fs.collection("users").document("userA").collection("cases") \
             .document(cid).collection("messages")
    for i in range(40):
        msgs.document(f"m{i:03d}").set(
            {"role": "user", "text": "x", "ts": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    r = app_client.post(f"/api/cases/{cid}/chat", json={"message": "x"}, headers=auth())
    assert r.status_code == 409


# ---- rate limit ------------------------------------------------
def test_rate_limit_5min(app_client):
    cid = _new_case(app_client)
    codes = [app_client.post(f"/api/cases/{cid}/chat", json={"message": "x"},
                             headers=auth("rl")).status_code for _ in range(22)]
    assert 429 in codes
    assert codes.count(200) <= 20


# ---- monthly cost ceiling ------------------------------------
def test_monthly_ceiling_blocks_model_calls(app_client, fs, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr("app.config.MONTHLY_COST_CEILING_INR", 5.0)
    monkeypatch.setattr("app.limits.MONTHLY_COST_CEILING_INR", 5.0)
    mk = datetime.now(timezone.utc).strftime("%Y-%m")
    fs.collection("counters").document(f"cost-{mk}").set({"spent_inr": 99.0})
    cid = _new_case(app_client)
    r = app_client.post(f"/api/cases/{cid}/chat", json={"message": "x"}, headers=auth())
    assert r.status_code == 429
    # deterministic endpoints still work
    assert app_client.post(f"/api/cases/{cid}/deadlines", json={}, headers=auth()).status_code == 200


# ---- draft + readiness ---------------------------------------
def test_draft_flags_wrong_amount(app_client):
    from app.gemini import GeminiResult
    cid = _new_case(app_client, amount_claimed_inr=2400)
    app_client.gemini.result = GeminiResult(
        ok=True, model="t",
        text=("On 10/03/2026 the sum of Rs 999999 was withheld. Pay Rs 999999 within "
              "15 days of this notice, failing which I will approach the consumer forum. "
              "Yours faithfully, (Name)"))
    r = app_client.post(f"/api/cases/{cid}/draft",
                        json={"kind": "legal_notice", "sender_name": "A",
                              "sender_address": "addr", "recipient_name": "B",
                              "recipient_address": "addr2"}, headers=auth())
    rd = r.json()["readiness"]
    assert rd["ready"] is False
    assert any("amount" in m.lower() for m in rd["missing"])


# ---- export / delete ---------------------------------------
# ---- evidence locker / appeal record -----------------------
import base64


def _png(n=64):
    return base64.b64encode(b"\x89PNG\r\n" + b"\x00" * n).decode()


def _upload(client, cid, kind, extracted, uid="userA", **over):
    import app.main as main
    main.parse_json = lambda res, _e=extracted: dict(_e)   # script the extraction
    body = {"kind": kind, "filename": f"{kind}.png", "mime": "image/png",
            "data_b64": _png()}
    body.update(over)
    return client.post(f"/api/cases/{cid}/evidence", json=body, headers=auth(uid))


def test_evidence_chains_and_extracts(app_client):
    cid = _new_case(app_client)
    r1 = _upload(app_client, cid, "support_chat",
                 {"summary": "asked support for reactivation", "refs": ["TKT-11"]})
    assert r1.status_code == 201, r1.text
    r2 = _upload(app_client, cid, "payslip",
                 {"amount_inr": 5600, "period_days": 7, "summary": "weekly payout"})
    assert r2.json()["evidence"]["seq"] == 2
    assert r2.json()["chain_ok"] is True

    items = app_client.get(f"/api/cases/{cid}", headers=auth()).json()["evidence"]
    assert [e["seq"] for e in items] == [1, 2]
    assert items[1]["prev_hash"] == items[0]["chain_hash"]
    assert items[0]["extracted"]["refs"] == ["TKT-11"]
    assert "data_b64" not in items[0]          # blobs not shipped in the list


def test_deactivation_evidence_populates_date_and_idrc_deadline(app_client):
    r = app_client.post("/api/cases", json={"title": "blocked id", "issue_type":
                        "deactivation", "platform": "Uber"}, headers=auth())
    cid = r.json()["id"]
    _upload(app_client, cid, "deactivation_notice",
            {"observed_date": "2026-08-20", "reason": "low ratings"})
    got = app_client.get(f"/api/cases/{cid}", headers=auth()).json()
    assert got["case"]["incident_date"] == "2026-08-20"
    assert "idrc_appeal" in {d["kind"] for d in got["deadlines"]}


def test_appeal_record_manifest_verifies(app_client):
    cid = _new_case(app_client)
    _upload(app_client, cid, "payslip", {"amount_inr": 5000, "period_days": 7})
    _upload(app_client, cid, "earnings_screen", {"amount_inr": 5200, "period_days": 7})
    m = app_client.get(f"/api/cases/{cid}/appeal-record", headers=auth()).json()
    assert m["verification"]["ok"] is True
    assert len(m["entries"]) == 2
    assert m["head"] == m["entries"][-1]["chain_hash"]


def test_evidence_oversize_is_413(app_client):
    cid = _new_case(app_client)
    big = base64.b64encode(b"\x00" * 950_000).decode()
    r = app_client.post(f"/api/cases/{cid}/evidence",
                        json={"kind": "payslip", "filename": "big.png",
                              "mime": "image/png", "data_b64": big}, headers=auth())
    assert r.status_code == 413


def test_lost_wages_endpoint(app_client):
    r = app_client.post("/api/cases", json={"title": "deact", "issue_type":
                        "deactivation", "platform": "Zomato",
                        "incident_date": "2026-08-25"}, headers=auth())
    cid = r.json()["id"]
    _upload(app_client, cid, "earnings_screen", {"amount_inr": 7000, "period_days": 7})
    _upload(app_client, cid, "payslip", {"amount_inr": 6800, "period_days": 7})
    lw = app_client.get(f"/api/cases/{cid}/lost-wages", headers=auth()).json()["lost_wages"]
    assert lw["daily_rate_inr"] == round((7000 + 6800) / 14)
    assert lw["estimate_inr"] > 0


def test_evidence_is_uid_scoped(app_client):
    cid = _new_case(app_client, "userA")
    _upload(app_client, cid, "payslip", {"amount_inr": 100, "period_days": 1}, uid="userA")
    assert app_client.get(f"/api/cases/{cid}/appeal-record",
                          headers=auth("userB")).status_code == 404
    assert app_client.get(f"/api/cases/{cid}/lost-wages",
                          headers=auth("userB")).status_code == 404


def test_export_then_delete(app_client):
    cid = _new_case(app_client, "userX")
    exp = app_client.get("/api/export", headers=auth("userX")).json()
    assert exp["cases"][0]["case"]["id"] == cid
    assert app_client.delete("/api/account", headers=auth("userX")).json() == {"deleted": True}
    assert app_client.get("/api/cases", headers=auth("userX")).json()["cases"] == []
