"""Case files for unpaid reports. Rules propose follow-ups; a NAMED HUMAN approves or rejects. AI never decides."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Assignment, Case, CaseAction, HirerProfile, Job, JobStatus as S, Reviewer, User
from . import audit
from .notifications import notify

ACTION_TYPES = {"remind_hirer", "request_hirer_response", "restrict_hirer_posting", "close_no_action"}


class CaseError(Exception):
    pass


def open_case(db: Session, asg: Assignment, job: Job) -> Case:
    existing = db.scalars(select(Case).where(Case.assignment_id == asg.id)).first()
    if existing:
        return existing
    c = Case(assignment_id=asg.id, job_id=job.id, hirer_id=job.hirer_id, worker_id=asg.worker_id,
             summary=f"Worker reported NOT PAID. Job {job.id}, payment day {job.payment_day}.")
    db.add(c)
    db.flush()
    prior = db.scalar(select(func.count()).select_from(Case).where(Case.hirer_id == job.hirer_id, Case.id != c.id))
    props = ["request_hirer_response", "remind_hirer"]
    if prior >= 2:
        props.append("restrict_hirer_posting")
    props.append("close_no_action")
    for p in props:
        db.add(CaseAction(case_id=c.id, action_type=p, proposed_by="rules"))
    audit.log(db, asg.worker_id, "case", c.id, "opened", data={"assignment": asg.id, "proposed": props})
    return c


def reviewer_view(db: Session, c: Case) -> dict:
    """Full detail for the human reviewer only."""
    worker, hirer = db.get(User, c.worker_id), db.get(User, c.hirer_id)
    asg = db.get(Assignment, c.assignment_id)
    from ..models import Agreement
    ag = db.get(Agreement, asg.agreement_id)
    return {"id": c.id, "status": c.status, "summary": c.summary, "created_at": c.created_at.isoformat(),
            "worker": {"name": worker.name, "phone": worker.phone}, "hirer": {"name": hirer.name, "phone": hirer.phone},
            "worker_report": asg.payment_report, "hirer_claim": asg.hirer_payment_claim,
            "agreement": {"id": ag.id, "terms": ag.terms, "hash": ag.terms_hash},
            "actions": [{"id": a.id, "type": a.action_type, "status": a.status, "reviewer": a.reviewer_name,
                         "note": a.note} for a in c.actions]}


def hirer_view(db: Session, c: Case) -> dict:
    """What the accused hirer may see. NEVER the worker's name or phone."""
    asg = db.get(Assignment, c.assignment_id)
    from ..models import Agreement
    ag = db.get(Agreement, asg.agreement_id)
    t = ag.terms
    return {"id": c.id, "status": c.status, "worker": "worker",
            "terms": {k: t[k] for k in ("task", "daily_rate", "days", "payment_day", "start_at", "location_text")}}


def decide(db: Session, reviewer: Reviewer, action_id: str, approve: bool, note: str | None = None) -> CaseAction:
    a = db.get(CaseAction, action_id)
    if not a or a.status != "proposed":
        raise CaseError("action_not_pending")
    a.status = "approved" if approve else "rejected"
    a.reviewer_name, a.note, a.decided_at = reviewer.name, note, utcnow()
    c = a.case
    audit.log(db, f"reviewer:{reviewer.name}", "case_action", a.id, a.status, data={"type": a.action_type, "case": c.id})
    if approve:
        if a.action_type in ("remind_hirer", "request_hirer_response"):
            notify(db, c.hirer_id, "payment_case", c.id)
        elif a.action_type == "restrict_hirer_posting":
            hp = db.get(HirerProfile, c.hirer_id) or HirerProfile(user_id=c.hirer_id)
            hp.posting_restricted = True
            db.add(hp)
        elif a.action_type == "close_no_action":
            c.status = "closed"
    db.commit()
    return a


def close_case(db: Session, reviewer: Reviewer, c: Case, resolution: str) -> Case:
    if resolution not in ("paid", "unresolved"):
        raise CaseError("bad_resolution")
    c.status = "closed"
    asg = db.get(Assignment, c.assignment_id)
    if resolution == "paid":
        asg.payment_report = "paid"
    audit.log(db, f"reviewer:{reviewer.name}", "case", c.id, f"closed_{resolution}")
    job = db.get(Job, c.job_id)
    if resolution == "paid" and job.status == S.disputed.value:
        open_left = db.scalar(select(func.count()).select_from(Case).where(Case.job_id == job.id, Case.status == "open", Case.id != c.id))
        if not open_left:
            from . import jobs
            jobs.transition(db, job, S.payment_confirmed, f"reviewer:{reviewer.name}")
    db.commit()
    return c
