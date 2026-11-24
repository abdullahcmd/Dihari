"""Offline mocks. Deterministic, no network. Used by CI, the demo and as the safe default."""
import json
import re
import struct
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..country_config import get_country
from ..settings import get_settings
from . import numbers as nm
from . import registry
from .base import Audio, Transcript


class MockASR:
    name, family, is_mock = "mock", "mock-asr", True

    def transcribe(self, audio: bytes, mime: str, lang: str) -> Transcript:
        fixed = get_settings().mock_asr_fixed_text
        if fixed:
            return Transcript(fixed, lang, 0.5, self.name)
        try:
            return Transcript(audio.decode("utf-8"), lang, 0.5, self.name)  # tests send text as "audio"
        except UnicodeDecodeError:
            raise RuntimeError("mock ASR cannot transcribe real audio; configure a real ASR provider")


class MockTTS:
    name, family, is_mock = "mock", "mock-tts", True

    def synthesize(self, text: str, lang: str) -> Audio:
        n = 800
        pcm = b"\x00\x00" * n
        hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16) + b"data" + struct.pack("<I", len(pcm))
        return Audio(hdr + pcm, "audio/wav", self.name)


class MockLLM:
    """Deterministic heuristics standing in for an LLM. NOT a measure of real LLM quality."""
    is_mock = True

    def __init__(self, name: str, family: str):
        self.name, self.family = name, family

    def complete_json(self, *, task: str, system: str, prompt: str, schema: dict) -> dict:
        payload = json.loads(prompt)
        if task == "extract_job":
            return _extract(payload)
        if task == "verify_readback":
            return _verify(payload)
        if task == "flag_violations":
            return _naive_flags(payload)
        raise ValueError(f"mock LLM: unknown task {task}")


# --------------------------------------------------------------------------------------------
def _extract(p: dict) -> dict:
    cfg = get_country(p["country"])
    text = nm.norm(p["text"])
    lang = p.get("lang", "ur")
    now = datetime.fromisoformat(p["now"])
    tz = ZoneInfo(cfg.timezone)
    out: dict = {k: None for k in ("task", "headcount", "location_text", "start_at", "days", "daily_rate",
                                    "hours_per_day", "payment_day", "advance", "deductions", "transport_mode",
                                    "transport_amount")}
    trade = cfg.find_trade(text)
    out["task"] = trade.code if trade else None
    place = cfg.find_place(text)
    scrub = text
    if place:
        out["location_text"] = place.name
        for n in [place.name, *place.aliases]:
            scrub = re.sub(re.escape(n.lower()), " ", scrub)
    toks = nm.tokenize(scrub, lang)
    spans = nm.number_spans(toks, lang)
    lex = lambda n: [w.lower() for w in nm.lex(n, lang)]  # noqa: E731
    used = set()

    def near(i, j, words, before=2, after=2):
        ws = {w.lower() for w in words}
        for k in range(max(0, i - before), min(len(toks), j + after + 1)):
            if k < i or k > j:
                if toks[k] in ws:
                    return True
        return False

    def following(j, words, within=1):
        ws = {w.lower() for w in words}
        return any(toks[k] in ws for k in range(j + 1, min(len(toks), j + 1 + within)))

    time_words, am, pm = lex("time_words"), lex("am_words"), lex("pm_words")
    start_hour = None
    for idx, (val, i, j) in enumerate(spans):
        nxt_time = following(j, time_words) or (j + 1 < len(toks) and toks[j + 1] in ("am", "pm"))
        if nxt_time and 0 < val <= 24 and start_hour is None:
            start_hour = val
            used.add(idx)
    for idx, (val, i, j) in enumerate(spans):
        if idx in used:
            continue
        if following(j, lex("worker_words"), 2) and out["headcount"] is None:
            out["headcount"] = int(val); used.add(idx)
        elif following(j, lex("hour_words")) and out["hours_per_day"] is None:
            out["hours_per_day"] = float(val); used.add(idx)
        elif near(i, j, lex("advance_words"), 2, 1):
            out["advance"] = int(val); used.add(idx)
        elif near(i, j, lex("deduct_words"), 2, 2):
            out["deductions"] = (out["deductions"] or []) + [{"label": "deduction", "amount": int(val)}]; used.add(idx)
        elif near(i, j, lex("transport_words"), 2, 2):
            out["transport_mode"], out["transport_amount"] = "allowance", int(val); used.add(idx)
        elif following(j, lex("day_words")) and not near(i, j, lex("daily"), 1, 2) and val < 60 and out["days"] is None:
            out["days"] = int(val); used.add(idx)
    for idx, (val, i, j) in enumerate(spans):
        if idx in used:
            continue
        if val >= 100 and (near(i, j, lex("daily"), 3, 3) or out["daily_rate"] is None):
            out["daily_rate"] = int(val); used.add(idx)
            break
    # explicit "none" statements
    def negated(words):
        ws = {w.lower() for w in words}; neg = set(lex("negation"))
        return any(t in ws and any(toks[k] in neg for k in range(max(0, n - 2), min(len(toks), n + 3)))
                   for n, t in enumerate(toks))
    if out["advance"] is None and negated(lex("advance_words")):
        out["advance"] = 0
    if out["deductions"] is None and negated(lex("deduct_words")):
        out["deductions"] = []
    if out["deductions"] is None and any(t in lex("deduct_words") for t in toks):
        out["deductions"] = [{"label": "deduction", "amount": None}]  # mentioned but no amount → hidden
    if out["transport_mode"] is None and any(t in lex("transport_words") for t in toks):
        out["transport_mode"] = "none" if negated(lex("transport_words")) else (
            "provided" if any(t in lex("provided_words") for t in toks) or "ملے" in toks else None)
    # dates
    today = now.astimezone(tz).date()
    d = None
    if any(t in lex("tomorrow") for t in toks):
        d = today + timedelta(days=1)
    elif any(t in lex("today") for t in toks):
        d = today
    else:
        wk = nm.lex("weekdays", lang)
        for t in toks:
            if t in wk:
                delta = (wk[t] - today.weekday()) % 7 or 7
                d = today + timedelta(days=delta)
                break
    if d is not None and start_hour is not None:
        h = int(start_hour) % 24
        if any(t in pm for t in toks) and h < 12:
            h += 12
        out["start_at"] = datetime(d.year, d.month, d.day, h, 0, tzinfo=tz).isoformat()
    # payment day
    pay_idx = [n for n, t in enumerate(toks) if t in lex("payment_words")]
    wk = nm.lex("weekdays", lang)
    if any(t in lex("same_day") for t in toks) or " ".join(toks).find("same day") >= 0:
        base = d or today
        out["payment_day"] = (base + timedelta(days=(out["days"] or 1) - 1)).isoformat()
    elif pay_idx:
        for n in pay_idx:
            for k in range(max(0, n - 3), min(len(toks), n + 5)):
                if toks[k] in wk:
                    delta = (wk[toks[k]] - today.weekday()) % 7 or 7
                    out["payment_day"] = (today + timedelta(days=delta)).isoformat()
                    break
            if out["payment_day"]:
                break
    return out


