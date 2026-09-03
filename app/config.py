"""
app/config.py
=============
Config + the ONE way secrets are read.

Constitution rule 4: the Gemini API key is read from Secret Manager at
runtime via the service account. It never appears in source, the client
bundle, the container image, an env default, or a log.

Local dev is the only exception: if GEMINI_API_KEY is set in the
environment (from a git-ignored .env), it's used, through the *same*
`get_secret()` interface so the code path is identical in prod.
"""

from __future__ import annotations

import functools
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # local only; no-op in prod where there is no .env

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:8000")

# The "-latest" aliases always resolve to the current release, so these don't
# break when a new Gemini flash version ships (as 2.5-flash did — it is no
# longer available to new API-key users). Override per environment if needed.
GEMINI_MODEL_CHAT = os.environ.get("GEMINI_MODEL_CHAT", "gemini-flash-latest")
GEMINI_MODEL_UTILITY = os.environ.get("GEMINI_MODEL_UTILITY", "gemini-flash-lite-latest")

MAX_TURNS_PER_CASE = int(os.environ.get("MAX_TURNS_PER_CASE", "20"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))
RATE_LIMIT_PER_5MIN = int(os.environ.get("RATE_LIMIT_PER_5MIN", "20"))
RATE_LIMIT_PER_DAY = int(os.environ.get("RATE_LIMIT_PER_DAY", "60"))
MONTHLY_COST_CEILING_INR = float(os.environ.get("MONTHLY_COST_CEILING_INR", "40"))

IS_EMULATED = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))

# rough public-price estimates, INR per 1M tokens, for the CostLog and the
# monthly-ceiling accounting only. Not billing-accurate — verify against
# current Gemini pricing if the ceiling matters precisely.
_PRICE_INR = {
    "gemini-flash-latest":        {"in": 30.0, "out": 250.0},
    "gemini-3.6-flash":           {"in": 30.0, "out": 250.0},
    "gemini-flash-lite-latest":   {"in": 10.0, "out": 36.0},
    "gemini-2.5-flash":           {"in": 25.0, "out": 210.0},
    "gemini-2.5-flash-lite":      {"in": 8.0,  "out": 30.0},
}
# for an unknown / overridden model id, bill at the most expensive tier we
# know so the monthly ceiling errs on the side of stopping early.
_PRICE_FALLBACK = max(_PRICE_INR.values(), key=lambda p: p["in"] + p["out"])


def price_known(model: str) -> bool:
    return model in _PRICE_INR


def est_cost_inr(model: str, in_tokens: int, out_tokens: int) -> float:
    p = _PRICE_INR.get(model, _PRICE_FALLBACK)
    return round((in_tokens * p["in"] + out_tokens * p["out"]) / 1_000_000, 4)


class SecretError(RuntimeError):
    pass


@functools.lru_cache(maxsize=8)
def get_secret(name: str) -> str:
    """
    Return a secret value. Order:
      1. env var of the same UPPER_SNAKE name  (local dev only)
      2. Secret Manager, latest version        (prod)
    Never logs the value. Raises SecretError if it cannot be resolved.
    """
    env_name = name.upper().replace("-", "_")
    if os.environ.get(env_name):
        return os.environ[env_name].strip()

    if not PROJECT_ID:
        raise SecretError(
            f"cannot resolve secret '{name}': no {env_name} env var and "
            "GOOGLE_CLOUD_PROJECT is not set"
        )
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
        resp = client.access_secret_version(request={"name": path})
        return resp.payload.data.decode("utf-8").strip()
    except Exception as exc:  # noqa: BLE001 - surface a safe message
        raise SecretError(f"Secret Manager lookup for '{name}' failed") from exc


def gemini_api_key() -> str:
    return get_secret("gemini-api-key")


# --- evidence locker ------------------------------------------------------
# decoded-size cap for one uploaded file (base64 stored inline in Firestore;
# a Firestore document is limited to ~1 MiB total)
EVIDENCE_MAX_BYTES = int(os.environ.get("EVIDENCE_MAX_BYTES", str(900_000)))
EVIDENCE_MAX_ITEMS = int(os.environ.get("EVIDENCE_MAX_ITEMS", "40"))


def evidence_signing_key() -> Optional[str]:
    """HMAC key for the appeal-record manifest signature. Optional: if it is
    not configured the manifest is still emitted, just unsigned."""
    try:
        return get_secret("evidence-signing-key")
    except SecretError:
        return None
