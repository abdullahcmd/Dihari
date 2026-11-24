"""Fallback chain with per-call logging: which provider answered, latency, failures."""
import logging
import time
from typing import Callable

from .base import AIUnavailable, CallRecord

log = logging.getLogger("dihari.ai")
_sinks: list[Callable[[CallRecord], None]] = []


def add_sink(fn: Callable[[CallRecord], None]) -> None:
    _sinks.append(fn)


def clear_sinks() -> None:
    _sinks.clear()


def _emit(rec: CallRecord) -> None:
    (log.info if rec.ok else log.warning)("ai.%s provider=%s ok=%s latency_ms=%d err=%s", rec.kind, rec.provider,
                                           rec.ok, rec.latency_ms, rec.error)
    for s in _sinks:
        try:
            s(rec)
        except Exception:  # noqa: BLE001
            log.exception("ai log sink failed")


class Chain:
    def __init__(self, kind: str, providers: list):
        self.kind, self.providers = kind, providers

    @property
    def primary_family(self) -> str | None:
        return self.providers[0].family if self.providers else None

    @property
    def has_real(self) -> bool:
        return any(not p.is_mock for p in self.providers)

    def call(self, method: str, *args, check: Callable | None = None, **kw):
        """Try providers in order. `check(result)` may raise to reject a result (counts as a failure)."""
        if not self.providers:
            raise AIUnavailable(f"no {self.kind} providers configured")
        errors = []
        for p in self.providers:
            t0 = time.perf_counter()
            try:
                res = getattr(p, method)(*args, **kw)
                if check:
                    check(res)
                _emit(CallRecord(self.kind, p.name, True, int((time.perf_counter() - t0) * 1000)))
                return res, p.name
            except Exception as e:  # noqa: BLE001
                _emit(CallRecord(self.kind, p.name, False, int((time.perf_counter() - t0) * 1000), f"{type(e).__name__}: {e}"))
                errors.append(f"{p.name}: {e}")
        raise AIUnavailable("; ".join(errors))
