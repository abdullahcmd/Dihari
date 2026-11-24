from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import reviewer
from ..models import Case, Reviewer
from ..modules import cases

router = APIRouter(prefix="/admin", tags=["admin"])
PAGE = Path(__file__).resolve().parent.parent / "admin_ui" / "index.html"


class Decide(BaseModel):
    approve: bool
    note: str | None = None


class CloseIn(BaseModel):
    resolution: str


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE.read_text(encoding="utf-8") if PAGE.exists() else "<h1>reviewer page missing</h1>"


@router.get("/api/cases")
def list_cases(status: str = "open", rev: Reviewer = Depends(reviewer), db: Session = Depends(get_db)):
    q = select(Case).order_by(Case.created_at.desc())
    if status != "all":
        q = q.where(Case.status == status)
    return {"reviewer": rev.name, "cases": [cases.reviewer_view(db, c) for c in db.scalars(q)]}


@router.post("/api/actions/{action_id}")
def decide(action_id: str, body: Decide, rev: Reviewer = Depends(reviewer), db: Session = Depends(get_db)):
    try:
        a = cases.decide(db, rev, action_id, body.approve, body.note)
    except cases.CaseError as e:
        raise HTTPException(409, str(e))
    return {"status": a.status, "reviewer": a.reviewer_name}


@router.post("/api/cases/{case_id}/close")
def close(case_id: str, body: CloseIn, rev: Reviewer = Depends(reviewer), db: Session = Depends(get_db)):
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404)
    try:
        cases.close_case(db, rev, c, body.resolution)
    except cases.CaseError as e:
        raise HTTPException(400, str(e))
    return {"status": c.status}
