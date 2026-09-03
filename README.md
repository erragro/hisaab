# Hisaab (हिसाब)

**A private case journal for gig-worker payment and deactivation disputes.**

Built for the Google Cloud "Accelerate AI with Cloud Run" challenge.
Social post hashtag: `#AccelerateAIwithCloudRun`.

> General information about process and drafting. **Not legal advice.**

---

## The problem

India has 7–8 million gig and platform workers, heading to 23.5 million by 2030.
The 2025 Labour Codes and new state portals (Karnataka launched India's first
gig-worker grievance system in May 2026) created redressal channels — but they
are new, fragmented, and nobody helps a worker actually use them: organise the
facts, pick the right channel, draft the notice or complaint, and track the
deadlines. A dispute plays out over weeks across the app's own grievance flow,
then the state portal, then a consumer or labour route, and the worker has
nothing to hold it together.

**Hisaab is the worker-side companion.** Not a new redressal body — a private
place to run your case: talk it through with an assistant, get the documents
drafted, and see your deadlines.

Sibling to an earlier project, [Sreshtha](https://erragro.github.io/sreshtha-blog/),
which helps a worker *understand one contract*. Hisaab helps them *act on a
dispute over time*. Same problem, different product.

---

## How it works

1. **Start a case** — what happened, which platform, the amount, the date.
2. **Talk it through** — a real multi-turn conversation with Gemini about where
   you stand and what to do next. Every exchange is auto-summarised into a
   structured record (a dated fact timeline + next steps + a short summary) and
   saved privately.
3. **Generate a document** — a legal notice, a platform grievance, a consumer
   complaint, or a labour complaint. Gemini drafts the body.
4. **Readiness check (the enhancement)** — deterministic Python, not the model,
   decides whether the draft is actually ready to send, by checking every
   element the document type requires (the parties, a dated statement, the
   specific amount, a compliance deadline, ...). It also cross-checks: if the
   draft states a rupee figure that doesn't match the amount on the case, or
   if the 2-year consumer-limitation window has already closed, the draft is
   *not ready* — and the model doesn't get to say otherwise.
5. **Deadlines** — statutory and practical windows computed by date
   arithmetic in Python, never by the model: the notice period, the Consumer
   Protection Act's 2-year limit, the wage-claim outer limit, the platform's
   own SLA, and — for a deactivation — the **7-working-day** window to appeal
   to the platform's IDRC under the Karnataka Rules, 2025 (weekends and
   gazetted holidays excluded), plus the IDRC-disposal and Board-escalation
   clocks.

---

## The Algorithmic Appeal Record (the standout feature)

Legal commentary in 2026 keeps naming the same gap: a deactivated gig
worker "cannot make a meaningful case without some record of what drove the
decision" — but the platform holds all the data and locks the worker out of
the app the moment they're deactivated. Hisaab gives the worker their own
record.

1. **Evidence locker.** The worker uploads what they grabbed before lockout
   — the deactivation message, an in-app earnings screen, a ratings screen,
   a support chat, a payslip. Files are stored inline in the user's private
   Firestore subtree (≤ 900 KB each).
2. **Gemini reads it; Python keeps it.** `gemini-2.5-flash` (multimodal)
   transcribes the date shown, the rupee figure and its period, the stated
   reason, order/ticket IDs, a rating. The model never sets a date it can't
   actually read; Python validates every field before it's stored.
3. **Tamper-evident chain.** Each entry commits to `sha256(file)` + the
   server capture time + the previous entry's hash (`app/core/evidence_chain.py`,
   pure, unit-tested). Re-deriving the chain proves nothing was reordered,
   back-dated, or edited after upload. `GET /appeal-record` emits a portable
   manifest, HMAC-signed with a Secret Manager key, that a paralegal or the
   IDRC can verify offline.
4. **It feeds the rest.** A legible deactivation date auto-populates the
   case and recomputes the IDRC deadline. Earnings evidence drives a
   **deterministic lost-wages estimate** (`app/core/lostwages.py`): a
   baseline ₹/day from the payslips × days offline, with the working shown —
   which then becomes the amount claimed in the IDRC-appeal draft, and the
   readiness check verifies the draft's figure matches it.

---

## Architecture

