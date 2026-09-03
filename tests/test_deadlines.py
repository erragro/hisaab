from datetime import date

import pytest

from app.core import deadlines as dl


TODAY = date(2026, 9, 2)


def test_notice_deadline_basic():
    d = dl.notice_deadline(date(2026, 9, 1), days=15, today=TODAY)
    assert d.kind == "notice_period"
    assert d.due_date == date(2026, 9, 16)
    assert d.days_remaining == 14
    assert d.passed is False
    assert "15 days" in d.basis


def test_notice_deadline_already_passed():
    d = dl.notice_deadline(date(2026, 8, 1), days=15, today=TODAY)
    assert d.due_date == date(2026, 8, 16)
    assert d.days_remaining == -17
    assert d.passed is True


def test_notice_deadline_rejects_nonpositive():
    with pytest.raises(ValueError):
        dl.notice_deadline(TODAY, days=0, today=TODAY)


def test_consumer_limitation_two_years():
    d = dl.consumer_limitation(date(2026, 3, 10), today=TODAY)
    assert d.due_date == date(2028, 3, 10)
    assert d.days_remaining == (date(2028, 3, 10) - TODAY).days
    assert "Consumer Protection Act" in d.basis


def test_wage_limitation_three_years():
    d = dl.wage_limitation(date(2026, 3, 10), today=TODAY)
    assert d.due_date == date(2029, 3, 10)


def test_leap_day_clamps():
    d = dl.consumer_limitation(date(2024, 2, 29), today=TODAY)
    # 2026 is not a leap year -> Feb 28
    assert d.due_date == date(2026, 2, 28)


def test_platform_sla():
    d = dl.platform_sla(date(2026, 9, 1), sla_days=7, today=TODAY)
    assert d.due_date == date(2026, 9, 8)
    assert d.kind == "platform_sla"


def test_platform_sla_rejects_nonpositive():
    with pytest.raises(ValueError):
        dl.platform_sla(TODAY, sla_days=0, today=TODAY)


def test_build_case_deadlines_sorted_and_skips_missing():
    out = dl.build_case_deadlines(
        incident_date=date(2026, 3, 10),
        notice_sent=date(2026, 9, 1),
        notice_days=15,
        grievance_filed=None,          # -> platform SLA skipped
        platform_sla_days=None,
        today=TODAY,
    )
    kinds = [d.kind for d in out]
    assert "platform_sla" not in kinds
    assert set(kinds) == {"consumer_limitation", "wage_limitation", "notice_period"}
    # sorted ascending by due date
    assert out == sorted(out, key=lambda d: d.due_date)


def test_build_case_deadlines_empty_when_no_dates():
    assert dl.build_case_deadlines(today=TODAY) == []


def test_to_dict_serialises_dates_as_iso():
    d = dl.notice_deadline(date(2026, 9, 1), today=TODAY).to_dict()
    assert d["due_date"] == "2026-09-16"
    assert d["from_date"] == "2026-09-01"
    assert isinstance(d["days_remaining"], int)


# ---- working-day arithmetic + IDRC windows ---------------------------
def test_add_working_days_skips_weekend():
    # Fri 2026-09-04 + 1 working day -> Mon 2026-09-07
    assert dl.add_working_days(date(2026, 9, 4), 1, holidays=()) == date(2026, 9, 7)


def test_add_working_days_skips_holiday():
    # 2026-10-02 (Gandhi Jayanti, a Friday) is in the default holiday set
    assert dl.add_working_days(date(2026, 10, 1), 1) == date(2026, 10, 5)  # skip Fri+wknd


def test_add_working_days_rejects_nonpositive():
    with pytest.raises(ValueError):
        dl.add_working_days(TODAY, 0)


def test_working_days_between_signed():
    assert dl.working_days_between(date(2026, 9, 7), date(2026, 9, 11), holidays=()) == 4
    assert dl.working_days_between(date(2026, 9, 11), date(2026, 9, 7), holidays=()) == -4


def test_idrc_appeal_is_seven_working_days():
    # termination Mon 2026-09-07 -> +7 working days -> Wed 2026-09-16
    d = dl.idrc_appeal_deadline(date(2026, 9, 7), today=date(2026, 9, 8))
    assert d.kind == "idrc_appeal"
    assert d.due_date == date(2026, 9, 16)
    assert d.working_days_remaining == 6
    assert "Karnataka" in d.basis


def test_idrc_appeal_can_be_already_blown():
    d = dl.idrc_appeal_deadline(date(2026, 8, 1), today=TODAY)
    assert d.passed is True


def test_build_includes_idrc_appeal_only_for_deactivation():
    with_deact = dl.build_case_deadlines(
        incident_date=date(2026, 8, 20), issue_type="deactivation", today=TODAY)
    assert "idrc_appeal" in {d.kind for d in with_deact}
    without = dl.build_case_deadlines(
        incident_date=date(2026, 8, 20), issue_type="unpaid_wages", today=TODAY)
    assert "idrc_appeal" not in {d.kind for d in without}


def test_build_grievance_adds_idrc_and_board_windows():
    out = dl.build_case_deadlines(grievance_filed=date(2026, 9, 1), today=TODAY)
    kinds = {d.kind for d in out}
    assert {"idrc_grievance", "board_escalation"} <= kinds
