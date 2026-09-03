SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip
REGION ?= asia-south1
SERVICE ?= hisaab
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
SA := $(SERVICE)-run@$(PROJECT).iam.gserviceaccount.com

# GEMINI_API_KEY is required; EVIDENCE_SIGNING_KEY is added only if the secret exists
SECRETS := GEMINI_API_KEY=gemini-api-key:latest$(shell gcloud secrets describe evidence-signing-key >/dev/null 2>&1 && echo ',EVIDENCE_SIGNING_KEY=evidence-signing-key:latest')

.PHONY: venv install test emulators run rules deploy gate secret-scan

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -q -r requirements.txt

# --- the lab gate: everything below deploy depends on this ---
gate: test secret-scan
	@echo "GATE PASSED"

test:
	$(PY) -m pytest -q

secret-scan:
	@echo "scanning tree for key patterns…"
	@! grep -RInE 'AIza[0-9A-Za-z_-]{20,}' \
	  --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.pytest_cache \
	  --exclude='*.pyc' . \
	  || (echo "FAIL: Google API key pattern found in source" && exit 1)
	@! grep -RInE '(GEMINI_API_KEY|GOOGLE_API_KEY|api_key)[ ]*[:=][ ]*["'"'"'][^"'"'"']{20,}' \
	  --include='*.py' --include='*.js' --include='*.ts' --include='*.json' --include='*.yaml' \
	  --include='*.yml' --include='*.sh' --include='*.toml' --include='Dockerfile' --include='Makefile' \
	  --exclude=.env.example --exclude-dir=.venv --exclude-dir=.git --exclude-dir=node_modules . \
	  || (echo "FAIL: hardcoded API key literal" && exit 1)
	@if git rev-parse --git-dir >/dev/null 2>&1; then \
	  git ls-files -- '*.env' 'serviceAccountKey.json' '*-service-account*.json' 2>/dev/null | grep -q . \
	    && (echo "FAIL: a secret file is tracked by git" && exit 1) || true ; \
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
