"""LLM extraction with strict JSON schema, then CODE grounding + validation. Uncertain → asked back, never guessed."""
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Literal

from pydantic import BaseModel, ValidationError

from ..country_config import CountryConfig
from . import numbers as nm
from .base import AIUnavailable
from .chain import Chain

NUMERIC = ["headcount", "daily_rate", "hours_per_day", "advance", "days", "transport_amount"]


class Deduction(BaseModel):
    label: str
    amount: int | None = None


class JobFields(BaseModel):
    task: str | None = None
    headcount: int | None = None
    location_text: str | None = None
    start_at: str | None = None        # ISO-8601 with offset
    days: int | None = None
    daily_rate: int | None = None
    hours_per_day: float | None = None
    payment_day: str | None = None     # ISO date
    advance: int | None = None         # 0 = explicitly none; null = not said
    deductions: list[Deduction] | None = None   # [] = explicitly none; null = not said
    transport_mode: Literal["none", "provided", "allowance"] | None = None
    transport_amount: int | None = None


SYSTEM = ("Extract a daily-wage job post into the JSON schema. Use null for anything not explicitly said. "
          "Never guess numbers. Never invent a deduction. Output JSON only.")


@dataclass
class Extraction:
    fields: dict
    uncertain: list[str] = field(default_factory=list)
    provider: str | None = None
    degraded: bool = False


def build_prompt(text: str, cfg: CountryConfig, lang: str, now: datetime) -> str:
    return json.dumps({"text": text, "lang": lang, "country": cfg.code, "now": now.isoformat(), "timezone": cfg.timezone,
                       "trade_codes": [t.code for t in cfg.trades]}, ensure_ascii=False)


def _parse(raw: dict) -> JobFields:
    return JobFields.model_validate(raw)


def ground(fields: dict, text: str, lang: str) -> tuple[dict, list[str]]:
    """Null out any number/date the transcript does not literally support."""
    f = dict(fields)
    unc: list[str] = []
    nums = nm.numbers_in(text, lang)
    for k in NUMERIC:
        v = f.get(k)
        if v is not None and k != "days" and float(v) not in nums:
            if not (k == "advance" and v == 0) and not (k == "transport_amount" and v == 0):
                f[k], _ = None, unc.append(k)
    if f.get("days") is not None and float(f["days"]) not in nums and f["days"] != 1:
        f["days"] = None; unc.append("days")
    ded = f.get("deductions")
    if ded:
        for d in ded:
            if d.get("amount") is not None and float(d["amount"]) not in nums:
                d["amount"] = None  # becomes a "hidden deduction" → asked/blocked, not trusted
                unc.append("deductions")
    if f.get("transport_mode") == "allowance" and f.get("transport_amount") is None:
        f["transport_mode"] = None
    cue = nm.has_time_cue(text, lang)
    for k in ("start_at", "payment_day"):
        if f.get(k) and not cue:
            f[k] = None; unc.append(k)
    return f, sorted(set(unc))


def normalise(fields: dict, cfg: CountryConfig) -> dict:
    f = dict(fields)
    if f.get("task") and not cfg.trade(f["task"]):
        t = cfg.find_trade(str(f["task"]))
        f["task"] = t.code if t else None
    return f


def extract(text: str, cfg: CountryConfig, chain: Chain, lang: str = "ur", now: datetime | None = None) -> Extraction:
    now = now or datetime.now(timezone.utc)
    try:
        raw, provider = chain.call("complete_json", task="extract_job", system=SYSTEM,
                                   prompt=build_prompt(text, cfg, lang, now), schema=JobFields.model_json_schema(),
                                   check=_parse)
    except AIUnavailable:
        return Extraction({}, [], None, degraded=True)
    parsed = _parse(raw).model_dump()
    parsed = normalise(parsed, cfg)
    grounded, unc = ground(parsed, text, lang)
    return Extraction(grounded, unc, provider)


def parse_answer(field_name: str, text: str, cfg: CountryConfig, chain: Chain, lang: str, now: datetime) -> dict:
    """Answer to ONE question: only that field is taken. Simple fields use code, not the LLM."""
    nums = sorted(nm.numbers_in(text, lang))
    yn = nm.yes_no(text, lang)
    if field_name in ("headcount", "daily_rate", "hours_per_day", "advance"):
        if field_name == "advance" and yn == "no" and not nums:
            return {"advance": 0}
        if nums:
            v = nums[0]
            return {field_name: float(v) if field_name == "hours_per_day" else int(v)}
        return {}
    if field_name == "deductions":
        if yn == "no" and not nums:
            return {"deductions": []}
        if nums:
            return {"deductions": [{"label": "deduction", "amount": int(nums[0])}]}
        return {}
    if field_name == "transport_mode":
        if yn == "no":
            return {"transport_mode": "none", "transport_amount": None}
        if nums:
            return {"transport_mode": "allowance", "transport_amount": int(nums[0])}
        if yn == "yes":
            return {"transport_mode": "provided", "transport_amount": None}
        return {}
    if field_name == "task":
        t = cfg.find_trade(text)
        return {"task": t.code} if t else {}
    if field_name == "location_text":
        p = cfg.find_place(text)
        return {"location_text": p.name} if p else {}
    ex = extract(text, cfg, chain, lang, now)
    return {field_name: ex.fields.get(field_name)} if ex.fields.get(field_name) is not None else {}
