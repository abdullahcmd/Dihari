"""Locale files: locales/<lang>.json, flat dotted keys. New language = new file."""
import json
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

FALLBACKS = ["en"]


@lru_cache
def _load(directory: str, lang: str) -> dict:
    p = Path(directory) / f"{lang}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def available(directory: str | None = None) -> list[str]:
    return sorted(p.stem for p in Path(directory or get_settings().locales_dir).glob("*.json"))


def get_raw(key: str, lang: str, directory: str | None = None, default=None):
    d = directory or get_settings().locales_dir
    for l in [lang, *FALLBACKS]:
        data = _load(d, l)
        if key in data:
            return data[key]
    return default


def t(key: str, lang: str = "ur", directory: str | None = None, **params) -> str:
    val = get_raw(key, lang, directory, default=key)
    if not isinstance(val, str):
        return key
    try:
        return val.format(**params)
    except (KeyError, IndexError):
        return val


def lexicon(name: str, lang: str, directory: str | None = None):
    """Merged lexicon across the requested language and fallbacks (lists are unioned, dicts merged)."""
    d = directory or get_settings().locales_dir
    out = None
    for l in [lang, *FALLBACKS]:
        v = _load(d, l).get(f"lexicon.{name}")
        if v is None:
            continue
        if out is None:
            out = list(v) if isinstance(v, list) else dict(v)
        elif isinstance(out, list):
            out += [x for x in v if x not in out]
        else:
            for k, val in v.items():
                out.setdefault(k, val)
    return out if out is not None else []


def meta(lang: str, directory: str | None = None) -> dict:
    return _load(directory or get_settings().locales_dir, lang).get("_meta", {})
