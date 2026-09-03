from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import app.limits as limits
from tests.fakefs import FakeClient


@pytest.fixture
def fs(monkeypatch):
    c = FakeClient()
    import app.firebase as fb
    monkeypatch.setattr(fb, "_init", lambda: None)
    monkeypatch.setattr(fb.firestore, "client", lambda *a, **k: c)
    limits._reset_cache_for_tests()
    return c


def _mk():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _dk():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_precheck_passes_when_empty(fs):
    limits.precheck("u")  # no raise


def test_monthly_ceiling_blocks(fs, monkeypatch):
    monkeypatch.setattr(limits, "MONTHLY_COST_CEILING_INR", 10.0)
    fs.collection("counters").document(f"cost-{_mk()}").set({"spent_inr": 12.5})
    limits._reset_cache_for_tests()
    with pytest.raises(HTTPException) as e:
        limits.precheck("u")
    assert e.value.status_code == 429


def test_daily_cap_blocks(fs, monkeypatch):
    monkeypatch.setattr(limits, "RATE_LIMIT_PER_DAY", 5)
    (fs.collection("users").document("u").collection("counters")
       .document(f"calls-{_dk()}").set({"model_calls": 5}))
    with pytest.raises(HTTPException):
        limits.precheck("u")
    # a different user is unaffected
    limits.precheck("other")


def test_record_increments_both_counters(fs):
    limits.record("u", 0.03)
    limits.record("u", 0.04)
    month = fs.collection("counters").document(f"cost-{_mk()}").get().to_dict()
    day = (fs.collection("users").document("u").collection("counters")
             .document(f"calls-{_dk()}").get().to_dict())
    assert round(month["spent_inr"], 2) == 0.07
    assert day["model_calls"] == 2


def test_monthly_cache_ttl(fs, monkeypatch):
    fs.collection("counters").document(f"cost-{_mk()}").set({"spent_inr": 1.0})
    limits._reset_cache_for_tests()
    assert limits.monthly_spent_inr() == 1.0
    fs.collection("counters").document(f"cost-{_mk()}").set({"spent_inr": 99.0})
    assert limits.monthly_spent_inr() == 1.0            # cached
    assert limits.monthly_spent_inr(force=True) == 99.0  # fresh read


def test_record_failure_is_swallowed(monkeypatch):
    import app.firebase as fb
    monkeypatch.setattr(fb, "_init", lambda: None)

    def _boom(*a, **k):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(fb.firestore, "client", _boom)
    limits.record("u", 0.01)  # must not raise
