import math
from datetime import datetime, timedelta, timezone

from app.models import Reviewer, User
from app.modules import geo
from app.settings import get_settings
import hashlib


def job_body(**kw):
    start = datetime.now(timezone.utc) + timedelta(days=1)
    b = dict(task="tile", headcount=2, location_text="G-13", start_at=start.isoformat(), daily_rate=1500,
             hours_per_day=8, payment_day=(start + timedelta(days=3)).date().isoformat(), advance=0, deductions=[],
             transport_mode="none")
    b.update(kw)
    return b


def setup_world(client, make_user):
    H, hid = make_user("03000000001", "hirer")
    client.put("/profiles/hirer", headers=H, json={"name": "Kamran", "hirer_type": "contractor"})
    W1, w1 = make_user("03000000002", "worker")
    client.put("/profiles/worker", headers=W1, json={"name": "Ali Khan", "trades": ["tile"], "area_name": "G-11"})
    W2, w2 = make_user("03000000003", "worker")
    client.put("/profiles/worker", headers=W2, json={"name": "Bashir Ahmed", "trades": ["tile"], "area_name": "F-10"})
    return H, hid, W1, w1, W2, w2


def test_haversine_and_fuzz():
    assert abs(geo.haversine_m(33.65, 72.95, 33.65, 72.96) - 928) < 10
    for i in range(30):
        flat, flon = geo.fuzz_location(f"job{i}", 33.6575, 72.959)
        d = geo.haversine_m(33.6575, 72.959, flat, flon)
        assert 100 <= d <= 505, d
    assert geo.fuzz_location("a", 33.6, 72.9) == geo.fuzz_location("a", 33.6, 72.9)  # deterministic


def test_postgis_sql_shape():
    from sqlalchemy.dialects import postgresql
    sql = str(geo.dwithin_clause(33.6, 72.9, 5000).compile(dialect=postgresql.dialect()))
    assert "ST_DWithin" in sql and "geography" in sql


def test_nearby_filters_by_radius_and_hides_exact_location(client, make_user, db):
    H, hid, W1, w1, W2, w2 = setup_world(client, make_user)
    near = client.post("/jobs", headers=H, json=job_body()).json()
    far = client.post("/jobs", headers=H, json=job_body(location_text="Bahria Town", daily_rate=1600)).json()
    res = client.get("/jobs/nearby?radius_km=5", headers=W1).json()
    ids = {j["id"] for j in res}
    assert near["id"] in ids and far["id"] not in ids
    j = next(x for x in res if x["id"] == near["id"])
    assert j["location_exact"] is False and "address_detail" not in j
    assert (j["lat"], j["lon"]) != (near["lat"], near["lon"])
    assert geo.haversine_m(j["lat"], j["lon"], near["lat"], near["lon"]) <= 505
    # wider radius sees both
    assert far["id"] in {x["id"] for x in client.get("/jobs/nearby?radius_km=40", headers=W1).json()}


def test_wage_floor_blocks_lowball_via_api(client, make_user):
    H, *_ = make_user("03000000001", "hirer")
    r = client.post("/jobs", headers=H, json=job_body(daily_rate=500))
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["code"] == "wage_floor" and d["detail"]["violations"][0]["code"] == "below_min_wage"
    assert any("روپے" in v["message"] for v in d["detail"]["violations"])


