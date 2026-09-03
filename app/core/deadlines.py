"""
app/core/deadlines.py
=====================
Deterministic date arithmetic for the legal windows that matter in a
gig-worker payment / deactivation dispute in India.

PURE. No I/O, no model calls, no network. Fully unit-tested in
tests/test_deadlines.py. The model may *narrate* these dates; it never
computes them.

General information, not legal advice. The windows below are the common
statutory / practical defaults; a real forum or lawyer may apply a
different period to a specific case. Every returned deadline carries the
basis it was computed from so the user can check it.

Deactivation-appeal windows follow the Karnataka Platform-Based Gig
Workers (Social Security and Welfare) Rules, 2025 — the first Indian
framework to put a clock on platform grievance redressal. Other states
may differ; the basis string always names the source.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Iterable, Literal, Optional

DeadlineKind = Literal[
    "notice_period",        # time you gave the other side to comply
    "consumer_limitation",  # 2 yrs — Consumer Protection Act, 2019 s.69
    "wage_limitation",      # 3 yrs — general limitation for money/contract claims
    "platform_sla",         # the platform's own promised grievance turnaround
    "idrc_appeal",          # 7 working days to appeal a termination to the IDRC
    "idrc_disposal",        # 15 working days for the IDRC to decide a termination appeal
    "idrc_grievance",       # 14 days for the IDRC to act on a grievance petition
    "board_escalation",     # 30 days to escalate an unresolved grievance to the Board
    "custom",
]

# --- statutory defaults ------------------------------------------------------
DEFAULT_NOTICE_DAYS = 15
CONSUMER_LIMITATION_YEARS = 2
WAGE_LIMITATION_YEARS = 3
IDRC_APPEAL_WORKING_DAYS = 7
IDRC_DISPOSAL_WORKING_DAYS = 15
IDRC_GRIEVANCE_DAYS = 14
BOARD_ESCALATION_DAYS = 30

_KA_RULES = "Karnataka Platform-Based Gig Workers Rules, 2025"

# Fixed-date gazetted holidays only (2026-2027). Festival dates move every
# year, so they are deliberately left out — a deployment should extend this
# from the state's official holiday notification. A holiday we miss only
# makes a computed deadline look one day tighter than it is, never looser.
INDIA_HOLIDAYS: frozenset[date] = frozenset({
    date(2026, 1, 1),   date(2026, 1, 26),  date(2026, 4, 14),
    date(2026, 5, 1),   date(2026, 8, 15),  date(2026, 10, 2),
    date(2026, 12, 25),
    date(2027, 1, 1),   date(2027, 1, 26),  date(2027, 4, 14),
    date(2027, 5, 1),   date(2027, 8, 15),  date(2027, 10, 2),
    date(2027, 12, 25),
})


# --- working-day arithmetic ------------------------------------------------
def is_working_day(d: date, holidays: Iterable[date] = INDIA_HOLIDAYS) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def add_working_days(start: date, n: int,
                     holidays: Iterable[date] = INDIA_HOLIDAYS) -> date:
    """The date `n` working days after `start` (start day itself not counted).
    `n` must be positive."""
    if n <= 0:
        raise ValueError("working-day offset must be positive")
    hol = set(holidays)
    d = start
    left = n
    while left > 0:
        d += timedelta(days=1)
        if is_working_day(d, hol):
            left -= 1
    return d


def working_days_between(a: date, b: date,
                         holidays: Iterable[date] = INDIA_HOLIDAYS) -> int:
    """Working days in the half-open interval (a, b].  Negative if b < a."""
    if b == a:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    hol = set(holidays)
    d = lo
    count = 0
    while d < hi:
        d += timedelta(days=1)
        if is_working_day(d, hol):
            count += 1
    return sign * count


@dataclass(frozen=True)
class Deadline:
    kind: DeadlineKind
    label: str
    due_date: date
    basis: str           # human-readable: what it was computed from
    from_date: date
    days_remaining: int   # calendar days relative to `today`; negative = passed
    passed: bool
    working_days_remaining: Optional[int] = None  # set for working-day deadlines

    def to_dict(self) -> dict:
        d = asdict(self)
        d["due_date"] = self.due_date.isoformat()
        d["from_date"] = self.from_date.isoformat()
        return d


def _mk(kind: DeadlineKind, label: str, due: date, basis: str,
        frm: date, today: date, *, working: bool = False) -> Deadline:
    rem = (due - today).days
    wdr = working_days_between(today, due) if working else None
    return Deadline(
        kind=kind, label=label, due_date=due, basis=basis,
        from_date=frm, days_remaining=rem, passed=rem < 0,
        working_days_remaining=wdr,
    )


def _years_out(d: date, years: int) -> date:
    """Add whole years, clamping Feb 29 -> Feb 28 on non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# --- individual windows --------------------------------------------------
