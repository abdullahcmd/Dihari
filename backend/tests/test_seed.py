import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from seed import seed  # noqa: E402


def test_seed_populates_demo_world_and_is_idempotent(db, client):
    r = seed(db)
    assert r["workers"] == 30 and r["jobs"] >= 10
    assert seed(db) == {"skipped": True}
    from app.models import Job
    from sqlalchemy import select
    assert all(j.daily_rate >= 1000 for j in db.scalars(select(Job)))
    # a seeded worker can log in and see nearby jobs
    ph = r["demo_worker_phone"]
    a = client.post("/auth/request-otp", json={"phone": ph}).json()
    tok = client.post("/auth/verify-otp", json={"phone": ph, "code": a["dev_otp"]}).json()["token"]
    jobs = client.get("/jobs/nearby?radius_km=40", headers={"Authorization": f"Bearer {tok}"}).json()
    assert jobs
