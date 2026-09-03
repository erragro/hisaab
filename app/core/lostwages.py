"""
app/core/lostwages.py
=====================
Deterministic estimate of earnings lost during a wrongful deactivation.

PURE. No I/O, no model. The model may read a payslip or an in-app
earnings screen and hand us {amount, period_days}; THIS module turns that
into a baseline daily rate and multiplies by the days offline. Every
figure carries the basis it was computed from — same rule as deadlines.

Recovering pay for the wrongful-deactivation period (based on past
earnings) is an emerging remedy; this is a supporting estimate for a
grievance or appeal, not an adjudicated amount.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

# sanity bounds for one earnings data point (INR) and its period (days)
_MAX_SAMPLE_INR = 10_000_000
_MAX_PERIOD_DAYS = 366


@dataclass(frozen=True)
class EarningsSample:
    amount_inr: int
    period_days: int
    source: str = ""     # e.g. "payslip", "earnings_screen"

    def valid(self) -> bool:
        return (0 < self.amount_inr <= _MAX_SAMPLE_INR
                and 0 < self.period_days <= _MAX_PERIOD_DAYS)


@dataclass(frozen=True)
class LostWages:
    daily_rate_inr: int
    days_offline: int
    estimate_inr: int
    samples_used: int
    basis: str

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce_samples(raw) -> list[EarningsSample]:
    out: list[EarningsSample] = []
    for r in raw or []:
        try:
            amt = int(round(float(r.get("amount_inr"))))
            per = int(r.get("period_days") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        s = EarningsSample(amount_inr=amt, period_days=per,
                           source=str(r.get("source", "")))
        if s.valid():
            out.append(s)
    return out


def estimate_lost_wages(
    earnings_samples,
    *,
    deactivated_on: Optional[date],
    until: Optional[date] = None,
    today: Optional[date] = None,
) -> Optional[LostWages]:
    """
    earnings_samples: iterable of {amount_inr, period_days, source}.
    deactivated_on : first day with no income (the cause-of-action date).
    until          : last day counted (default: today; capped at today).
    Returns None if there isn't enough to compute an honest number.
    """
    today = today or date.today()
    if deactivated_on is None:
        return None

    samples = _coerce_samples(earnings_samples)
    if not samples:
        return None

    end = until or today
    if end > today:
        end = today
    days_offline = (end - deactivated_on).days + 1  # inclusive of both ends
    if days_offline <= 0:
        return None

    total_amt = sum(s.amount_inr for s in samples)
    total_days = sum(s.period_days for s in samples)
    daily_rate = int(round(total_amt / total_days))
    if daily_rate <= 0:
        return None

    estimate = daily_rate * days_offline
    basis = (
        f"baseline Rs {daily_rate}/day (from {len(samples)} earnings record"
        f"{'s' if len(samples) != 1 else ''}: Rs {total_amt} over {total_days} days) "
        f"x {days_offline} days offline "
        f"({deactivated_on.isoformat()} to {end.isoformat()}, both inclusive)"
    )
    return LostWages(daily_rate_inr=daily_rate, days_offline=days_offline,
                     estimate_inr=estimate, samples_used=len(samples), basis=basis)
