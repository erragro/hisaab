import pytest
from fastapi import HTTPException

import app.ratelimit as rl


@pytest.fixture(autouse=True)
def _clean():
    rl._reset_for_tests()
    yield
    rl._reset_for_tests()


def test_model_bucket_5min_ceiling(monkeypatch):
    monkeypatch.setattr(rl, "_BUCKETS", {"model": (3, 100)})
    for _ in range(3):
        rl.check("u", bucket="model")
    with pytest.raises(HTTPException) as e:
        rl.check("u", bucket="model")
    assert e.value.status_code == 429


def test_buckets_are_independent(monkeypatch):
    monkeypatch.setattr(rl, "_BUCKETS", {"model": (1, 10), "write": (1, 10)})
    rl.check("u", bucket="model")
    rl.check("u", bucket="write")          # separate budget, still fine
    with pytest.raises(HTTPException):
        rl.check("u", bucket="model")


def test_daily_ceiling(monkeypatch):
    monkeypatch.setattr(rl, "_BUCKETS", {"model": (999, 2)})
    rl.check("u"); rl.check("u")
    with pytest.raises(HTTPException):
        rl.check("u")


def test_users_isolated(monkeypatch):
    monkeypatch.setattr(rl, "_BUCKETS", {"model": (1, 10)})
    rl.check("a")
    rl.check("b")  # different uid, unaffected


def test_sweep_evicts_drained_deques(monkeypatch):
    monkeypatch.setattr(rl, "_SWEEP_EVERY", 3)
    t = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: t[0])
    rl.check("gone")
    t[0] += rl._WIN_DAY + 10          # let the entry age out
    rl.check("x"); rl.check("y"); rl.check("z")   # triggers a sweep
    assert ("model", "gone") not in rl._events
