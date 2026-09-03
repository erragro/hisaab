"""Pydantic request/response models. Note: NO model here carries a uid —
the uid always comes from the verified token."""

from __future__ import annotations

import base64
import binascii
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _iso_date(cls, v):  # noqa: N805 - pydantic validator signature
    """Shared validator: accept None or a strict ISO yyyy-mm-dd string."""
    if v is None:
        return v
    from datetime import date
    if not isinstance(v, str):
        raise ValueError("date must be a string")
    date.fromisoformat(v)  # raises ValueError if malformed
    return v


IssueType = Literal[
    "unpaid_wages", "wrong_deduction", "deactivation",
    "incentive_dispute", "accident_claim", "other",
]
DraftKind = Literal[
    "legal_notice", "platform_grievance", "consumer_complaint", "labour_complaint",
]

SCHEMA_VERSION = 1


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    issue_type: IssueType
    platform: str = Field(min_length=1, max_length=60)
    amount_claimed_inr: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    incident_date: Optional[str] = None  # ISO yyyy-mm-dd

    _v_incident_date = field_validator("incident_date")(_iso_date)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class DraftIn(BaseModel):
    kind: DraftKind
    sender_name: str = Field(min_length=1, max_length=120)
    sender_address: str = Field(default="", max_length=400)
    sender_worker_id: str = Field(default="", max_length=80)
    recipient_name: str = Field(min_length=1, max_length=160)
    recipient_address: str = Field(default="", max_length=400)


class PartyIn(BaseModel):
    notice_sent: Optional[str] = None
    notice_days: int = Field(default=15, ge=1, le=90)
    grievance_filed: Optional[str] = None
    platform_sla_days: Optional[int] = Field(default=None, ge=1, le=180)
    idrc_appeal_filed: Optional[str] = None

    _v_notice_sent = field_validator("notice_sent")(_iso_date)
    _v_grievance_filed = field_validator("grievance_filed")(_iso_date)
    _v_idrc_appeal_filed = field_validator("idrc_appeal_filed")(_iso_date)


EvidenceKind = Literal[
    "deactivation_notice", "earnings_screen", "ratings_screen",
    "support_chat", "payslip", "other",
]
EvidenceMime = Literal[
    "image/png", "image/jpeg", "image/webp", "application/pdf",
]

# ~900 KB decoded -> ~1.2 MB of base64 text; Firestore doc limit is ~1 MiB,
# the route re-checks the decoded size against config.EVIDENCE_MAX_BYTES.
_MAX_B64_LEN = 1_600_000


class EvidenceIn(BaseModel):
    kind: EvidenceKind
    filename: str = Field(min_length=1, max_length=200)
    mime: EvidenceMime
    data_b64: str = Field(min_length=8, max_length=_MAX_B64_LEN)
    captured_hint: Optional[str] = None  # optional date the worker says it's from

    _v_captured_hint = field_validator("captured_hint")(_iso_date)

    @field_validator("data_b64")
    @classmethod
    def _b64(cls, v):
        try:
            base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("data_b64 is not valid base64")
        return v
