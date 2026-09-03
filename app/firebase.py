"""
app/firebase.py
===============
One-time Firebase Admin init (Auth + Firestore) and the token-verify
dependency.

Constitution rule 3: verify the Firebase ID token server-side on every
request; never trust a client-supplied uid.
"""

from __future__ import annotations

import firebase_admin
from fastapi import Depends, Header, HTTPException, Request, status
from firebase_admin import auth as fb_auth
from firebase_admin import firestore

from app.config import PROJECT_ID

_app = None


def _init() -> None:
    global _app
    if _app is not None:
        return
    opts = {"projectId": PROJECT_ID} if PROJECT_ID else None
    # Application Default Credentials in prod (the Cloud Run service account);
    # the emulators need no credentials.
    _app = firebase_admin.initialize_app(options=opts)


def db() -> "firestore.Client":
    _init()
    return firestore.client()


def current_uid(request: Request, authorization: str = Header(default="")) -> str:
    """
    FastAPI dependency. Returns the verified uid or raises 401.
    The uid comes ONLY from the token — request bodies never carry a uid.

    Sync (not async) on purpose: verify_id_token is a blocking call, so this
    and every route that depends on it run in Starlette's worker threadpool
    and never block the event loop.

    The decoded claims are stashed on request.state so a handler that also
    needs the email doesn't have to verify the token a second time.
    """
    _init()
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=True)
    except Exception:  # noqa: BLE001 - any failure is a 401, no detail leaked
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token has no uid")
    request.state.claims = decoded
    return uid


UidDep = Depends(current_uid)
