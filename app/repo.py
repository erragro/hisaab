"""
app/repo.py
===========
Every Firestore path in the app is built here, and every method takes
`uid` and touches only `/users/{uid}/...`. There is no code path that
reads or writes another user's data. Firestore rules deny all direct
client access; this module (Admin SDK) is the only door.

Constitution rule 8: decisions/drafts are immutable — edits create a new
version doc. rule 16: writes are idempotent, keyed by id.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from google.cloud import firestore

from app.firebase import db
from app.schemas import SCHEMA_VERSION


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid_doc(uid: str):
    return db().collection("users").document(uid)


# --- user ------------------------------------------------------------------
def ensure_user(uid: str, email: str) -> None:
    ref = _uid_doc(uid)
    if not ref.get().exists:
        ref.set({"email": email, "createdAt": _now(),
                 "schemaVersion": SCHEMA_VERSION})
        audit("user_created", uid)


# --- cases ---------------------------------------------------------------
def create_case(uid: str, data: dict) -> str:
    case_id = uuid.uuid4().hex
    _uid_doc(uid).collection("cases").document(case_id).set({
        **data,
        "id": case_id,
        "status": "active",
        "facts": [],
        "next_steps": [],
        "summary": "",
        "createdAt": _now(),
        "updatedAt": _now(),
        "schemaVersion": SCHEMA_VERSION,
    })
    return case_id


def list_cases(uid: str) -> list[dict]:
    q = (_uid_doc(uid).collection("cases")
         .order_by("updatedAt", direction=firestore.Query.DESCENDING).limit(100))
    return [_ser(d.to_dict()) for d in q.stream()]


def get_case(uid: str, case_id: str) -> Optional[dict]:
    d = _uid_doc(uid).collection("cases").document(case_id).get()
    return _ser(d.to_dict()) if d.exists else None


def patch_case(uid: str, case_id: str, patch: dict) -> None:
    ref = _uid_doc(uid).collection("cases").document(case_id)
    if not ref.get().exists:
        raise KeyError(case_id)
    ref.update({**patch, "updatedAt": _now()})


# --- messages ----------------------------------------------------------
def add_message(uid: str, case_id: str, role: str, text: str) -> None:
    (_uid_doc(uid).collection("cases").document(case_id)
     .collection("messages").document(uuid.uuid4().hex)
     .set({"role": role, "text": text, "ts": _now()}))


def list_messages(uid: str, case_id: str, limit: int = 200) -> list[dict]:
    """Return the most recent `limit` messages, in chronological order.
    (order_by('ts').limit() would return the OLDEST — the wrong end.)"""
    q = (_uid_doc(uid).collection("cases").document(case_id)
         .collection("messages")
         .order_by("ts", direction=firestore.Query.DESCENDING).limit(limit))
    rows = [_ser(d.to_dict()) for d in q.stream()]
    rows.reverse()
    return rows


def message_count(uid: str, case_id: str) -> int:
    col = (_uid_doc(uid).collection("cases").document(case_id)
           .collection("messages"))
    try:
        return int(col.count().get()[0][0].value)  # aggregation query
    except Exception:  # noqa: BLE001 - emulator / API variance: fall back
        return sum(1 for _ in col.stream())


# --- drafts (immutable, versioned) ----------------------------------
def add_draft(uid: str, case_id: str, kind: str, body: str, readiness: dict) -> dict:
    draft_id = uuid.uuid4().hex
    doc = {"id": draft_id, "kind": kind, "body": body, "readiness": readiness,
           "createdAt": _now(), "schemaVersion": SCHEMA_VERSION}
    (_uid_doc(uid).collection("cases").document(case_id)
     .collection("drafts").document(draft_id).set(doc))
    return _ser(doc)


def list_drafts(uid: str, case_id: str) -> list[dict]:
    q = (_uid_doc(uid).collection("cases").document(case_id)
         .collection("drafts").order_by("createdAt",
                                        direction=firestore.Query.DESCENDING))
    return [_ser(d.to_dict()) for d in q.stream()]


# --- evidence (append-only, hash-chained) -------------------------
def _evidence_col(uid: str, case_id: str):
    return (_uid_doc(uid).collection("cases").document(case_id)
            .collection("evidence"))


def last_evidence(uid: str, case_id: str) -> Optional[dict]:
    q = (_evidence_col(uid, case_id)
         .order_by("seq", direction=firestore.Query.DESCENDING).limit(1))
    rows = [d.to_dict() for d in q.stream()]
    return rows[0] if rows else None


def add_evidence(uid: str, case_id: str, doc: dict) -> dict:
    ev_id = uuid.uuid4().hex
    stored = {**doc, "id": ev_id, "createdAt": _now(),
              "schemaVersion": SCHEMA_VERSION}
    _evidence_col(uid, case_id).document(ev_id).set(stored)
    return _ser(stored)


def evidence_count(uid: str, case_id: str) -> int:
    col = _evidence_col(uid, case_id)
    try:
        return int(col.count().get()[0][0].value)
    except Exception:  # noqa: BLE001
        return sum(1 for _ in col.stream())


def list_evidence(uid: str, case_id: str, *, include_data: bool = False) -> list[dict]:
    q = _evidence_col(uid, case_id).order_by("seq")
    out = []
    for d in q.stream():
        row = _ser(d.to_dict())
        if not include_data:
            row.pop("data_b64", None)
        out.append(row)
    return out


def get_evidence(uid: str, case_id: str, ev_id: str) -> Optional[dict]:
    d = _evidence_col(uid, case_id).document(ev_id).get()
    return _ser(d.to_dict()) if d.exists else None


# --- deadlines (recomputed, deterministic) ------------------------
def set_deadlines(uid: str, case_id: str, deadlines: list[dict]) -> None:
    (_uid_doc(uid).collection("cases").document(case_id)
     .collection("meta").document("deadlines")
     .set({"items": deadlines, "computedAt": _now()}))


def get_deadlines(uid: str, case_id: str) -> list[dict]:
    d = (_uid_doc(uid).collection("cases").document(case_id)
         .collection("meta").document("deadlines").get())
    return (d.to_dict() or {}).get("items", []) if d.exists else []


# --- export / delete -------------------------------------------------
def export_all(uid: str) -> dict:
    user = _uid_doc(uid).get().to_dict() or {}
    cases = []
    for c in _uid_doc(uid).collection("cases").stream():
        cid = c.id
        cases.append({
            "case": _ser(c.to_dict()),
            "messages": list_messages(uid, cid, limit=1000),
            "drafts": list_drafts(uid, cid),
            "deadlines": get_deadlines(uid, cid),
            "evidence": list_evidence(uid, cid, include_data=True),
        })
    return {"user": _ser(user), "cases": cases,
            "exportedAt": _now().isoformat()}


def delete_account(uid: str) -> None:
    # recursive delete of the whole subtree, then the user doc
    ref = _uid_doc(uid)
    _recursive_delete(ref)
    ref.delete()
    audit("account_deleted", uid)
    # remove the auth identity too — otherwise the same uid signs back in
    # and ensure_user() silently recreates the account.
    try:
        from firebase_admin import auth as fb_auth
        fb_auth.delete_user(uid)
    except Exception as exc:  # noqa: BLE001 - data is already gone; log and move on
        from app.logging_setup import log
        log.warning("repo.auth_delete_failed", error=type(exc).__name__)


def _recursive_delete(doc_ref) -> None:
    for col in doc_ref.collections():
        _delete_collection(col)


def _delete_collection(col, batch_size: int = 300) -> None:
    while True:
        docs = list(col.limit(batch_size).stream())
        if not docs:
            return
        for d in docs:
            _recursive_delete(d.reference)   # depth-first: kill subcollections
            d.reference.delete()
        if len(docs) < batch_size:
            return


# --- idempotency (best-effort dedupe of retried POSTs) ---------------
def idempotency_get(uid: str, key: str) -> Optional[dict]:
    d = _uid_doc(uid).collection("idempotency").document(key).get()
    return (d.to_dict() or {}).get("response") if d.exists else None


def idempotency_put(uid: str, key: str, response: dict) -> None:
    (_uid_doc(uid).collection("idempotency").document(key)
     .set({"response": response, "ts": _now()}))


# --- audit (append-only, no PII) -----------------------------------
def audit(event: str, uid: str) -> None:
    from app.core.redact import uid_hash
    db().collection("audit").document(uuid.uuid4().hex).set({
        "ts": _now(), "event": event, "uid_hash": uid_hash(uid),
    })


# --- serialisation ------------------------------------------------
def _ser(d):
    if isinstance(d, dict):
        return {k: _ser(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_ser(v) for v in d]
    if isinstance(d, datetime):
        return d.isoformat()
    return d
