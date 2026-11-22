# client.py
"""
EX2 - JSON-over-TCP client (student skeleton)

Two ways to use it (both must work when you are done):

  one-shot (handy for scripts and for the examples in the assignment):
      python client.py --host 127.0.0.1 --port 5555 --mode calc --expr "1+2*3"
      python client.py --host 127.0.0.1 --port 5555 --mode gpt  --prompt "count to 10"

  interactive (no --mode): a menu that lets you send many requests over ONE
  connection without restarting the client:
      python client.py --host 127.0.0.1 --port 5554

The client does not know (or care) whether host:port is the real server or
the proxy - that is the whole point of the proxy being protocol-compatible.

What is GIVEN:
    build_calc_request / build_gpt_request  - request dicts (match protocol.md!)
    PRESET_EXPRESSIONS                      - ready-made expressions for the menu
    print_response                          - pretty printer
    main                                    - argument parsing and routing

What YOU must complete (search for "TODO"):
    TODO 1  recv_line()            framing - same contract as in server.py
    TODO 2  Connection.request()   send one request, wait for its ONE response
    TODO 3  Connection.close()     close the connection cleanly (look for the FIN in Wireshark)
    TODO 4  interactive_loop()     menu: preset / typed expression / GPT prompt / quit
"""
import argparse
import json
import socket
import sys
from typing import Any, Dict, Optional, Tuple

# A few expressions the user can pick from the menu. The last ones are only
# useful once the server supports comparisons and and/or/not (server TODO 3).
PRESET_EXPRESSIONS = [
    "1+2*3",
    "sin(max(2, 3*4, 5) / 7) * 3",
    "sqrt(16) + 2**10 % 7",
    "1 < 2 and 3 >= 4",
    "not (pi > 3) or e < 3",
    "1 < 2 < 3",
]


# ======================================================================
# Request builders (GIVEN - keep them in sync with protocol.md)
# ======================================================================
def build_calc_request(expr: str, use_cache: bool = True) -> Dict[str, Any]:
    return {"mode": "calc", "data": {"expr": expr}, "options": {"cache": use_cache}}


def build_gpt_request(prompt: str, use_cache: bool = True) -> Dict[str, Any]:
    return {"mode": "gpt", "data": {"prompt": prompt}, "options": {"cache": use_cache}}


def print_response(resp: Optional[Dict[str, Any]]) -> None:
    if resp is None:
        print("!! no response (connection closed by the other side)")
        return
    print(json.dumps(resp, ensure_ascii=False, indent=2))


# ======================================================================
# Framing (TODO 1)
# ======================================================================
def recv_line(sock: socket.socket, buf: bytes) -> Tuple[Optional[bytes], bytes]:
    """
    Same contract as server.recv_line():
    return (one complete message without the trailing b"\\n", leftover bytes),
    or (None, leftover) if the peer closed the connection first.

    TODO 1: implement (you may share the code with the server/proxy in a
    module of your own - just make sure everything you submit is in the ZIP).
    """
    raise NotImplementedError("TODO 1: implement framing in recv_line()")


# ======================================================================
# One open connection (TODO 2, TODO 3)
# ======================================================================
class Connection:
    """
    ONE TCP connection to the server or the proxy, plus the receive buffer
    that framing needs between calls. Open it once, send many requests,
    then close it - that is what "persistent connection" means.
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        # A real GPT call can take several seconds - do not make the timeout too small.
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""

    def request(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send `payload` as ONE framed message and return the ONE response dict.
        Return None if the connection was closed before a response arrived.

        TODO 2:
            * serialise + frame the message (same framing as send_json in server.py)
            * sendall() it
            * recv_line() the answer, remember to keep self.buf updated
            * json.loads() the answer (what if the server sent garbage?)
            * socket.timeout -> decide what to tell the user
        """
        raise NotImplementedError("TODO 2: implement Connection.request()")

    def close(self) -> None:
        """
        TODO 3: close cleanly. After this, the server's recv() must return b""
        (it sees your FIN) so it can finish its loop. Look at socket.shutdown()
        in addition to close(), and make sure closing twice does not crash.
        """
        raise NotImplementedError("TODO 3: implement Connection.close()")

    # Allow `with Connection(...) as c:`
    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def request(host: str, port: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One-shot helper: open, send one request, close. Used by --mode."""
    with Connection(host, port) as conn:
        return conn.request(payload)


# ======================================================================
# Interactive mode (TODO 4)
# ======================================================================
MENU = """
--- EX2 client -------------------------------------------
  1) calc  - pick a preset expression
  2) calc  - type an expression (arithmetic or logical)
  3) gpt   - type a prompt
  4) toggle cache option (currently: {cache})
  q) quit
----------------------------------------------------------
> """


def interactive_loop(conn: Connection) -> None:
    """
    TODO 4: implement the menu.
        * read a choice, build the matching request with the builders above
        * for 1) show PRESET_EXPRESSIONS numbered and let the user pick one
        * send it over `conn` (the SAME connection every time) and print_response()
        * loop until the user chooses q - then return so main() can close cleanly
        * do not crash on empty input, a bad menu choice or Ctrl+C / Ctrl+D
        * if request() returns None the other side closed the connection:
          tell the user and stop (or reconnect - your choice, document it)
    """
    use_cache = True
    raise NotImplementedError("TODO 4: implement interactive_loop()")


# ======================================================================
# Entry point (GIVEN)
# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description="EX2 client (calc / gpt over JSON TCP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555, help="server or proxy port")
    ap.add_argument("--mode", choices=["calc", "gpt"], help="one-shot mode; omit for the interactive menu")
    ap.add_argument("--expr", help="expression for --mode calc")
    ap.add_argument("--prompt", help="prompt for --mode gpt")
    ap.add_argument("--no-cache", action="store_true", help="send options.cache=false")
    args = ap.parse_args()

    try:
        if args.mode is None:
            with Connection(args.host, args.port) as conn:
                interactive_loop(conn)
            return

        if args.mode == "calc":
            if not args.expr:
                sys.exit("Missing --expr")
            payload = build_calc_request(args.expr, not args.no_cache)
        else:
            if not args.prompt:
                sys.exit("Missing --prompt")
            payload = build_gpt_request(args.prompt, not args.no_cache)

        print_response(request(args.host, args.port, payload))
    except ConnectionRefusedError:
        sys.exit(f"Could not connect to {args.host}:{args.port} - is the server/proxy running?")


if __name__ == "__main__":
    main()
