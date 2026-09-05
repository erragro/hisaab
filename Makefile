SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip
REGION ?= asia-south1
SERVICE ?= hisaab
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
SA := $(SERVICE)-run@$(PROJECT).iam.gserviceaccount.com

# GEMINI_API_KEY is required; EVIDENCE_SIGNING_KEY is added only if the secret exists
SECRETS := GEMINI_API_KEY=gemini-api-key:latest$(shell gcloud secrets describe evidence-signing-key >/dev/null 2>&1 && echo ',EVIDENCE_SIGNING_KEY=evidence-signing-key:latest')

OTEL_ENDPOINT ?= http://localhost:4318
PERF_PORT ?= 8800
LOAD_USERS ?= 50
LOAD_TIME ?= 60s
GEMINI_FAKE_LATENCY_MS ?= 250

.PHONY: venv install install-dev test test-perf emulators run rules deploy gate \
        secret-scan otel-up otel-down otel-logs perf-serve load

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -q -r requirements.txt

install-dev: install
	$(PIP) install -q -r requirements-dev.txt

# --- the lab gate: everything below deploy depends on this ---
gate: test secret-scan
	@echo "GATE PASSED"

test:
	$(PY) -m pytest -q

# timing-sensitive concurrency / throughput tests (excluded from `test`)
test-perf:
	$(PY) -m pytest -q -o addopts="" -m perf -s tests/test_perf.py

# --- observability + load testing -------------------------------------------
otel-up:
	cd otel && docker compose up -d
	@echo "Jaeger  http://localhost:16686   Grafana http://localhost:3000   Prometheus http://localhost:9090"

otel-down:
	cd otel && docker compose down

otel-logs:
	cd otel && docker compose logs -f otel-collector

# run the real app with in-memory fakes + OTel on (Ctrl-C to stop)
perf-serve:
	HISAAB_OTEL=1 OTEL_EXPORTER_OTLP_ENDPOINT=$(OTEL_ENDPOINT) \
	OTEL_SERVICE_NAME=hisaab GEMINI_FAKE_LATENCY_MS=$(GEMINI_FAKE_LATENCY_MS) \
	PORT=$(PERF_PORT) $(PY) -m perf.serve_fake

# headless load test: starts the perf server, runs Locust, tears down
load:
	@HISAAB_OTEL=1 OTEL_EXPORTER_OTLP_ENDPOINT=$(OTEL_ENDPOINT) OTEL_SERVICE_NAME=hisaab \
	 GEMINI_FAKE_LATENCY_MS=$(GEMINI_FAKE_LATENCY_MS) PORT=$(PERF_PORT) \
	 $(PY) -m perf.serve_fake & echo $$! > /tmp/hisaab-perf.pid ; \
	 sleep 3 ; \
	 .venv/bin/locust -f perf/locustfile.py --headless -u $(LOAD_USERS) -r 10 \
	   -t $(LOAD_TIME) --host http://127.0.0.1:$(PERF_PORT) ; \
	 kill $$(cat /tmp/hisaab-perf.pid) 2>/dev/null ; rm -f /tmp/hisaab-perf.pid

# Scans exactly what could be committed: git-tracked + untracked-not-ignored
# files (so a gitignored .env holding your local key never trips it). Outside
# a git repo it falls back to a filtered recursive scan.
secret-scan:
	@echo "scanning committable files for key patterns…"
	# Firebase Web API keys identify a project and are intentionally public; auth.js
	# is the sole allowlisted browser configuration file.
	@if git rev-parse --git-dir >/dev/null 2>&1 ; then \
	  git ls-files -z --cached --others --exclude-standard \
	    | xargs -0 grep -lIE 'AIza[0-9A-Za-z_-]{20,}' 2>/dev/null \
	    | grep -vx 'static/js/auth.js' \
	    | grep -q . \
	    && { echo "FAIL: Google API key pattern in a committable file"; exit 1; } || true ; \
	  git ls-files -z --cached --others --exclude-standard ':!.env.example' \
	    | xargs -0 grep -lIE '(GEMINI_API_KEY|GOOGLE_API_KEY|api_key)[ ]*[:=][ ]*["'"'"'][^"'"'"']{20,}' 2>/dev/null \
	    && { echo "FAIL: hardcoded API key literal"; exit 1; } || true ; \
	  git ls-files -- '*.env' 'serviceAccountKey.json' '*-service-account*.json' 2>/dev/null | grep -q . \
	    && { echo "FAIL: a secret file is tracked by git"; exit 1; } || true ; \
	else \
	  grep -RlIE 'AIza[0-9A-Za-z_-]{20,}' --exclude-dir=.venv --exclude-dir=.git \
	    --exclude-dir=node_modules --exclude-dir=.pytest_cache --exclude='*.pyc' \
	    --exclude='.env' --exclude='.env.*' . \
	    && { echo "FAIL: Google API key pattern found in source"; exit 1; } || true ; \
	fi
	@echo "secret-scan clean"

emulators:
	firebase emulators:start --only auth,firestore

run:
	FRONTEND_ORIGIN=http://localhost:8000 $(PY) -m uvicorn app.main:app --reload --port 8000

rules:
	gcloud firestore databases update --project=$(PROJECT) >/dev/null 2>&1 || true
	firebase deploy --only firestore:rules --project=$(PROJECT)

deploy: gate
	# phase 1: deploy the code. Rate limits + the monthly cost ceiling are
	# Firestore-backed (app/limits.py), so >1 instance is fine.
	gcloud run deploy $(SERVICE) \
	  --source . \
	  --project $(PROJECT) \
	  --region $(REGION) \
	  --allow-unauthenticated \
	  --min-instances=1 --max-instances=5 --concurrency=40 --cpu=1 --memory=512Mi \
	  --timeout=90 \
	  --service-account=$(SA) \
	  --set-secrets=$(SECRETS) \
	  --set-env-vars=GOOGLE_CLOUD_PROJECT=$(PROJECT) \
	  --update-labels=dev-tutorial=cloud-run-ai-challenge
	# phase 2: now that the URL exists, pin CORS to it (idempotent on re-deploy)
	URL=$$(gcloud run services describe $(SERVICE) --region=$(REGION) \
	        --project=$(PROJECT) --format='value(status.url)') ; \
	  test -n "$$URL" || (echo "could not resolve service URL" && exit 1) ; \
	  gcloud run services update $(SERVICE) --region=$(REGION) --project=$(PROJECT) \
	    --update-env-vars=FRONTEND_ORIGIN=$$URL ; \
	  echo "FRONTEND_ORIGIN pinned to $$URL"

rollback:
	@echo "revisions:"; gcloud run revisions list --service=$(SERVICE) --region=$(REGION) --format='value(name)'
	@echo "then: gcloud run services update-traffic $(SERVICE) --region=$(REGION) --to-revisions=<REV>=100"
