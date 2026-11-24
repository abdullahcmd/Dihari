"""Deterministic, template-based read-back (locale files). Verified afterwards by a second model."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .. import i18n
from ..country_config import CountryConfig


def _hour(dt: datetime, lang: str) -> str:
    h = dt.hour
    period = "morning" if h < 12 else "afternoon" if h < 16 else "evening" if h < 20 else "night"
    h12 = h % 12 or 12
    if dt.minute:
        t = i18n.t("time.minute_format", lang, hour=h12, minute=f"{dt.minute:02d}")
    else:
        t = i18n.t("time.format", lang, hour=h12)
    return f"{i18n.t(f'time.period.{period}', lang)} {t}"


def _day(d: date, today: date, lang: str) -> str:
    if d == today:
        return i18n.t("date.today", lang)
    if (d - today).days == 1:
        return i18n.t("date.tomorrow", lang)
    return i18n.t("date.format", lang, day=d.day, weekday=i18n.t(f"weekday.{d.weekday()}", lang))


def render(f: dict, cfg: CountryConfig, lang: str, now: datetime) -> str:
    """f: task, headcount, location_text, start_at (iso|datetime), days, daily_rate, hours_per_day,
    payment_day (iso|date), advance, deductions, transport_mode, transport_amount."""
    tz = ZoneInfo(cfg.timezone)
    today = now.astimezone(tz).date()
    cur = i18n.t(f"currency.{cfg.currency.code}", lang) if i18n.get_raw(f"currency.{cfg.currency.code}", lang) else cfg.currency.code
    start = f["start_at"] if isinstance(f["start_at"], datetime) else datetime.fromisoformat(f["start_at"])
    start = start.astimezone(tz)
    pay = f["payment_day"]
    pay = pay if isinstance(pay, date) and not isinstance(pay, datetime) else date.fromisoformat(str(pay)[:10])
    trade = cfg.trade(f["task"])
    task = (trade.names.get(lang) or trade.names.get("en") or trade.code) if trade else f["task"]
    ded = [d if isinstance(d, dict) else d.model_dump() for d in (f.get("deductions") or [])]
    ded_txt = "؛ ".join(i18n.t("readback.deduction", lang, label=d.get("label", ""), amount=d.get("amount") if d.get("amount") is not None else "?", currency=cur)
                        for d in ded) if ded else i18n.t("readback.none", lang)
    mode = f.get("transport_mode") or "none"
    tr = (i18n.t("readback.transport.allowance", lang, amount=f.get("transport_amount"), currency=cur)
          if mode == "allowance" else i18n.t(f"readback.transport.{mode}", lang))
    adv = f"{f['advance']} {cur}" if f.get("advance") else i18n.t("readback.none", lang)
    h = f["hours_per_day"]
    return i18n.t("readback.job", lang, headcount=f["headcount"], task=task, location=f["location_text"],
                  start=f"{_day(start.date(), today, lang)} {_hour(start, lang)}", rate=f["daily_rate"], currency=cur,
                  hours=int(h) if float(h).is_integer() else h, days=f.get("days") or 1,
                  payment_day=_day(pay, today, lang), advance=adv, deductions=ded_txt, transport=tr)
