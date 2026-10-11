"""Identifiers: opaque, type-prefixed, time-sortable, never reused."""
import secrets
import time


def new_id(prefix: str, now: float | None = None) -> str:
    millis = int((time.time() if now is None else now) * 1000)
    return f"{prefix}_{millis:012x}{secrets.token_hex(5)}"
