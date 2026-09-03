"""
perf/serve_fake.py
==================
Run the REAL FastAPI app against in-memory fakes, with OpenTelemetry on,
so you can load-test the app's own overhead and concurrency behaviour
without Firebase / Gemini / a bill.

    make otel-up          # collector + Jaeger + Prometheus + Grafana
    make load             # this server + Locust headless
  or manually:
    HISAAB_OTEL=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
      GEMINI_FAKE_LATENCY_MS=250 .venv/bin/python -m perf.serve_fake

Auth: send  Authorization: Bearer <uid>:token   (any uid; "bad…" -> 401).
The fake model sleeps GEMINI_FAKE_LATENCY_MS (blocking, like the real SDK)
then returns a canned reply, so threadpool behaviour is realistic.
"""

from __future__ import annotations

import os
import time

_LAT = float(os.environ.get("GEMINI_FAKE_LATENCY_MS", "250")) / 1000.0

# ---- wire the fakes BEFORE importing app.main -----------------------------
import firebase_admin  # noqa: E402
import app.firebase as fb  # noqa: E402
from tests.fakefs import FakeClient  # noqa: E402

_FS = FakeClient()
fb._init = lambda: None
fb.firestore.client = lambda *a, **k: _FS


def _verify(token, check_revoked=False):
    if not token or token.startswith("bad"):
        raise ValueError("bad token")
    uid = token.split(":", 1)[0]
    return {"uid": uid, "email": f"{uid}@example.com"}


fb.fb_auth.verify_id_token = _verify
firebase_admin.auth.delete_user = lambda uid: None

import app.gemini as gem  # noqa: E402
from app.gemini import GeminiResult  # noqa: E402

_CANNED_JSON = (
    '{"summary":"case is progressing","facts":[{"date":"2026-08-28","text":"blocked"}],'
    '"next_steps":[{"text":"file the appeal","done":false}],'
    '"observed_date":"2026-08-28","amount_inr":2400,"period_days":7,'
    '"reason":"account under review","refs":["TRIP-1"],"rating":"4.7"}'
)
_CANNED_TEXT = (
    "On 10/03/2026 the sum of Rs 2400 was withheld. Pay Rs 2400 within 15 days "
    "of this notice, failing which I will approach the consumer forum. "
    "Yours faithfully, (Name)"
)


from app import telemetry  # noqa: E402


def _fake_generate(*, want_json=False, model="fake", **kw):
    with telemetry.span("gemini.generate", {"gemini.model": model, "gemini.fake": True}):
        time.sleep(_LAT)  # blocking, like google-genai
        res = GeminiResult(ok=True, text=_CANNED_JSON if want_json else _CANNED_TEXT,
                           model=model, in_tokens=1100, out_tokens=280, est_inr=0.04,
                           latency_ms=int(_LAT * 1000))
    telemetry.record_gemini(model=res.model, ok=True, latency_ms=res.latency_ms,
                            in_tokens=res.in_tokens, out_tokens=res.out_tokens,
                            cost_inr=res.est_inr, fell_back=False)
    return res


gem.generate = _fake_generate

import app.main as main  # noqa: E402

main.generate = _fake_generate  # main imported the name directly

app = main.app

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8800"))
    print(f"perf server on http://127.0.0.1:{port}  "
          f"(fake model latency {_LAT * 1000:.0f}ms, OTel={os.environ.get('HISAAB_OTEL', '0')})")
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, log_level="warning")
