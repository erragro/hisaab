# Hisaab — Engineering Documentation

> A private case journal for gig-worker payment and deactivation disputes in
> India. FastAPI + Firebase Auth + Cloud Firestore + Gemini, one Cloud Run
> service. Built for the Google Cloud *"Accelerate AI with Cloud Run"*
> challenge.

**Repository:** <https://github.com/erragro/hisaab>
**Live (scale-to-zero):** <https://hisaab-czz6dnltla-el.a.run.app>
**UI walkthrough (mock data, no backend):** <https://hisaab-czz6dnltla-el.a.run.app/demo.html>

---

## 0. What this document covers

This is a full technical reference for the system as it stands, plus a record
of the work done in the engineering session that produced the current state:

| Phase | Outcome |
|---|---|
| **Hardening pass** | ~29 findings from a critical review, all fixed; test suite 26 → 102 |
| **Algorithmic Appeal Record** | New feature — hash-chained evidence locker, multimodal extraction, working-day IDRC deadlines, lost-wages estimate |
| **Frontend rebuild** | Research-backed, timeline-centric, no-build PWA, English + Hindi |
| **Authentication** | Phone-number OTP primary, Google secondary |
| **Observability & load testing** | OpenTelemetry, a local Jaeger/Prometheus/Grafana stack, a Locust harness, concurrency tests |
| **Deployment** | Live on Cloud Run in `asia-south1`, scale-to-zero, pending two manual setup steps |

Size: `app/` ≈ 2,740 LOC Python, `static/js/` ≈ 1,480 LOC, `tests/` ≈ 1,400 LOC,
106 tests.

---

## 1. System overview

### 1.1 Core principle — *the model proposes, Python decides*

Gemini helps the worker think, drafts documents, narrates numbers, and
transcribes uploaded screenshots. It **never** produces a score, a deadline, a
lost-wages figure, or the "ready to send" verdict. Every number and every
gating decision is computed by pure, unit-tested Python in `app/core/`.

### 1.2 Architecture

```
 Browser — static PWA (no build step)
   • Firebase Auth: phone/OTP primary, Google secondary
   • timeline-centric UI, offline write queue, en/hi
        │  Authorization: Bearer <Firebase ID token>
        ▼
 Cloud Run service — FastAPI (app/main.py)
   route handlers are plain `def` → Starlette threadpool → event loop never blocks
   │
   ├─ app/firebase.py    verify ID token on every /api route; uid comes only from the token
   ├─ app/gemini.py      the ONLY module that imports the model SDK
   │                       20s hard timeout · transient-only retries · circuit breaker
   │                       · template fallback · CostLog · text + multimodal
   ├─ app/core/*         deterministic core, pure / no I/O / no model / unit-tested:
   │                       readiness · deadlines (working-day math) · lostwages
   │                       · evidence_chain (hash chain + HMAC manifest) · redact
   ├─ app/limits.py      Firestore-backed daily cap + enforced monthly cost ceiling
   ├─ app/ratelimit.py   in-memory per-instance burst limiter (backstop)
   ├─ app/telemetry.py   OpenTelemetry traces + metrics (no-op unless OTEL_* set)
   └─ app/repo.py        every Firestore path; every method scoped to /users/{uid}/…
        │
        ├── Cloud Firestore   per-user subcollections + counters/ ; rules DENY all client access
        └── Secret Manager    gemini-api-key + evidence-signing-key → env vars at deploy
```

### 1.3 Tech stack

| Layer | Choice | Version |
|---|---|---|
| API | FastAPI / Starlette on Uvicorn | fastapi 0.115.6, uvicorn 0.34.0 |
| Validation | Pydantic v2 | 2.10.4 |
| Model SDK | `google-genai` | 0.8.0 (`gemini-2.5-flash`, `gemini-2.5-flash-lite`) |
| Data | `google-cloud-firestore` (Admin SDK) | 2.19.0 |
| Auth | `firebase-admin` | 6.6.0 |
| Secrets | `google-cloud-secret-manager` | 2.21.1 |
| Logs | `structlog` (JSON) | 24.4.0 |
| Telemetry | OpenTelemetry SDK + OTLP/HTTP exporter + FastAPI/requests instrumentation | 1.44.0 / 0.65b0 |
| Frontend | Vanilla ES modules, one CSS system, a service worker — **no bundler** | — |
| Load testing | Locust (dev only) | 2.46.4 |
| Runtime | Python 3.13 (`python:3.13.7-slim`) | — |

### 1.4 Repository layout

```
app/            FastAPI service
  main.py           routes, middleware, lifespan, per-case lock, history trimming
  firebase.py       Admin SDK init + current_uid dependency (token verify)
  gemini.py         model wrapper (timeout/retry/breaker/fallback/multimodal)
  repo.py           all Firestore access, uid-scoped
  config.py         env config + get_secret() (env-var / Secret Manager)
  schemas.py        Pydantic request models (never carry a uid)
  prompts.py        system prompts (CONSTITUTION + per-task)
  limits.py         Firestore daily cap + monthly cost ceiling
  ratelimit.py      in-memory burst limiter
  logging_setup.py  structlog config + recursive scrub processor
  telemetry.py      OpenTelemetry setup + helpers
  core/
    readiness.py       deterministic "is this draft ready to send" check
    deadlines.py       working-day arithmetic + statutory/IDRC windows
    lostwages.py       lost-earnings estimate from evidence
    evidence_chain.py  tamper-evident hash chain + signed manifest
    redact.py          PII/secret scrubbing, uid_hash
static/         the PWA (served by the same service)
  index.html, demo.html, app.css, manifest.webmanifest, sw.js, icon*.svg
  js/  main · screens · actions · api · auth · i18n · ui · help
tests/          106 tests + fakefs.py (in-memory Firestore) + conftest.py
otel/           docker-compose stack: Collector + Jaeger + Prometheus + Grafana
perf/           serve_fake.py (real app + fakes) + locustfile.py
firestore.rules deny-all (defence in depth)
Dockerfile, Makefile, requirements*.txt
```

---

## 2. Request lifecycle

### 2.1 Authentication

1. The browser signs in with Firebase Auth (phone/OTP or Google) and obtains a
   Firebase **ID token**.
2. Every `/api/*` request carries `Authorization: Bearer <token>`.
3. `app.firebase.current_uid` (a **synchronous** FastAPI dependency) calls
   `firebase_admin.auth.verify_id_token(token, check_revoked=True)`. Any failure
   → `401`, no detail leaked. The decoded claims are stashed on
   `request.state.claims` so a handler that also needs the email
   (`create_case`) does not verify the token a second time.
4. **The uid comes only from the token.** No request body in `app/schemas.py`
   carries a uid.

Phone and Google are interchangeable at this layer — the uid is stable per
identity and email is treated as best-effort (phone users have none).

