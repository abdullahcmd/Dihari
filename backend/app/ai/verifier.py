"""Second-model check that the read-back matches the extracted fields. Can only TIGHTEN, never override code checks."""
import json
from dataclasses import dataclass, field

from .base import AIUnavailable
from .chain import Chain

SYSTEM = "You compare a spoken read-back to structured job fields. Reply JSON {matches: bool, mismatches: [string]}."
SCHEMA = {"type": "object", "properties": {"matches": {"type": "boolean"}, "mismatches": {"type": "array", "items": {"type": "string"}}},
          "required": ["matches", "mismatches"]}


@dataclass
class Verdict:
    ok: bool | None            # None = verifier unavailable
    mismatches: list[str] = field(default_factory=list)
    provider: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "mismatches": self.mismatches, "provider": self.provider, "available": self.ok is not None}


def _check(r: dict):
    if not isinstance(r.get("matches"), bool):
        raise ValueError("bad verifier output")


def verify(readback: str, fields: dict, chain: Chain) -> Verdict:
    payload = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in fields.items()}
    try:
        r, prov = chain.call("complete_json", task="verify_readback", system=SYSTEM, schema=SCHEMA, check=_check,
                             prompt=json.dumps({"readback": readback, "fields": payload}, ensure_ascii=False, default=str))
    except AIUnavailable:
        return Verdict(None)
    return Verdict(bool(r["matches"]), list(r.get("mismatches") or []), prov)
