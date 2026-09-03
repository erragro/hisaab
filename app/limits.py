"""
app/limits.py
=============
Cross-instance spend guards, backed by Firestore so they hold no matter
how many Cloud Run instances are running.

- per-uid daily cap on model calls   -> users/{uid}/counters/calls-YYYY-MM-DD
- global monthly cost ceiling (INR)   -> counters/cost-YYYY-MM

`precheck(uid)` is called before a model call and raises 429 if either
limit is hit. `record(uid, est_inr)` is called after and bumps both
counters with atomic increments.

The monthly total is cached briefly per instance to keep the read cost
down; the daily per-uid count is read fresh (it is the abuse gate).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import HTTPException, status
from google.cloud import firestore

from app.config import MONTHLY_COST_CEILING_INR, RATE_LIMIT_PER_DAY
from app.firebase import db
from app.logging_setup import log

_MONTH_TTL_S = 60.0
_month_cache = {"key": "", "val": 0.0, "at": 0.0}


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _monthly_doc():
    return db().collection("counters").document(f"cost-{_month_key()}")


def _daily_doc(uid: str):
    return (db().collection("users").document(uid)
            .collection("counters").document(f"calls-{_day_key()}"))


def monthly_spent_inr(*, force: bool = False) -> float:
    mk = _month_key()
    now = time.monotonic()
    c = _month_cache
    if not force and c["key"] == mk and (now - c["at"]) < _MONTH_TTL_S:
        return c["val"]
    try:
        snap = _monthly_doc().get()
        val = float((snap.to_dict() or {}).get("spent_inr", 0.0)) if snap.exists else 0.0
    except Exception:  # noqa: BLE001 - if Firestore is down, don't hard-block
        val = c["val"] if c["key"] == mk else 0.0
    c.update(key=mk, val=val, at=now)
    return val


def _daily_calls(uid: str) -> int:
    try:
        snap = _daily_doc(uid).get()
        return int((snap.to_dict() or {}).get("model_calls", 0)) if snap.exists else 0
    except Exception:  # noqa: BLE001
        return 0


def precheck(uid: str) -> None:
    if MONTHLY_COST_CEILING_INR > 0 and monthly_spent_inr() >= MONTHLY_COST_CEILING_INR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "The monthly usage budget for this service is used up. Your saved "
            "cases, the deadline calculator, and template drafts still work.",
        )
    if _daily_calls(uid) >= RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Daily limit reached — the rest of the app still works.",
        )


def record(uid: str, est_inr: float) -> None:
    now = datetime.now(timezone.utc)
    try:
        _daily_doc(uid).set(
            {"model_calls": firestore.Increment(1), "updatedAt": now}, merge=True
        )
        if est_inr:
            _monthly_doc().set(
                {"spent_inr": firestore.Increment(float(est_inr)), "updatedAt": now},
                merge=True,
            )
            c = _month_cache
            if c["key"] == _month_key():
                c["val"] += float(est_inr)
    except Exception as exc:  # noqa: BLE001 - accounting failure must not 500 the user
        log.warning("limits.record_failed", error=type(exc).__name__)


def _reset_cache_for_tests() -> None:
    _month_cache.update(key="", val=0.0, at=0.0)
