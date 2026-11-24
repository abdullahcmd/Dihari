from sqlalchemy.orm import Session

from ..country_config import get_country
from ..models import HirerProfile, User, WorkerProfile
from . import audit

HIRER_TYPES = {"household", "contractor", "business"}


class ProfileError(Exception):
    pass


def upsert_worker(db: Session, user: User, *, name=None, trades=None, area_name=None,
                  lat=None, lon=None, radius_km=None) -> WorkerProfile:
    cfg = get_country(user.country_code)
    p = db.get(WorkerProfile, user.id) or WorkerProfile(user_id=user.id)
    if trades is not None:
        valid = {t.code for t in cfg.trades}
        bad = [t for t in trades if t not in valid]
        if bad:
            raise ProfileError(f"unknown trades: {bad}")
        p.trades = trades
    if area_name is not None:
        p.area_name = area_name
        place = cfg.find_place(area_name)
        if place and lat is None:
            lat, lon = place.lat, place.lon
    if lat is not None and lon is not None:
        p.lat, p.lon = lat, lon
    if radius_km is not None:
        p.radius_km = min(max(radius_km, 1), cfg.max_radius_km)
    elif p.radius_km is None:
        p.radius_km = cfg.default_radius_km
    if name is not None:
        user.name = name
    user.role = "worker" if user.role not in ("worker",) else user.role
    db.add(p)
    audit.log(db, user.id, "worker_profile", user.id, "upsert")
    db.commit()
    return p


def upsert_hirer(db: Session, user: User, *, name=None, hirer_type=None) -> HirerProfile:
    if hirer_type is not None and hirer_type not in HIRER_TYPES:
        raise ProfileError(f"hirer_type must be one of {sorted(HIRER_TYPES)}")
    p = db.get(HirerProfile, user.id) or HirerProfile(user_id=user.id)
    if hirer_type:
        p.hirer_type = hirer_type
    if name is not None:
        user.name = name
    db.add(p)
    audit.log(db, user.id, "hirer_profile", user.id, "upsert")
    db.commit()
    return p
