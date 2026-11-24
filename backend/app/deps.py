import hashlib

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Reviewer, User
from .security import read_token


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    uid = read_token(token) if token else None
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "unauthenticated")
    if user.suspended:
        raise HTTPException(403, "suspended")
    return user


def need_role(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role != role:
            raise HTTPException(403, f"{role} only")
        return user
    return dep


def reviewer(x_reviewer_token: str = Header(default=""), db: Session = Depends(get_db)) -> Reviewer:
    h = hashlib.sha256(x_reviewer_token.encode()).hexdigest()
    r = db.scalars(select(Reviewer).where(Reviewer.token_hash == h, Reviewer.active == True)).first()  # noqa: E712
    if not r:
        raise HTTPException(401, "reviewer token required")
    return r
