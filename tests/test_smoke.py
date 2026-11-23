# tests/test_smoke.py
"""
Smoke tests for EX2: start the server and the proxy in background threads and
talk to them with the client's own helpers.

Run (from the project root):
    python -m pytest tests/          # pip install pytest
or
    python tests/test_smoke.py

The tests FAIL until you complete the TODOs - use them as a checklist, not as
proof of correctness (they do not cover everything the assignment asks for).
If you renamed things in client.py, update the imports / calls below.
Scenario 3 (server shut down, proxy still answers from cache) is not covered
here - it needs a real shutdown; do it by hand and capture it with Wireshark.
"""
import json
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import client   # noqa: E402
import common   # noqa: E402
import proxy    # noqa: E402
import server   # noqa: E402

HOST = "127.0.0.1"
SERVER_PORT = 5599
PROXY_PORT = 5598

_started = False


def _start_system_once() -> None:
    """Start server + proxy once per test session (daemon threads)."""
    global _started
    if _started:
        return
    threading.Thread(target=server.serve, args=(HOST, SERVER_PORT, 16), daemon=True).start()
    threading.Thread(target=proxy.serve, args=(HOST, PROXY_PORT, HOST, SERVER_PORT, 16),
                     daemon=True).start()
    time.sleep(0.4)
    _started = True


# ---------------------------------------------------------------- server ----
def test_calc_arithmetic_direct():
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        r = c.request(client.build_calc_request("1+2*3"))
    assert r is not None and r["ok"] is True
    assert abs(r["result"] - 7) < 1e-9


def test_persistent_connection_and_server_cache():
    """Two requests on the SAME socket; the second one must be a server cache hit."""
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        r1 = c.request(client.build_calc_request("sin(0)"))
        r2 = c.request(client.build_calc_request("sin(0)"))
        r3 = c.request(client.build_calc_request("cos(0)"))
    assert r1["ok"] and abs(r1["result"]) < 1e-9
    assert r2["ok"] and r2["meta"]["from_cache"] is True
    assert r3["ok"] and abs(r3["result"] - 1.0) < 1e-9


def test_many_requests_on_one_connection():
    """Assignment section 3: the server keeps serving requests on the SAME socket
    until the client closes it (protocol.md §8.1). Uses a raw socket, so it does
    not depend on the client implementation."""
    _start_system_once()
    with socket.create_connection((HOST, SERVER_PORT), timeout=5) as s:
        buf = b""
        for expr, expected in [("1+2", 3), ("2*5", 10), ("7-4", 3)]:
            common.send_json(s, {"mode": "calc", "data": {"expr": expr}})
            line, buf = common.recv_line(s, buf)
            assert line is not None, "server closed the connection after a response"
            r = json.loads(line)
            assert r["ok"] is True and abs(r["result"] - expected) < 1e-9


def test_boolean_expression():
    """Needs server TODO 3 + TODO 4. Adjust the assertion if your protocol.md
    represents booleans differently (and say so in protocol.md)."""
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        r = c.request(client.build_calc_request("1 < 2 and not (3 > 4)"))
        f = c.request(client.build_calc_request("1 < 2 < 1"))
    assert r["ok"] is True and r["result"] in (True, 1, 1.0)
    assert f["ok"] is True and f["result"] in (False, 0, 0.0)


def test_gpt_stub():
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        r = c.request(client.build_gpt_request("Summarize Newton in 3 bullet points"))
    assert r["ok"] is True and isinstance(r["result"], str) and r["result"]


def test_bad_requests_get_error_responses():
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        unknown = c.request({"mode": "banana", "data": {}})
        bad_expr = c.request(client.build_calc_request("import os"))
        missing = c.request({"mode": "calc", "data": {}})
    for r in (unknown, bad_expr, missing):
        assert r is not None and r["ok"] is False and r["error"]


def test_malformed_json_does_not_kill_the_server():
    """Raw bytes that are not JSON. The server must answer with an error
    (and must still accept a new, valid connection afterwards)."""
    _start_system_once()
    with client.Connection(HOST, SERVER_PORT) as c:
        c.sock.sendall(b"{this is not json\n")
        line, c.buf = client.recv_line(c.sock, c.buf)
    assert line is not None
    assert json.loads(line)["ok"] is False

    with client.Connection(HOST, SERVER_PORT) as c:
        r = c.request(client.build_calc_request("2+2"))
    assert r["ok"] and abs(r["result"] - 4) < 1e-9


# ----------------------------------------------------------------- proxy ----
def test_proxy_forwards_and_caches():
    """Same request twice through the proxy: both answers must be correct.
    Extend this with an assertion on YOUR hit marker (meta field / counters)
    once you have decided how a proxy hit is visible to the client."""
    _start_system_once()
    with client.Connection(HOST, PROXY_PORT) as c:
        r1 = c.request(client.build_calc_request("sqrt(16)"))
        r2 = c.request(client.build_calc_request("sqrt(16)"))
        r3 = c.request(client.build_calc_request("sqrt(25)"))
    assert r1["ok"] and abs(r1["result"] - 4) < 1e-9
    assert r2["ok"] and abs(r2["result"] - 4) < 1e-9
    assert r3["ok"] and abs(r3["result"] - 5) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("OK")
