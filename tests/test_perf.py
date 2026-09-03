"""
Performance / concurrency tests.

These assert the properties the hardening pass claimed:
  - deterministic endpoints stay fast under concurrent load
  - a slow (blocking) model call does NOT stall the event loop — other
    requests keep flowing  (the C1 fix: sync handlers -> threadpool)
  - the per-case chat lock serialises turns for ONE case without
    serialising unrelated cases

Run just these:  .venv/bin/python -m pytest -q tests/test_perf.py -m perf
"""

import asyncio
import base64
import time

import firebase_admin
import httpx
import pytest

pytestmark = pytest.mark.perf

DELAY = 0.15  # simulated model round-trip, seconds
PNG = base64.b64encode(b"\x89PNG\r\n" + b"\x00" * 128).decode()


@pytest.fixture
def perf_client(monkeypatch):
    """The real app, in-memory backends, a model that BLOCKS for `DELAY`."""
    from tests.fakefs import FakeClient
    import app.firebase as fb
    import app.gemini as gem
    import app.limits as limits
    import app.main as main
    import app.ratelimit as rl
    from app.gemini import GeminiResult

    fs = FakeClient()
    monkeypatch.setattr(fb, "_init", lambda: None)
    monkeypatch.setattr(fb.firestore, "client", lambda *a, **k: fs)
    monkeypatch.setattr(fb.fb_auth, "verify_id_token",
                        lambda tok, check_revoked=False: {"uid": tok.split(":", 1)[0],
                                                          "email": ""})
    monkeypatch.setattr(firebase_admin.auth, "delete_user", lambda uid: None, raising=False)

    CANNED = ('{"summary":"ok","facts":[],"next_steps":[],"observed_date":"",'
              '"amount_inr":2400,"period_days":7,"reason":"","refs":[],"rating":""}')

    def slow_generate(*, want_json=False, model="m", **kw):
        time.sleep(DELAY)                       # blocking, like the real SDK
        txt = CANNED if want_json else (
            "On 10/03/2026 the sum of Rs 2400 was withheld. Pay Rs 2400 within "
            "15 days of this notice, failing which I will approach the consumer "
            "forum. Yours faithfully, (Name)")
        return GeminiResult(ok=True, text=txt, model=model, in_tokens=1000,
                            out_tokens=250, est_inr=0.03, latency_ms=int(DELAY * 1000))

    monkeypatch.setattr(main, "generate", slow_generate)
    rl._reset_for_tests()
    gem._reset_state_for_tests()
    limits._reset_cache_for_tests()

    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


def _auth(uid="p"):
    return {"Authorization": f"Bearer {uid}:token"}


async def _mkcase(c, uid="p", **over):
    body = {"title": "perf case", "issue_type": "deactivation", "platform": "Uber",
            "incident_date": "2026-08-28", "amount_claimed_inr": 2400, **over}
    r = await c.post("/api/cases", json=body, headers=_auth(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_deterministic_endpoint_fast_under_load(perf_client):
    async with perf_client as c:
        cid = await _mkcase(c)
        N = 60
        t0 = time.perf_counter()
        res = await asyncio.gather(*[
            c.post(f"/api/cases/{cid}/deadlines", json={"notice_sent": "2026-09-01"},
                   headers=_auth()) for _ in range(N)])
        elapsed = time.perf_counter() - t0
        assert all(r.status_code == 200 for r in res)
        # no model call on this path; 60 of them should finish well under a second
        assert elapsed < 2.0, f"{N} /deadlines took {elapsed:.2f}s"


async def test_slow_model_does_not_block_the_event_loop(perf_client):
    async with perf_client as c:
        cid = await _mkcase(c)
        # fire 12 slow /draft calls, then immediately hit a fast read
        slow = [asyncio.create_task(c.post(
            f"/api/cases/{cid}/draft",
            json={"kind": "platform_grievance", "sender_name": "A",
                  "sender_worker_id": "W1", "recipient_name": "Uber"},
            headers={**_auth(), "Idempotency-Key": f"k{i}"})) for i in range(12)]
        await asyncio.sleep(0.02)

        t0 = time.perf_counter()
        fast = await c.get("/api/cases", headers=_auth())
        fast_ms = (time.perf_counter() - t0) * 1000

        assert fast.status_code == 200
        # if the loop were blocked by the 12 blocking calls this would be >> DELAY
        assert fast_ms < DELAY * 1000, f"fast read waited {fast_ms:.0f}ms behind slow calls"
        assert all(r.status_code == 200 for r in await asyncio.gather(*slow))


async def test_per_case_lock_rejects_concurrent_same_case_chats(perf_client):
    async with perf_client as c:
        c1 = await _mkcase(c, uid="a")
        N = 5

        # N chats on the SAME case at once: one wins the per-case lock, the
        # rest get 409 (rather than interleaving the history / clobbering
        # the auto-summary). Distinct idempotency keys so it's not that.
        r1 = await asyncio.gather(*[c.post(
            f"/api/cases/{c1}/chat", json={"message": f"hi {i}"},
            headers={**_auth("a"), "Idempotency-Key": f"s{i}"}) for i in range(N)])
        codes = sorted(r.status_code for r in r1)
        assert codes.count(200) == 1
        assert codes.count(409) == N - 1

        # N chats on N DIFFERENT cases run concurrently in the threadpool:
        # wall time is ~one chat (2 blocking model calls), not N of them.
        cases = [await _mkcase(c, uid=f"u{i}") for i in range(N)]
        t0 = time.perf_counter()
        r2 = await asyncio.gather(*[c.post(
            f"/api/cases/{cid}/chat", json={"message": "hi"},
            headers={**_auth(f"u{i}"), "Idempotency-Key": f"d{i}"})
            for i, cid in enumerate(cases)])
        diff = time.perf_counter() - t0
        assert all(r.status_code == 200 for r in r2)
        assert diff < N * 2 * DELAY, f"different cases didn't parallelise ({diff:.2f}s)"


async def test_throughput_smoke(perf_client, capsys):
    async with perf_client as c:
        cid = await _mkcase(c)
        N = 40
        t0 = time.perf_counter()
        res = await asyncio.gather(*[c.get(f"/api/cases/{cid}", headers=_auth())
                                     for _ in range(N)])
        dt = time.perf_counter() - t0
        assert all(r.status_code == 200 for r in res)
        with capsys.disabled():
            print(f"\n  GET /api/cases/{{id}}  x{N}  in {dt*1000:.0f}ms  "
                  f"= {N/dt:.0f} req/s")