### 2.2 Handlers run in a threadpool

Every route handler and `current_uid` are plain `def`, not `async def`. The
work underneath them — `verify_id_token`, the Firestore Admin SDK, the
`google-genai` SDK — is **synchronous and blocking**. Declaring the handlers
`def` makes Starlette run them in its worker threadpool (anyio, 40 tokens by
default, matching `--concurrency=40`), so a slow model call occupies one worker
thread and **never stalls the event loop**. This is verified under load
(§9.4). A regression test (`tests/test_api.py::test_route_handlers_are_sync…`)
fails if any `/api` handler becomes a coroutine.

### 2.3 Middleware & handlers

| Order | Component | Purpose |
|---|---|---|
| outermost | `trace` middleware | assigns `request.state.trace_id`; wraps the request in `telemetry.inflight()`; adds `X-Trace-Id` response header |
| | `CORSMiddleware` | `allow_origins=[FRONTEND_ORIGIN]` — defence in depth only (API + frontend share an origin) |
| | FastAPI OTel instrumentation | request spans + `http.server.*` metrics (when telemetry is on) |
| exception | `@app.exception_handler(Exception)` | `HTTPException` → `{"error": detail}`; anything else → logged with a scrubbed one-liner + `{"error":"internal error"}` 500 |
| routes | see §2.4 | |
| mount | `StaticFiles(directory="static", html=True)` at `/` | serves the PWA |

### 2.4 API surface