```
Static PWA frontend — no build step (ES modules, one small CSS system,
  a service worker). Firebase Auth — phone/OTP primary, Google secondary.
  Timeline-centric: one
  scrolling "thread" per case with a pinned next-step card; a 3-action
  speed-dial is the whole in-case nav. Offline writes queue and sync.
  English + Hindi, adjustable text size, per-screen help.
        │  Authorization: Bearer <Firebase ID token>
        ▼
Cloud Run service — FastAPI (app/main.py)   [handlers are sync -> threadpool;
  │                                            the event loop is never blocked]
  ├─ app/firebase.py   verify ID token on every /api route; uid comes only from the token
  ├─ app/gemini.py     the ONLY module that imports the model SDK — 20s hard timeout,
  │                    bounded retries (transient only), circuit breaker,
  │                    template fallback, CostLog per call; text + multimodal
  ├─ app/core/*        deterministic core, all pure / no I/O / no model / unit-tested:
  │                    readiness.py, deadlines.py (working-day math), redact.py,
  │                    lostwages.py, evidence_chain.py (hash chain + signed manifest)
  ├─ app/limits.py     Firestore-backed daily cap + monthly cost ceiling (cross-instance)
  ├─ app/ratelimit.py  in-memory per-instance burst limit (backstop only)
  └─ app/repo.py       every Firestore path; every method uid-scoped to /users/{uid}/...
        │
        ├── Cloud Firestore   per-user subcollections (cases, messages, drafts,
        │                     evidence) + counters/; rules DENY all client access
        └── Secret Manager    gemini-api-key + evidence-signing-key -> env vars at deploy
```

**The model proposes; Python decides.** The model helps you think, drafts the
documents, narrates the numbers, and transcribes an uploaded screenshot. It
never produces a score, a deadline, a lost-wages figure, or the "ready to
send" verdict.

---

## Frontend design

The UI is built against the **SARAL** guidelines for low-literate smartphone
users (Srivastava et al., CSCW 2021) and access-to-justice legal-design
research:

- **One thread per case.** A dispute plays out over weeks; the case screen is
  a single vertical timeline that braids together the incident, every piece
  of proof (with what the model read off it), the conversation, the drafts,
  and the deadlines as future events.
- **A pinned "next step" card**, filled by the deterministic engine, always
  says the one thing to do and how long is left — as a big number
  (`3` working days), colour-coded red / amber / green. Numbers and dates are
  what low-literate users trust, so the UI leads with them.
- **Flat navigation.** No menus-within-menus: a 3-action speed-dial (📷 add
  proof · 💬 ask · 📄 make a document) and bottom sheets, one task per sheet.
