"""
app/core/readiness.py
=====================
Deterministic readiness check for an outgoing document (a legal notice,
a platform grievance, a consumer complaint, a labour complaint).

The MODEL drafts the document. This module decides whether it is actually
ready to send, by checking that every element the document type requires
is present — partly from the structured case fields, partly from the
draft text itself.

PURE. No I/O, no model calls. Fully unit-tested. This is the "code
decides" half of the app: a confident, plausible-looking draft that is
missing the amount, cites the *wrong* amount, states a deadline that is
already blown, or is missing the recipient is not ready, and the model
does not get to say otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import Literal, Optional

from app.core.deadlines import consumer_limitation

DraftKind = Literal[
    "legal_notice",
    "platform_grievance",
    "consumer_complaint",
    "labour_complaint",
]

# --- lightweight text signals ------------------------------------------------
_RUPEE = re.compile(r"(₹|\bRs\.?\b|\bINR\b)\s?\d", re.IGNORECASE)
# a rupee figure with its digits captured, for cross-checking the amount
_RUPEE_AMOUNT = re.compile(
    r"(?:₹|\bRs\.?\b|\bINR\b)\s?([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE
)
_DATE = re.compile(
    r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})\b",
    re.IGNORECASE,
)
# "within N days" only counts as a compliance deadline when it sits next to a
# demand verb or a consequence clause — not in a narrative sentence like
# "the platform replied within 3 days".
_DEADLINE_PHRASE = re.compile(
    r"\b(pay|remit|credit|refund|reimburse|comply|respond|reply|reactivate|"
    r"restore|reverse|settle|rectify)\b[^.]{0,90}?\bwithin\s+\d+\s+(working\s+)?days?\b"
    r"|\bwithin\s+\d+\s+(working\s+)?days?\b[^.]{0,90}?"
    r"\b(failing which|failing this|of (this|the) notice|hereof|from receipt|"
    r"of receipt|to comply|to respond|to pay)\b",
    re.IGNORECASE,
)
_SIGNATURE = re.compile(
    r"\b(yours (faithfully|sincerely)|signature|signed|\(name\)|name:)\b",
    re.IGNORECASE,
)
_INTENT_TO_PROCEED = re.compile(
    r"\b(failing which|legal (action|proceedings)|approach the (consumer|labour|"
    r"appropriate)|file a (complaint|case)|consumer (commission|forum|court)"
    r"|labour (commissioner|court))\b",
    re.IGNORECASE,
)
_CONTRAST = re.compile(
    r"\b(expected|instead|but (only )?received|received only|shortfall|short-paid"
    r"|underpaid|should have been|as against|whereas|vs\.?|versus)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    ok: bool
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Readiness:
    kind: DraftKind
    checks: list[Check]
    score: float             # fraction of ALL checks passing, 0..1
    required_passed: int
    required_total: int
    ready: bool              # all *required* checks pass
    missing: list[str]       # labels of failed required checks

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [c.to_dict() for c in self.checks]
        return d


# --- helpers -------------------------------------------------------------
def _s(v) -> str:
    """Coerce any field value to a stripped string; None/0/[] -> ''."""
    if v is None:
        return ""
    return str(v).strip()


def _has(case: dict, *keys: str) -> bool:
    for k in keys:
        v = case.get(k)
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        if isinstance(v, (list, dict)) and len(v) == 0:
            return False
    return True


def _party(case: dict, side: str) -> bool:
    """side in {'sender','recipient'} — needs a name and something to reach them."""
    p = case.get(side) or {}
    if not isinstance(p, dict):
        return False
    reach = _s(p.get("address")) or _s(p.get("email")) or _s(p.get("worker_id"))
    return bool(_s(p.get("name"))) and bool(reach)


def _body_amounts(body: str) -> set[int]:
    out: set[int] = set()
    for m in _RUPEE_AMOUNT.finditer(body or ""):
        raw = m.group(1).replace(",", "")
        try:
            out.add(int(round(float(raw))))
        except (TypeError, ValueError):
            pass
    return out


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _amount_check(case: dict, body: str) -> tuple[bool, str]:
    """
    The amount is 'present' if the case carries a claimed amount (or a
    computed lost-wages estimate) or the draft states a rupee figure. But if
    a case amount exists and the draft's figure disagrees with it, that is a
    hard fail — the model does not get to quietly change the number.

    A lost-wages estimate is fuzzy, so a draft figure within 10% of it counts
    as a match even when it isn't exact.
    """
    claimed = _int_or_none(case.get("amount_claimed_inr"))
    lost = _int_or_none(case.get("lost_wages_inr"))
    found = _body_amounts(body)

    if claimed is not None and found and claimed not in found:
        near_estimate = lost is not None and any(
            abs(a - lost) <= max(1, round(lost * 0.10)) for a in found)
        if not near_estimate:
            shown = ", ".join(f"₹{a}" for a in sorted(found))
            return False, f"draft cites {shown} but the case records ₹{claimed}"
    if claimed is not None or lost is not None:
        return True, ""
    if found:
        return True, ""
    return False, "no amount on file and none stated in the draft"


def _within_consumer_limitation(case: dict) -> tuple[bool, str]:
    raw = _s(case.get("incident_date"))
    if not raw:
        return False, "no cause-of-action date on file"
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return False, "cause-of-action date is malformed"
    dl = consumer_limitation(d)
    if dl.passed:
        return False, f"the 2-year limitation window closed on {dl.due_date.isoformat()}"
    return True, ""


# --- per-kind checklists --------------------------------------------------
def _legal_notice(case: dict, body: str) -> list[Check]:
    amt_ok, amt_note = _amount_check(case, body)
    return [
        Check("sender", "Your name and address", _party(case, "sender")),
        Check("recipient", "Recipient's name and address", _party(case, "recipient")),
        Check("facts_dated", "A dated statement of what happened",
              bool(_DATE.search(body)) and _has(case, "facts")),
        Check("amount", "The specific amount / relief demanded", amt_ok, amt_note),
        Check("deadline", "A deadline for the other side to comply "
              "(e.g. 'pay ... within 15 days')", bool(_DEADLINE_PHRASE.search(body))),
        Check("intent", "A statement of what you will do if they don't comply",
              bool(_INTENT_TO_PROCEED.search(body))),
        Check("signature", "A signature block", bool(_SIGNATURE.search(body))),
    ]


def _platform_grievance(case: dict, body: str) -> list[Check]:
    amt_ok, amt_note = _amount_check(case, body)
    return [
        Check("worker_id", "Your partner / worker ID",
              bool(_s((case.get("sender") or {}).get("worker_id")))),
        Check("platform", "Which platform", _has(case, "platform")),
        Check("refs", "Order / trip IDs or the exact dates involved",
              bool(_DATE.search(body)) or _has(case, "facts")),
        Check("amount", "The exact amount in dispute", amt_ok, amt_note),
        Check("expected_vs_got", "What you expected vs what you received",
              bool(_CONTRAST.search(body)) and len(body.split()) >= 30),
        Check("ask", "A clear ask (pay X / reactivate / explain the deduction)",
              bool(re.search(r"\b(please|request|kindly)\b.*\b(pay|credit|reactivate|"
                             r"restore|reverse|explain)\b", body, re.IGNORECASE | re.DOTALL))),
    ]


def _consumer_complaint(case: dict, body: str) -> list[Check]:
    amt_ok, amt_note = _amount_check(case, body)
    lim_ok, lim_note = _within_consumer_limitation(case)
    return [
        Check("complainant", "Complainant details", _party(case, "sender")),
        Check("opposite_party", "Opposite party details", _party(case, "recipient")),
        Check("jurisdiction", "Territorial + pecuniary jurisdiction stated",
              bool(re.search(r"\bjurisdiction\b", body, re.IGNORECASE))),
        Check("cause_date", "The cause-of-action date", _has(case, "incident_date")),
        Check("facts_dated", "A dated statement of facts",
              bool(_DATE.search(body)) and _has(case, "facts")),
        Check("relief", "The relief claimed (refund / compensation)", amt_ok, amt_note),
        Check("limitation", "Filed within 2 years of the cause of action",
              lim_ok, lim_note),
        Check("verification", "A verification / affidavit clause",
              bool(re.search(r"\bverif(y|ied|ication)\b", body, re.IGNORECASE))),
    ]


def _labour_complaint(case: dict, body: str) -> list[Check]:
    amt_ok, amt_note = _amount_check(case, body)
    return [
        Check("worker", "Worker details", _party(case, "sender")),
        Check("employer", "Employer / aggregator details", _party(case, "recipient")),
        Check("nature", "The nature of the claim (unpaid wages / deduction)",
              _has(case, "issue_type")),
        Check("amount_period", "The amount and the period it covers",
              amt_ok and bool(_DATE.search(body)),
              amt_note or ("" if _DATE.search(body) else "no dated period in the draft")),
        Check("attempted", "That you first raised it with the platform",
              bool(re.search(r"\b(grievance|raised|complaint|contacted|reached out)\b",
                             body, re.IGNORECASE))),
    ]


_CHECKLISTS = {
    "legal_notice": _legal_notice,
    "platform_grievance": _platform_grievance,
    "consumer_complaint": _consumer_complaint,
    "labour_complaint": _labour_complaint,
}

# Which checks are "required" (block sending) vs "recommended".
_REQUIRED = {
    "legal_notice": {"sender", "recipient", "facts_dated", "amount", "deadline"},
    "platform_grievance": {"worker_id", "platform", "amount", "ask"},
    "consumer_complaint": {"complainant", "opposite_party", "cause_date",
                           "facts_dated", "relief", "limitation"},
    "labour_complaint": {"worker", "employer", "nature", "amount_period"},
}


def check_readiness(kind: DraftKind, case: dict, draft_body: str) -> Readiness:
    if kind not in _CHECKLISTS:
        raise ValueError(f"unknown draft kind: {kind}")
    case = case or {}
    body = draft_body or ""
    checks = _CHECKLISTS[kind](case, body)
    required = _REQUIRED[kind]

    passed = sum(1 for c in checks if c.ok)
    score = round(passed / len(checks), 3) if checks else 0.0

    req_checks = [c for c in checks if c.id in required]
    req_passed = sum(1 for c in req_checks if c.ok)
    missing_required = [c.label for c in req_checks if not c.ok]
    ready = len(missing_required) == 0

    return Readiness(kind=kind, checks=checks, score=score,
                     required_passed=req_passed, required_total=len(req_checks),
                     ready=ready, missing=missing_required)
