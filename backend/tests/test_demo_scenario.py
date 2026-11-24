"""The DEMO.md 3-minute story, executed through the public API only."""
from datetime import datetime, timedelta, timezone
import hashlib

from app.models import Reviewer


def test_demo_story(client, make_user, db):
    H, hid = make_user("03000000001", "hirer")
    client.put("/profiles/hirer", headers=H, json={"name": "Kamran", "hirer_type": "contractor"})
    W, wid = make_user("03000000002", "worker")
    client.put("/profiles/worker", headers=W, json={"name": "Ali Raza", "trades": ["tile"], "area_name": "G-11"})

    # 1. hirer lowballs by voice → the floor stops it, with a spoken-language explanation and a one-tap fix
    say = "چار مزدور کل صبح 8 بجے جی 13 میں ٹائل کا کام روزانہ 600 روپے"
    d = client.post("/voice/draft", headers=H, json={"transcript": say, "lang": "ur"}).json()
    for field, answer in [("hours_per_day", "8 گھنٹے"), ("payment_day", "ادائیگی جمعہ کو"), ("deductions", "نہیں"),
                          ("advance", "صفر"), ("transport_mode", "نہیں")]:
        if d["next_question"] and d["next_question"]["field"] == field:
            d = client.post("/voice/answer", headers=H, json={"field": field, "transcript": answer, "fields": d["fields"], "lang": "ur"}).json()
    assert not d["ready"] and not d["can_post"]
    assert "کم از کم" in d["wage"]["violations"][0]["message"]
    fix = d["fixes"][0]
    assert fix == {"field": "daily_rate", "value": 1000, "code": "below_min_wage"}
    assert client.post("/jobs", headers=H, json={**d["fields"], "start_at": d["fields"]["start_at"]}).status_code == 422   # server refuses too

    # 2. hirer fixes the offer → read-back in Urdu → confirms
    d = client.post("/voice/validate", headers=H, json={"fields": {**d["fields"], "daily_rate": 1500}, "lang": "ur"}).json()
    assert d["ready"] and d["can_post"] and "1500" in d["readback"]
    assert client.post("/voice/intent", headers=H, json={"transcript": "ہاں"}).json()["intent"] == "yes"
    job = client.post("/jobs", headers=H, json={**d["fields"], "readback_verified": d["verifier"]["ok"]}).json()

    # 3. worker hears the job in Urdu and accepts
    near = client.get("/jobs/nearby?radius_km=10", headers=W).json()
    assert [j["id"] for j in near] == [job["id"]] and near[0]["location_exact"] is False
    spoken = client.get(f"/jobs/{job['id']}/readback", headers=W).json()["text"]
    assert "ٹائل" in spoken and "1500" in spoken
    offer = client.post(f"/jobs/{job['id']}/offers", headers=W, json={}).json()
    asg = client.post(f"/jobs/{job['id']}/assign", headers=H, json={"offer_ids": [offer["id"]]}).json()[0]
    assert "1500" in client.get(f"/agreements/{asg['agreement_id']}/readback", headers=W).json()["text"]
    client.post(f"/assignments/{asg['assignment_id']}/confirm", headers=W)
    client.post(f"/jobs/{job['id']}/start", headers=H)
    client.post(f"/jobs/{job['id']}/complete", headers=H, json={})

    # 4. a week later: "پیسے نہیں ملے" → case → human approves
    assert client.post("/dev/advance-days", params={"days": 8}).json()["offset_days"] == 8
    assert client.post("/dev/tick").json()["reminders_sent"] == 2
    assert client.post(f"/assignments/{asg['assignment_id']}/payment", headers=W, json={"status": "unpaid"}).status_code == 200
    assert client.get(f"/jobs/{job['id']}", headers=H).json()["status"] == "disputed"
    db.add(Reviewer(name="Sana", token_hash=hashlib.sha256(b"t").hexdigest())); db.commit()
    case = client.get("/admin/api/cases", headers={"X-Reviewer-Token": "t"}).json()["cases"][0]
    act = next(a for a in case["actions"] if a["type"] == "request_hirer_response")
    r = client.post(f"/admin/api/actions/{act['id']}", headers={"X-Reviewer-Token": "t"}, json={"approve": True})
    assert r.json()["reviewer"] == "Sana"
    inbox = client.get("/notifications", headers=H).json()
    assert any("ادائیگی" in n["title"] for n in inbox)    # hirer notified in Urdu, no worker name
    assert "Ali" not in str(inbox)