| Method | Path | Notes |
|---|---|---|
| GET | `/livez` (and `/healthz`) | liveness — `/healthz` is swallowed by Cloud Run's front end, hence `/livez` |
| GET | `/readyz` | Firestore + Secret Manager reachability; result cached 10 s (unauthenticated → can't be used to amplify load) |
| POST | `/api/cases` | create; `Idempotency-Key` honoured |
| GET | `/api/cases` | list (most-recent 100) |
| GET | `/api/cases/{id}` | case + messages + drafts + deadlines + evidence + lost-wages estimate |
| POST | `/api/cases/{id}/chat` | multi-turn; rate-limited; per-case lock; auto-summarise |
| POST | `/api/cases/{id}/draft` | model drafts body → **`check_readiness` decides** → stored immutably |
| POST | `/api/cases/{id}/deadlines` | fully deterministic; `bucket="write"` rate limit |
| POST | `/api/cases/{id}/evidence` | upload → multimodal extract → hash-chain → store |
| GET | `/api/cases/{id}/evidence/{ev}` | one item incl. base64 bytes |
| GET | `/api/cases/{id}/appeal-record` | signed, verifiable manifest of the evidence chain |
| GET | `/api/cases/{id}/lost-wages` | deterministic lost-earnings estimate |
| GET | `/api/export` | full user export (JSON) |
| DELETE | `/api/account` | recursive Firestore wipe **+ Firebase Auth user delete** |

### 2.5 Firestore data model

```
users/{uid}                                  { email, createdAt, schemaVersion }
  cases/{caseId}                             { title, issue_type, platform,
                                               amount_claimed_inr, incident_date,
                                               status, facts[], next_steps[], summary,
                                               createdAt, updatedAt, schemaVersion }
    messages/{msgId}                         { role, text, ts }
    drafts/{draftId}                         { kind, body, readiness{}, createdAt }   (immutable)
    evidence/{evId}                          { kind, filename, mime, size, sha256,
                                               prev_hash, chain_hash, seq, captured_at,
                                               captured_hint, data_b64, extracted{},
                                               model_degraded, createdAt }
    meta/deadlines                           { items[], computedAt }
  counters/calls-YYYY-MM-DD                  { model_calls, updatedAt }   (daily cap)
  idempotency/{key}                          { response{}, ts }
counters/cost-YYYY-MM                        { spent_inr, updatedAt }      (monthly ceiling)
audit/{id}                                   { ts, event, uid_hash }       (append-only, no PII)
```

`firestore.rules` is `allow read, write: if false` for every path — **no client
ever holds a Firestore handle**. The Admin SDK (`app/repo.py`) is the only door,
and every method is scoped to `/users/{uid}/…`.

---

## 3. The deterministic core (`app/core/`)

All four modules are **pure**: no I/O, no network, no model, no `app.telemetry`
import. They are timed from their call sites in `app/main.py`
(`telemetry.measure("readiness" | "deadlines" | "lost_wages" | "evidence_chain")`).

### 3.1 `readiness.py` — "is this draft ready to send"

The model writes the document body; this module decides whether it is actually
sendable, by checking that every element the document type requires is present —
partly from the structured case fields, partly from the draft text.

**Per-kind checklists** (`_CHECKLISTS`) with a **required** subset (`_REQUIRED`)
that blocks sending vs. recommended checks that only lower the score:

| kind | required checks |
|---|---|
| `legal_notice` | sender, recipient, dated statement, **amount**, **deadline** |
| `platform_grievance` | worker_id, platform, **amount**, clear ask |
| `consumer_complaint` | complainant, opposite party, cause-of-action date, dated facts, relief, **limitation still open** |
| `labour_complaint` | worker, employer, nature of claim, amount + period |

**The cross-checks** (this is what makes it more than keyword-spotting):

- **Amount** — `_amount_check` parses every rupee figure in the draft
  (`_RUPEE_AMOUNT`). If the case records `amount_claimed_inr` **and** the draft
  states a *different* figure, the check **fails** with a note
  (`"draft cites ₹X but the case records ₹Y"`) — unless the drafted figure is
  within 10 % of a computed lost-wages estimate. The model cannot quietly
  change the number.
- **Limitation** — the consumer-complaint `limitation` check calls
  `deadlines.consumer_limitation(incident_date)` and **fails if the 2-year
  window has already closed** (`"the 2-year limitation window closed on …"`).
- **Deadline context** — `_DEADLINE_PHRASE` only counts "within N days" when it
  sits next to a demand verb (*pay / comply / respond / …*) or a consequence
  clause (*failing which / of this notice / …*), so a narrative sentence
  ("the platform replied within 3 days") does not satisfy it.
- **None-safety** — `_s()` coerces `None`/`0`/`[]` to `""` before `.strip()`,
  so a Firestore document with null party fields cannot crash the check.

**Output** (`Readiness.to_dict()`): `kind`, `checks[]` (`id/label/ok/note`),
`score` (fraction of *all* checks passing), `required_passed`,
`required_total`, `ready` (bool), `missing[]` (labels of failed required
checks). The frontend shows **"Ready to send"** vs
**"Not ready — N required item(s) missing"**, plus "X of Y checks passed" — it
never shows a misleading "ready · 71 %".

### 3.2 `deadlines.py` — working-day arithmetic + statutory windows

**Working-day engine.** `is_working_day(d)` = weekday and not in
`INDIA_HOLIDAYS` (a conservative fixed-date gazetted-holiday set for 2026-2027;
festival dates deliberately excluded — a missed holiday only makes a deadline
look *tighter*, never looser). `add_working_days(start, n)` and
`working_days_between(a, b)` build on it.

**Windows** (`build_case_deadlines`, all inputs optional, missing inputs
skipped — no guessing):

| kind | computed from | basis string cites |
|---|---|---|
| `consumer_limitation` | incident + 2 years | Consumer Protection Act, 2019, s.69 |
| `wage_limitation` | incident + 3 years | general limitation for money claims |
| `notice_period` | notice sent + N days | your own notice period |
| `platform_sla` | grievance filed + N days | the platform's promised turnaround |
| `idrc_appeal` | termination + **7 working days** | Karnataka Platform-Based Gig Workers Rules, 2025 |
| `idrc_disposal` | appeal filed + **15 working days** | ″ |
| `idrc_grievance` | grievance filed + 14 days | ″ |
| `board_escalation` | grievance filed + 30 days | ″ |

`idrc_appeal` fires only when `issue_type == "deactivation"`. Every returned
`Deadline` carries `due_date`, `from_date`, `basis`, `days_remaining`
(calendar), `working_days_remaining` (set for working-day windows), and
`passed`. `_years_out` clamps Feb 29 → Feb 28 on non-leap years.

### 3.3 `lostwages.py` — lost-earnings estimate

`estimate_lost_wages(earnings_samples, deactivated_on, until=today)`:

- `earnings_samples` are `{amount_inr, period_days, source}` dicts, derived by
  `app.main._earnings_samples` from evidence entries of kind `earnings_screen`
  / `payslip` that have an extracted amount **and** period.
- Garbage samples are dropped (`EarningsSample.valid()` — bounds on both fields).
- `daily_rate = Σ amount / Σ period_days`; `days_offline` = calendar days in
  `[deactivated_on, until]` inclusive (capped at today); `estimate = daily_rate
  × days_offline`.
- Returns `None` if there isn't enough to compute an honest number.
- The `basis` string shows the full working. It feeds the IDRC-appeal draft
  prompt and the readiness amount cross-check (§3.1).

### 3.4 `evidence_chain.py` — tamper-evident record

The trust primitive behind the Appeal Record (§6).

- `sha256_hex(bytes)` — the file commitment.
- `chain_hash(prev_hash, file_sha256, captured_at, kind)` =
  `sha256("\n".join([prev_hash or "GENESIS", file_sha256, captured_at, kind]))`
  — order and separators fixed so it is reproducible from the stored fields.
- `link(prev_entry, …)` — returns `{seq, prev_hash, chain_hash}` for a new
  entry following `prev_entry` (`None` for the first).
- `verify(entries)` — re-walks the chain: contiguous `seq`, `prev_hash` matches
  the previous `chain_hash`, and each `chain_hash` matches its own fields.
  Returns `{ok, length, broken_at, reason}`. Detects reordering, editing, and
  deletion.
- `manifest(entries, signing_key)` — a portable summary (no file bytes, just
  the commitments) + `verify()` result + an **HMAC-SHA256 signature** over the
  canonical JSON, using a Secret Manager key. Unsigned (but still emitted) when
  no key is configured.

**Scope, honestly:** this does not prove *when* a screenshot was taken — only
that the worker held these exact bytes at the server-stamped `captured_at`, and
that nothing was inserted or altered afterwards.

### 3.5 `redact.py` — PII / secret hygiene

`uid_hash(uid)` = first 12 hex of SHA-256 (stable, non-reversible; `"anon"`
for empty). `scrub(text)` removes Google API keys, `Bearer …` tokens, emails,
and any 40+ char opaque token. `safe_error(exc)` → a scrubbed one-line
`Type: message`, truncated to 300 chars **after** scrubbing.

---

## 4. The model wrapper (`app/gemini.py`)

The **only** module that imports the Gemini SDK. `generate()` never raises to
the caller — on total failure it returns `GeminiResult(ok=False, …)` with
`text` set to a safe template, so a route can always complete from the
deterministic path.

| Concern | Implementation |
|---|---|
| **Timeout** | `genai.Client(http_options=HttpOptions(timeout=20_000))` — 20 s hard cap (was previously a dead `_TIMEOUT_S` constant) |
| **Retries** | up to 3 attempts, backoff `min(2**attempt + rand, 8)` s — **only for transient failures**: `_is_retryable` returns `False` for a `ClientError` that isn't a 429 (bad request, auth, safety block), so those fail fast |
| **Circuit breaker** | 5 consecutive failures → breaker open for 30 s; `generate()` returns the fallback immediately while open. State guarded by a `threading.Lock` |
| **Fallback** | caller passes `fallback_text` (a filled template); `parse_json` returns `None` on any failure so the caller never falls back to raw text |
| **Multimodal** | `generate(media=[(bytes, mime), …])` → `_with_media` builds native `types.Content` with `Part.from_bytes`; used for evidence extraction |
| **CostLog** | every successful call logs `event_type="CostLog"` with `in_tokens`, `out_tokens`, `est_inr` (`config.est_cost_inr` — unknown model bills at the most expensive known tier), `price_known`, `latency_ms`, `attempt` |
| **Telemetry** | a `gemini.generate` span + `hisaab.gemini.{calls,latency,tokens,cost_inr}` metrics on every return path |

Bounded input: `app.main._trim_history` caps the conversation sent to the model
at 30 messages / 12 000 chars regardless of the turn cap; `max_output_tokens`
is capped per call.

---

## 5. Spend & abuse guards

Two layers, checked in this order on the model-calling routes:

1. **`ratelimit.check(uid, bucket=…)`** — in-memory sliding window, **per
   process**. Buckets: `model` (20 / 5 min, 60 / day) and `write` (higher, for
   `/deadlines`). A backstop that resets on restart. Drained deques are swept
   every 500 calls so idle uids don't leak memory. Emits
   `hisaab.ratelimit.rejections{bucket,window}` on a 429.
2. **`limits.precheck(uid)`** — **Firestore-backed, cross-instance**:
   - monthly cost ceiling: `counters/cost-YYYY-MM.spent_inr ≥
     MONTHLY_COST_CEILING_INR` → 429 (`reason="monthly_ceiling"`). The monthly
     total is cached per instance for 60 s to bound reads.
   - per-uid daily cap: `users/{uid}/counters/calls-YYYY-MM-DD.model_calls ≥
     RATE_LIMIT_PER_DAY` → 429 (`reason="daily_cap"`).
   - `limits.record(uid, est_inr)` after each model call increments both
     counters with `firestore.Increment`. **Chat makes two model calls** (reply
     + auto-summary), so it consumes the daily *model-call* cap twice as fast
     as a draft — intended, since the cap protects cost.

When the model budget is spent, the routes return 429 but **the deterministic
app keeps working** (verified in §9.5).

**Other guards:** per-conversation turn cap (`MAX_TURNS_PER_CASE * 2`
messages); per-case `threading.Lock` in `chat` (§2 — non-blocking acquire, a
concurrent same-case turn gets 409 rather than interleaving the history or
clobbering the summary); `Idempotency-Key` header on the mutating POSTs
(`repo.idempotency_get/put`, best-effort within an instance); output-token cap.

---

## 6. The Algorithmic Appeal Record

### 6.1 The problem

Research (Aug–Sep 2026) into India's gig-worker redressal landscape surfaced a
named, documented gap:

- **Karnataka's grievance system (live May 2026)** runs on punishing
  *working-day* clocks: appeal a termination to the platform's Internal Dispute
  Resolution Committee within **7 working days**; IDRC disposes termination
  appeals in **15 working days**; grievances resolved in 14 days; escalate to
  the Welfare Board within 30 days.
  ([Karnataka Platform-Based Gig Workers Rules, 2025](https://www.argus-p.com/updates/updates/karnataka-platform-based-gig-workers-social-security-and-welfare-rules-2025/))
- **Workers have no contemporaneous record.** Legal commentary explicitly calls
  for an *"algorithmic appeal record"* — a worker "cannot make a meaningful
  case without some record of what drove the decision," but the platform holds
  all the data and locks the worker out of the app the moment they're
  deactivated.
  ([Countercurrents, Aug 2026](https://countercurrents.org/2026/08/indias-gig-worker-protections-need-an-algorithmic-appeal-record/) ·
  [LiveLaw](https://www.livelaw.in/lawschool/articles/algorithmic-deactivation-article14-karnataka-gig-worker-litigation-542390))
- **Lost wages during a wrongful deactivation** is an emerging remedy that
  needs the worker's *historical earnings data* — the exact thing they lose.
  ([FareShare, arXiv 2505.08904](https://arxiv.org/html/2505.08904v1))
- Unions (IFAT, Telangana's TGPWU — 25-30 deactivation cases/week) organise on
  WhatsApp; nothing structures a worker's own proof or timestamps it.

### 6.2 What was built

**A — Evidence locker (multimodal + tamper-evident chain).** The worker
uploads what they grabbed before lockout. `POST /api/cases/{id}/evidence`:

1. `EvidenceIn` validates `kind` (deactivation_notice / earnings_screen /
   ratings_screen / support_chat / payslip / other), `mime` (png/jpeg/webp/
   pdf), and that `data_b64` decodes; the route re-checks the decoded size
   against `EVIDENCE_MAX_BYTES` (≈ 900 KB) and `EVIDENCE_MAX_ITEMS` (40).
2. `gemini.generate(media=[(raw, mime)], want_json=True)` with `EVIDENCE_SYSTEM`
   — `gemini-2.5-flash-lite` transcribes: the date visible *in the image*, the
   rupee figure and its period, the platform's stated reason, order/ticket IDs,
   a rating value, a ≤ 25-word summary.
3. `_clean_extracted` validates every field — **a date that doesn't parse is
   dropped**, strings are length-capped, the model never sets a value it
   couldn't read.
4. `evidence_chain.link()` computes `seq`, `prev_hash`, `chain_hash` from the
   file SHA-256 + server `captured_at` + `kind`.
5. `repo.add_evidence` stores it (base64 inline in Firestore — no Cloud Storage
   dependency).
6. If it's a `deactivation_notice` with a legible date and the case has no
   `incident_date` yet, `_maybe_apply_evidence_date` populates it and
   recomputes deadlines — so Hisaab immediately shows *"IDRC appeal due Fri —
   3 working days left."*

`GET /api/cases/{id}/appeal-record` → `evidence_chain.manifest(entries,
signing_key=config.evidence_signing_key())` — the portable, HMAC-signed,
independently-verifiable record.

**B — Working-day IDRC deadlines** — §3.2.

**C — Lost-wages estimate** — §3.3. `app.main._lost_wages` runs on
`GET /api/cases/{id}` and `/lost-wages` for deactivation cases, and threads
`lost_wages_inr` into `check_readiness` so an IDRC-appeal draft that states the
computed figure passes the amount check.

### 6.3 Why it scores as a standout

It closes a gap legal writers are naming *right now*; uses Gemini multimodal
for something genuinely hard (OCR of messy Indian payslips / app screens); adds
a real trust primitive (a verifiable chain, not a gimmick); and makes every
existing feature better (real deadline inputs, real amounts, grounded chat)
instead of bolting on something orthogonal.

---

## 7. Frontend

### 7.1 Design basis

Built against **SARAL** — 13 actionable UI guidelines for low-literate
smartphone users synthesised from two decades of HCI research
([Srivastava et al., CSCW 2021](https://anupriyatuli.github.io/publications/2021_CSCW.pdf)) —
plus access-to-justice legal-design research and offline-first patterns.

| Research finding | In Hisaab |
|---|---|
| Flat navigation, one task per screen (G3/G6/G7) | No tabs. A case is **one scrolling thread**; a 3-action speed-dial (📷 add proof · 💬 ask · 📄 make a document) + bottom sheets are the entire in-case nav |
| Low-literate users trust numbers & dates (G2) | A pinned **"next step" card** — the one action + a big colour-coded countdown (`3` working days), filled by the deterministic engine |
| Colour-coded urgency as the primary cue (G4) | Red / amber / green (`urgency()`), working-day-aware, runs through pills, card borders, timeline nodes |
| Keep jargon out of the UI (G5) | "Complaint to the platform", not "IDRC petition"; the legal term lives in the per-screen **Help** sheet's glossary |
| Multiple input modes (G1) | Camera-first evidence capture; **voice input** for chat (Web Speech API, `hi-IN` / `kn-IN` / …) |
| Culturally responsive, local language (G11) | ₹ everywhere; **English + Hindi** (full string tables); Noto Sans Devanagari; text-size toggle — all persisted |
| Legal case = a chronology | The timeline **braids** the incident, every proof (+ what the model read off it), the conversation, drafts (+ readiness), and deadlines as future events |
| Offline-first for weak connections | Service worker shell cache; offline writes queue (idempotency-keyed) and flush on reconnect; installable PWA |

### 7.2 No-build architecture

ES modules loaded directly by the browser — **no bundler, no framework, no
transpile**. Still deploys as `COPY static/`.

| Module | Responsibility |
|---|---|
| `js/main.js` | bootstrap: auth gate, hash routing (`#/` , `#/case/:id`), topbar, FAB, offline bar, the ☰ menu, service-worker registration |
| `js/auth.js` | Firebase Auth, **lazily imported** (`import()` inside a function) so a blocked CDN or `/demo.html` never breaks the app; phone/OTP + Google; `window.__mockUser` dev seam |
| `js/api.js` | fetch helper — bearer token, `Idempotency-Key` on every mutation, an **offline queue** in `localStorage` that flushes on `online`; `window.__mockApi` dev seam |
| `js/screens.js` | the two screens: Home (case list + per-card urgency pill) and Case (the timeline + `computeNextStep` + record strip + lost-wages card) |
| `js/actions.js` | the bottom sheets: new case, evidence, chat, draft, view-draft, dates |
| `js/i18n.js` | `LANGS`, string tables (`en`, `hi` complete), `t(key, vars)`, `applyStatic(root)` for `[data-t]` nodes |
| `js/ui.js` | `el()` DOM builder, bottom-sheet primitive, toast, `urgency()`, `pill()`, `fmtDate`, `rupees` |
| `js/help.js` | per-screen help text + plain-word → legal-term glossary |

### 7.3 The timeline model

`screens.renderCase` fetches `GET /api/cases/{id}` and assembles a single
`items[]` sorted by date: the incident, each evidence item (icon by kind + a
lazily-fetched thumbnail + extracted-fact chips), the conversation collapsed to
"You talked this through — N messages" (expandable inline), each draft with its
readiness pill, and every deadline as a future node with an urgency rail.

`computeNextStep(data)` picks the pinned card: the nearest live deadline
(sorted by `days_remaining`, including recently-passed actionable ones), with a
primary button that opens the matching action; else a not-ready draft to
finish; else "you're on track". The countdown uses `working_days_remaining`
when the deadline has it.

### 7.4 PWA

`sw.js` (`hisaab-v5`) — **network-first** for the app's own HTML/CSS/JS so a
deploy is picked up immediately and stale code never sticks, falling back to
cache offline; **stale-while-revalidate** for Google Fonts; `/api/*` is never
touched. `manifest.webmanifest` + SVG icons make it installable.

### 7.5 Authentication flow

- **Landing:** `+91` prefix + 10-digit field → **"Send code"** (primary);
  **"Continue with Google"** below.
- **`startPhoneSignIn(e164)`** → `RecaptchaVerifier` (invisible) →
  `signInWithPhoneNumber` → returns a confirmation object.
- **OTP sheet:** 6-digit field that auto-submits when full; "Send the code
  again" (resets the verifier); "Change number". `confirmation.confirm(code)`
  → Firebase `onAuthStateChanged` fires → the app screen shows.
- Firebase error codes are mapped to plain messages
  (`invalid-phone` → "Enter your 10-digit mobile number", etc.).

### 7.6 `demo.html` + dev seams

`static/demo.html` sets `window.__mockUser` and `window.__mockApi` (a small
in-memory API with a realistic deactivation case: urgent IDRC deadline, three
evidence items with a hash chain, a not-ready draft, a ₹6,853 lost-wages
estimate) and loads the real `js/main.js`. It renders the entire UI with no
backend — the shareable walkthrough. `auth.js` / `api.js` short-circuit to the
mocks when those globals are set; in production they are never set.

---

## 8. Observability (`app/telemetry.py` + `otel/`)

### 8.1 Design

- **A genuine no-op unless turned on.** `HISAAB_OTEL=1`, or an
  `OTEL_EXPORTER_OTLP_ENDPOINT`, or `OTEL_TRACES_EXPORTER` activates it;
  otherwise the OTel API returns no-op tracers/meters and the `record_*`
  helpers cost a few dict operations.
- When on, `init(app)` sets a `Resource` (`service.name=hisaab`,
  `service.version`, `deployment.environment`), a `TracerProvider` +
  `BatchSpanProcessor`, a `MeterProvider` + `PeriodicExportingMetricReader`,
  instruments FastAPI (`excluded_urls="livez,healthz,readyz"`) and `requests`,
  and sets `OTEL_SEMCONV_STABILITY_OPT_IN=http` so metrics carry a **templated
  `http.route`** (`/api/cases/{case_id}/chat`) rather than a high-cardinality
  target.
- Standard `OTEL_*` env vars are respected. In production, point
  `OTEL_EXPORTER_OTLP_ENDPOINT` at the Cloud Trace / Monitoring OTLP receiver —
  nothing else changes.
- **The pure core never imports this module.** Readiness / deadlines /
  lost-wages / the hash chain are timed from their call sites in `main.py` via
  `telemetry.measure("<op>")`, which emits a `core.<op>` span **and** a
  `hisaab.deterministic.latency{op}` metric.

### 8.2 What it emits

| Signal | Where |
|---|---|
| `gemini.generate` span (model, want_json, multimodal, ok, fell_back, latency) + nested `gemini.request{attempt}` | `gemini.py` |
| `hisaab.gemini.{calls,latency,tokens,cost_inr}` | `gemini.py` (`_finish`) |
| `core.{readiness,deadlines,lost_wages,evidence_chain}` spans + `hisaab.deterministic.latency{op}` | `main.py` (`telemetry.measure`) |
| `hisaab.readiness.{checks{kind,ready},score{kind}}` | `main.py` after `check_readiness` |
| `hisaab.evidence.uploads{kind,degraded}` | `main.py` evidence route |
| `hisaab.ratelimit.rejections{bucket,window}` | `ratelimit.py` |
| `hisaab.limits.rejections{reason}` + `limits.precheck` span | `limits.py` |
| `hisaab.requests.inflight` | `trace` middleware (`telemetry.inflight()`) |
| FastAPI request spans + `http.server.request.duration` (+ size, active) | FastAPI instrumentation |

### 8.3 The local stack (`otel/docker-compose.yml`)

| Service | Image | Port | Role |
|---|---|---|---|
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.103.1` | 4318 (OTLP HTTP), 4317, 8889 | receives OTLP → Jaeger (traces) + Prometheus scrape endpoint (metrics) |
| `jaeger` | `jaegertracing/all-in-one:1.57` | 16686 | trace UI |
| `prometheus` | `prom/prometheus:v2.53.0` | 9090 | scrapes `otel-collector:8889` every 5 s |
| `grafana` | `grafana/grafana:11.1.0` | 3001 (`GRAFANA_PORT`) | anonymous-admin; provisioned Prometheus + Jaeger datasources + an 11-panel Hisaab dashboard |

`make otel-up` / `make otel-down` / `make otel-logs`.

---

## 9. Performance & load testing

### 9.1 The fake harness (`perf/serve_fake.py`)

Runs the **real** FastAPI app with Firebase and Gemini stubbed *before*
`app.main` is imported (the same monkeypatch approach as `tests/conftest.py`,
reusing `tests/fakefs.py`). The fake model **`time.sleep`s** for
`GEMINI_FAKE_LATENCY_MS` (blocking, exactly like the real SDK) then returns a
canned reply, and records the same `hisaab.gemini.*` metrics. Auth accepts
`Bearer <uid>:token`. This measures the app's own overhead and threadpool
behaviour with realistic model latency, no external services, no bill.

### 9.2 The load profile (`perf/locustfile.py`)

Each virtual user is a gig worker: opens a case on start, then a weighted mix
of `view_case` (6), `deadlines` (4), `list_cases` (3), `chat` (3),
`evidence` (2), `draft` (2), `appeal_record` (1). `make load` starts the fake
server with OTel on, runs Locust headless (`LOAD_USERS`, `LOAD_TIME`,
`GEMINI_FAKE_LATENCY_MS` overridable), and tears down.

### 9.3 The concurrency tests (`tests/test_perf.py`, marked `perf`, **excluded from `make gate`**)

Run with `make test-perf`. Uses `httpx.ASGITransport` + `asyncio.gather` with a
model fixture that blocks for `DELAY = 0.15 s`:

| Test | Asserts |
|---|---|
| `test_deterministic_endpoint_fast_under_load` | 60 concurrent `POST /deadlines` finish in **< 2 s total** |
| `test_slow_model_does_not_block_the_event_loop` | while 12 slow `POST /draft` are in flight, a `GET /api/cases` returns in **< DELAY** — the loop isn't blocked |
| `test_per_case_lock_rejects_concurrent_same_case_chats` | 5 concurrent same-case chats → exactly **1×200 + 4×409**; 5 chats on 5 different cases all 200 and run concurrently |
| `test_throughput_smoke` | prints req/s for `GET /api/cases/{id}` (~1,700/s local) |

### 9.4 Load-test result — 60 users, 60 s, fake model @ 250 ms

**1,402 requests · 0 failures · 0 server errors · ~23.5 req/s**

| endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `GET /api/cases`, `/api/cases/{id}`, `POST /deadlines`, `GET /appeal-record` | 4–5 ms | **8–10 ms** | 15–18 ms |
| `POST /draft`, `POST /evidence` (1 model call) | 260 ms | 270 ms | 270 ms |
| `POST /chat` (2 sequential model calls) | 510 ms | 520 ms | 520 ms |

**The headline:** with 60 users hammering endpoints that each pin a worker
thread for 250–540 ms, the deterministic endpoints still answer at **8–10 ms
p95**. That is the "sync handlers → threadpool, event loop never blocked"
property proven under sustained load, not just asserted.

Prometheus cross-check for the same run: 553 Gemini calls (274 flash + 279
flash-lite), gemini p95 242 ms, **est spend ₹22.12** (would trip the ₹40
monthly ceiling in ~2 runs), deterministic core p95 ≤ 4.75 ms, 106 readiness
verdicts all `ready=false` (the load's draft omits an address — the engine
correctly withholds "ready"). Jaeger shows the `/chat` span waterfall:
`limits.precheck` (0 ms) + `gemini.generate` × 2 (~24 ms + ~21 ms).

### 9.5 Abuse scenario — one uid, limits tightened to 15/5 min, 25/day, ₹5 ceiling

45 rapid `POST /chat` from one user → **13 × 200, 32 × 429**. Metrics:
`hisaab_ratelimit_rejections{bucket=model,window=5min}` = 30,
`hisaab_limits_rejections{reason=daily_cap}` = 2 (13 chats × 2 model calls ≈
the 25 daily cap). The throttled user's `POST /deadlines` still returned
**200** — the deterministic app stays up when the model budget is spent.

---

## 10. Testing

`make gate` = **102 tests** (`pytest -m "not perf"`) + `make secret-scan`.
`make test-perf` = the 4 timing-sensitive concurrency tests.

| File | # | Covers |
|---|---|---|
| `test_api.py` | 25 | routes end to end — auth, uid-scoping, idempotency, validation (422 not 500), turn cap, rate limit, monthly ceiling, evidence chain + auto-populate, appeal-record manifest, 413 oversize, lost-wages, export/delete, sync-handler regression guard |
| `test_deadlines.py` | 19 | statutory windows, leap-day clamp, working-day arithmetic + holiday skipping, IDRC windows, `build_case_deadlines` |
| `test_readiness.py` | 14 | per-kind checklists, required vs recommended, wrong-amount fail, time-barred fail, narrative-deadline fail, None-safety, `to_dict` shape |
| `test_gemini.py` | 8 | success, retry-then-fallback, empty-response, no-retry-when-not-retryable, breaker opens & short-circuits, `parse_json`, `_is_retryable` 429 vs 400, media attached to the last user turn |
| `test_redact.py` | 7 | `uid_hash`, `scrub` (key/bearer/email, keeps ordinary text), recursive `_scrub_event`, `safe_error` |
| `test_evidence_chain.py` | 6 | genesis link, valid chain, tampered-bytes / reorder / delete detection, signed vs unsigned manifest |
| `test_limits.py` | 6 | precheck passes empty, monthly ceiling blocks, daily cap blocks (per-uid), `record` increments both, cache TTL, failure swallowed |
| `test_schemas.py` | 5 | ISO-date validators on `CaseCreate` and `PartyIn`, day bounds, required names |
| `test_ratelimit.py` | 5 | model bucket ceiling, bucket independence, daily ceiling, user isolation, sweep evicts drained deques |
| `test_lostwages.py` | 4 | basic estimate, `None` without samples/date, garbage samples dropped, `until` capped at today |
| `test_perf.py` | 4 | §9.3 |

**`tests/fakefs.py`** — a ~150-line in-memory stand-in for the Firestore Admin
client: `collection/document/get/set/update/create/delete/collections`,
`order_by/limit/stream/get`, `count()`, and `firestore.Increment` handling.
Lets the route and limits tests run end to end with zero external services.

**`make secret-scan`** — greps the tree for `AIza…` keys and hardcoded
`GEMINI_API_KEY`/`GOOGLE_API_KEY`/`api_key` literals; checks no `.env` /
service-account file is git-tracked. (This gate was previously *broken* — it
tripped on the `AIza…` test fixtures in `test_redact.py`, so `make deploy`
could never pass. The fixtures now build key-shaped strings at runtime.)

---

## 11. Security posture

| Threat | Mitigation |
|---|---|
| Cross-user data access | `firestore.rules` deny all client access; every `repo.py` method scoped to `/users/{uid}/…` from a **token-verified** uid; no schema carries a uid |
| Key exfiltration | key sourced from Secret Manager, injected as an env var by Cloud Run; never in source, the client bundle, the image, or a log; `make secret-scan` in the gate |
| Prompt injection via case text | model output is untrusted input to the next step; readiness + deadlines are deterministic; a draft is checked before it's "ready" |
| Model hallucination (wrong amount / deadline) | deadlines computed in Python only; readiness **fails** the draft if its amount ≠ the case, or if the consumer-limitation window has closed |
| Model / Firestore outage | `gemini.py` — 20 s timeout + circuit breaker → template; deterministic path still saves the case; blocking work is off the event loop so one slow call can't stall the instance |
| Cost blow-up / abuse | in-memory burst limit + Firestore daily cap + **enforced** monthly ceiling; turn cap; bounded input; output-token cap; `CostLog` + telemetry |
| Duplicate writes on retry | `Idempotency-Key` on mutating POSTs; per-case lock serialises chat turns within an instance |
| PII in logs | `uid_hash` only; `scrub()` on every log value, recursively (dicts/lists too) |
| Unauthenticated endpoint abuse | `/readyz` result cached ~10 s so it can't amplify Firestore / Secret Manager load |
| Frontend XSS | every DOM write is `textContent` / `el()`; no `innerHTML` sink for user or model data |
| CSRF | bearer token in a header, not a cookie — no CSRF surface |

**Honest limits:** rate-limit *burst* window and idempotency and the per-case
lock are best-effort *within an instance* (cross-instance a simultaneous double
request can still slip through — the daily cap and monthly ceiling are the
cross-instance guards). The IDRC/limitation windows in `deadlines.py` are the
common defaults with the basis shown; a real forum may differ. This is a
drafting and organisation aid, not legal advice, and says so.

---

## 12. Configuration reference

All via environment (`.env.example` is the template; nothing is read from a
file in production).

| Var | Default | Meaning |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | — | GCP / Firebase project id (Firestore, Secret Manager, Auth) |
| `GEMINI_API_KEY` | — | local dev only; in prod injected from Secret Manager `gemini-api-key` |
| `EVIDENCE_SIGNING_KEY` | — | HMAC key for the appeal-record manifest; from Secret Manager `evidence-signing-key`; optional (manifest still emitted unsigned) |
| `FRONTEND_ORIGIN` | `http://localhost:8000` | CORS allow-origin; deploy pins it to the service URL |
| `FIRESTORE_EMULATOR_HOST` / `FIREBASE_AUTH_EMULATOR_HOST` | — | local emulators |
| `GEMINI_MODEL_CHAT` | `gemini-2.5-flash` | chat + draft model |
| `GEMINI_MODEL_UTILITY` | `gemini-2.5-flash-lite` | auto-summary + evidence extraction |
| `MAX_TURNS_PER_CASE` | `20` | × 2 = message cap per case |
| `MAX_OUTPUT_TOKENS` | `1024` | per-call output cap |
| `RATE_LIMIT_PER_5MIN` / `RATE_LIMIT_PER_DAY` | `20` / `60` | burst limiter (in-memory) **and** the Firestore daily model-call cap |
| `MONTHLY_COST_CEILING_INR` | `40` | Firestore monthly spend ceiling |
| `EVIDENCE_MAX_BYTES` / `EVIDENCE_MAX_ITEMS` | `900000` / `40` | per-file decoded size / items per case |
| `HISAAB_OTEL` | unset | `1` turns telemetry on |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | also turns telemetry on; the collector / Cloud Trace receiver |
| `OTEL_TRACES_EXPORTER` | `otlp` | `console` to dump to stdout |
| `GEMINI_FAKE_LATENCY_MS` | `250` | `perf/serve_fake.py` only |

**Secrets in the deployed project:** `gemini-api-key`,
`evidence-signing-key`. The runtime service account
(`hisaab-run@…`) has `roles/secretmanager.secretAccessor` +
`roles/datastore.user`.

---

## 13. Build & deployment

### 13.1 Dockerfile

`python:3.13.7-slim`, non-root user, `pip install -r requirements.txt`, `COPY
app/ static/`, `CMD uvicorn app.main:app --workers 1`. `--workers 1` is
deliberate: the burst-limiter state is per-process, and the authoritative caps
are in Firestore. `.dockerignore` / `.gcloudignore` exclude `.venv`, `tests/`,
`perf/`, `otel/`, `requirements-dev.txt`.

### 13.2 Makefile targets

| Target | Does |
|---|---|
| `install` / `install-dev` | venv + `requirements.txt` (+ `requirements-dev.txt`) |
| `test` | `pytest -m "not perf"` |
| `test-perf` | the 4 concurrency tests |
| `secret-scan` | key-pattern grep + tracked-secret check |
| `gate` | `test` + `secret-scan` — **deploy depends on this** |
| `run` | local uvicorn with `--reload` on :8000 |
| `emulators` | Firebase Auth + Firestore emulators |
| `otel-up` / `otel-down` / `otel-logs` | the local observability stack |
| `perf-serve` | the fake app + OTel on |
| `load` | `perf-serve` + Locust headless + teardown |
| `deploy` | `gate`, then the two-phase Cloud Run deploy |
| `rollback` | list revisions + the traffic-split command |

### 13.3 The two-phase deploy

```
phase 1  gcloud run deploy hisaab --source . --region asia-south1 \
           --allow-unauthenticated --min-instances=1 --max-instances=5 \
           --concurrency=40 --cpu=1 --memory=512Mi --timeout=90 \
           --service-account=hisaab-run@… \
           --set-secrets=GEMINI_API_KEY=gemini-api-key:latest[,EVIDENCE_SIGNING_KEY=…] \
           --set-env-vars=GOOGLE_CLOUD_PROJECT=…
phase 2  resolve the service URL, then
         gcloud run services update hisaab --update-env-vars=FRONTEND_ORIGIN=<url>
```

Phase 2 exists because `FRONTEND_ORIGIN` can't be known until the service URL
exists (the first deploy previously produced a broken origin). The
`--set-secrets` list includes `EVIDENCE_SIGNING_KEY` only if that secret
exists (a `$(shell gcloud secrets describe …)` check in the Makefile).

### 13.4 GCP resources created

| Resource | Value |
|---|---|
| Project | `gen-lang-client-0368265372` (owner: `surajit.chaudhuri.95@gmail.com`, billing on) |
| APIs enabled | `firestore`, `secretmanager`, `identitytoolkit`, `iamcredentials` (+ `run`, `cloudbuild`, `artifactregistry` pre-existing) |
| Firestore | `(default)` database, **`asia-south1`**, native mode — *permanent, cannot be moved* |
| Secrets | `gemini-api-key` (**placeholder** — see §13.6), `evidence-signing-key` (random 32-byte) |
| Service account | `hisaab-run@gen-lang-client-0368265372.iam.gserviceaccount.com` + 2 IAM bindings |
| Cloud Run service | `hisaab`, `asia-south1`, `--allow-unauthenticated`, currently **`min-instances=0`** (scale to zero), `max-instances=5` |
| Artifact Registry | `cloud-run-source-deploy` repo (auto-created) |

### 13.5 The `/healthz` → `/livez` quirk

`GET /healthz` on Cloud Run returns the **Google Front End's own 404** before
the request reaches the container — `/healthz` behaves as a reserved path.
`/readyz`, `/`, and `/api/*` all reach the app normally. The fix: `/livez` is
the liveness route (both `@app.get("/livez")` and `@app.get("/healthz")` map to
the handler; only `/livez` is reachable externally). Cloud Run's default
startup probe is TCP on `:8080`, so nothing depended on `/healthz`.

### 13.6 Current deployment state & remaining manual steps

**Live and healthy:** `/readyz` → `{"ok":true,"firestore":true,"secret_manager":true}`,
`/api/cases` → 401, all static assets → 200, `/demo.html` fully functional.
Scale-to-zero (~2–4 s cold start after idle, then back to zero).

The `gemini-api-key` secret holds a **placeholder** and `firebaseConfig` in
`static/js/auth.js` is still `REPLACE_ME`, so:

1. **Real Gemini key** —
   `printf '%s' "<key>" | gcloud secrets versions add gemini-api-key --data-file=- --project=gen-lang-client-0368265372`
   then bump traffic (`gcloud run services update hisaab --region=asia-south1`).
   Until then model calls degrade to templates.
2. **Firebase** — console → add Firebase to the project → Authentication →
   enable **Phone** + **Google** → copy the web config into
   `static/js/auth.js` → `firebase deploy --only firestore:rules` → `make
   deploy`. Until then nobody can sign in.

When ready, `make deploy` restores `--min-instances=1` (a warm instance for
judging).

---

## 14. Session changelog

| Commit | Summary |
|---|---|
| [`24e8f16`](https://github.com/erragro/hisaab/commit/24e8f16) | **Hardening pass + Algorithmic Appeal Record** — the ~29 fixes below, plus `deadlines.py` working-day engine + IDRC windows, `evidence_chain.py`, `lostwages.py`, multimodal `gemini.py`, evidence routes, 26 → 102 tests |
| [`027b46b`](https://github.com/erragro/hisaab/commit/027b46b) | **Frontend rebuild** — no-build ES modules, timeline-centric, PWA, en/hi i18n, `demo.html` |
| [`4ac61d8`](https://github.com/erragro/hisaab/commit/4ac61d8) | **Phone OTP auth** primary + Google secondary; lazy Firebase load |
| [`706b946`](https://github.com/erragro/hisaab/commit/706b946) | **Observability + load testing** — `telemetry.py`, `otel/` stack, `perf/`, `tests/test_perf.py` |
| [`26cfdb0`](https://github.com/erragro/hisaab/commit/26cfdb0) | `/livez` route (Cloud Run swallows `/healthz`) |

### 14.1 Hardening findings

**Critical**

| # | Finding | Fix |
|---|---|---|
| C1 | Async route handlers doing blocking I/O — one slow Gemini call stalls the whole instance | handlers + `current_uid` → plain `def` (threadpool); regression test |
| C2 | "Every call has a timeout" was false — `_TIMEOUT_S` was a dead constant | `HttpOptions(timeout=20_000)` on the client |
| C3 | Monthly cost ceiling defined but **never enforced** | `app/limits.py` — Firestore `counters/cost-YYYY-MM`, checked in `precheck`, incremented in `record` |
| C4 | Rate limit was per-process; deploy runs up to 5 instances → 5× the intended limit | Firestore-backed daily cap (authoritative); in-memory limiter demoted to a burst backstop |
| C5 | Readiness checks were keyword-spotting — a draft with the *wrong* amount, or a time-barred complaint, passed | amount cross-check vs the case; consumer `limitation` check calls `deadlines`; `_DEADLINE_PHRASE` requires demand/consequence context |
| C6 | `check_readiness` crashed on `None`-valued party fields | `_s()` coerces `None`/`0`/`[]` before `.strip()` |

**High**

| # | Finding | Fix |
|---|---|---|
| H1 | `PartyIn.notice_sent` / `grievance_filed` unvalidated → 500 on a bad date | shared `_iso_date` validator |
| H2 | `/deadlines` had no rate limit → Firestore write amplification | `rate_check(uid, bucket="write")` |
| H3 | `/readyz` unauthenticated, hit Firestore + Secret Manager every call | 10 s in-process cache |
| H4 | "Writes idempotent, keyed by id" was false — double-submit duplicated | `Idempotency-Key` header + `repo.idempotency_get/put` on the mutating POSTs |
| H5 | Account deletion left the Firebase Auth user (re-sign-in recreated the account); recursive delete was O(n²) and fragile | correct paginated depth-first delete + `fb_auth.delete_user(uid)` |
| H6 | `list_messages` returned the **oldest** N — chat context froze once a case exceeded the limit | `order_by ts DESC, limit, reverse` → the most recent N |

**Medium** — M1 reuse token claims instead of a second `verify_id_token`;
M2 retry classification (don't burn backoff on a 400/safety block);
M3 bounded model-input history; M4 evict drained rate-limit deques;
M5 recursive log scrubbing; M6 "Ready to send" instead of "ready · 71 %";
M7 CORS documented as defence-in-depth, not the abuse gate;
M8 per-case chat lock; M9 corrected the Secret-Manager-path docs.

**Low** — L1 `secret-scan` broadened **and fixed** (it tripped on the
`AIza…` test fixtures, so `make gate` could never pass);
L2 `.dockerignore` / `.gcloudignore`; L3 pinned base image;
L4 `lifespan` instead of `on_event`;
L5 unknown-model cost falls back to the most expensive tier;
L6 emulator gate accepts `127.0.0.1`;
L7 two-phase deploy fixes first-deploy `FRONTEND_ORIGIN`;
L8 targeted `filterwarnings` instead of a blanket `DeprecationWarning` ignore.

---

## Appendix — command cheat-sheet

```bash
make install-dev          # venv + prod + dev deps
make gate                 # 102 tests + secret-scan  (the deploy gate)
make test-perf            # the 4 concurrency tests
make run                  # local :8000  (needs .env + emulators)
make emulators            # Firebase Auth + Firestore emulators

make otel-up              # Jaeger :16686 · Grafana :3001 · Prometheus :9090
make load                 # real app + fakes + Locust headless + OTel
make otel-down

make deploy               # gate → two-phase Cloud Run deploy
gcloud secrets versions add gemini-api-key --data-file=- --project=gen-lang-client-0368265372   # add the real key

# telemetry to stdout, no stack:
HISAAB_OTEL=1 OTEL_TRACES_EXPORTER=console make run
```