def _verify(p: dict) -> dict:
    """Independent check: every number the fields imply must appear in the read-back, and nothing extra."""
    f, rb = p["fields"], nm.norm(p["readback"])
    expect = []
    for k in ("headcount", "daily_rate", "days"):
        if f.get(k) is not None:
            expect.append(int(f[k]))
    if f.get("hours_per_day") is not None:
        expect.append(int(f["hours_per_day"]))
    if f.get("advance"):
        expect.append(int(f["advance"]))
    for d in f.get("deductions") or []:
        if d.get("amount") is not None:
            expect.append(int(d["amount"]))
    if f.get("transport_amount"):
        expect.append(int(f["transport_amount"]))
    found = [int(x) for x in re.findall(r"\d+", rb)]
    mism = []
    pool = list(found)
    for e in expect:
        if e in pool:
            pool.remove(e)
        else:
            mism.append(f"number {e} missing from read-back")
    return {"matches": not mism, "mismatches": mism}


def _naive_flags(p: dict) -> dict:
    """Stand-in 'LLM-only' judge for the adversarial baseline: reads the post like a quick human skim.
    Deliberately has NO wage rules, NO arithmetic on deductions and does not know the legal hours limit."""
    t = nm.norm(p["text"])
    flags = []
    if re.search(r"\b(500|600|700|800)\b", t) and re.search(r"per day|a day|daily|روز|دیہاڑی", t):
        flags.append("below_min_wage")
    if not re.search(r"friday|monday|tuesday|wednesday|thursday|saturday|sunday|same day|جمعہ|پیر|منگل|بدھ|جمعرات|ہفتہ|اتوار|اسی دن|payment|ادائیگی|پیسے", t):
        flags.append("missing_payment_day")
    if re.search(r"deduct|کٹوتی", t) and not re.search(r"\d", t.split("deduct")[-1] if "deduct" in t else t.split("کٹوتی")[-1]):
        flags.append("hidden_deduction")
    if re.search(r"\b(1[2-9]|2[0-4])\s*(hours|hrs|گھنٹے)", t):
        flags.append("hours_exceed_max")
    return {"flags": flags}


registry.register("asr", "mock", MockASR)
registry.register("tts", "mock", MockTTS)
registry.register("llm", "mock-a", lambda: MockLLM("mock-a", "mock-family-a"))
registry.register("llm", "mock-b", lambda: MockLLM("mock-b", "mock-family-b"))
