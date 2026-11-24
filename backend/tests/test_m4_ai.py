from datetime import datetime, timezone

import pytest

from app.ai import chain as chainmod, extraction, numbers as nm, pipeline, readback, registry, service, validation
from app.ai.base import AIUnavailable, ConfigError
from app.ai.chain import Chain
from app.country_config import get_country
from app.settings import get_settings

NOW = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)   # a Monday
CFG = lambda: get_country("PK")  # noqa: E731


@pytest.fixture(autouse=True)
def _reset():
    service.reset()
    chainmod.clear_sinks()
    yield
    service.reset()


def test_number_parsing_digits_words_and_multipliers():
    assert 1500 in nm.numbers_in("1500 a day")
    assert 1500 in nm.numbers_in("پندرہ سو روپے")
    assert 1500 in nm.numbers_in("ڈیڑھ ہزار")
    assert 2000 in nm.numbers_in("دو ہزار")
    assert 4 in nm.numbers_in("four workers")
    assert 1500 in nm.numbers_in("۱۵۰۰")
    assert 100 not in nm.numbers_in("hazar")


def test_extraction_english_example_from_spec():
    ex = extraction.extract("four workers, tomorrow 8am, tile work in G-13, 1500 a day", CFG(), service.get_chain("extract"), "en", NOW)
    f = ex.fields
    assert f["headcount"] == 4 and f["daily_rate"] == 1500 and f["task"] == "tile" and f["location_text"] == "G-13"
    assert f["start_at"].startswith("2026-06-02T08:00")
    assert f["hours_per_day"] is None and f["payment_day"] is None and f["deductions"] is None


def test_extraction_urdu():
    t = "چار مزدور چاہئیں کل صبح 8 بجے جی 13 میں ٹائل کا کام روزانہ 1500 روپے"
    f = extraction.extract(t, CFG(), service.get_chain("extract"), "ur", NOW).fields
    assert f["headcount"] == 4 and f["daily_rate"] == 1500 and f["task"] == "tile" and f["location_text"] == "G-13"
    assert f["start_at"].startswith("2026-06-02T08:00")


def test_grounding_removes_numbers_llm_invented():
    fields = {"headcount": 4, "daily_rate": 2500, "hours_per_day": 8, "payment_day": "2026-06-05", "start_at": "2026-06-02T08:00:00+05:00"}
    g, unc = extraction.ground(fields, "four workers 1500 a day", "en")
    assert g["daily_rate"] is None and g["hours_per_day"] is None and g["headcount"] == 4
    assert g["payment_day"] is None and g["start_at"] is None
    assert set(unc) >= {"daily_rate", "hours_per_day", "payment_day", "start_at"}


def test_hidden_deduction_detected_when_amount_missing():
    f = extraction.extract("two workers tomorrow 9am tile G-13 1200 a day 8 hours pay friday deductions for food", CFG(),
                           service.get_chain("extract"), "en", NOW).fields
    assert f["deductions"] == [{"label": "deduction", "amount": None}]
    rep = validation.validate(f | {"advance": 0, "transport_mode": "none"}, CFG(), "en", NOW)
    assert any(v["code"] == "hidden_deduction" for v in rep.wage["violations"]) and not rep.ready


def test_validate_asks_one_question_at_a_time_in_order():
    d = pipeline.draft_from_text("four workers, tomorrow 8am, tile work in G-13, 1500 a day", CFG(), "ur", None, NOW)
    assert not d["ready"] and d["next_question"]["field"] == "hours_per_day"
    assert d["next_question"]["prompt"] == "روزانہ کتنے گھنٹے کام ہوگا؟"
    steps = [("hours_per_day", "8 hours"), ("payment_day", "payment on friday"), ("deductions", "نہیں"),
             ("advance", "zero"), ("transport_mode", "no")]
    for fld, said in steps:
        assert d["next_question"]["field"] == fld, d["next_question"]
        d = pipeline.draft_from_answer(fld, said, d["fields"], CFG(), "ur", NOW)
    assert d["ready"] and d["can_post"] and d["readback"]
    assert d["verifier"]["ok"] is True and d["verifier"]["provider"] == "mock-b"
    assert "1500" in d["readback"] and "G-13" in d["readback"] and "ٹائل" in d["readback"]


def test_lowball_stopped_with_fix_suggestion():
    f = {"task": "tile", "headcount": 2, "location_text": "G-13", "start_at": "2026-06-02T08:00:00+05:00", "daily_rate": 600,
         "hours_per_day": 8, "payment_day": "2026-06-05", "deductions": [], "advance": 0, "transport_mode": "none"}
    d = pipeline.draft_from_fields(f, CFG(), "ur", NOW)
    assert not d["ready"] and not d["can_post"]
    assert d["fixes"] == [{"field": "daily_rate", "value": 1000, "code": "below_min_wage"}]
    f["daily_rate"] = 1000
    assert pipeline.draft_from_fields(f, CFG(), "ur", NOW)["ready"]


def test_unknown_place_is_asked_back():
    f = {"task": "tile", "headcount": 2, "location_text": "Nowhereville", "start_at": "2026-06-02T08:00:00+05:00", "daily_rate": 1500,
         "hours_per_day": 8, "payment_day": "2026-06-05", "deductions": [], "advance": 0, "transport_mode": "none"}
    d = pipeline.draft_from_fields(f, CFG(), "en", NOW)
    assert d["next_question"]["field"] == "location_text" and d["next_question"]["invalid"]


def test_yes_no_intent():
    assert nm.yes_no("ہاں", "ur") == "yes" and nm.yes_no("جی ہاں", "ur") == "yes"
    assert nm.yes_no("نہیں", "ur") == "no" and nm.yes_no("haan theek hai", "ur") == "yes"
    assert nm.yes_no("hmm", "ur") == "unknown"


