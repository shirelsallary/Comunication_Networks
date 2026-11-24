# client.py
"""
EX2 - JSON-over-TCP client

Two ways to use it:

  one-shot (handy for scripts and for the examples in the assignment):
      python client.py --host 127.0.0.1 --port 5555 --mode calc --expr "1+2*3"
      python client.py --host 127.0.0.1 --port 5555 --mode gpt  --prompt "count to 10"
      add --cache / --no-cache to force caching on / off (omit both for the per-mode default)

  interactive (no --mode): a menu that lets you send many requests over ONE
  connection without restarting the client:
      python client.py --host 127.0.0.1 --port 5554

The client does not know (or care) whether host:port is the real server or
the proxy - that is the whole point of the proxy being protocol-compatible.
The protocol is defined in protocol.md; comments reference its sections (§).

Given in the skeleton (adjusted where noted):
    PRESET_EXPRESSIONS                      - ready-made expressions for the menu
    build_calc_request / build_gpt_request  - request dicts; changed to send `options`
                                              only when the user chose a cache value (§3.3)
    print_response                          - pretty printer
    main                                    - argument parsing and routing; `--no-cache`
                                              replaced by `--cache / --no-cache` (§3.3)

Implemented by us:
    recv_line()            framing: one message per "\\n", 64 KiB limit (§2.2, §2.3)
    Connection.request()   send one request, wait for its ONE response, handle errors (§8.6, §8.7)
    Connection.close()     close cleanly: shutdown() sends FIN, then close() (§8.3)
    interactive_loop()     menu over one persistent connection, with reconnect (§8.1, §8.8)
"""
import argparse
import json
import socket
import sys
from typing import Any, Dict, Optional, Tuple

# A few expressions the user can pick from the menu. The last three use
# comparisons and and/or/not, which the server supports (protocol.md §6.3).
PRESET_EXPRESSIONS = [
    "1+2*3",
    "sin(max(2, 3*4, 5) / 7) * 3",
    "sqrt(16) + 2**10 % 7",
    "1 < 2 and 3 >= 4",
    "not (pi > 3) or e < 3",
    "1 < 2 < 3",
]


# ======================================================================
# Request builders - see protocol.md §3
# ======================================================================
def build_calc_request(expr: str, use_cache: Optional[bool] = None) -> Dict[str, Any]:
    """
    Build a calc request: {"mode": "calc", "data": {"expr": ...}, ["options": {"cache": ...}]}.

    use_cache has three states (protocol.md §3.3):
        None  - the user did not choose: no `options` are sent, the receiver
                applies the per-mode default (calc: cache on)
        True  - explicitly allow caching
        False - explicitly bypass the cache
    """
    req = {"mode": "calc", "data": {"expr": expr}}
    # "is not None" and not just "if use_cache": False is a real choice that must be sent
    if use_cache is not None:
        req["options"] = {"cache": use_cache}
    return req

def build_gpt_request(prompt: str, use_cache: Optional[bool] = None) -> Dict[str, Any]:
    """
    Build a gpt request: {"mode": "gpt", "data": {"prompt": ...}, ["options": {"cache": ...}]}.
    Same three-state use_cache as build_calc_request; the default for gpt is cache off,
    because model answers are not deterministic (protocol.md §3.3).
    """
    req = {"mode": "gpt", "data": {"prompt": prompt}}
    if use_cache is not None:
        req["options"] = {"cache": use_cache}
    return req


def print_response(resp: Optional[Dict[str, Any]]) -> None:
    """Pretty-print one response dict, or a notice when no response arrived (None)."""
    if resp is None:
        print("!! no response (connection closed by the other side)")
        return
    # ensure_ascii=False keeps non-English text (e.g. Hebrew GPT answers) readable
    print(json.dumps(resp, ensure_ascii=False, indent=2))


# ======================================================================
# Framing - see protocol.md §2
# ======================================================================
def recv_line(sock: socket.socket, buf: bytes) -> Tuple[Optional[bytes], bytes]:
    """
    Read exactly ONE message from the stream - see protocol.md §2.2.

    Returns (line, leftover):
        line     - one complete message WITHOUT the trailing b"\\n",
                   or None if the peer closed the connection (sent FIN) first.
        leftover - bytes already received that belong to the NEXT message;
                   the caller must pass them back in as `buf` on the next call.

    Raises ValueError if a message is longer than 65,536 bytes (protocol.md §2.3).

    Why a loop and a buffer: TCP is a byte stream, so one recv() may return half a
    message, exactly one, or one and a half. Only the "\\n" tells where a message ends.
    """
    #loop until we return something
    while True:
        if b"\n" in buf: #True if the buffer has a new line
            line, rest = buf.split(b"\n", 1) #Split the first new line only (1 is for split once)
            if len(line) > 65536: #checks line size and limit
                raise ValueError("Message exceeded 64KiB limit")
            return line, rest #returns the recieved line and the rest of the buffer

        # No "\n" yet but already over the limit: this message can only be too long,
        # so stop instead of buffering forever
        if len(buf) > 65536: #checks buffer size and limit
            raise ValueError("Message exceeded 64KiB limit")

        chunk = sock.recv(4096) #waits for data and returns up to 4096 bytes; b"" means that the other side was closed
        if not chunk: #if the received chunk is empty, return tuple (None, buf)
            return None, buf
        buf += chunk #join recieved bytes together


