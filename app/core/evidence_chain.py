"""
app/core/evidence_chain.py
==========================
The tamper-evident core of the "algorithmic appeal record".

Every piece of evidence a worker uploads is linked into an append-only
hash chain: each entry commits to the bytes of the file, the moment it
was captured, and the entry before it. Re-deriving the chain later proves
the record has not been reordered, back-dated, or edited since upload.

PURE. No I/O. `hashlib` / `hmac` only. Fully unit-tested.

This does not prove *when* a screenshot was originally taken — only that
the worker held these exact bytes on the server-stamped `captured_at`,
and that nothing was inserted or altered afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional

GENESIS = "GENESIS"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain_hash(prev_hash: str, file_sha256: str, captured_at: str, kind: str) -> str:
    """The commitment stored on one entry. Order and separators are fixed so
    the value is reproducible from the stored fields alone."""
    payload = "\n".join([prev_hash or GENESIS, file_sha256, captured_at, kind])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def link(prev_entry: Optional[dict], *, file_sha256: str, captured_at: str,
         kind: str) -> dict:
    """Return the chain fields for a new entry that follows `prev_entry`
    (None for the first entry)."""
    seq = (prev_entry["seq"] + 1) if prev_entry else 1
    prev = prev_entry["chain_hash"] if prev_entry else GENESIS
    return {
        "seq": seq,
        "prev_hash": prev,
        "chain_hash": chain_hash(prev, file_sha256, captured_at, kind),
    }


def verify(entries: list[dict]) -> dict:
    """entries: chain-ordered list of dicts with seq, prev_hash, chain_hash,
    sha256, captured_at, kind. Returns {ok, length, broken_at, reason}."""
    prev = GENESIS
    for i, e in enumerate(sorted(entries, key=lambda x: x.get("seq", 0))):
        if e.get("seq") != i + 1:
            return _broken(e, "sequence number is not contiguous")
        if e.get("prev_hash") != prev:
            return _broken(e, "prev_hash does not match the previous entry")
        expect = chain_hash(prev, e.get("sha256", ""), e.get("captured_at", ""),
                            e.get("kind", ""))
        if e.get("chain_hash") != expect:
            return _broken(e, "chain_hash does not match the entry's own fields")
        prev = e["chain_hash"]
    return {"ok": True, "length": len(entries), "broken_at": None, "reason": ""}


def _broken(entry: dict, reason: str) -> dict:
    return {"ok": False, "length": None, "broken_at": entry.get("seq"),
            "reason": reason}


def manifest(entries: list[dict], *, signing_key: Optional[str]) -> dict:
    """A portable, verifiable summary of the record — no file bytes, just the
    commitments. Signed with an HMAC key (from Secret Manager) when available."""
    ordered = sorted(entries, key=lambda x: x.get("seq", 0))
    body = {
        "version": 1,
        "entries": [
            {
                "seq": e.get("seq"),
                "kind": e.get("kind"),
                "filename": e.get("filename"),
                "sha256": e.get("sha256"),
                "captured_at": e.get("captured_at"),
                "prev_hash": e.get("prev_hash"),
                "chain_hash": e.get("chain_hash"),
            }
            for e in ordered
        ],
        "head": ordered[-1]["chain_hash"] if ordered else GENESIS,
        "verification": verify(ordered),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    if signing_key:
        body["signature"] = {
            "alg": "HMAC-SHA256",
            "value": hmac.new(signing_key.encode("utf-8"),
                              canonical.encode("utf-8"), hashlib.sha256).hexdigest(),
        }
    else:
        body["signature"] = None
    return body
