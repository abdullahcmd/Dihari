import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import AICallLog, Job, Notification, User
from app.modules import notifications, payments
from app.modules.notifications import get_sms
from tests.test_m3_flow import job_body, setup_world


def test_report_button_flags_job_after_threshold(client, make_user, db):
    H, hid, W1, w1, W2, w2 = setup_world(client, make_user)
    jid = client.post("/jobs", headers=H, json=job_body()).json()["id"]
    W3, _ = make_user("03000000004", "worker")
    client.put("/profiles/worker", headers=W3, json={"trades": ["tile"], "area_name": "G-13"})
    for h in (W1, W2, W3):
        assert client.post("/reports", headers=h, json={"target_type": "job", "target_id": jid, "reason": "fake"}).status_code == 201
    assert db.get(Job, jid).flagged
    assert jid not in {j["id"] for j in client.get("/jobs/nearby", headers=W1).json()}
    assert client.post(f"/jobs/{jid}/offers", headers=W1, json={}).status_code == 409
    assert client.post("/reports", headers=H, json={"target_type": "job", "target_id": jid, "reason": "x"}).status_code == 400


def test_job_posting_throttles_and_duplicates(client, make_user):
    H, _ = make_user("03000000001", "hirer")
    assert client.post("/jobs", headers=H, json=job_body()).status_code == 201
    assert client.post("/jobs", headers=H, json=job_body()).status_code == 409           # duplicate
    codes = [client.post("/jobs", headers=H, json=job_body(headcount=n + 2, location_text="G-11")).status_code for n in range(8)]
    assert 429 in codes                                                              # open-job / hourly cap


def test_notifications_push_then_sms_fallback(client, make_user, db):
    W, wid = make_user("03000000002", "worker")
    sms = get_sms()
    sms.outbox.clear()
    # inbox provider (log) delivers; no SMS needed
    assert notifications.notify(db, wid, "t", "b") == "log" and not sms.outbox
    # failing push provider → falls through to sms
    class Dead:
        name = "dead"
        def send(self, *a): raise RuntimeError("push down")
    notifications.register_push("dead", Dead)
    from app.settings import get_settings
    import os
    os.environ["NOTIFY_PROVIDERS"] = "dead"; get_settings.cache_clear()
    from app.models import PushSubscription
    db.add(PushSubscription(user_id=wid, endpoint="https://x", keys={})); db.commit()
    assert notifications.notify(db, wid, "t2", "b2") == "sms" and sms.outbox
    os.environ.pop("NOTIFY_PROVIDERS"); get_settings.cache_clear()


def test_notifications_are_localised_and_inbox(client, make_user, db):
    W, wid = make_user("03000000002", "worker")
    notifications.notify(db, wid, "payment_checkin_worker", "x"); db.commit()
    n = client.get("/notifications", headers=W).json()
    assert n and n[0]["channel"] == "log"
    assert client.post("/notifications/subscribe", headers=W, json={"endpoint": "https://p", "keys": {"p256dh": "k"}}).status_code == 201


def test_ai_call_log_written_by_app(client, make_user, db):
    H, _ = make_user("03005550001", "hirer")
    client.post("/voice/draft", headers=H, json={"transcript": "four workers 1500 a day", "lang": "en"})
    rows = db.scalars(select(AICallLog)).all()
    assert {r.provider for r in rows} >= {"mock-a"} and all(r.ok for r in rows)


def test_mcp_tools(client, make_user, db, monkeypatch):
    from fastmcp import Client
    from app import mcp_server
    H, hid, W1, w1, W2, w2 = setup_world(client, make_user)
    start = datetime.now(timezone.utc) + timedelta(days=1)

    async def run():
        async with Client(mcp_server.mcp) as c:
            tools = {t.name for t in await c.list_tools()}
            assert tools == {"post_job", "check_wage_floor", "find_workers", "file_case"}
            chk = (await c.call_tool("check_wage_floor", {"location_text": "G-13", "daily_rate": 500, "hours_per_day": 8})).data
            assert not chk["ok"] and chk["violations"][0]["code"] == "below_min_wage"
            low = (await c.call_tool("post_job", dict(hirer_phone="+923000000001", task="tile", headcount=2, location_text="G-13",
                   start_at=start.isoformat(), daily_rate=500, hours_per_day=8, payment_day=(start + timedelta(days=2)).date().isoformat()))).data
            assert low["posted"] is False and low["code"] == "wage_floor"
            ok = (await c.call_tool("post_job", dict(hirer_phone="+923000000001", task="tile", headcount=2, location_text="G-13",
                  start_at=start.isoformat(), daily_rate=1500, hours_per_day=8, payment_day=(start + timedelta(days=2)).date().isoformat()))).data
            assert ok["posted"] is True
            ws = (await c.call_tool("find_workers", {"lat": 33.66, "lon": 72.96, "radius_km": 10, "trade": "tile"})).data
            assert {w["first_name"] for w in ws} == {"Ali", "Bashir"} and all("phone" not in w for w in ws)
            nf = (await c.call_tool("file_case", {"worker_phone": "+923000000002", "assignment_id": "nope"})).data
            assert nf == {"filed": False, "code": "not_found"}
    # the MCP server opens its own sessions on the same in-memory engine
    asyncio.run(run())