# ======================================================================
# One open connection - see protocol.md §8
# ======================================================================
class Connection:
    """
    ONE TCP connection to the server or the proxy, plus the receive buffer
    that framing needs between calls. Open it once, send many requests,
    then close it - that is what "persistent connection" means.

    Attributes:
        sock   - the TCP socket
        buf    - bytes received but not yet consumed (the start of the next message)
        closed - True once the connection is closed by us or found dead;
                 interactive_loop() checks it to offer a reconnect (§8.8)
        host, port - kept so a new connection to the same address can be opened
    """

    def __init__(self, host: str, port: int, timeout: float = 30.0):
        # A real GPT call can take several seconds - do not make the timeout too small.
        # 30 s is the client's layer in the timeout chain of protocol.md §8.9
        # (larger than the proxy's 3 + 25 s, so errors from below arrive first).
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self.closed = False
        self.host = host
        self.port = port

    def request(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send `payload` as ONE framed message and return the ONE response dict.

        Returns None when no usable response arrived. Check `self.closed` to tell why:
            closed      - peer disconnected, timeout, socket error or oversized
                          response; the connection cannot be used anymore
            still open  - the response line was not valid JSON / UTF-8; the "\\n"
                          still bounded it, so the stream is in sync (§8.7)
        """
        try:
            text = json.dumps(payload) #turns dictionary request to string
            data = (text + "\n").encode("utf-8") #encode the string to bytes
            self.sock.sendall(data) #sends all the bytes

            line, self.buf = recv_line(self.sock, self.buf) # save the leftover for the next call

            if line is None: # if recv_line returned None
                self.close()
                return None
            obj = json.loads(line.decode("utf-8")) #turns the encoded bytes into a dictionary and returns it
            return obj

        # Order matters: Python uses the FIRST matching except.
        # socket.timeout is a subclass of OSError, so it must come before OSError;
        # json.JSONDecodeError is a subclass of ValueError, so it must come before ValueError.
        except socket.timeout: #if no answer was recieved within the timeout period
            # Close, because a late answer would be mistaken for the reply to
            # the next request (requests carry no id) - protocol.md §8.6
            print("No answer was recieved within the timeout")
            self.close()
            return None
        except OSError:
            # Connection reset / broken pipe, e.g. the server was killed - §8.5
            print("Connection error")
            self.close()
            return None
        except (json.JSONDecodeError, UnicodeDecodeError): #checks if the encoding is in the right format
            # The connection stays open: the bad line was still one whole message - §8.7
            print("Server sent an invalid (non-JSON) response")
            return None
        except ValueError:
            # Raised by recv_line: no "\n" within 64 KiB, the stream is out of sync - §2.3
            print("Size limit exceeded")
            self.close()
            return None



    def close(self) -> None:
        """
        Close the connection cleanly - see protocol.md §8.3.

        shutdown() sends a FIN, so the other side's recv() returns b"" and it can
        end its loop (visible in Wireshark). close() then frees the socket.
        Safe to call more than once, and safe when the peer is already gone.
        """

        if self.closed: # if the connection is already closed, we do nothing
            return
        try:
            self.sock.shutdown(socket.SHUT_RDWR) # sends FIN (finish alert) to the server (can be refered as the message "I am done receiving")
        except OSError: # if its already disconected, prevent double closing crash
            pass
        # Outside the try: the socket is released even when shutdown() failed
        self.sock.close()
        self.closed = True


    # Allow `with Connection(...) as c:`
    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        # Runs when the `with` block ends, also on an exception
        self.close()


def request(host: str, port: int, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One-shot helper: open, send one request, close. Used by --mode."""
    with Connection(host, port) as conn:
        return conn.request(payload)


# ======================================================================
# Interactive mode - see protocol.md §8.1, §8.8
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
    Menu loop: every request is sent over the SAME connection (persistent
    connection, protocol.md §8.1) until the user quits.

    Behavior:
        * 1 / 2 / 3 build a calc or gpt request, send it and print the response
        * 4 cycles the cache option: default -> True -> False -> default (§3.3)
        * empty input or a bad choice is ignored; Ctrl+C / Ctrl+D quit cleanly
        * if the connection closes, the user is asked whether to reconnect;
          the failed request is NOT resent automatically (§8.8)
    The current connection is always closed on exit (the finally block).
    """
    # None = the user has not chosen, so no `options` are sent (§3.3)
    use_cache = None
    try:
        while True:
            try:
                # Recomputed on every pass so the menu always shows the current value
                cache_text = "default (calc on, gpt off)" if use_cache is None else use_cache
                choice = input(MENU.format(cache=cache_text)).strip().lower() #fills {cache} in the menu text

                match choice:
                    case "1": #if option 1 was choosed, print the expressions
                        for i, expr in enumerate(PRESET_EXPRESSIONS, start=1):
                            print(f"   {i}) {expr}")
                        idx = int(input("number: ")) # read a number
                        # Without this check, 0 or a negative number would silently
                        # pick from the END of the list (negative indexing)
                        if not 1 <= idx <= len(PRESET_EXPRESSIONS): # check that 1 <= idx <= len(PRESET_EXPRESSIONS)
                            print("Invalid Number")
                            continue
                        expr = PRESET_EXPRESSIONS[idx - 1]
                        req = build_calc_request(expr, use_cache) # builds a calc request
                    case "2": # reads a typed calc request
                        expr = input("Expression: ").strip()
                        if not expr: continue  # empty expression: back to the menu, nothing is sent
                        req = build_calc_request(expr, use_cache)
                    case "3": # reads a typed GPT prompt
                        prompt = input("Prompt: ").strip()
                        if not prompt: continue  # empty prompt: back to the menu, nothing is sent
                        req = build_gpt_request(prompt, use_cache)
                    case "4": # cycle the cache option through its three states
                        if use_cache is None:
                            use_cache = True
                        elif use_cache is True:
                            use_cache = False
                        else:
                            use_cache = None
                        continue  # nothing to send, show the menu again

                    case "q":
                        return  # the finally block closes the connection
                    case _:
                        print("Invalid choice")
                        continue

                respond = conn.request(req)
                print_response(respond)
                # request() closes the connection on a timeout, a socket error or a
                # disconnect - ask before reconnecting, never resend on our own (§8.8)
                if conn.closed:
                    print("Connection is closed, would you like to reconnect ? (y/n)")
                    ans = input("Answer: ").strip().lower()
                    if ans == "y":
                        # Replaces conn; the old one is already closed, and the new
                        # one is closed by the finally block below
                        conn = Connection(conn.host,conn.port)
                    else:
                        return

            except (KeyboardInterrupt, EOFError):
                # Ctrl+C / Ctrl+D: quit (looping again would spin forever on EOF)
                return
            except ValueError:
                # int() could not parse the preset number
                print("Invalid Input")
            except OSError:
                # Connection() failed while reconnecting (e.g. ConnectionRefusedError)
                print("Could not reconnect to the server")
                return
    finally:
        # Runs on every way out of the loop; close() is safe to call twice
        conn.close()


# ======================================================================
# Entry point
# ======================================================================
def main() -> None:
    """Parse the command line, then run one request (--mode) or the interactive menu."""
    ap = argparse.ArgumentParser(description="EX2 client (calc / gpt over JSON TCP)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555, help="server or proxy port")
    ap.add_argument("--mode", choices=["calc", "gpt"], help="one-shot mode; omit for the interactive menu")
    ap.add_argument("--expr", help="expression for --mode calc")
    ap.add_argument("--prompt", help="prompt for --mode gpt")
    # BooleanOptionalAction creates both --cache and --no-cache; args.cache is
    # True, False, or None when neither flag is given (protocol.md §3.3)
    ap.add_argument("--cache", action=argparse.BooleanOptionalAction, default=None, help="force caching on (--cache) or off (--no-cache); omit for the per-mode default")
    args = ap.parse_args()

    try:
        # No --mode: interactive menu over one persistent connection
        if args.mode is None:
            with Connection(args.host, args.port) as conn:
                interactive_loop(conn)
            return

        # --mode given: build one request, send it, print the answer, exit
        if args.mode == "calc":
            if not args.expr:
                sys.exit("Missing --expr")
            payload = build_calc_request(args.expr, args.cache)
        else:
            if not args.prompt:
                sys.exit("Missing --prompt")
            payload = build_gpt_request(args.prompt, args.cache)

        print_response(request(args.host, args.port, payload))
    except ConnectionRefusedError:
        sys.exit(f"Could not connect to {args.host}:{args.port} - is the server/proxy running?")


if __name__ == "__main__":
    main()
