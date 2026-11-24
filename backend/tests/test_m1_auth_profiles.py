import pytest
from app.country_config import get_country, registry
from app import i18n


def test_phone_normalisation_from_config():
    c = get_country("PK")
    assert c.normalize_phone("0300 1234567") == "+923001234567"
    assert c.normalize_phone("+92 300 1234567") == "+923001234567"
    assert c.normalize_phone("123") is None
    assert c.normalize_phone("+14155550123") is None


def test_otp_flow_and_wrong_code(client):
    r = client.post("/auth/request-otp", json={"phone": "03001234567"})
    assert r.status_code == 200 and r.json()["phone"] == "+923001234567"
    bad = client.post("/auth/verify-otp", json={"phone": "03001234567", "code": "000000"})
    assert bad.status_code == 400 and bad.json()["detail"] == "otp_wrong"
    ok = client.post("/auth/verify-otp", json={"phone": "03001234567", "code": r.json()["dev_otp"], "role": "worker"})
    assert ok.status_code == 200 and ok.json()["is_new"]


def test_otp_reuse_rejected(client):
    r = client.post("/auth/request-otp", json={"phone": "03001234567"}).json()
    client.post("/auth/verify-otp", json={"phone": "03001234567", "code": r["dev_otp"]})
    again = client.post("/auth/verify-otp", json={"phone": "03001234567", "code": r["dev_otp"]})
    assert again.status_code == 400


def test_otp_rate_limited(client):
    for _ in range(3):
        assert client.post("/auth/request-otp", json={"phone": "03001234567"}).status_code == 200
    assert client.post("/auth/request-otp", json={"phone": "03001234567"}).status_code == 429


def test_otp_attempt_lockout(client):
    r = client.post("/auth/request-otp", json={"phone": "03001234567"}).json()
    for _ in range(5):
        client.post("/auth/verify-otp", json={"phone": "03001234567", "code": "111111"})
    locked = client.post("/auth/verify-otp", json={"phone": "03001234567", "code": r["dev_otp"]})
    assert locked.json()["detail"] == "otp_locked"


def test_profiles(client, make_user):
    h, _ = make_user("03001111111", "worker")
    r = client.put("/profiles/worker", headers=h, json={"trades": ["tile"], "area_name": "G-13", "radius_km": 500})
    assert r.status_code == 200
    assert r.json()["lat"] and r.json()["radius_km"] == 40  # clamped to country max
    assert client.put("/profiles/worker", headers=h, json={"trades": ["nope"]}).status_code == 400
    assert client.put("/profiles/hirer", headers=h, json={}).status_code == 403
    h2, _ = make_user("03002222222", "hirer")
    assert client.put("/profiles/hirer", headers=h2, json={"hirer_type": "contractor"}).status_code == 200
    assert client.put("/profiles/hirer", headers=h2, json={"hirer_type": "alien"}).status_code == 400
    assert client.get("/profiles/me").status_code == 401


def test_i18n_fallback_and_lexicon():
    assert i18n.t("app.name", "ur") == "دیہاڑی"
    assert i18n.t("app.name", "xx") == "Dihari"  # falls back to en
    assert "ہاں" in i18n.lexicon("yes", "ur")
