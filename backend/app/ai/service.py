"""Builds the configured chains. Verifier family must differ from the extractor family."""
from ..settings import get_settings
from .base import ConfigError
from .chain import Chain
from . import registry

_cache: dict[str, Chain] = {}


def _names(csv: str) -> list[str]:
    return [x.strip() for x in csv.split(",") if x.strip()]


def reset():
    _cache.clear()


def get_chain(which: str) -> Chain:
    s = get_settings()
    if which not in _cache:
        spec = {"asr": ("asr", s.asr_providers), "tts": ("tts", s.tts_providers),
                "extract": ("llm", s.llm_extract_providers), "verify": ("llm", s.llm_verify_providers)}[which]
        _cache[which] = Chain(spec[0], registry.build(spec[0], _names(spec[1])))
    return _cache[which]


def check_families() -> None:
    ex, ve = get_chain("extract"), get_chain("verify")
    fam_e = {p.family for p in ex.providers}
    fam_v = {p.family for p in ve.providers}
    if fam_e & fam_v:
        raise ConfigError(f"verifier must use a different model family than extraction; shared: {sorted(fam_e & fam_v)}")
