from sqlalchemy.orm import Session

from ..models import AuditLog


def log(db: Session, actor: str, entity: str, entity_id: str, action: str,
        from_state: str | None = None, to_state: str | None = None, data: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, entity=entity, entity_id=entity_id, action=action,
                    from_state=from_state, to_state=to_state, data=data))