class Boom:
    name, family, is_mock = "boom", "boom-family", False
    def complete_json(self, **kw): raise RuntimeError("down")
    def transcribe(self, *a): raise RuntimeError("down")


def test_chain_falls_back_and_logs():
    recs = []
    chainmod.add_sink(recs.append)
    ch = Chain("asr", [Boom(), registry.build("asr", ["mock"])[0]])
    res, prov = ch.call("transcribe", b"hello", "audio/webm", "ur")
    assert prov == "mock" and res.text == "hello"
    assert [(r.provider, r.ok) for r in recs] == [("boom", False), ("mock", True)]
    assert recs[0].error and recs[1].latency_ms >= 0


def test_all_providers_down_degrades_to_tap_only():
    service._cache["extract"] = Chain("llm", [Boom()])
    d = pipeline.draft_from_text("anything", CFG(), "ur", None, NOW)
    assert d["degraded"] is True and d["fields"] == {} and d["next_question"]["field"] == "task"
    with pytest.raises(AIUnavailable):
        Chain("asr", [Boom()]).call("transcribe", b"x", "a", "ur")


def test_schema_invalid_llm_output_counts_as_failure_and_falls_over():
    class Bad:
        name, family, is_mock = "bad", "bad", False
        def complete_json(self, **kw): return {"headcount": "lots"}
    good = registry.build("llm", ["mock-a"])[0]
    ex = extraction.extract("four workers 1500 a day", CFG(), Chain("llm", [Bad(), good]), "en", NOW)
    assert ex.provider == "mock-a" and ex.fields["headcount"] == 4


def test_verifier_must_be_different_family(monkeypatch):
    monkeypatch.setenv("LLM_VERIFY_PROVIDERS", "mock-a")
    get_settings.cache_clear(); service.reset()
    with pytest.raises(ConfigError):
        service.check_families()
    monkeypatch.setenv("LLM_VERIFY_PROVIDERS", "mock-b")
    get_settings.cache_clear(); service.reset()
    service.check_families()


def test_verifier_mismatch_blocks_but_cannot_unblock():
    f = {"task": "tile", "headcount": 2, "location_text": "G-13", "start_at": "2026-06-02T08:00:00+05:00", "daily_rate": 1500,
         "hours_per_day": 8, "payment_day": "2026-06-05", "deductions": [], "advance": 0, "transport_mode": "none"}
    class Liar:
        name, family, is_mock = "liar", "liar", False
        def complete_json(self, **kw): return {"matches": False, "mismatches": ["rate wrong"]}
    class Yes(Liar):
        def complete_json(self, **kw): return {"matches": True, "mismatches": []}
    service._cache["verify"] = Chain("llm", [Liar()])
    d = pipeline.draft_from_fields(f, CFG(), "ur", NOW)
    assert d["ready"] and d["can_post"] is False
    f["daily_rate"] = 100
    service._cache["verify"] = Chain("llm", [Yes()])
    d = pipeline.draft_from_fields(f, CFG(), "ur", NOW)
    assert d["can_post"] is False and not d["ready"]
    service._cache["verify"] = Chain("llm", [Boom()])
    f["daily_rate"] = 1500
    d = pipeline.draft_from_fields(f, CFG(), "ur", NOW)
    assert d["can_post"] is True and d["verifier"]["available"] is False


def test_mock_verifier_catches_wrong_readback():
    from app.ai.verifier import verify
    v = verify("3 workers 1500 per day", {"headcount": 4, "daily_rate": 1500}, service.get_chain("verify"))
    assert v.ok is False and v.mismatches


def test_readback_urdu_contains_all_terms():
    f = {"task": "tile", "headcount": 4, "location_text": "G-13", "start_at": "2026-06-02T08:00:00+05:00", "daily_rate": 1500,
         "hours_per_day": 8, "payment_day": "2026-06-05", "days": 2, "deductions": [{"label": "کھانا", "amount": 100}],
         "advance": 500, "transport_mode": "allowance", "transport_amount": 200}
    t = readback.render(f, CFG(), "ur", NOW)
    for s in ["4", "1500", "G-13", "کل", "صبح 8 بجے", "100", "500", "200", "جمعہ"]:
        assert s in t, (s, t)


def test_voice_endpoints_end_to_end(client, make_user):
    H, _ = make_user("03005550001", "hirer")
    caps = client.get("/ai/capabilities").json()
    assert caps["tts"]["real"] is False and caps["asr"]["real"] is False
    r = client.post("/ai/transcribe", headers=H, files={"audio": ("a.webm", "four workers 1500 a day".encode(), "audio/webm")}, data={"lang": "en"})
    assert r.status_code == 200 and r.json()["text"] == "four workers 1500 a day"
    assert client.post("/ai/tts", headers=H, json={"text": "salam", "lang": "ur"}).headers["X-TTS-Provider"] == "mock"
    d = client.post("/voice/draft", headers=H, json={"transcript": r.json()["text"], "lang": "en"}).json()
    assert d["fields"]["headcount"] == 4 and d["next_question"]
    assert client.post("/voice/intent", headers=H, json={"transcript": "ہاں"}).json()["intent"] == "yes"
    assert client.post("/voice/validate", headers=H, json={"fields": {}}).json()["next_question"]["field"] == "task"
    assert client.post("/voice/draft", json={"transcript": "x"}).status_code == 401


def test_asr_failure_returns_degraded_503(client, make_user):
    H, _ = make_user("03005550002", "hirer")
    service._cache["asr"] = Chain("asr", [Boom()])
    r = client.post("/ai/transcribe", headers=H, files={"audio": ("a.webm", b"x", "audio/webm")})
    assert r.status_code == 503 and r.json()["detail"]["degraded"] is True
