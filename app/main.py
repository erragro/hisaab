"""
app/main.py
===========
Hisaab API + static frontend, one Cloud Run service.

Security posture:
- Firebase ID token verified on every /api route (app.firebase.current_uid).
- uid comes only from the token; request bodies never carry a uid.
- All Firestore access via app.repo, scoped to /users/{uid}/...
- Gemini key only via Secret Manager (app.config.get_secret).
- CORS locked to FRONTEND_ORIGIN (defence in depth only — the API and the
  frontend share an origin, so the real gate is the token check + rate limits).
- No stack traces / secrets / PII in responses (global handler + redact).

Route handlers are plain `def` (not `async def`): everything below them
(token verify, Firestore, the Gemini SDK) is blocking, so Starlette runs
them in a worker threadpool and the event loop is never stalled.
"""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import limits, repo, telemetry
from app.config import (
    EVIDENCE_MAX_BYTES,
    EVIDENCE_MAX_ITEMS,
    FRONTEND_ORIGIN,
    GEMINI_MODEL_CHAT,
    GEMINI_MODEL_UTILITY,
    MAX_TURNS_PER_CASE,
    PROJECT_ID,
    evidence_signing_key,
)
from app.core import evidence_chain
from app.core.deadlines import build_case_deadlines
from app.core.lostwages import estimate_lost_wages
from app.core.readiness import check_readiness
from app.core.redact import safe_error, uid_hash
from app.firebase import current_uid, db
from app.gemini import generate, parse_json
from app.logging_setup import configure_logging, log
from app.prompts import CHAT_SYSTEM, DRAFT_SYSTEM, EVIDENCE_SYSTEM, EXTRACT_SYSTEM
from app.ratelimit import check as rate_check
from app.schemas import CaseCreate, ChatIn, DraftIn, EvidenceIn, PartyIn

configure_logging()

# per-case lock: serialises chat turns for one case within this instance so
# two tabs can't interleave the history or clobber the auto-summary.
_case_locks: dict[str, threading.Lock] = {}
_case_locks_guard = threading.Lock()

# history sent to the model is bounded regardless of the turn cap
_HISTORY_MAX_MSGS = 30
_HISTORY_MAX_CHARS = 12_000


def _case_lock(key: str) -> threading.Lock:
    with _case_locks_guard:
        if len(_case_locks) > 5000:
            _case_locks.clear()  # crude cap; locks are cheap to recreate
        return _case_locks.setdefault(key, threading.Lock())


_EARNINGS_KINDS = {"earnings_screen", "payslip"}


def _earnings_samples(evidence: list[dict]) -> list[dict]:
    out = []
    for e in evidence or []:
        if e.get("kind") not in _EARNINGS_KINDS:
            continue
        ex = e.get("extracted") or {}
        amt, per = ex.get("amount_inr"), ex.get("period_days")
        if amt and per:
            out.append({"amount_inr": amt, "period_days": per, "source": e["kind"]})
    return out


def _lost_wages(case: dict, evidence: list[dict]) -> Optional[dict]:
    if case.get("issue_type") != "deactivation":
        return None
    raw = case.get("incident_date")
    try:
        d = date.fromisoformat(raw) if raw else None
    except ValueError:
        d = None
    with telemetry.measure("lost_wages"):
        lw = estimate_lost_wages(_earnings_samples(evidence), deactivated_on=d)
    return lw.to_dict() if lw else None


def _trim_history(history: list[dict]) -> list[dict]:
    out: list[dict] = []
    total = 0
    for m in reversed(history):
        t = m.get("text") or ""
        if out and (len(out) >= _HISTORY_MAX_MSGS or total + len(t) > _HISTORY_MAX_CHARS):
            break
        out.append(m)
        total += len(t)
    out.reverse()
    return out


def _idem_key(request: Request) -> str | None:
    k = request.headers.get("idempotency-key", "").strip()
    return k[:128] or None


