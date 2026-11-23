# common.py
"""
EX2 - code shared by the server and the proxy.

Both components build responses and frame messages, and protocol.md requires
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
