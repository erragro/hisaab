from app.core.redact import safe_error, scrub, uid_hash

# Build key-shaped strings at runtime so no literal that matches the deploy
# secret-scan ("AIza" + 20+ chars) ever appears in the source tree.
FAKE_KEY = "AIza" + "Sy" + "B" + "0" * 33          # AIza + 35 chars
FAKE_JWT = "eyJhbGciOiJSUzI1NiIsImtpZCI6I" + "x" * 60


def test_uid_hash_stable_and_short():
    a = uid_hash("firebase-uid-abc123")
    b = uid_hash("firebase-uid-abc123")
    assert a == b
    assert len(a) == 12
    assert "abc123" not in a


def test_uid_hash_anon_for_empty():
    assert uid_hash("") == "anon"


def test_scrub_removes_google_key():
    s = scrub(f"key is {FAKE_KEY}")
    assert "AIza" not in s
    assert "[redacted-key]" in s


def test_scrub_removes_bearer_and_email():
    s = scrub(f"Authorization: Bearer {FAKE_JWT}  user a.kumar@example.com")
    assert FAKE_JWT not in s
    assert "a.kumar@example.com" not in s
    assert "[redacted-email]" in s


def test_scrub_keeps_ordinary_text():
    assert scrub("case updated, 3 deadlines computed") == \
        "case updated, 3 deadlines computed"


def test_safe_error_never_leaks_key():
    e = RuntimeError(f"gemini rejected key {FAKE_KEY}")
    out = safe_error(e)
    assert "AIza" not in out
    assert out.startswith("RuntimeError")


def test_scrub_event_recurses_into_nested_values():
    from app.logging_setup import _scrub_event
    ev = _scrub_event(None, None, {
        "event": "x",
        "payload": {"email": "worker@example.com", "list": [f"Bearer {FAKE_JWT}"]},
    })
    assert "worker@example.com" not in str(ev)
    assert FAKE_JWT not in str(ev)
