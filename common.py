# common.py
"""
EX2 - code shared by the server and the proxy.

Both components build responses, and protocol.md §4 requires the same
response shape everywhere in the system, so the builders live in one place.
"""
from typing import Any, Dict


def make_meta(from_cache: bool, took_ms: int) -> Dict[str, Any]:
    """Build the `meta` object that every response carries - see protocol.md §4.3."""
    return {"from_cache": from_cache, "took_ms": took_ms}


def make_error(code: str, message: str, took_ms: int = 0) -> Dict[str, Any]:
    """
    Build an error response - see protocol.md §4.2.
    `code` is one of the codes in protocol.md §5; `message` is free text for humans.
    """
    # Errors carry meta too, and an error built here did not come from a cache - see protocol.md §4.3
    return {"ok": False, "error": {"code": code, "message": message}, "meta": make_meta(False, took_ms)}
