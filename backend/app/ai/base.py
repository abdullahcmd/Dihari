"""Provider interfaces. Real providers implement these and register themselves (see providers/ + docs/PROVIDERS.md)."""
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


class AIUnavailable(Exception):
    """All providers in a chain failed. Callers degrade to tap-only input / browser TTS."""


class ConfigError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    lang: str = "ur"
    confidence: float | None = None
    provider: str = ""


@dataclass
class Audio:
    data: bytes
    mime: str = "audio/wav"
    provider: str = ""


@runtime_checkable
class ASR(Protocol):
    name: str
    family: str
    is_mock: bool
    def transcribe(self, audio: bytes, mime: str, lang: str) -> Transcript: ...


@runtime_checkable
class TTS(Protocol):
    name: str
    family: str
    is_mock: bool
    def synthesize(self, text: str, lang: str) -> Audio: ...


@runtime_checkable
class LLM(Protocol):
    name: str
    family: str          # model family, e.g. "gemini", "claude", "gpt". Verifier must differ from extractor.
    is_mock: bool
    def complete_json(self, *, task: str, system: str, prompt: str, schema: dict) -> dict: ...


@dataclass
class CallRecord:
    kind: str
    provider: str
    ok: bool
    latency_ms: int
    error: str | None = None
