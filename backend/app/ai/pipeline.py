"""draft(): transcript → extraction → code validation → read-back → verifier. One place that wires the rules:
code checks are authoritative; the verifier can only add a block, never remove one."""
from datetime import datetime, timezone

from ..country_config import CountryConfig
from . import extraction, readback, service, validation, verifier


def _merge(base: dict, new: dict) -> dict:
    out = dict(base)
    for k, v in new.items():
        if v is not None:
            out[k] = v
    return out


def _finish(fields: dict, cfg: CountryConfig, lang: str, now: datetime, *, provider=None, uncertain=None, degraded=False) -> dict:
    rep = validation.validate(fields, cfg, lang, now)
    out = {"fields": _public(fields), "uncertain": uncertain or [], "provider": provider, "degraded": degraded,
           **rep.to_dict(), "readback": None, "verifier": None, "can_post": False}
    if rep.ready:
        rb = readback.render(rep.typed, cfg, lang, now)
        v = verifier.verify(rb, _public(fields), service.get_chain("verify"))
        out["readback"], out["verifier"] = rb, v.to_dict()
        out["can_post"] = v.ok is not False       # mismatch blocks; unavailable verifier degrades to "unverified"
    return out


def _public(f: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in f.items()}


def draft_from_text(text: str, cfg: CountryConfig, lang: str, existing: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ex = extraction.extract(text, cfg, service.get_chain("extract"), lang, now)
    fields = _merge(existing or {}, ex.fields)
    return _finish(fields, cfg, lang, now, provider=ex.provider, uncertain=ex.uncertain, degraded=ex.degraded)


def draft_from_answer(field_name: str, text: str, existing: dict, cfg: CountryConfig, lang: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    new = extraction.parse_answer(field_name, text, cfg, service.get_chain("extract"), lang, now)
    unc = [] if new else [field_name]
    return _finish(_merge(existing, new), cfg, lang, now, uncertain=unc)


def draft_from_fields(fields: dict, cfg: CountryConfig, lang: str, now: datetime | None = None) -> dict:
    """Tap-only path (no ASR/LLM at all)."""
    return _finish(fields, cfg, lang, now or datetime.now(timezone.utc))
