"""
app/ratelimit.py
================
In-memory per-uid *burst* limiting for the API. This is a per-process
backstop that resets on restart; the authoritative daily cap and the
monthly cost ceiling live in Firestore (app/limits.py) so they hold
across instances.

Buckets keep model-calling endpoints and cheap write endpoints on
separate budgets.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app import telemetry
from app.config import RATE_LIMIT_PER_5MIN, RATE_LIMIT_PER_DAY

_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

_WIN_5MIN = 300
_WIN_DAY = 86_400

# (per-5min, per-day) ceilings by bucket
_BUCKETS = {
    "model": (RATE_LIMIT_PER_5MIN, RATE_LIMIT_PER_DAY),
    "write": (max(RATE_LIMIT_PER_5MIN * 3, 30), max(RATE_LIMIT_PER_DAY * 5, 200)),
}

_calls_since_sweep = 0
_SWEEP_EVERY = 500


def _sweep(now: float) -> None:
    """Drop deques that have fully drained so idle uids don't leak memory."""
    global _calls_since_sweep
    _calls_since_sweep = 0
    for key in list(_events):
        dq = _events[key]
        while dq and now - dq[0] > _WIN_DAY:
            dq.popleft()
        if not dq:
            _events.pop(key, None)


def check(uid: str, *, bucket: str = "model") -> None:
    global _calls_since_sweep
    per_5min, per_day = _BUCKETS.get(bucket, _BUCKETS["model"])
    now = time.monotonic()

    _calls_since_sweep += 1
    if _calls_since_sweep >= _SWEEP_EVERY:
        _sweep(now)

    dq = _events[(bucket, uid)]
    while dq and now - dq[0] > _WIN_DAY:
        dq.popleft()

    if sum(1 for t in dq if now - t <= _WIN_5MIN) >= per_5min:
        telemetry.record_ratelimit_reject(bucket, "5min")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many requests — try again in a few minutes.")
    if len(dq) >= per_day:
        telemetry.record_ratelimit_reject(bucket, "day")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Daily limit reached — the rest of the app still works.")
    dq.append(now)


def _reset_for_tests() -> None:
    _events.clear()
    global _calls_since_sweep
    _calls_since_sweep = 0