@asynccontextmanager
async def lifespan(app_: FastAPI):
    configure_logging()
    otel = telemetry.init(app_)
    log.info("hisaab.boot", project=PROJECT_ID or "(none)",
             frontend_origin=FRONTEND_ORIGIN, telemetry=otel)
    yield


app = FastAPI(title="Hisaab", docs_url=None, redoc_url=None, lifespan=lifespan)
telemetry.init(app)  # also instrument at import for TestClient / uvicorn --workers

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


@app.middleware("http")
async def trace(request: Request, call_next):
    request.state.trace_id = uuid.uuid4().hex[:12]
    with telemetry.inflight():
        resp = await call_next(request)
    resp.headers["X-Trace-Id"] = request.state.trace_id
    return resp


@app.exception_handler(Exception)
async def _safe_errors(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    log.error("unhandled", trace_id=getattr(request.state, "trace_id", "-"),
              error=safe_error(exc))
    return JSONResponse({"error": "internal error"}, status_code=500)


# ---- health ---------------------------------------------------------------
# NB: Cloud Run's front end swallows GET /healthz (returns its own 404 before
# the request reaches the container), so the liveness route is /livez.
@app.get("/livez")
@app.get("/healthz")
async def livez():
    return {"ok": True}


_readyz_cache = {"at": 0.0, "body": None, "code": 503}
_READYZ_TTL_S = 10.0


@app.get("/readyz")
def readyz():
    # unauthenticated: cache so it can't be used to amplify Firestore /
    # Secret Manager load.
    now = time.monotonic()
    if _readyz_cache["body"] is not None and now - _readyz_cache["at"] < _READYZ_TTL_S:
        return JSONResponse(_readyz_cache["body"], status_code=_readyz_cache["code"])

    checks = {"firestore": False, "secret_manager": False}
    try:
        db().collection("_readyz").limit(1).get()
        checks["firestore"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.config import gemini_api_key
        checks["secret_manager"] = bool(gemini_api_key())
    except Exception:  # noqa: BLE001
        pass
    ok = all(checks.values())
    body = {"ok": ok, **checks}
    _readyz_cache.update(at=now, body=body, code=200 if ok else 503)
    return JSONResponse(body, status_code=200 if ok else 503)


# ---- cases ---------------------------------------------------------------
@app.post("/api/cases", status_code=201)
def create_case(body: CaseCreate, request: Request, uid: str = Depends(current_uid)):
    ik = _idem_key(request)
    if ik:
        cached = repo.idempotency_get(uid, ik)
        if cached is not None:
            return cached

    # email is best-effort for the profile doc; not trusted for anything
    email = (getattr(request.state, "claims", {}) or {}).get("email", "") or ""
    repo.ensure_user(uid, email=email)
    case_id = repo.create_case(uid, {
        "title": body.title, "issue_type": body.issue_type,
        "platform": body.platform,
        "amount_claimed_inr": body.amount_claimed_inr,
        "incident_date": body.incident_date,
    })
    repo.audit("case_created", uid)
    result = {"id": case_id}
    if ik:
        repo.idempotency_put(uid, ik, result)
    return result


@app.get("/api/cases")
def list_cases(uid: str = Depends(current_uid)):
    return {"cases": repo.list_cases(uid)}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str, uid: str = Depends(current_uid)):
    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    evidence = repo.list_evidence(uid, case_id)
    return {
        "case": case,
        "messages": repo.list_messages(uid, case_id),
        "drafts": repo.list_drafts(uid, case_id),
        "deadlines": repo.get_deadlines(uid, case_id),
        "evidence": evidence,
        "lost_wages": _lost_wages(case, evidence),
    }


# ---- chat (multi-turn) + auto-summary ---------------------------------
@app.post("/api/cases/{case_id}/chat")
def chat(case_id: str, body: ChatIn, request: Request,
         uid: str = Depends(current_uid)):
    ik = _idem_key(request)
    if ik:
        cached = repo.idempotency_get(uid, ik)
        if cached is not None:
            return cached

    rate_check(uid)
    limits.precheck(uid)

    lock = _case_lock(f"{uid}:{case_id}")
    if not lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A message is already being processed for this case — "
                            "wait for the reply before sending another.")
    try:
        case = repo.get_case(uid, case_id)
        if not case:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

        turns = repo.message_count(uid, case_id)
        if turns >= MAX_TURNS_PER_CASE * 2:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This case's conversation is full. Start a new case "
                                "or work from the summary and drafts.")

        trace_id = request.state.trace_id
        uh = uid_hash(uid)

        repo.add_message(uid, case_id, "user", body.message)
        history = _trim_history(repo.list_messages(uid, case_id))
        contents = [{"role": "user" if m["role"] == "user" else "model",
                     "parts": [{"text": m["text"]}]} for m in history]

        res = generate(
            model=GEMINI_MODEL_CHAT, system=CHAT_SYSTEM, contents=contents,
            trace_id=trace_id, uid_hash=uh,
            fallback_text=("I couldn't reach the assistant just now. Your message is "
                           "saved. Try again in a minute — the rest of the app works."),
        )
        limits.record(uid, res.est_inr)
        repo.add_message(uid, case_id, "model", res.text)

        _auto_summarise(uid, case_id,
                        history + [{"role": "model", "text": res.text}], trace_id, uh)

        result = {"reply": res.text, "degraded": not res.ok}
        if ik:
            repo.idempotency_put(uid, ik, result)
        return result
    finally:
        lock.release()


