import os
import sys

# make `import app...` work from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from tests.fakefs import FakeClient  # noqa: E402


@pytest.fixture
def fs():
    """A fresh in-memory Firestore for one test."""
    return FakeClient()


@pytest.fixture
def gemini_stub():
    """Mutable holder so a test can script the model's reply."""
    from app.gemini import GeminiResult

    class Stub:
        def __init__(self):
            self.result = GeminiResult(ok=True, text="MODEL DRAFT BODY", model="test",
                                       in_tokens=10, out_tokens=20, est_inr=0.01)
            self.calls = []

        def __call__(self, **kw):
            self.calls.append(kw)
            return self.result

    return Stub()


@pytest.fixture
def app_client(fs, gemini_stub, monkeypatch):
    """FastAPI TestClient with Firestore, Firebase Auth and Gemini stubbed."""
    import firebase_admin
    from fastapi.testclient import TestClient

    import app.firebase as fb
    import app.gemini as gem
    import app.limits as limits
    import app.main as main
    import app.ratelimit as rl

    monkeypatch.setattr(fb, "_init", lambda: None)
    monkeypatch.setattr(fb.firestore, "client", lambda *a, **k: fs)

    def _verify(token, check_revoked=False):
        if not token or token.startswith("bad"):
            raise ValueError("invalid token")
        uid = token.split(":", 1)[0]
        return {"uid": uid, "email": f"{uid}@example.com"}

    monkeypatch.setattr(fb.fb_auth, "verify_id_token", _verify)
    monkeypatch.setattr(firebase_admin.auth, "delete_user", lambda uid: None,
                        raising=False)

    monkeypatch.setattr(main, "generate", gemini_stub)
    # _auto_summarise should not corrupt anything by default -> empty JSON
    monkeypatch.setattr(main, "parse_json", lambda res: {})

    rl._reset_for_tests()
    gem._reset_state_for_tests()
    limits._reset_cache_for_tests()

    with TestClient(main.app) as c:
        c.gemini = gemini_stub
        yield c


def auth(uid="userA"):
    return {"Authorization": f"Bearer {uid}:token"}
