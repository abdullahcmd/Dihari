from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Notification, PushSubscription, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class SubIn(BaseModel):
    endpoint: str
    keys: dict = {}


@router.get("")
def inbox(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50))
    return [{"id": n.id, "title": n.title, "body": n.body, "channel": n.channel, "at": n.created_at.isoformat()} for n in rows]


@router.post("/subscribe", status_code=201)
def subscribe(body: SubIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.scalars(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)).first():
        db.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, keys=body.keys))
        db.commit()
    return {"ok": True}
