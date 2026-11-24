"""Create a named reviewer. Usage: python scripts/create_reviewer.py "Sana Malik" [token]"""
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Reviewer  # noqa: E402

if __name__ == "__main__":
    init_db()
    name = sys.argv[1]
    token = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(24)
    with SessionLocal() as db:
        db.add(Reviewer(name=name, token_hash=hashlib.sha256(token.encode()).hexdigest()))
        db.commit()
    print(f"reviewer {name!r} created. token: {token}")
