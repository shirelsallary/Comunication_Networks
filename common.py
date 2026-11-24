# common.py
"""
EX2 - code shared by the server, the proxy and the client.

All three frame messages (the client uses recv_line / send_json), and the server
and the proxy also validate requests and build responses. protocol.md requires
the same format everywhere in the system (§2, §4), so this code lives in one place.
"""
import json
import socket
from typing import Any, Dict, Optional, Tuple


def send_json(sock: socket.socket, obj: Dict[str, Any]) -> None:
    """
    Serialise `obj` and write it as ONE message: compact JSON, UTF-8, trailing "\\n".
    json.dumps never emits a raw newline, so the delimiter cannot appear inside
    a message - see protocol.md §2.1.
    """
    sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def recv_line(sock: socket.socket, buf: bytes) -> Tuple[Optional[bytes], bytes]:
    """
    Framing helper - see protocol.md §2.2. Return (line, leftover):
        line     - ONE complete message WITHOUT the trailing b"\\n",
                   or None if the peer closed the connection (sent FIN).
        leftover - bytes already received that belong to the NEXT message(s).
                   The caller must pass them back in as `buf` on the next call.
                   When line is None, a non-empty leftover is a partial message
                   cut off by the disconnect (protocol.md §8.3).

    Raises ValueError if a message is longer than 65,536 bytes (protocol.md §2.3).

    Why: TCP is a byte stream. One recv() may return half a message, exactly
    one message, or one-and-a-half messages. Never assume one send() == one recv().
    """
    while True:
        if b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            # A whole oversized message can arrive at once - see protocol.md §2.3
            if len(line) > 65536:
                raise ValueError("message exceeds 65536 bytes")
            return line, buf
        # No newline yet and already over the limit: the message can only be too long
        if len(buf) > 65536:
            raise ValueError("message exceeds 65536 bytes")
        chunk = sock.recv(4096)
        if not chunk:
            return None, buf
        buf += chunk


def validate_request(msg: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str], Optional[bool]]:
    """
    Structural validation: steps 4-10 of protocol.md §3.4, in that order; the
    first failing check decides the error. Return (error, mode, text, use_cache):
        valid request   - error is None, text is the stripped expr / prompt (§3.5)
                          and use_cache applies the per-mode default (§3.3)
        invalid request - error is the ready error response, the rest are None
    """
    # Step 4
    if not isinstance(msg, dict):
        return make_error("BAD_REQUEST", "request must be a JSON object"), None, None, None
    # Step 5: an unknown field is a sent value, so it is rejected, not ignored - see protocol.md §3.4
    for name in msg:
        if name not in ("mode", "data", "options"):
            return make_error("BAD_REQUEST", f"unknown field {name!r}"), None, None, None
    # Step 6
    mode = msg.get("mode")
    if not isinstance(mode, str):
        return make_error("BAD_REQUEST", "'mode' is required (string)"), None, None, None
    # Step 7
    if mode not in ("calc", "gpt"):
        return make_error("UNKNOWN_MODE", f"unknown mode {mode!r}"), None, None, None
    # Step 8: data holds exactly one string field, chosen by mode - see protocol.md §3.2
    field = "expr" if mode == "calc" else "prompt"
    data = msg.get("data")
    if not isinstance(data, dict) or list(data) != [field] or not isinstance(data[field], str):
        return make_error("BAD_REQUEST", f"'data' must contain exactly one string field {field!r}"), None, None, None
    # Step 9: options may be absent, but a sent value must have the right type (null does not) - see protocol.md §3.4
    options = msg.get("options", {})
    if not isinstance(options, dict) or any(name != "cache" for name in options) \
            or not isinstance(options.get("cache", False), bool):
        return make_error("BAD_REQUEST", "'options' may only contain a boolean 'cache'"), None, None, None
    # Step 10: surrounding whitespace has no meaning; empty after stripping means missing - see protocol.md §3.5
    text = data[field].strip()
    if not text:
        return make_error("BAD_REQUEST", f"{field!r} must not be empty"), None, None, None
    # Default cache depends on mode - see protocol.md §3.3
    use_cache = options.get("cache", mode == "calc")
    return None, mode, text, use_cache


def cache_key(mode: str, text: str) -> Tuple[str, str]:
    """
    Cache key shared by the server and the proxy - see protocol.md §9.2.
    `text` is the stripped expr / prompt; `options` are deliberately not part of it.
    """
    return (mode, text)


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
