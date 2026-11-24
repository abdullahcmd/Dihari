"""MCP server (FastMCP). Operator-run: no end-user auth here, so only expose it to trusted agents.
Run: python -m app.mcp_server   (stdio)   |   python -m app.mcp_server --http 8765"""
import sys
from datetime import date, datetime

from fastmcp import FastMCP
from sqlalchemy import select

from .country_config import get_country
from .db import SessionLocal, init_db
from .models import Assignment, Case, User
from .modules import geo, jobs, payments, reputation, wage_floor
from .settings import get_settings

mcp = FastMCP("dihari")


def _user(db, phone: str, role: str) -> User:
    u = db.scalars(select(User).where(User.phone == phone)).first()
    if not u or u.role != role or not u.phone_verified:
        raise ValueError(f"no verified {role} with that phone")
    return u


@mcp.tool
def check_wage_floor(location_text: str, daily_rate: int | None = None, hours_per_day: float | None = None,
                     payment_day: str | None = None, start_date: str | None = None, days: int = 1,
                     deductions: list[dict] | None = None, country: str | None = None, lang: str = "en") -> dict:
    """Pure-code wage-floor check (no LLM). Dates are ISO (YYYY-MM-DD). Returns violations, warnings and the rule used."""
    cfg = get_country(country)
    region = cfg.resolve_region(location_text)
    r = wage_floor.check(country=cfg.code, region=region, daily_rate=daily_rate, hours_per_day=hours_per_day,
                         payment_day=date.fromisoformat(payment_day) if payment_day else None,
                         start_date=date.fromisoformat(start_date) if start_date else None, days=days,
                         deductions=deductions or [], on=date.today())
    return r.to_dict(lang) | {"region": region}


@mcp.tool
def post_job(hirer_phone: str, task: str, headcount: int, location_text: str, start_at: str, daily_rate: int,
             hours_per_day: float, payment_day: str, advance: int = 0, deductions: list[dict] | None = None,
             transport_mode: str = "none", transport_amount: int | None = None, days: int = 1) -> dict:
    """Post a job for a verified hirer. Same server-side checks as the app: wage floor, abuse limits, duplicates."""
    with SessionLocal() as db:
        hirer = _user(db, hirer_phone, "hirer")
        try:
            j = jobs.create_job(db, hirer, dict(task=task, headcount=headcount, location_text=location_text,
                                                start_at=datetime.fromisoformat(start_at), daily_rate=daily_rate,
                                                hours_per_day=hours_per_day, payment_day=date.fromisoformat(payment_day),
                                                advance=advance, deductions=deductions or [], transport_mode=transport_mode,
                                                transport_amount=transport_amount, days=days))
        except jobs.JobRejected as e:
            return {"posted": False, "code": e.code, "detail": e.detail}
        return {"posted": True, "job_id": j.id, "status": j.status, "rule_verified": j.rule_verified}


@mcp.tool
def find_workers(lat: float, lon: float, radius_km: float = 10, trade: str | None = None, country: str | None = None) -> list[dict]:
    """Workers near a point (PostGIS ST_DWithin on Postgres). No phone numbers or full names are returned."""
    with SessionLocal() as db:
        out = []
        for u, wp, dist in geo.nearby_workers(db, lat, lon, radius_km, trade=trade, country=country or get_settings().default_country):
            out.append({"worker_id": u.id, "first_name": reputation.first_name(u), "trades": wp.trades,
                        "distance_km": round(dist / 1000, 1), **reputation.worker_reputation(db, u.id)})
        return out


@mcp.tool
def file_case(worker_phone: str, assignment_id: str) -> dict:
    """File an unpaid case on behalf of a worker. Goes through the same rules as the app (job completed, payment day reached).
    Creates a case file for a HUMAN reviewer; nothing is decided automatically."""
    with SessionLocal() as db:
        worker = _user(db, worker_phone, "worker")
        asg = db.get(Assignment, assignment_id)
        if not asg:
            return {"filed": False, "code": "not_found"}
        try:
            payments.report_payment(db, asg, worker, "unpaid")
        except payments.PaymentError as e:
            return {"filed": False, "code": e.code}
        c = db.scalars(select(Case).where(Case.assignment_id == asg.id)).first()
        return {"filed": True, "case_id": c.id, "status": c.status}


if __name__ == "__main__":
    init_db()
    if "--http" in sys.argv:
        mcp.run(transport="http", port=int(sys.argv[sys.argv.index("--http") + 1]))
    else:
        mcp.run()
