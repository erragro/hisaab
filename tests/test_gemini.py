import types

import pytest

import app.gemini as gem


@pytest.fixture(autouse=True)
def _fast_and_clean(monkeypatch):
    monkeypatch.setattr(gem.time, "sleep", lambda *_: None)
    gem._reset_state_for_tests()
    yield
    gem._reset_state_for_tests()


def _resp(text="hello", pin=3, pout=7):
    return types.SimpleNamespace(
        text=text,
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=pin, candidates_token_count=pout),
    )


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        outer = self

        class _Models:
            def generate_content(self, *, model, contents, config):
                item = outer.script[min(outer.calls, len(outer.script) - 1)]
                outer.calls += 1
                if isinstance(item, Exception):
                    raise item
                return item

        self.models = _Models()


def _gen(**over):
    kw = dict(model="m", system="s", contents=[], trace_id="t", uid_hash="u",
              fallback_text="FALLBACK")
    kw.update(over)
    return gem.generate(**kw)


def test_success(monkeypatch):
    fc = FakeClient([_resp("drafted")])
    monkeypatch.setattr(gem, "_get_client", lambda: fc)
    r = _gen()
    assert r.ok and r.text == "drafted" and r.in_tokens == 3 and r.out_tokens == 7
    assert fc.calls == 1


def test_retries_then_falls_back(monkeypatch):
    fc = FakeClient([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")])
    monkeypatch.setattr(gem, "_get_client", lambda: fc)
    r = _gen()
    assert r.ok is False and r.fell_back and r.text == "FALLBACK"
    assert fc.calls == 3


def test_empty_response_is_a_failure(monkeypatch):
    fc = FakeClient([_resp("")])
    monkeypatch.setattr(gem, "_get_client", lambda: fc)
    monkeypatch.setattr(gem, "_is_retryable", lambda e: False)
    r = _gen()
    assert r.ok is False and fc.calls == 1


def test_no_retry_when_not_retryable(monkeypatch):
    fc = FakeClient([RuntimeError("nope")])
    monkeypatch.setattr(gem, "_get_client", lambda: fc)
    monkeypatch.setattr(gem, "_is_retryable", lambda e: False)
    _gen()
    assert fc.calls == 1


def test_circuit_breaker_opens_and_short_circuits(monkeypatch):
    fc = FakeClient([RuntimeError("boom")])
    monkeypatch.setattr(gem, "_get_client", lambda: fc)
    monkeypatch.setattr(gem, "_is_retryable", lambda e: False)
    for _ in range(gem._BREAKER_THRESHOLD):
        _gen()
    calls_before = fc.calls
    r = _gen()
    assert r.fell_back and fc.calls == calls_before  # client not touched


def test_media_is_attached_to_the_last_user_turn(monkeypatch):
    captured = {}

    class FC:
        class models:
            @staticmethod
            def generate_content(*, model, contents, config):
                captured["contents"] = contents
                return _resp('{"ok": true}')

    monkeypatch.setattr(gem, "_get_client", lambda: FC())
    r = _gen(contents=[{"role": "user", "parts": [{"text": "read it"}]}],
             media=[(b"\x89PNG\r\n", "image/png")], want_json=True)
    assert r.ok
    parts = captured["contents"][-1].parts
    assert parts[0].text == "read it"
    assert parts[1].inline_data.mime_type == "image/png"


def test_parse_json():
    from app.gemini import GeminiResult, parse_json
    assert parse_json(GeminiResult(ok=True, text='{"a": 1}', model="m")) == {"a": 1}
    assert parse_json(GeminiResult(ok=True, text='[1,2]', model="m")) is None
    assert parse_json(GeminiResult(ok=True, text='not json', model="m")) is None
    assert parse_json(GeminiResult(ok=False, text='{}', model="m")) is None


def test_is_retryable_distinguishes_client_errors():
    from google.genai import errors as ge

    class _RR:
        body_segments = [{"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                    "message": "bad"}}]

    try:
        e400 = ge.ClientError(400, _RR())
        e429 = ge.ClientError(429, _RR())
    except Exception:
        pytest.skip("genai error constructor shape differs in this SDK version")
    assert gem._is_retryable(e400) is False
    assert gem._is_retryable(e429) is True
    assert gem._is_retryable(RuntimeError("timeout")) is True
