# CLAUDE.md — assistant instructions for Hisaab

Standing guardrails for any agentic coding assistant (Claude Code, or a
similar tool) working on this repository. This is the "Custom Instructions"
for the project: it teaches the assistant how to add features and wire in
third-party integrations **without weakening the security or reliability
posture**. Read it before making changes; extend the relevant section
whenever a new integration is added.

The prose reference for *how the system works* is
[`docs/ENGINEERING.md`](docs/ENGINEERING.md). This file is about *how to
change it safely*.

---

## 0. The one rule everything else serves

**The model proposes; Python decides.** Gemini drafts documents, narrates
numbers, answers questions, and transcribes screenshots. It must **never**
be the thing that produces a score, a deadline, a monetary amount, or a
"ready to send" verdict. Those come from pure functions in `app/core/`
and are only passed *into* the model for wording.

When you add a feature, ask: *does the model's output gate a
consequential decision?* If yes, put a deterministic check in `app/core/`
between the model and the decision, and unit-test it.

---

## 1. Working agreements

- `make gate` (102 tests + `make secret-scan`) must pass before any commit
  that touches `app/`. `make test-perf` covers the timing-sensitive
  concurrency tests and is run separately.
- New behaviour gets a test in the same change. Route behaviour →
  `tests/test_api.py` against `tests/fakefs.py` (no real Firebase/Gemini).
  Pure logic → a `tests/test_<module>.py`.
- Never introduce a real secret, key, or token into the tree — not in
  code, a fixture, a comment, a `.env`, or a test. `make secret-scan`
  fails the build if you do. Build key-shaped test strings at runtime.
- Route handlers stay **plain `def`**, never `async def` — everything
  underneath them (token verify, Firestore, the Gemini SDK) is blocking,
  and `def` puts them on Starlette's threadpool. `tests/test_api.py` has a
  guard that fails if an `/api` handler becomes a coroutine.
- The pure core (`app/core/*`) imports no I/O, no network, no model, and
  **not `app.telemetry`**. Instrument it from its call site in `main.py`
  via `telemetry.measure("<op>")`.
- User-facing copy: plain words, the legal term goes in the frontend Help
  glossary, not the UI. "General information, not legal advice" stays.

---

## 2. Integration guardrails

### 2.1 Firebase Auth (`app/firebase.py`)

- Verify the Firebase ID token on **every** `/api` route via the
  `current_uid` dependency. No unauthenticated route may touch user data.
- The `uid` comes **only from the verified token**. No Pydantic model in
  `app/schemas.py` may carry a `uid`, `user_id`, `email`, or similar — if
  you need the caller's identity, take the `uid: str = Depends(current_uid)`
  parameter.
- `verify_id_token(..., check_revoked=True)` — keep the revocation check.
- Email from the token is **best-effort profile data only**, never trusted
  for authorization. Phone-auth users have no email; handle `""`.
- Any verification failure → `401` with no detail. Never echo the token,
  the reason, or a stack trace.

### 2.2 Cloud Firestore (`app/repo.py`)

- `firestore.rules` denies every direct client request. It stays that way
  — the client never gets a Firestore handle. The Admin SDK in
  `app/repo.py` is the only door.
- **Every** `repo` function takes `uid` and touches only
  `/users/{uid}/…` (or a `uid_hash`-keyed audit/counter doc). There must
  be no code path that reads or writes another user's subtree. If you add
  a collection, nest it under the user document.
- Drafts and audit entries are append-only / immutable. Edits create a
  new version, they don't mutate.
- Mutating routes accept an `Idempotency-Key` header
  (`repo.idempotency_get/put`) so a retry can't act twice.
- `delete_account` must recursively wipe the user subtree **and** call
  `fb_auth.delete_user(uid)` — data and identity both.

### 2.3 Secret Manager (`app/config.py`)

- Secrets are read only through `config.get_secret(name)`. Order: an
  UPPER_SNAKE env var of the same name (local dev / the Cloud Run
  `--set-secrets` injection), then Secret Manager.
- A secret value **never** appears in source, the client bundle, the
  container image, a Dockerfile `ENV` default, an error response, or a
  log line. `app/core/redact.py::scrub` runs on every log value; keep new
  secret shapes covered by its patterns.
- New secret → add it to `.env.example` (empty), the README one-time
  setup, and — if optional — guard its use so the app still runs when it
  is absent (see `evidence_signing_key()` returning `None`).
- The Cloud Run runtime service account gets the **minimum** roles:
  `roles/secretmanager.secretAccessor` + `roles/datastore.user`. Don't
  broaden.

