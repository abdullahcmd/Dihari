import base64
import hashlib
import hmac
import secrets
import time

from .settings import get_settings


def hash_code(value: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def make_token(user_id: str, ttl_hours: int | None = None) -> str:
    exp = int(time.time()) + 3600 * (ttl_hours or get_settings().token_ttl_hours)
    body = f"{user_id}.{exp}"
    sig = hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body.encode()).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def read_token(token: str) -> str | None:
    try:
        b, s = token.split(".")
        body = base64.urlsafe_b64decode(b).decode()
        sig = base64.urlsafe_b64decode(s)
        good = hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, good):
            return None
        uid, exp = body.rsplit(".", 1)
        return uid if int(exp) > time.time() else None
    except Exception:
        return None
