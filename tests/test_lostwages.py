from datetime import date

from app.core.lostwages import estimate_lost_wages

TODAY = date(2026, 9, 20)


def test_basic_estimate():
    samples = [
        {"amount_inr": 7000, "period_days": 7, "source": "earnings_screen"},
        {"amount_inr": 6600, "period_days": 7, "source": "earnings_screen"},
    ]
    lw = estimate_lost_wages(samples, deactivated_on=date(2026, 9, 1), today=TODAY)
    # (7000+6600)/14 = 971.4 -> 971/day ; 2026-09-01..2026-09-20 inclusive = 20 days
    assert lw.daily_rate_inr == 971
    assert lw.days_offline == 20
    assert lw.estimate_inr == 971 * 20
    assert "20 days offline" in lw.basis


def test_none_without_samples_or_date():
    assert estimate_lost_wages([], deactivated_on=date(2026, 9, 1), today=TODAY) is None
    assert estimate_lost_wages([{"amount_inr": 100, "period_days": 1}],
                               deactivated_on=None, today=TODAY) is None


def test_ignores_garbage_samples():
    samples = [
        {"amount_inr": "not a number", "period_days": 7},
        {"amount_inr": 5000, "period_days": 0},          # zero period
        {"amount_inr": 3500, "period_days": 7},          # the only good one
    ]
    lw = estimate_lost_wages(samples, deactivated_on=date(2026, 9, 18), today=TODAY)
    assert lw.samples_used == 1
    assert lw.daily_rate_inr == 500


def test_until_capped_at_today():
    lw = estimate_lost_wages([{"amount_inr": 700, "period_days": 7}],
                             deactivated_on=date(2026, 9, 18),
                             until=date(2027, 1, 1), today=TODAY)
    assert lw.days_offline == 3  # 18,19,20
