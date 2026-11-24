from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Job, Report, User
from ..modules import audit
from ..modules.abuse import RateLimited, limiter
from ..settings import get_settings

router = APIRouter(prefix="/reports", tags=["abuse"])


class ReportIn(BaseModel):
    target_type: str = Field(pattern="^(job|user)$")
    target_id: str
    reason: str = Field(min_length=1, max_length=200)


@router.post("", status_code=201)
def report(body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        limiter.check(f"report:{user.id}", 10, 86400)
    except RateLimited:
        raise HTTPException(429, "rate_limited")
    target = db.get(Job if body.target_type == "job" else User, body.target_id)
    if not target:
        raise HTTPException(404)
    if body.target_type == "job" and target.hirer_id == user.id or body.target_type == "user" and target.id == user.id:
        raise HTTPException(400, "cannot report yourself")
    dup = db.scalars(select(Report).where(Report.reporter_id == user.id, Report.target_id == body.target_id)).first()
    if not dup:
        db.add(Report(reporter_id=user.id, target_type=body.target_type, target_id=body.target_id, reason=body.reason))
        db.flush()
        audit.log(db, user.id, body.target_type, body.target_id, "reported", data={"reason": body.reason})
        if body.target_type == "job":
            n = db.scalar(select(func.count(func.distinct(Report.reporter_id))).where(Report.target_id == body.target_id))
            if n >= get_settings().reports_to_flag_job and not target.flagged:
                target.flagged = True   # hidden from the nearby feed until a human looks
                audit.log(db, "system", "job", target.id, "auto_flagged", data={"reports": n})
    db.commit()
    return {"ok": True}