def test_full_lifecycle_unpaid_case_and_reviewer(client, make_user, db):
    H, hid, W1, w1, W2, w2 = setup_world(client, make_user)
    job = client.post("/jobs", headers=H, json=job_body()).json()
    jid = job["id"]
    # worker 1 accepts, worker 2 counters upward; downward counter rejected
    o1 = client.post(f"/jobs/{jid}/offers", headers=W1, json={}).json()
    assert client.post(f"/jobs/{jid}/offers", headers=W2, json={"rate": 1000}).status_code == 422
    o2 = client.post(f"/jobs/{jid}/offers", headers=W2, json={"rate": 1700}).json()
    assert o2["kind"] == "counter"
    ranked = client.get(f"/jobs/{jid}/offers", headers=H).json()
    assert len(ranked) == 2 and all("phone" not in r for r in ranked) and ranked[0]["first_name"] in ("Ali", "Bashir")
    # assign both
    asg = client.post(f"/jobs/{jid}/assign", headers=H, json={"offer_ids": [o1["id"], o2["id"]]}).json()
    assert len(asg) == 2
    # too many
    assert client.post(f"/jobs/{jid}/assign", headers=H, json={"offer_ids": [o1["id"]]}).status_code == 409
    # agreement: immutable snapshot with exact location, visible to both
    a1 = next(a for a in asg if a["worker_id"] == w1)
    ag = client.get(f"/agreements/{a1['agreement_id']}", headers=W1).json()
    assert ag["terms"]["daily_rate"] == 1500 and ag["terms"]["lat"] == job["lat"]
    ag2 = client.get(f"/agreements/{asg[0]['agreement_id']}", headers=H).json()
    assert ag2["worker"]["phone"] and ag2["hirer"] is None
    assert ag["hirer"]["phone"] and ag["worker"] is None   # each side sees the other's contact only after assignment
    assert len(client.get(f"/jobs/{jid}/assignments", headers=H).json()) == 2
    assert client.get("/my/work", headers=W1).json()[0]["agreement_id"] == a1["agreement_id"]
    from app.models import Agreement
    import pytest
    obj = db.get(Agreement, a1["agreement_id"])
    obj.terms = {"x": 1}
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()
    # exact location unlocked for assigned worker
    assert client.get(f"/jobs/{jid}", headers=W1).json()["location_exact"] is True
    # confirm, start, complete
    for a in asg:
        h = W1 if a["worker_id"] == w1 else W2
        assert client.post(f"/assignments/{a['assignment_id']}/confirm", headers=h).status_code == 200
    assert client.post(f"/jobs/{jid}/start", headers=H).status_code == 200
    assert client.post(f"/jobs/{jid}/complete", headers=H, json={}).json()["status"] == "completed"
    # unpaid report before payment day is refused
    assert client.post(f"/assignments/{a1['assignment_id']}/payment", headers=W1, json={"status": "unpaid"}).status_code == 409
    # a week later: reminders go to both parties, worker reports unpaid
    later = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()
    assert client.post("/dev/tick", params={"now": later}).json()["reminders_sent"] == 4
    assert client.post("/dev/tick", params={"now": later}).json()["reminders_sent"] == 0  # idempotent
    # report unpaid (time override: direct module call with later date)
    from app.modules import payments
    from app.models import Assignment
    payments.report_payment(db, db.get(Assignment, a1["assignment_id"]), db.get(User, w1), "unpaid",
                            now=datetime.now(timezone.utc) + timedelta(days=8))
    assert client.get(f"/jobs/{jid}", headers=H).json()["status"] == "disputed"
    # hirer sees the case WITHOUT the worker's name/phone
    hc = client.get("/my/cases", headers=H).json()
    assert len(hc) == 1 and hc[0]["worker"] == "worker"
    blob = str(hc)
    assert "Ali" not in blob and "+92" not in blob and w1 not in blob
    # worker 2 reports paid → job stays disputed
    payments.report_payment(db, db.get(Assignment, [a for a in asg if a["worker_id"] == w2][0]["assignment_id"]),
                            db.get(User, w2), "paid", now=datetime.now(timezone.utc) + timedelta(days=8))
    assert client.get(f"/jobs/{jid}", headers=H).json()["status"] == "disputed"
    # reputation
    rep = client.get(f"/reputation/{hid}", headers=W1).json()
    assert rep["on_time_payment_rate"] == 0.5 and rep["self_reported"]
    # reviewer
    token = "rev-token"
    db.add(Reviewer(name="Sana", token_hash=hashlib.sha256(token.encode()).hexdigest())); db.commit()
    assert client.get("/admin/api/cases").status_code == 401
    cs = client.get("/admin/api/cases", headers={"X-Reviewer-Token": token}).json()["cases"]
    assert len(cs) == 1 and cs[0]["worker"]["name"] == "Ali Khan"
    act = next(a for a in cs[0]["actions"] if a["type"] == "request_hirer_response")
    r = client.post(f"/admin/api/actions/{act['id']}", headers={"X-Reviewer-Token": token}, json={"approve": True, "note": "call hirer"})
    assert r.json() == {"status": "approved", "reviewer": "Sana"}
    assert client.post(f"/admin/api/actions/{act['id']}", headers={"X-Reviewer-Token": token}, json={"approve": False}).status_code == 409
    # audit trail names the reviewer
    from app.models import AuditLog
    from sqlalchemy import select
    assert db.scalars(select(AuditLog).where(AuditLog.actor == "reviewer:Sana")).first()
    # reviewer resolves → job back to payment_confirmed
    assert client.post(f"/admin/api/cases/{cs[0]['id']}/close", headers={"X-Reviewer-Token": token}, json={"resolution": "paid"}).status_code == 200
    assert client.get(f"/jobs/{jid}", headers=H).json()["status"] == "payment_confirmed"


def test_reputation_completion_and_no_show(client, make_user, db):
    H, hid, W1, w1, W2, w2 = setup_world(client, make_user)
    jid = client.post("/jobs", headers=H, json=job_body()).json()["id"]
    o1 = client.post(f"/jobs/{jid}/offers", headers=W1, json={}).json()
    o2 = client.post(f"/jobs/{jid}/offers", headers=W2, json={}).json()
    asg = client.post(f"/jobs/{jid}/assign", headers=H, json={"offer_ids": [o1["id"], o2["id"]]}).json()
    for a in asg:
        client.post(f"/assignments/{a['assignment_id']}/confirm", headers=W1 if a["worker_id"] == w1 else W2)
    client.post(f"/jobs/{jid}/start", headers=H)
    absent = [a["assignment_id"] for a in asg if a["worker_id"] == w2]
    client.post(f"/jobs/{jid}/complete", headers=H, json={"absent_assignment_ids": absent})
    assert client.get(f"/reputation/{w1}", headers=H).json()["completion_rate"] == 1.0
    assert client.get(f"/reputation/{w2}", headers=H).json()["completion_rate"] == 0.0
    mine = [a for a in asg if a["worker_id"] == w1][0]["assignment_id"]
    assert client.post(f"/assignments/{mine}/rate", headers=H, json={"stars": 5}).status_code == 200
    assert client.get(f"/reputation/{w1}", headers=H).json()["avg_rating"] == 5.0
