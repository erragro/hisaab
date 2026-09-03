import pytest

from app.core.readiness import check_readiness


def _full_notice_case():
    return {
        "sender": {"name": "A. Kumar", "address": "12 MG Road, Bengaluru"},
        "recipient": {"name": "Acme Logistics Pvt Ltd",
                      "address": "Prestige Tech Park, Bengaluru"},
        "facts": [{"date": "2026-03-10", "text": "Incentive of Rs 2400 withheld"}],
        "amount_claimed_inr": 2400,
        "issue_type": "incentive_dispute",
        "platform": "Acme",
        "incident_date": "2026-03-10",
    }


GOOD_NOTICE_BODY = """
On 10/03/2026 the incentive of Rs 2,400 due to me was not credited.
I call upon you to pay Rs 2,400 within 15 days of this notice, failing which
I will approach the consumer commission.
Yours faithfully,
(Name)
"""


def test_full_legal_notice_is_ready():
    r = check_readiness("legal_notice", _full_notice_case(), GOOD_NOTICE_BODY)
    assert r.ready is True
    assert r.missing == []
    assert r.score == 1.0


def test_legal_notice_missing_deadline_is_not_ready():
    body = GOOD_NOTICE_BODY.replace("within 15 days of this notice", "soon")
    r = check_readiness("legal_notice", _full_notice_case(), body)
    assert r.ready is False
    assert any("deadline" in m.lower() for m in r.missing)


def test_legal_notice_missing_amount_is_not_ready():
    case = _full_notice_case()
    case.pop("amount_claimed_inr")
    body = GOOD_NOTICE_BODY.replace("Rs 2,400", "the amount").replace("Rs 2400", "the amount")
    r = check_readiness("legal_notice", case, body)
    assert r.ready is False
    assert any("amount" in m.lower() for m in r.missing)


def test_legal_notice_missing_recipient_is_not_ready():
    case = _full_notice_case()
    case["recipient"] = {"name": "", "address": ""}
    r = check_readiness("legal_notice", case, GOOD_NOTICE_BODY)
    assert r.ready is False
    assert any("recipient" in m.lower() for m in r.missing)


def test_recommended_check_lowers_score_but_not_readiness():
    # drop the signature (recommended, not required)
    body = GOOD_NOTICE_BODY.replace("Yours faithfully,\n(Name)", "")
    r = check_readiness("legal_notice", _full_notice_case(), body)
    assert r.ready is True          # still sendable
    assert r.score < 1.0            # but not perfect
    assert not any("signature" in m.lower() for m in r.missing)  # not in required-missing


def test_platform_grievance_ready():
    case = {
        "sender": {"name": "A. Kumar", "worker_id": "PARTNER-99213"},
        "platform": "Acme",
        "amount_claimed_inr": 2400,
        "facts": [{"date": "2026-03-10", "text": "..."}],
    }
    body = ("On 10/03/2026 my incentive of Rs 2,400 was not paid. Expected Rs 2,400, "
            "received Rs 0 for the March incentive slab. I request you to credit Rs 2,400 "
            "to my account and explain the deduction. " * 1)
    r = check_readiness("platform_grievance", case, body)
    assert r.ready is True


def test_consumer_complaint_needs_cause_date():
    case = {
        "sender": {"name": "A", "address": "x"},
        "recipient": {"name": "B", "address": "y"},
        "facts": [{"date": "2026-03-10", "text": "..."}],
        "amount_claimed_inr": 2400,
        # incident_date deliberately absent
    }
    body = "Facts: on 10/03/2026 ... relief: refund of Rs 2,400 ... jurisdiction ... verification"
    r = check_readiness("consumer_complaint", case, body)
    assert r.ready is False
    assert any("cause-of-action" in m.lower() or "cause of action" in m.lower()
               for m in r.missing)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        check_readiness("smoke_signal", {}, "hi")


def test_empty_body_is_not_ready():
    r = check_readiness("legal_notice", _full_notice_case(), "")
    assert r.ready is False
    assert 0.0 <= r.score <= 1.0


def test_to_dict_shape():
    d = check_readiness("legal_notice", _full_notice_case(), GOOD_NOTICE_BODY).to_dict()
    assert set(d) == {"kind", "checks", "score", "ready", "missing",
                      "required_passed", "required_total"}
    assert all(set(c) == {"id", "label", "ok", "note"} for c in d["checks"])


# ---- hardened checks (previously gameable) -----------------------------
def test_wrong_amount_in_draft_is_not_ready():
    body = GOOD_NOTICE_BODY.replace("Rs 2,400", "Rs 999999")
    r = check_readiness("legal_notice", _full_notice_case(), body)
    assert r.ready is False
    amount_check = next(c for c in r.checks if c.id == "amount")
    assert amount_check.ok is False
    assert "999999" in amount_check.note


def test_time_barred_consumer_complaint_is_not_ready():
    case = _full_notice_case()
    case["incident_date"] = "2019-01-01"          # > 2 years before 2026
    body = ("Facts: on 01/01/2019 the deduction happened. Relief: refund of Rs 2,400. "
            "Territorial and pecuniary jurisdiction lies with this Commission. "
            "Verification: the above is true.")
    r = check_readiness("consumer_complaint", case, body)
    assert r.ready is False
    lim = next(c for c in r.checks if c.id == "limitation")
    assert lim.ok is False and "limitation" in lim.note.lower()


def test_narrative_within_n_days_is_not_a_deadline():
    body = GOOD_NOTICE_BODY.replace(
        "I call upon you to pay Rs 2,400 within 15 days of this notice, failing which",
        "The platform replied to me within 3 days. I will")
    r = check_readiness("legal_notice", _full_notice_case(), body)
    assert any("deadline" in m.lower() for m in r.missing)


def test_none_valued_party_fields_do_not_crash():
    case = {
        "sender": {"name": "A", "address": None, "email": None, "worker_id": None},
        "recipient": {"name": "B", "address": "somewhere"},
        "facts": [{"date": "2026-03-10", "text": "f"}],
        "amount_claimed_inr": 2400, "incident_date": "2026-03-10",
    }
    r = check_readiness("legal_notice", case, GOOD_NOTICE_BODY)
    assert next(c for c in r.checks if c.id == "sender").ok is False  # no reach info
