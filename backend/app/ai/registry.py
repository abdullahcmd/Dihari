"""Config-driven provider registry. Add a provider = drop a module in providers/ that calls register()."""
import importlib
import pkgutil
from typing import Callable

from .base import ConfigError

_FACTORIES: dict[tuple[str, str], Callable[[], object]] = {}
_loaded = False


def register(kind: str, name: str, factory: Callable[[], object]) -> None:
    assert kind in ("asr", "tts", "llm")
    _FACTORIES[(kind, name)] = factory


def autodiscover() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import mock  # noqa: F401  (registers mocks)
    from . import providers
    for m in pkgutil.iter_modules(providers.__path__):
        if not m.name.startswith("_"):
            importlib.import_module(f"{providers.__name__}.{m.name}")


def build(kind: str, names: list[str]) -> list:
    autodiscover()
    out = []
    for n in names:
        if (kind, n) not in _FACTORIES:
            raise ConfigError(f"{kind} provider '{n}' is not registered. Registered: "
                              f"{sorted(k[1] for k in _FACTORIES if k[0] == kind)}")
        out.append(_FACTORIES[(kind, n)]())
    return out


def registered(kind: str) -> list[str]:
    autodiscover()
    return sorted(k[1] for k in _FACTORIES if k[0] == kind)