- **Plain words in the UI, the legal term in Help** ("Complaint to the
  platform", not "IDRC petition") — reachable from every screen.
- **Multiple input modes**: camera-first evidence capture, voice input for
  chat (Web Speech API, `hi-IN` / `kn-IN` / …).
- **Sign in with a phone number + OTP** (the auth Indian users know from UPI
  and every govt portal); "Continue with Google" is the one-tap fallback.
  The backend is identical either way — the uid comes from the verified
  token, and email is treated as best-effort (phone users have none).
- **English + Hindi**, adjustable text size, both persisted.
- **Offline-first**: a service worker caches the shell; writes made offline
  queue in `localStorage` (idempotency-keyed) and flush on reconnect;
  installable as a PWA for a weak-connection phone.

No framework, no bundler — it still deploys as `COPY static/`. `static/demo.html`
renders the whole UI against mock data with no backend.

---

## Security

- Firebase ID token verified server-side on **every** `/api` route. No
  unauthenticated route touches user data.
- **No client-supplied uid is ever trusted** — request bodies carry no uid.
- 100% of Firestore access is backend, via `app/repo.py`, scoped to
  `/users/{uid}/...`. Firestore rules (`firestore.rules`) **deny every direct
  client request** — even a leaked web config reads nothing.
- Gemini key sourced from Secret Manager and injected by Cloud Run as the
  `GEMINI_API_KEY` env var (`--set-secrets`), read once via
  `app/config.get_secret`. Never in source, the client bundle, the image, a
  Dockerfile default, or a log. Least-privilege service account
  (`secretmanager.secretAccessor` + `datastore.user`). `make secret-scan`
  fails the build if a key literal or a tracked secret file appears.
- Structured JSON logs; `uid_hash` only, never the raw uid / email / token /
  user text — `scrub()` runs on every log value, including nested
  dicts/lists (`app/logging_setup.py` + `app/core/redact.py`).
- CORS is pinned to the frontend origin as defence in depth. It is **not**
  the abuse gate (the API and frontend share an origin; a scripted client
  ignores CORS) — the real gates are the token check and the rate limits.
- **Burst limit** per uid, in-memory per instance (20 / 5 min model, more
  for cheap writes) — a backstop that resets on restart.
- **Authoritative caps in Firestore**, so they hold across all instances:
  a per-uid daily model-call cap (`RATE_LIMIT_PER_DAY`) and a global
  monthly cost ceiling (`MONTHLY_COST_CEILING_INR`). When the monthly
  budget is spent, model endpoints return 429 and the deterministic app
  (saved cases, deadlines, template drafts) keeps working.
- Per-conversation turn cap; bounded model-input history; output-token cap.
- Mutating POSTs accept an `Idempotency-Key` header; a retried request
  returns the stored result instead of acting twice.
- "Delete account" recursively wipes the user's Firestore subtree **and**
  deletes the Firebase Auth identity.

---

## Run it locally

```bash
make install
cp .env.example .env         # add a Gemini key for local dev only
make emulators               # terminal 1: Firebase Auth + Firestore emulators
make run                     # terminal 2: the app on :8000
# fill firebaseConfig in static/js/auth.js from your Firebase console
```

## Test (the deploy gate)

```bash
make gate     # runs the full test suite + secret-scan; deploy depends on this
```

The suite covers the pure core (`readiness`, `deadlines`, `redact`), the
Gemini wrapper (retry/breaker/fallback), both rate-limit layers, and the
API routes end to end (auth, uid-scoping, idempotency, validation, the
cost ceiling) against an in-memory Firestore.

`make deploy` runs `make gate` first and aborts on failure, then deploys
in two phases (code, then pin `FRONTEND_ORIGIN` to the real service URL).

## Deploy

```bash
# one-time
gcloud services enable run.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com
printf '%s' "$GEMINI_KEY" | gcloud secrets create gemini-api-key --data-file=-
# optional: signs the exported appeal-record manifest (see below)
openssl rand -hex 32 | gcloud secrets create evidence-signing-key --data-file=-
gcloud iam service-accounts create hisaab-run
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:hisaab-run@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:hisaab-run@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
firebase deploy --only firestore:rules

# In the Firebase console (Authentication → Sign-in method), enable:
#   - Phone          (primary; SMS is billed past the free tier)
#   - Google         (secondary, one-tap)
# then paste the web config into static/js/auth.js
# every deploy
make deploy
```

---

## Scope / non-goals (honest)

- Single region (`asia-south1`), single service. No multi-region / HA failover.
- The daily cap and monthly cost ceiling are Firestore-backed and correct
  across instances; the extra in-memory burst limit is a per-instance
  backstop only. Idempotency and the per-case chat lock are best-effort
  within an instance — a simultaneous double request across two instances
  can still slip through.
- The legal windows in `deadlines.py` are common defaults; a real forum may
  apply a different period. Every computed deadline shows the basis it used.
- Readiness checks are structural, not a legal opinion: they confirm the
  document *contains* the required elements and that a stated amount matches
  the case and the limitation window is still open — they do not judge the
  argument.
- This is a drafting and organisation aid, not a substitute for a lawyer or a
  paralegal, and it says so.

---

## Threat model (summary)

| Threat | Mitigation |
|---|---|
| Cross-user data access | Rules deny client access; backend uid-scoped from a verified token; no client uid trusted |
| Key exfiltration | Secret Manager only; least-privilege SA; `make secret-scan`; key never in logs/errors |
| Prompt injection via case text | Model output is untrusted input to the next step; readiness + deadlines are deterministic; drafts are checked before they're "ready" |
| Model hallucination (wrong amount / deadline) | Deadlines computed in Python only. For the draft body, readiness fails the document if the amount it states doesn't match the case, or if the consumer-limitation window has already closed |
| Model / Firestore outage | `gemini.py` has a 20s hard timeout + circuit breaker and degrades to a template; the deterministic path still saves the case; blocking work is off the event loop so one slow call can't stall the instance |
| Cost blow-up / abuse | In-memory burst limit + Firestore-backed daily cap + **enforced** monthly cost ceiling (`app/limits.py`); turn cap; bounded input history; output-token cap; CostLog per call |
| Duplicate writes on retry | `Idempotency-Key` header on mutating POSTs; per-case lock serialises chat turns within an instance |
| PII in logs | `uid_hash` only; `scrub()` on every log value, recursively |
| Unauthenticated endpoint abuse | `/readyz` result cached ~10s so it can't amplify Firestore / Secret Manager load |
