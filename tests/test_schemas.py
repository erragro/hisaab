import pytest
from pydantic import ValidationError

from app.schemas import CaseCreate, DraftIn, PartyIn


def test_case_accepts_iso_date_and_none():
    assert CaseCreate(title="abcd", issue_type="other", platform="X",
                      incident_date="2026-03-10").incident_date == "2026-03-10"
    assert CaseCreate(title="abcd", issue_type="other", platform="X").incident_date is None


@pytest.mark.parametrize("bad", ["2026-13-01", "10/03/2026", "not-a-date", "2026-02-30"])
def test_case_rejects_bad_incident_date(bad):
    with pytest.raises(ValidationError):
        CaseCreate(title="abcd", issue_type="other", platform="X", incident_date=bad)


def test_party_validates_both_dates():
    PartyIn(notice_sent="2026-09-01", grievance_filed="2026-09-02")
    with pytest.raises(ValidationError):
        PartyIn(notice_sent="soon")
    with pytest.raises(ValidationError):
        PartyIn(grievance_filed="2026/09/02")


def test_party_day_bounds():
    with pytest.raises(ValidationError):
        PartyIn(notice_days=0)
    with pytest.raises(ValidationError):
        PartyIn(platform_sla_days=1000)


def test_draft_requires_names():
    with pytest.raises(ValidationError):
        DraftIn(kind="legal_notice", sender_name="", recipient_name="B")
    DraftIn(kind="legal_notice", sender_name="A", recipient_name="B")