def _auto_summarise(uid, case_id, history, trace_id, uh):
    """Model proposes a structured summary; code validates and stores it.
    On any failure the previous summary is kept — never corrupted."""
    history = _trim_history(history)
    contents = [{"role": "user", "parts": [{"text":
        "Conversation:\n" + "\n".join(
            f'{m["role"]}: {m["text"]}' for m in history)}]}]
    res = generate(model=GEMINI_MODEL_UTILITY, system=EXTRACT_SYSTEM,
                   contents=contents, trace_id=trace_id, uid_hash=uh,
                   fallback_text="{}", want_json=True, max_output_tokens=600)
    limits.record(uid, res.est_inr)
    obj = parse_json(res)
    if not obj:
        return
    patch = {}
    if isinstance(obj.get("summary"), str) and obj["summary"].strip():
        patch["summary"] = obj["summary"].strip()[:600]
    if isinstance(obj.get("facts"), list):
        patch["facts"] = [
            {"date": str(f.get("date", "")), "text": str(f.get("text", ""))[:300]}
            for f in obj["facts"][:20] if isinstance(f, dict) and f.get("text")
        ]
    if isinstance(obj.get("next_steps"), list):
        patch["next_steps"] = [
            {"text": str(s.get("text", ""))[:200], "done": bool(s.get("done"))}
            for s in obj["next_steps"][:10] if isinstance(s, dict) and s.get("text")
        ]
    if patch:
        repo.patch_case(uid, case_id, patch)


# ---- draft + deterministic readiness check ---------------------------
@app.post("/api/cases/{case_id}/draft")
def make_draft(case_id: str, body: DraftIn, request: Request,
               uid: str = Depends(current_uid)):
    ik = _idem_key(request)
    if ik:
        cached = repo.idempotency_get(uid, ik)
        if cached is not None:
            return cached

    rate_check(uid)
    limits.precheck(uid)

    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    lw = _lost_wages(case, repo.list_evidence(uid, case_id))

    case_for_check = {
        **case,
        "sender": {"name": body.sender_name, "address": body.sender_address,
                   "worker_id": body.sender_worker_id},
        "recipient": {"name": body.recipient_name, "address": body.recipient_address},
        "lost_wages_inr": lw["estimate_inr"] if lw else None,
    }

    payload = {
        "kind": body.kind, "case": case_for_check,
        "amount_claimed_inr": case.get("amount_claimed_inr"),
        "incident_date": case.get("incident_date"),
        "facts": case.get("facts", []),
        "platform": case.get("platform"),
        "lost_wages_estimate": lw,
    }
    contents = [{"role": "user", "parts": [{"text":
        "Draft this document. Case data:\n" + _json(payload)}]}]

    res = generate(model=GEMINI_MODEL_CHAT, system=DRAFT_SYSTEM, contents=contents,
                   trace_id=request.state.trace_id, uid_hash=uid_hash(uid),
                   fallback_text=_draft_template(body, case),
                   max_output_tokens=900)
    limits.record(uid, res.est_inr)

    # DETERMINISTIC: the model wrote the body; Python decides if it's ready.
    with telemetry.measure("readiness", {"kind": body.kind}):
        readiness = check_readiness(body.kind, case_for_check, res.text).to_dict()
    telemetry.record_readiness(body.kind, readiness["ready"], readiness["score"])
    stored = repo.add_draft(uid, case_id, body.kind, res.text, readiness)
    repo.audit("draft_created", uid)
    result = {"draft": stored, "readiness": readiness, "degraded": not res.ok}
    if ik:
        repo.idempotency_put(uid, ik, result)
    return result


