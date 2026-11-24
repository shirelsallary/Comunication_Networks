# proxy.py
"""
EX2 - Caching proxy

        client  <--TCP-->  proxy  <--TCP-->  server

Run:
    python proxy.py --listen-port 5554 --server-port 5555 --cache-size 64
    python client.py --host 127.0.0.1 --port 5554 --mode calc --expr "sqrt(16)"

The proxy speaks the SAME application protocol as the server (protocol.md),
so the client cannot tell them apart. Note that simply copying bytes in
both directions would not be enough: the proxy would then have no idea
where one request ends and the next begins, so it could never answer from
a cache. The proxy must therefore:
    1. read ONE complete request from the client (framing),
    2. look it up in its cache,
    3. on a HIT  answer the client itself - the server is never contacted,
    4. on a MISS forward the request to the server, store the answer, reply,
    5. keep working (for cached requests!) when the server is down.

The protocol is defined in protocol.md; comments reference its sections (§).

What is GIVEN:
    argument parsing, the listening socket, one thread per client connection,
    the overall shape of handle_client().

Completed (TODO 1-5):
    recv_line / send_json, cache_key  in common.py, shared with the server - §2, §9.2
    ProxyCache           the server's LRUCache plus hits / misses / bypassed counters - §9.4
    forward_to_server()  new TCP connection per forwarded request, original line - §10.3-§10.5
    handle_request()     validate, bypass / hit / miss, SERVER_UNAVAILABLE - §10.1, §10.2
    handle_client()      persistent connection + error handling, proxy_cache and took_ms - §8, §10.6
"""
import argparse
import json
import socket
import threading
import time
from typing import Any, Dict, Optional, Tuple

# Framing, validation, the cache key and error responses are the same code as in
# the server, so a request is judged identically by both - see protocol.md §10.2
from common import cache_key, make_error, recv_line, send_json, validate_request
from server import LRUCache


# ======================================================================
# Cache - see protocol.md §9
# ======================================================================
class ProxyCache(LRUCache):
    """
    The server's LRU cache (protocol.md §9.4) plus counters for the report:
        hits / misses - lookups that found / did not find a stored response
        bypassed      - requests with "cache": false, which skip the cache (§9.1)

    Keys come from common.cache_key(): (mode, stripped text) - see protocol.md §9.2.
    LRU: a hit moves the entry to the most recently used end, and when the
    capacity is exceeded the least recently used entry is evicted.
    """

    def __init__(self, capacity: int):
        super().__init__(capacity)
        self.hits = 0
        self.misses = 0
        self.bypassed = 0

    def get(self, key: Any) -> Optional[Dict[str, Any]]:
        response = super().get(key)
        # The same lock as the cache: client threads update the counters concurrently
        with self._lock:
            if response is None:
                self.misses += 1
            else:
                self.hits += 1
        return response

    def put(self, key: Any, response: Dict[str, Any]) -> None:
        self.set(key, response)

    def count_bypass(self) -> None:
        with self._lock:
            self.bypassed += 1

    def counters(self) -> str:
        return f"hits={self.hits}, misses={self.misses}, bypassed={self.bypassed}"


