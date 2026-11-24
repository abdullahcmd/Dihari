import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.modules.abuse import limiter
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("DEV_MODE", "true")
    get_settings.cache_clear()
    dbmod.init_db("sqlite://")
    limiter.reset()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db():
    s = dbmod.SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c


def login(client, phone, role):
    r = client.post("/auth/request-otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    code = r.json()["dev_otp"]
    r = client.post("/auth/verify-otp", json={"phone": phone, "code": code, "role": role})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}"}, d["user_id"]


@pytest.fixture
def make_user(client):
    def _mk(phone, role):
        return login(client, phone, role)
    return _mk