def notice_deadline(notice_sent: date, *, days: int = DEFAULT_NOTICE_DAYS,
                    today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    if days <= 0:
        raise ValueError("notice period must be positive")
    due = notice_sent + timedelta(days=days)
    return _mk(
        "notice_period",
        f"Other party has until this date to respond to your notice ({days} days)",
        due, f"notice sent {notice_sent.isoformat()} + {days} days",
        notice_sent, today,
    )


def consumer_limitation(cause_of_action: date, *,
                        today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    due = _years_out(cause_of_action, CONSUMER_LIMITATION_YEARS)
    return _mk(
        "consumer_limitation",
        "Last date to file a consumer complaint",
        due,
        f"cause of action {cause_of_action.isoformat()} + "
        f"{CONSUMER_LIMITATION_YEARS} years (Consumer Protection Act, 2019, s.69)",
        cause_of_action, today,
    )


def wage_limitation(cause_of_action: date, *,
                    today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    due = _years_out(cause_of_action, WAGE_LIMITATION_YEARS)
    return _mk(
        "wage_limitation",
        "Approximate outer limit to pursue the unpaid amount",
        due,
        f"cause of action {cause_of_action.isoformat()} + "
        f"{WAGE_LIMITATION_YEARS} years (general limitation for money claims)",
        cause_of_action, today,
    )


def platform_sla(grievance_filed: date, *, sla_days: int,
                 today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    if sla_days <= 0:
        raise ValueError("SLA days must be positive")
    due = grievance_filed + timedelta(days=sla_days)
    return _mk(
        "platform_sla",
        f"Platform's own deadline to resolve your grievance ({sla_days} days)",
        due, f"grievance filed {grievance_filed.isoformat()} + {sla_days} days",
        grievance_filed, today,
    )


def idrc_appeal_deadline(termination_date: date, *,
                         today: Optional[date] = None) -> Deadline:
    """The hard one: appeal a termination / deactivation to the platform's
    Internal Dispute Resolution Committee within 7 WORKING days."""
    today = today or date.today()
    due = add_working_days(termination_date, IDRC_APPEAL_WORKING_DAYS)
    return _mk(
        "idrc_appeal",
        "Last day to appeal the deactivation to the platform's IDRC",
        due,
        f"termination {termination_date.isoformat()} + "
        f"{IDRC_APPEAL_WORKING_DAYS} working days ({_KA_RULES})",
        termination_date, today, working=True,
    )


def idrc_disposal_deadline(appeal_filed: date, *,
                           today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    due = add_working_days(appeal_filed, IDRC_DISPOSAL_WORKING_DAYS)
    return _mk(
        "idrc_disposal",
        "Date the IDRC is expected to have decided your termination appeal",
        due,
        f"appeal filed {appeal_filed.isoformat()} + "
        f"{IDRC_DISPOSAL_WORKING_DAYS} working days ({_KA_RULES})",
        appeal_filed, today, working=True,
    )


def idrc_grievance_deadline(grievance_filed: date, *,
                            today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    due = grievance_filed + timedelta(days=IDRC_GRIEVANCE_DAYS)
    return _mk(
        "idrc_grievance",
        "Date the IDRC should have sent you an action-taken report",
        due,
        f"grievance filed {grievance_filed.isoformat()} + "
        f"{IDRC_GRIEVANCE_DAYS} days ({_KA_RULES})",
        grievance_filed, today,
    )


def board_escalation_deadline(grievance_filed: date, *,
                              today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    due = grievance_filed + timedelta(days=BOARD_ESCALATION_DAYS)
    return _mk(
        "board_escalation",
        "By this date, escalate an unresolved grievance to the Welfare Board",
        due,
        f"grievance filed {grievance_filed.isoformat()} + "
        f"{BOARD_ESCALATION_DAYS} days ({_KA_RULES})",
        grievance_filed, today,
    )


def custom_deadline(label: str, due: date, *,
                    today: Optional[date] = None) -> Deadline:
    today = today or date.today()
    return _mk("custom", label, due, "user-entered", due, today)


def build_case_deadlines(
    *,
    incident_date: Optional[date] = None,
    issue_type: Optional[str] = None,
    notice_sent: Optional[date] = None,
    notice_days: int = DEFAULT_NOTICE_DAYS,
    grievance_filed: Optional[date] = None,
    platform_sla_days: Optional[int] = None,
    idrc_appeal_filed: Optional[date] = None,
    today: Optional[date] = None,
) -> list[Deadline]:
    """
    Compute every deadline we can from the dates the case has so far.
    Returns them sorted by due_date. Missing inputs are simply skipped —
    no guessing.
    """
    today = today or date.today()
    out: list[Deadline] = []

    if incident_date is not None:
        out.append(consumer_limitation(incident_date, today=today))
        out.append(wage_limitation(incident_date, today=today))
        if issue_type == "deactivation":
            out.append(idrc_appeal_deadline(incident_date, today=today))
    if idrc_appeal_filed is not None:
        out.append(idrc_disposal_deadline(idrc_appeal_filed, today=today))
    if notice_sent is not None:
        out.append(notice_deadline(notice_sent, days=notice_days, today=today))
    if grievance_filed is not None:
        out.append(idrc_grievance_deadline(grievance_filed, today=today))
        out.append(board_escalation_deadline(grievance_filed, today=today))
        if platform_sla_days:
            out.append(platform_sla(grievance_filed, sla_days=platform_sla_days,
                                    today=today))

    return sorted(out, key=lambda d: d.due_date)
