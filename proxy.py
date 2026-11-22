# proxy.py
"""
EX2 - Caching proxy (student skeleton)

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

What is GIVEN:
    argument parsing, the listening socket, one thread per client connection,
    the overall shape of handle_client().

What YOU must complete (search for "TODO"):
    TODO 1  recv_line()          framing - same contract as in server.py
    TODO 2  cache_key()          what makes two requests "the same request"?
    TODO 3  ProxyCache           storage + eviction policy (LRU or another, explain it)
    TODO 4  forward_to_server()  one request to the real server, one response back
    TODO 5  handle_client()      hit / miss / server-down logic, many requests per connection
"""
import argparse
import json
import socket
import threading
from typing import Any, Dict, Optional, Tuple


# ======================================================================
# Framing (TODO 1)
# ======================================================================
def recv_line(sock: socket.socket, buf: bytes) -> Tuple[Optional[bytes], bytes]:
    """Same contract as server.recv_line(). TODO 1: implement."""
    raise NotImplementedError("TODO 1: implement framing in recv_line()")


def send_json(sock: socket.socket, obj: Dict[str, Any]) -> None:
    sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


# ======================================================================
# Cache (TODO 2, TODO 3)
# ======================================================================
def cache_key(request: Dict[str, Any]) -> str:
    """
    Return a string that identifies "the same request" for caching purposes.

    TODO 2: decide and DOCUMENT in protocol.md. Questions to answer:
        * Are `mode` + `data` enough? Do `options` belong in the key?
        * JSON objects are unordered: {"a":1,"b":2} and {"b":2,"a":1} are the
          same request. Does your key treat them the same? (hint: sort_keys)
        * Is "1+2" the same request as "1 + 2"? Must it be?
        * Should options.cache == false bypass the cache entirely (not even
          stored)? Where is that decided - here or in handle_client()?
    """
    raise NotImplementedError("TODO 2: implement cache_key()")


class ProxyCache:
    """
    Stores responses keyed by cache_key().

    TODO 3: implement. You may take the LRU idea from server.LRUCache or use a
    different eviction policy, but you must be able to explain how it works
    and why you chose it. Remember several client threads share this object.

    The hit / miss counters are for YOU: print them (or expose them) so your
    report can show the numbers next to the Wireshark capture.
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        # TODO 3: choose a data structure

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("TODO 3: implement ProxyCache.get()")

    def put(self, key: str, response: Dict[str, Any]) -> None:
        raise NotImplementedError("TODO 3: implement ProxyCache.put()")


# ======================================================================
# Upstream (TODO 4)
# ======================================================================
def forward_to_server(server_host: str, server_port: int,
                      request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Send ONE request to the real server and return its ONE response dict.
    Return None if the server cannot be reached or disconnects before answering.

    TODO 4:
        * The assignment lets you choose: open a fresh TCP connection to the
          server for every forwarded request (simple), or keep one persistent
          upstream connection per client (fewer handshakes - compare the two in
          Wireshark!). Either way, document the choice.
        * ConnectionRefusedError / socket.timeout / peer closed -> return None,
          never let the exception kill the client thread.
    """
    raise NotImplementedError("TODO 4: implement forward_to_server()")


# ======================================================================
# Per-client loop (TODO 5)
# ======================================================================
def handle_client(conn: socket.socket, addr, cache: ProxyCache,
                  server_host: str, server_port: int) -> None:
    """
    Serve ONE client connection: many requests, one response each.

    TODO 5: for every complete line received from the client:
        a. parse it as JSON. If it is not valid JSON, decide: answer with an
           error yourself, or forward it and let the server decide? (document)
        b. key = cache_key(req)   -> HIT:  send the stored response and `continue`
                                            (the server is not contacted at all -
                                            this is what scenario 2 must show)
        c. MISS: resp = forward_to_server(...)
             - None (server down)  -> send a well-formed error response to the
                                      client (scenario 3) - do not hang, do not crash
             - otherwise           -> store it (should ok=false responses be
                                      cached?), then send it to the client
        d. Think about what the client should SEE: the stored response says
           "from_cache": false from the server's point of view. Should the
           proxy mark its own hits (e.g. an extra meta field)? That makes your
           Wireshark explanation much easier.
    """
    print(f"[proxy] + connection from {addr}")
    buf = b""
    with conn:
        while True:
            line, buf = recv_line(conn, buf)
            if line is None:
                break

            # TODO 5: parse, cache lookup, forward on miss, answer the client.
            raise NotImplementedError("TODO 5: implement the proxy logic")
    print(f"[proxy] - connection from {addr} closed  (hits={cache.hits}, misses={cache.misses})")


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
            print(f"\n[proxy] shutting down (hits={cache.hits}, misses={cache.misses})")


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