# ---- deadlines (fully deterministic) --------------------------------
@app.post("/api/cases/{case_id}/deadlines")
def recompute_deadlines(case_id: str, body: PartyIn,
                        uid: str = Depends(current_uid)):
    rate_check(uid, bucket="write")
    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    def _d(v):
        return date.fromisoformat(v) if v else None

    with telemetry.measure("deadlines"):
        deadlines = build_case_deadlines(
            incident_date=_d(case.get("incident_date")),
            issue_type=case.get("issue_type"),
            notice_sent=_d(body.notice_sent),
            notice_days=body.notice_days,
            grievance_filed=_d(body.grievance_filed),
            platform_sla_days=body.platform_sla_days,
            idrc_appeal_filed=_d(body.idrc_appeal_filed),
        )
    items = [d.to_dict() for d in deadlines]
    repo.set_deadlines(uid, case_id, items)
    return {"deadlines": items}


# ---- evidence locker (algorithmic appeal record) --------------------
@app.post("/api/cases/{case_id}/evidence", status_code=201)
def add_evidence(case_id: str, body: EvidenceIn, request: Request,
                 uid: str = Depends(current_uid)):
    import base64

    rate_check(uid)
    limits.precheck(uid)

    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if repo.evidence_count(uid, case_id) >= EVIDENCE_MAX_ITEMS:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This case already has the maximum number of evidence items.")

    raw = base64.b64decode(body.data_b64, validate=True)
    if len(raw) > EVIDENCE_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File is larger than {EVIDENCE_MAX_BYTES // 1000} KB. "
                            "Crop or compress the screenshot and try again.")

    trace_id = request.state.trace_id
    uh = uid_hash(uid)

    # model reads the file; Python decides what to keep
    res = generate(
        model=GEMINI_MODEL_UTILITY, system=EVIDENCE_SYSTEM,
        contents=[{"role": "user", "parts": [{"text":
            f"This is a '{body.kind}' the worker saved. Extract the JSON."}]}],
        media=[(raw, body.mime)], trace_id=trace_id, uid_hash=uh,
        fallback_text="{}", want_json=True, max_output_tokens=500,
    )
    limits.record(uid, res.est_inr)
    extracted = _clean_extracted(parse_json(res))

    with telemetry.measure("evidence_chain", {"kind": body.kind, "bytes": len(raw)}):
        file_sha = evidence_chain.sha256_hex(raw)
        captured_at = repo._now().isoformat()
        prev = repo.last_evidence(uid, case_id)
        chain = evidence_chain.link(prev, file_sha256=file_sha,
                                    captured_at=captured_at, kind=body.kind)
    telemetry.record_evidence(body.kind, not res.ok)

    stored = repo.add_evidence(uid, case_id, {
        "kind": body.kind, "filename": body.filename[:200], "mime": body.mime,
        "size": len(raw), "sha256": file_sha, "captured_at": captured_at,
        "captured_hint": body.captured_hint or "",
        "data_b64": body.data_b64, "extracted": extracted,
        "model_degraded": not res.ok, **chain,
    })
    repo.audit("evidence_added", uid)

    # let a legible deactivation date populate the case + recompute deadlines
    _maybe_apply_evidence_date(uid, case_id, case, body.kind, extracted)

    out = {k: v for k, v in stored.items() if k != "data_b64"}
    return {"evidence": out, "degraded": not res.ok,
            "chain_ok": evidence_chain.verify(
                repo.list_evidence(uid, case_id))["ok"]}


