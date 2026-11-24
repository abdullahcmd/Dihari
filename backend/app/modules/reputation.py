from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Assignment, Job, User


def first_name(user: User | None) -> str:
    return (user.name or "").split(" ")[0] if user and user.name else "—"


def hirer_reputation(db: Session, hirer_id: str) -> dict:
    rows = db.execute(select(Assignment.payment_report, func.count()).join(Job, Job.id == Assignment.job_id)
                      .where(Job.hirer_id == hirer_id, Assignment.payment_report.is_not(None))
                      .group_by(Assignment.payment_report)).all()
    c = {k: n for k, n in rows}
    paid, unpaid = c.get("paid", 0), c.get("unpaid", 0)
    jobs_posted = db.scalar(select(func.count()).select_from(Job).where(Job.hirer_id == hirer_id))
    return {"on_time_payment_rate": paid / (paid + unpaid) if paid + unpaid else None,
            "reports": paid + unpaid, "jobs_posted": jobs_posted, "self_reported": True}


def worker_reputation(db: Session, worker_id: str) -> dict:
    rows = db.execute(select(Assignment.status, func.count()).where(Assignment.worker_id == worker_id)
                      .group_by(Assignment.status)).all()
    c = {k: n for k, n in rows}
    done, bad = c.get("completed", 0), c.get("no_show", 0) + c.get("cancelled", 0)
    avg, n = db.execute(select(func.avg(Assignment.rating), func.count(Assignment.rating))
                        .where(Assignment.worker_id == worker_id, Assignment.rating.is_not(None))).one()
    return {"completion_rate": done / (done + bad) if done + bad else None, "jobs_completed": done,
            "avg_rating": float(avg) if avg is not None else None, "ratings": n}
