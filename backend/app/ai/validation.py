"""Plain-code validation — AUTHORITATIVE. Nothing from an LLM can override this."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import i18n
from ..country_config import CountryConfig
from ..modules import wage_floor

FIELD_ORDER = ["task", "headcount", "location_text", "start_at", "daily_rate", "hours_per_day",
               "payment_day", "deductions", "advance", "transport_mode"]


@dataclass
class Report:
    typed: dict
    missing: list[str] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)
    wage: dict | None = None
    fixes: list[dict] = field(default_factory=list)
    next_question: dict | None = None
    ready: bool = False

    def to_dict(self) -> dict:
        return {"missing": self.missing, "invalid": self.invalid, "wage": self.wage, "fixes": self.fixes,
                "next_question": self.next_question, "ready": self.ready}


def _dt(v):
    if v is None or isinstance(v, datetime):
        return v
    return datetime.fromisoformat(v)


def _d(v):
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    return date.fromisoformat(v[:10]) if isinstance(v, str) else v.date()


def validate(fields: dict, cfg: CountryConfig, lang: str, now: datetime | None = None) -> Report:
    now = now or datetime.now(timezone.utc)
    f = dict(fields)
    rep = Report(typed=f)
    try:
        f["start_at"], f["payment_day"] = _dt(f.get("start_at")), _d(f.get("payment_day"))
    except ValueError:
        rep.invalid.append({"field": "start_at", "code": "bad_date"})
        f["start_at"], f["payment_day"] = None, None
    f["days"] = int(f.get("days") or 1)
    # required-ness: unknown ≠ none
    for k in FIELD_ORDER:
        v = f.get(k)
        if v is None or v == "":
            rep.missing.append(k)
    if f.get("transport_mode") == "allowance" and not f.get("transport_amount"):
        rep.invalid.append({"field": "transport_mode", "code": "amount_needed"})
    # ranges
    def bad(k, code):
        rep.invalid.append({"field": k, "code": code})
    if f.get("headcount") is not None and not 1 <= f["headcount"] <= 200:
        bad("headcount", "out_of_range")
    if f.get("daily_rate") is not None and f["daily_rate"] <= 0:
        bad("daily_rate", "out_of_range")
    if f.get("hours_per_day") is not None and not 0 < f["hours_per_day"] <= 24:
        bad("hours_per_day", "out_of_range")
    if f.get("advance") is not None and f["advance"] < 0:
        bad("advance", "out_of_range")
    if f.get("start_at") and not (now - timedelta(hours=1) <= f["start_at"] <= now + timedelta(days=60)):
        bad("start_at", "out_of_window")
    place = None
    if f.get("location_text"):
        place = cfg.find_place(f["location_text"])
        if not place:
            bad("location_text", "unknown_place")
    # wage floor — pure code
    if f.get("daily_rate") or f.get("hours_per_day") or f.get("payment_day"):
        tz = ZoneInfo(cfg.timezone)
        region = cfg.resolve_region(f.get("location_text"), place.lat if place else None, place.lon if place else None)
        ded = f.get("deductions") or []
        ded = [d if isinstance(d, dict) else d.model_dump() for d in ded]
        chk = wage_floor.check(country=cfg.code, region=region, daily_rate=f.get("daily_rate"),
                               hours_per_day=f.get("hours_per_day"), payment_day=f.get("payment_day"),
                               start_date=f["start_at"].astimezone(tz).date() if f.get("start_at") else None,
                               days=f["days"], deductions=ded, on=now.astimezone(tz).date())
        # a still-to-be-asked payment day isn't a violation yet; it's a missing field
        chk.violations = [v for v in chk.violations if not (v.code == "missing_payment_day" and "payment_day" in rep.missing)]
        chk.ok = not chk.violations
        rep.wage = chk.to_dict(lang)
        for v in chk.violations:
            if v.code == "below_min_wage":
                rep.fixes.append({"field": "daily_rate", "value": v.params["min"], "code": v.code})
            if v.code == "hours_exceed_max":
                rep.fixes.append({"field": "hours_per_day", "value": v.params["max"], "code": v.code})
    wage_ok = rep.wage is None or rep.wage["ok"]
    rep.ready = not rep.missing and not rep.invalid and wage_ok and rep.wage is not None
    # next question: invalid fields first, then missing in fixed order
    order = [i["field"] for i in rep.invalid] + [m for m in FIELD_ORDER if m in rep.missing]
    if order:
        k = order[0]
        rep.next_question = {"field": k, "prompt": i18n.t(f"ask.{k}", lang), "invalid": any(i["field"] == k for i in rep.invalid)}
    return rep
