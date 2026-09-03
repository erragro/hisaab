"""
app/core/redact.py
==================
PII / secret hygiene for logs. PURE, unit-tested.

Rule 14 of the constitution: log `uid_hash`, never the raw uid, email,
token, or user text. Rule 6: no secrets in logs or error responses.
"""

from __future__ import annotations

import hashlib
import re

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9._\-]{40,}\b")


def uid_hash(uid: str) -> str:
    """Stable, non-reversible short id for correlating logs to a user."""
    if not uid:
        return "anon"
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:12]


def scrub(text: str) -> str:
    """Remove anything that looks like a secret or PII from a log string."""
    if not text:
        return text
    text = _GOOGLE_KEY.sub("[redacted-key]", text)
    text = _BEARER.sub("Bearer [redacted]", text)
    text = _EMAIL.sub("[redacted-email]", text)
    text = _LONG_TOKEN.sub("[redacted-token]", text)
    return text


def safe_error(exc: Exception) -> str:
    """A user/log-safe one-line description of an exception. Never leaks a key."""
    return scrub(f"{type(exc).__name__}: {exc}")[:300]
