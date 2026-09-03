"""
app/logging_setup.py
====================
Structured JSON logs. Every line carries trace_id + uid_hash. Values are
scrubbed for keys / tokens / emails before they're written.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.redact import scrub


def _scrub_val(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, dict):
        return {k: _scrub_val(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_scrub_val(x) for x in v]
    return v


def _scrub_event(_, __, event_dict):
    for k, v in list(event_dict.items()):
        event_dict[k] = _scrub_val(v)
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _scrub_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger("hisaab")