### 2.4 Gemini — text (`app/gemini.py`)

- `app/gemini.py` is the **only** module that imports the model SDK. If
  another module needs the model, it calls `gemini.generate()`.
- `generate()` never raises to the caller. Every call path has: a 20s
  hard timeout (`HttpOptions(timeout=20_000)`), bounded retries **for
  transient failures only** (`_is_retryable` — a non-429 `ClientError`,
  and a depleted-credits / hard-quota 429, are terminal; a plain
  rate-limit 429 is retried), a circuit breaker, and a caller-supplied
  `fallback_text` template. On total failure it returns `ok=False` + the
  template.
- Model ids are the **`-latest` aliases** (`gemini-flash-latest`,
  `gemini-flash-lite-latest`) so a version retirement doesn't break the
  app — `gemini-2.5-flash` stopped serving new API keys. If you pin an
  explicit version, add it to `config._PRICE_INR`.
- Every call emits a `CostLog` log line and the `hisaab.gemini.*`
  telemetry. If you add a call site, record its cost via
  `limits.record(uid, res.est_inr)` and gate it with
  `rate_check(uid)` + `limits.precheck(uid)` **before** the call.
- Bound the input: trim history (`_trim_history`), cap
  `max_output_tokens`. Model output is untrusted input to the next step —
  treat prompt-injection in case text as expected and never let model
  output reach a deterministic decision unchecked.

### 2.5 Gemini — multimodal / file extraction

- Uploaded bytes: validate `mime` against an allow-list, confirm the
  base64 decodes, and re-check the **decoded** size against
  `EVIDENCE_MAX_BYTES` in the route (not just the Pydantic `max_length`).
  Cap items per case (`EVIDENCE_MAX_ITEMS`).
- The extraction prompt asks the model to transcribe only what is legible
  and to use `""` / `null` for anything it cannot read.
- **`_clean_extracted` validates every field the model returns**: a date
  that doesn't `date.fromisoformat` is dropped; strings are length-capped;
  numbers are coerced or nulled. The model never sets a value that flows
  onward unchecked (e.g. a bad `observed_date` must not populate
  `incident_date`).

### 2.6 Cost / abuse controls (`app/limits.py`, `app/ratelimit.py`)

- Any new model-calling route: `rate_check(uid, bucket=…)` then
  `limits.precheck(uid)` before the call, `limits.record(uid, est_inr)`
  after. Deterministic write routes use `bucket="write"`.
- The **authoritative** caps (daily per-uid, monthly cost ceiling) are
  Firestore-backed in `limits.py` so they hold across instances. The
  in-memory `ratelimit.py` is a per-process burst backstop — don't rely
  on it alone.
- When a limit is hit, return `429` but keep the **deterministic** routes
  (deadlines, evidence chain, saved data, template drafts) working. The
  app degrades to "no model", never to "down".

### 2.7 Evidence hash chain (`app/core/evidence_chain.py`)

- Pure crypto, no I/O. The `chain_hash` input order and separators are
  fixed and load-bearing — changing them breaks every stored chain.
  Version the schema instead.
- The manifest HMAC signing key comes from Secret Manager
  (`evidence-signing-key`); the manifest is still emitted (unsigned) when
  the key is absent. Never fall back to a hardcoded key.
- Don't claim more than the primitive proves: it shows the bytes were
  held at the server-stamped `captured_at` and nothing was reordered or
  altered since — not when a photo was originally taken.

### 2.8 OpenTelemetry (`app/telemetry.py`)

- Telemetry is a genuine no-op unless `HISAAB_OTEL` / an `OTEL_*`
  endpoint is set. Keep it that way — no hard dependency on a collector.
- Span and metric attributes must not carry PII: no raw `uid`, email,
  token, case title, message text, or file bytes. `trace_id` and
  `uid_hash` are fine.
- Instrument new deterministic core work from `main.py` with
  `telemetry.measure("<op>")`, not by importing telemetry into `core/`.

---

## 3. Deployment (`Makefile`, `Dockerfile`)

- `make deploy` runs `make gate` first and aborts on failure, then
  deploys in two phases (code, then pin `FRONTEND_ORIGIN` to the resolved
  service URL). Don't bypass the gate.
- `--workers 1` is deliberate (per-process burst state). Scaling is
  `--max-instances`; the cross-instance caps make that safe.
- `.dockerignore` / `.gcloudignore` keep `tests/`, `perf/`, `otel/`, and
  the venv out of the image. New dev-only tooling goes there too.
- Region is `asia-south1` (the users are in India); Firestore location is
  permanent.