# ======================================================================
# Upstream - see protocol.md §10.3-§10.5
# ======================================================================
def forward_to_server(server_host: str, server_port: int,
                      request: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Send ONE request to the real server and return (response, None), or
    (None, reason) when no valid response was obtained (protocol.md §10.5).

    `request` is the client's original line without the "\\n"; it is forwarded
    byte for byte, so both legs of a capture show the same payload (§10.4).

    Every call opens a NEW TCP connection and closes it after the response
    (§10.3): each miss is a separate connection in Wireshark, a hit opens none,
    and a restarted server works on the next request with no state to repair.
    """
    # Short connect timeout: a stopped server is detected quickly - see protocol.md §8.9
    try:
        sock = socket.create_connection((server_host, server_port), timeout=3)
    except ConnectionRefusedError:
        return None, "connection refused"
    except socket.timeout:
        return None, "connect timeout (3 s)"
    except OSError as e:
        return None, f"cannot connect: {e}"

    # close() at the end of the block sends our FIN - nothing is left unread
    with sock:
        try:
            # Long read timeout: a slow but working server has time to answer,
            # and 3 + 25 s is still below the client's 30 s - see protocol.md §8.9
            sock.settimeout(25)
            sock.sendall(request + b"\n")
            line, _ = recv_line(sock, b"")
        except socket.timeout:
            return None, "read timeout (25 s)"
        except ValueError:
            return None, "response larger than 65536 bytes"
        except OSError as e:
            return None, f"socket error: {e}"

    if line is None:
        return None, "server closed the connection before responding"
    try:
        response = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None, "response is not valid JSON"
    if not isinstance(response, dict):
        return None, "response is not a JSON object"
    return response, None


# ======================================================================
# Request handling - see protocol.md §10.1
# ======================================================================
def handle_request(line: bytes, msg: Any, cache: ProxyCache,
                   server_host: str, server_port: int) -> Tuple[Dict[str, Any], bool, str]:
    """
    Take ONE parsed request and return (response, proxy_cache, log_text).
    The response is returned without the proxy's meta fields; handle_client adds them.
    """
    # Same validation as the server: a malformed request gets its real error
    # even while the server is down - see protocol.md §10.2
    error, mode, text, use_cache = validate_request(msg)
    if error:
        return error, False, f"invalid ({error['error']['code']})"

    key = cache_key(mode, text)
    if not use_cache:
        # cache: false - no lookup and no store - see protocol.md §9.1
        cache.count_bypass()
        label = "BYPASS"
        response, reason = forward_to_server(server_host, server_port, line)
    else:
        hit = cache.get(key)
        if hit is not None:
            # The server is not contacted at all
            return hit, True, f"HIT {key}"
        label = "MISS"
        response, reason = forward_to_server(server_host, server_port, line)
        # Only successes and BAD_EXPR have a fixed outcome; the full response is
        # stored - see protocol.md §9.3
        if response is not None and (response["ok"] or response["error"]["code"] == "BAD_EXPR"):
            cache.put(key, response)

    if response is None:
        what = "cache bypassed" if label == "BYPASS" else "cache miss"
        message = f"{what} and no valid response from the server: {reason}"
        return make_error("SERVER_UNAVAILABLE", message), False, f"{label} {key} -> SERVER_UNAVAILABLE ({reason})"
    return response, False, f"{label} {key}"


def with_proxy_meta(response: Dict[str, Any], proxy_cache: bool, started: float) -> Dict[str, Any]:
    """
    Return a COPY of `response` with the proxy's took_ms and proxy_cache - see
    protocol.md §10.6. A copy, so a cached entry is never changed. The server's
    from_cache is kept, so each layer has its own flag.
    """
    meta = {**response["meta"], "took_ms": int((time.time() - started) * 1000), "proxy_cache": proxy_cache}
    return {**response, "meta": meta}


# ======================================================================
# Per-client loop - see protocol.md §8
# ======================================================================
def handle_client(conn: socket.socket, addr, cache: ProxyCache,
                  server_host: str, server_port: int) -> None:
    """
    Serve ONE client connection: many requests, one response each (protocol.md §8.1).
    Same robustness as the server: a bad line keeps the connection open, an
    oversized message closes it, and socket errors never crash the thread.
    """
    print(f"[proxy] + connection from {addr}")
    buf = b""
    with conn:
        try:
            while True:
                try:
                    line, buf = recv_line(conn, buf)
                except ValueError as e:
                    # The newline never arrived, so the stream is out of sync: answer and close - see protocol.md §2.3
                    send_json(conn, with_proxy_meta(make_error("MESSAGE_TOO_LARGE", str(e)), False, time.time()))
                    break
                if line is None:
                    if buf:
                        # A partial message followed by FIN can never be completed - see protocol.md §8.3
                        print(f"[proxy] {addr} disconnected mid-message, discarded {len(buf)} bytes")
                    break
                started = time.time()

                # A bad line keeps the connection open: the "\n" bounds it - see protocol.md §8.2
                try:
                    msg = json.loads(line.decode("utf-8"))
                except UnicodeDecodeError:
                    response, proxy_cache, log = make_error("BAD_ENCODING", "request is not valid UTF-8"), False, "invalid (BAD_ENCODING)"
                except (json.JSONDecodeError, RecursionError):
                    # RecursionError: JSON nested too deeply for Python's parser
                    response, proxy_cache, log = make_error("BAD_JSON", "request is not valid JSON"), False, "invalid (BAD_JSON)"
                else:
                    try:
                        response, proxy_cache, log = handle_request(line, msg, cache, server_host, server_port)
                    except Exception as e:
                        # Safety net: a bug must not kill the thread or skip the response - see protocol.md §5
                        response, proxy_cache, log = make_error("INTERNAL_ERROR", "unexpected proxy error"), False, f"INTERNAL_ERROR {e!r}"

                # Every response sent by the proxy carries proxy_cache - see protocol.md §10.6
                send_json(conn, with_proxy_meta(response, proxy_cache, started))
                print(f"[proxy] {addr} {log}  ({cache.counters()})")
        except OSError as e:
            # Reset or another socket failure: log and clean up, never crash - see protocol.md §8.5
            print(f"[proxy] socket error with {addr}: {e}")
    print(f"[proxy] - connection from {addr} closed  ({cache.counters()})")


# ======================================================================
# Accept loop (GIVEN)
# ======================================================================
def serve(listen_host: str, listen_port: int, server_host: str, server_port: int,
          cache_size: int) -> None:
    cache = ProxyCache(cache_size)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((listen_host, listen_port))
        srv.listen(16)
        print(f"[proxy] {listen_host}:{listen_port} -> {server_host}:{server_port} (cache size={cache_size})")
        try:
            while True:
                conn, addr = srv.accept()
                threading.Thread(target=handle_client,
                                 args=(conn, addr, cache, server_host, server_port),
                                 daemon=True).start()
        except KeyboardInterrupt:
            print(f"\n[proxy] shutting down ({cache.counters()})")


def main() -> None:
    ap = argparse.ArgumentParser(description="EX2 caching proxy")
    ap.add_argument("--listen-host", default="127.0.0.1")
    ap.add_argument("--listen-port", type=int, default=5554)
    ap.add_argument("--server-host", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=5555)
    ap.add_argument("--cache-size", type=int, default=64)
    args = ap.parse_args()
    serve(args.listen_host, args.listen_port, args.server_host, args.server_port, args.cache_size)


if __name__ == "__main__":
    main()
