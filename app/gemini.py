"""
app/gemini.py
=============
The ONLY module that imports the Gemini SDK.

Constitution rules 12-15: every call has a hard timeout, bounded retries
with backoff (only for transient failures), a circuit breaker, and a
template fallback; every call emits a CostLog; the model never produces a
score or a verdict.

`generate()` returns a GeminiResult. On total failure it returns
`ok=False` with `text` set to a safe template — it never raises to the
caller, so a route can always complete from the deterministic path.

`generate()` is a *blocking* call (the google-genai SDK is synchronous and
so is the retry backoff). Route handlers therefore MUST be plain `def`
(not `async def`) so Starlette runs them in a worker thread and the event
loop is never blocked.
"""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app import telemetry
from app.config import (
    MAX_OUTPUT_TOKENS,
    est_cost_inr,
    gemini_api_key,
    price_known,
)
from app.logging_setup import log

_TIMEOUT_S = 20
_TIMEOUT_MS = _TIMEOUT_S * 1000  # google-genai HttpOptions.timeout is milliseconds
_MAX_RETRIES = 3
_BREAKER_THRESHOLD = 5
_BREAKER_COOLDOWN_S = 30

_lock = threading.Lock()
_consecutive_failures = 0
_breaker_open_until = 0.0

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=gemini_api_key(),
            http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
        )
    return _client


@dataclass
class GeminiResult:
    ok: bool
    text: str
    model: str
    in_tokens: int = 0
    out_tokens: int = 0
    est_inr: float = 0.0
    latency_ms: int = 0
    fell_back: bool = False


def _breaker_open() -> bool:
    with _lock:
        return time.monotonic() < _breaker_open_until


def _record(success: bool) -> None:
    global _consecutive_failures, _breaker_open_until
    with _lock:
        if success:
            _consecutive_failures = 0
            return
        _consecutive_failures += 1
        if _consecutive_failures >= _BREAKER_THRESHOLD:
            _breaker_open_until = time.monotonic() + _BREAKER_COOLDOWN_S


def _reset_state_for_tests() -> None:
    global _consecutive_failures, _breaker_open_until, _client
    with _lock:
        _consecutive_failures = 0
        _breaker_open_until = 0.0
    _client = None


_TERMINAL_429 = ("credit", "billing", "quota exceeded", "exceeded your current quota")


def _is_retryable(exc: Exception) -> bool:
    """Retry transient failures only. A 4xx that isn't 429 (bad request,
    auth, safety block) will fail again — don't waste the backoff on it. A
    429 is usually a per-minute rate limit (worth a retry), but a
    depleted-credits / hard-quota 429 will not recover in 8s, so skip it."""
    try:
        from google.genai import errors as gerr
    except Exception:  # noqa: BLE001
        return True
    if isinstance(exc, gerr.ClientError):
        if getattr(exc, "code", None) != 429:
            return False
        msg = (str(getattr(exc, "message", "")) or str(exc)).lower()
        return not any(t in msg for t in _TERMINAL_429)
    if isinstance(exc, gerr.ServerError):
        return True
    # timeouts, connection resets, empty-response RuntimeError, etc.
    return True


def _with_media(contents: list, media) -> list:
    """Append inline file parts (bytes, mime) to the last user turn.
    Returns native genai Content objects."""
    from google.genai import types

    out = []
    for c in contents:
        role = c["role"] if isinstance(c, dict) else c.role
        parts_src = c["parts"] if isinstance(c, dict) else c.parts
        parts = []
        for p in parts_src:
            if isinstance(p, dict):
                parts.append(types.Part.from_text(text=p["text"]))
            else:
                parts.append(p)
        out.append(types.Content(role=role, parts=parts))
    if out and media:
        for data, mime in media:
            out[-1].parts.append(types.Part.from_bytes(data=data, mime_type=mime))
    return out


