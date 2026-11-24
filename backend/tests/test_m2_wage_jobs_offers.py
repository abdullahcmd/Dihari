from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import Job, JobStatus as S, User
from app.modules import jobs, offers, wage_floor
from app.modules.offers import OfferError

TODAY = date(2026, 6, 1)


def chk(**kw):
    base = dict(country="PK", region="ICT", daily_rate=1500, hours_per_day=8, payment_day=TODAY + timedelta(days=3),
                start_date=TODAY + timedelta(days=1), days=1, deductions=[], on=TODAY)
    base.update(kw)
    return wage_floor.check(**base)


def codes(r):
    return {v.code for v in r.violations}


def test_floor_pass_and_unverified_warning():
    r = chk()
    assert r.ok and "unverified_rule" in r.warnings
    assert r.rule.verified is False and r.rule.placeholder is True


def test_below_min_wage_explained_in_urdu():
    r = chk(daily_rate=600)
    assert "below_min_wage" in codes(r)
    msg = r.explain("ur")[0]
    assert "1000" in msg and "روپے" in msg


def test_hours_payment_and_hidden_deductions():
    assert "hours_exceed_max" in codes(chk(hours_per_day=12))
    assert "missing_payment_day" in codes(chk(payment_day=None))
    assert "payment_too_late" in codes(chk(payment_day=TODAY + timedelta(days=30)))
    assert "payment_before_start" in codes(chk(payment_day=TODAY))
    assert "hidden_deduction" in codes(chk(deductions=[{"label": "food", "amount": None}]))
    assert "net_below_min_wage" in codes(chk(daily_rate=1100, deductions=[{"label": "food", "amount": 300}]))
    assert chk(deductions=[{"label": "food", "amount": 100}]).ok


def test_rule_versioning_picks_latest_effective(tmp_path):
    rules = [
        wage_floor.Rule("*", "old", date(2020, 1, 1), "XXX", 500, 8, 7, None, True),
        wage_floor.Rule("*", "new", date(2026, 1, 1), "XXX", 900, 8, 7, "http://x", True),
    ]
    assert wage_floor.find_rule("PK", "ICT", date(2025, 1, 1), rules).version == "old"
    assert wage_floor.find_rule("PK", "ICT", date(2026, 6, 1), rules).version == "new"
    r = wage_floor.check(country="PK", region="ICT", daily_rate=700, hours_per_day=8, payment_day=TODAY + timedelta(days=2),
                         start_date=TODAY + timedelta(days=1), on=TODAY, rules=rules)
    assert "below_min_wage" in codes(r) and not r.warnings


@pytest.fixture
def hirer(db):
    u = User(phone="+923001000001", country_code="PK", role="hirer", locale="ur", phone_verified=True)
    db.add(u); db.commit(); return u


@pytest.fixture
def worker(db):
    u = User(phone="+923001000002", country_code="PK", role="worker", locale="ur", phone_verified=True)
    db.add(u); db.commit(); return u


def fields(**kw):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    f = dict(task="tile", headcount=2, location_text="G-13", start_at=start, daily_rate=1500, hours_per_day=8,
             payment_day=start.date() + timedelta(days=2), advance=0, deductions=[], transport_mode="none", days=1)
    f.update(kw)
    return f


def test_create_job_rejects_below_floor(db, hirer):
    with pytest.raises(jobs.JobRejected) as e:
        jobs.create_job(db, hirer, fields(daily_rate=500))
    assert e.value.code == "wage_floor"
    assert e.value.detail["violations"][0]["code"] == "below_min_wage"


def test_create_job_missing_fields_and_location(db, hirer):
    with pytest.raises(jobs.JobRejected) as e:
        jobs.create_job(db, hirer, fields(daily_rate=None))
    assert e.value.code == "missing_fields"
    with pytest.raises(jobs.JobRejected) as e:
        jobs.create_job(db, hirer, fields(location_text="Atlantis"))
    assert e.value.code == "location_unresolved"


def test_state_machine_legal_path_and_audit(db, hirer):
    j = jobs.create_job(db, hirer, fields())
    for to in [S.offers, S.assigned, S.in_progress, S.completed, S.payment_confirmed]:
        jobs.transition(db, j, to, hirer.id)
    db.commit()
    from app.models import AuditLog
    from sqlalchemy import select
    rows = db.scalars(select(AuditLog).where(AuditLog.entity == "job", AuditLog.entity_id == j.id)).all()
    assert len(rows) == 6  # created + 5 transitions


@pytest.mark.parametrize("path,bad", [
    ([], S.completed), ([], S.in_progress), ([], S.payment_confirmed),
    ([S.offers, S.assigned], S.completed),
    ([S.offers, S.assigned, S.in_progress, S.completed, S.payment_confirmed], S.disputed),
    ([S.cancelled], S.offers), ([S.offers, S.assigned, S.in_progress], S.cancelled),
    ([S.offers, S.assigned, S.in_progress, S.completed], S.in_progress),
])
def test_illegal_transitions_raise(db, hirer, path, bad):
    j = jobs.create_job(db, hirer, fields())
    for to in path:
        jobs.transition(db, j, to, "t")
    with pytest.raises(jobs.IllegalTransition):
        jobs.transition(db, j, bad, "t")


def test_every_pair_matches_table(db, hirer):
    j = jobs.create_job(db, hirer, fields())
    for frm in S:
        for to in S:
            j.status = frm.value
            allowed = to in jobs.TRANSITIONS[frm] and (to != frm or frm in (S.offers, S.assigned))
            if allowed:
                jobs.transition(db, j, to, "t")
            else:
                with pytest.raises(jobs.IllegalTransition):
                    jobs.transition(db, j, to, "t")


def test_offers_upward_only(db, hirer, worker):
    j = jobs.create_job(db, hirer, fields())
    with pytest.raises(OfferError) as e:
        offers.make_offer(db, j, worker, 1400)
    assert e.value.code == "counter_must_be_higher"
    with pytest.raises(OfferError) as e:
        offers.make_offer(db, j, worker, 99999)
    assert e.value.code == "counter_too_high"
    o = offers.make_offer(db, j, worker, 1700)
    assert o.kind == "counter" and j.status == "offers"
    o = offers.make_offer(db, j, worker, 1600)  # revising own counter, still above the posted rate
    assert o.rate == 1600
    with pytest.raises(OfferError):
        offers.make_offer(db, j, worker, 1499)
    o = offers.make_offer(db, j, worker, None)
    assert o.kind == "accept" and o.rate == 1500


def test_offer_on_closed_job(db, hirer, worker):
    j = jobs.create_job(db, hirer, fields())
    jobs.transition(db, j, S.cancelled, "t")
    with pytest.raises(OfferError):
        offers.make_offer(db, j, worker)
