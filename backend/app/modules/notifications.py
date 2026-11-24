"""Notification + SMS provider interfaces. Real providers are added later (docs/PROVIDERS.md)."""
import logging
from typing import Protocol

log = logging.getLogger("dihari.notify")


class SmsProvider(Protocol):
    name: str
    def send(self, phone: str, text: str) -> bool: ...


class StubSms:
    """Dev stub: records messages in memory, never leaves the process."""
    name = "stub"

    def __init__(self):
        self.outbox: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> bool:
        self.outbox.append((phone, text))
        log.info("SMS(stub) to %s: %s", phone, text)
        return True


_SMS_FACTORIES: dict[str, type] = {"stub": StubSms}
_sms_instances: dict[str, SmsProvider] = {}


def register_sms(name: str, factory) -> None:
    _SMS_FACTORIES[name] = factory


def get_sms(name: str | None = None) -> SmsProvider:
    from ..settings import get_settings
    name = name or get_settings().sms_provider
    if name not in _sms_instances:
        if name not in _SMS_FACTORIES:
            raise RuntimeError(f"SMS provider '{name}' not registered (see docs/PROVIDERS.md)")
        _sms_instances[name] = _SMS_FACTORIES[name]()
    return _sms_instances[name]