@app.get("/api/cases/{case_id}/evidence/{ev_id}")
def get_evidence(case_id: str, ev_id: str, uid: str = Depends(current_uid)):
    ev = repo.get_evidence(uid, case_id, ev_id)
    if not ev:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return {"evidence": ev}


@app.get("/api/cases/{case_id}/appeal-record")
def appeal_record(case_id: str, uid: str = Depends(current_uid)):
    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    entries = repo.list_evidence(uid, case_id)
    return evidence_chain.manifest(entries, signing_key=evidence_signing_key())


@app.get("/api/cases/{case_id}/lost-wages")
def lost_wages(case_id: str, uid: str = Depends(current_uid)):
    case = repo.get_case(uid, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    est = _lost_wages(case, repo.list_evidence(uid, case_id))
    return {"lost_wages": est}


def _clean_extracted(obj: Optional[dict]) -> dict:
    obj = obj or {}
    def _int(v):
        try:
            return int(round(float(v))) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    date_s = str(obj.get("observed_date", "") or "")
    try:
        date.fromisoformat(date_s)
    except ValueError:
        date_s = ""
    refs = obj.get("refs")
    return {
        "observed_date": date_s,
        "amount_inr": _int(obj.get("amount_inr")),
        "period_days": _int(obj.get("period_days")),
        "reason": str(obj.get("reason", "") or "")[:280],
        "refs": [str(r)[:60] for r in refs[:8]] if isinstance(refs, list) else [],
        "rating": str(obj.get("rating", "") or "")[:16],
        "summary": str(obj.get("summary", "") or "")[:200],
    }


def _maybe_apply_evidence_date(uid, case_id, case, kind, extracted):
    if (kind == "deactivation_notice" and extracted.get("observed_date")
            and not case.get("incident_date")):
        try:
            repo.patch_case(uid, case_id, {"incident_date": extracted["observed_date"]})
        except Exception:  # noqa: BLE001
            return
        case = repo.get_case(uid, case_id) or case
        items = [d.to_dict() for d in build_case_deadlines(
            incident_date=date.fromisoformat(case["incident_date"]),
            issue_type=case.get("issue_type"),
        )]
        repo.set_deadlines(uid, case_id, items)


# ---- export / delete ------------------------------------------------
@app.get("/api/export")
def export(uid: str = Depends(current_uid)):
    return repo.export_all(uid)


@app.delete("/api/account")
def delete_account(uid: str = Depends(current_uid)):
    repo.delete_account(uid)
    return {"deleted": True}


# ---- helpers -------------------------------------------------------
def _json(obj) -> str:
    import json
    return json.dumps(obj, default=str, ensure_ascii=False)


def _draft_template(body: DraftIn, case: dict) -> str:
    amt = case.get("amount_claimed_inr")
    amt_s = f"Rs {amt}" if amt else "[amount]"
    return (
        f"To: {body.recipient_name}\n{body.recipient_address}\n\n"
        f"From: {body.sender_name}\n{body.sender_address}\n\n"
        f"Subject: {case.get('title', '[subject]')}\n\n"
        f"On [date], the following happened: [describe]. The amount of {amt_s} "
        f"remains unpaid.\n\n"
        f"I call upon you to pay {amt_s} within 15 days of this notice, failing "
        f"which I will approach the appropriate consumer or labour forum.\n\n"
        f"Yours faithfully,\n(Name)"
    )


# ---- static frontend (mounted last) -------------------------------
_static = Path(__file__).parent.parent / "static"
if _static.is_dir():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