def generate(
    *,
    model: str,
    system: str,
    contents: list,          # genai "contents": list of {role, parts:[{text}]}
    trace_id: str,
    uid_hash: str,
    fallback_text: str,
    want_json: bool = False,
    max_output_tokens: Optional[int] = None,
    media: Optional[list] = None,   # [(bytes, mime_type)] for multimodal calls
) -> GeminiResult:
    with telemetry.span("gemini.generate", {
        "gemini.model": model, "gemini.want_json": want_json,
        "gemini.multimodal": bool(media), "trace_id": trace_id,
    }) as _s:
        return _finish(_generate(
            model=model, system=system, contents=contents, trace_id=trace_id,
            uid_hash=uid_hash, fallback_text=fallback_text, want_json=want_json,
            max_output_tokens=max_output_tokens, media=media), _s)


def _finish(res: "GeminiResult", s) -> "GeminiResult":
    try:
        s.set_attribute("gemini.ok", res.ok)
        s.set_attribute("gemini.fell_back", res.fell_back)
        s.set_attribute("gemini.latency_ms", res.latency_ms)
        s.set_attribute("gemini.out_tokens", res.out_tokens)
    except Exception:  # noqa: BLE001
        pass
    telemetry.record_gemini(
        model=res.model, ok=res.ok, latency_ms=res.latency_ms,
        in_tokens=res.in_tokens, out_tokens=res.out_tokens,
        cost_inr=res.est_inr, fell_back=res.fell_back)
    return res


def _generate(*, model, system, contents, trace_id, uid_hash, fallback_text,
              want_json, max_output_tokens, media) -> GeminiResult:
    started = time.monotonic()
    tokens_out = max_output_tokens or MAX_OUTPUT_TOKENS

    if _breaker_open():
        log.warning("gemini.breaker_open", trace_id=trace_id, uid_hash=uid_hash, model=model)
        return GeminiResult(ok=False, text=fallback_text, model=model,
                            fell_back=True, latency_ms=_ms(started))

    from google.genai import types

    if media:
        contents = _with_media(contents, media)

    cfg = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=tokens_out,
        temperature=0.4,
        response_mime_type="application/json" if want_json else "text/plain",
    )

    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            client = _get_client()
            with telemetry.span("gemini.request", {"gemini.attempt": attempt}):
                resp = client.models.generate_content(
                    model=model, contents=contents, config=cfg,
                )
            text = (resp.text or "").strip()
            if not text:
                raise RuntimeError("empty response")

            um = getattr(resp, "usage_metadata", None)
            in_tok = getattr(um, "prompt_token_count", 0) or 0
            out_tok = getattr(um, "candidates_token_count", 0) or 0
            cost = est_cost_inr(model, in_tok, out_tok)

            _record(True)
            log.info("gemini.call", event_type="CostLog", trace_id=trace_id,
                     uid_hash=uid_hash, model=model, in_tokens=in_tok,
                     out_tokens=out_tok, est_inr=cost, price_known=price_known(model),
                     latency_ms=_ms(started), attempt=attempt)
            return GeminiResult(ok=True, text=text, model=model, in_tokens=in_tok,
                                out_tokens=out_tok, est_inr=cost,
                                latency_ms=_ms(started))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _MAX_RETRIES and _is_retryable(exc):
                time.sleep(min(2 ** attempt + random.random(), 8))
            else:
                break

    _record(False)
    log.error("gemini.failed", trace_id=trace_id, uid_hash=uid_hash, model=model,
              error=f"{type(last_exc).__name__}", latency_ms=_ms(started))
    return GeminiResult(ok=False, text=fallback_text, model=model, fell_back=True,
                        latency_ms=_ms(started))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def parse_json(result: GeminiResult) -> Optional[dict]:
    """Schema-agnostic JSON parse. Returns None on any failure — the caller
    then falls back to a deterministic template, never to raw text."""
    if not result.ok:
        return None
    try:
        obj = json.loads(result.text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None
