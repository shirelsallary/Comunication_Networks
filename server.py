# server.py
"""
EX2 - Application-layer lab: JSON-over-TCP server (student skeleton)

Run:
    python server.py --host 127.0.0.1 --port 5555 --cache-size 128

The server accepts TCP connections, reads application-layer messages
(the skeleton suggests ONE JSON object per line, terminated by "\\n"),
and answers each one with a single JSON response. Two request types must
be supported: mode="calc" and mode="gpt" (see your protocol.md).

What is GIVEN (you may keep, change or rewrite it - just keep the requirements):
    LRUCache        - small LRU cache based on OrderedDict (server-side cache).
    safe_eval_expr  - safe ARITHMETIC evaluation using the `ast` module. No eval()!
    call_gpt        - stub that answers without any API key.
    handle_request  - validates a parsed request dict and dispatches to calc / gpt.
    send_json       - serialises a response dict and writes it to the socket.
    serve           - accept loop, one thread per client connection.

What YOU must complete (search the file for "TODO"):
    TODO 1  recv_line()      framing: read ONE complete message from the byte stream.
    TODO 2  handle_client()  persistent connection + error handling.
    TODO 3  _eval_node()     comparisons (< <= == != > >=) and and / or / not.
    TODO 4  safe_eval_expr() decide how a boolean result is returned (document it!).
    TODO 5  (optional) call_gpt() - talk to a real model. Key goes in .env, NEVER in git/ZIP.

Enabling real GPT calls (optional):
    1. pip install -r requirements.txt
    2. copy .example.env to .env and put your key there
    3. implement the real call inside call_gpt()
"""
import argparse
import ast
import collections
import json
import math
import operator
import socket
import threading
import time
from typing import Any, Dict, Optional

from common import make_error, make_meta, recv_line, send_json

# ======================================================================
# LRU cache (GIVEN)
# ======================================================================
class LRUCache:
    """
    Minimal LRU cache built on OrderedDict.

    * get() moves the key to the "most recently used" end.
    * set() inserts/updates and evicts the LEAST recently used entry
      (the one at the front) when capacity is exceeded.

    You will need a cache in proxy.py as well. You may reuse this class, but
    think carefully about what the KEY should be there (see proxy.py).
    """

    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self._d: "collections.OrderedDict[str, Any]" = collections.OrderedDict()
        self._lock = threading.Lock()  # several client threads share one cache

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._d:
                return None
            self._d.move_to_end(key)
            return self._d[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            if len(self._d) > self.capacity:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


# ======================================================================
# Safe expression evaluation (GIVEN for arithmetic, TODO for booleans)
# ======================================================================
# We never call eval(). The expression is parsed into an AST and only the
# node types / operators / functions listed below are allowed. Anything
# else raises ValueError, which handle_request turns into an error response.

_ALLOWED_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "sqrt": math.sqrt,
    "log": math.log, "exp": math.exp, "max": max, "min": min, "abs": abs,
}
_ALLOWED_CONSTS = {"pi": math.pi, "e": math.e}

# Arithmetic operators: binary (BinOp) and unary (UnaryOp).
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
    # TODO 3: `not x` is ast.UnaryOp(op=ast.Not(), operand=x). Where does it belong?
}

# TODO 3: comparison operators. The AST classes are ast.Lt, ast.LtE, ast.Eq,
# ast.NotEq, ast.Gt, ast.GtE and the matching functions live in `operator`
# (operator.lt, operator.le, ...). Fill this dict in.
_ALLOWED_CMP_OPS: Dict[type, Any] = {
    # ast.Lt: operator.lt,
}


def _eval_node(node: ast.AST) -> Any:
    """Recursively evaluate a restricted AST node."""
    # --- numbers --------------------------------------------------------
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        # Note: bool is a subclass of int, so `True` / `False` literals pass the
        # check above. Decide whether you want that and document it.
        raise ValueError("illegal constant type")

    # --- named constants (pi, e) ---------------------------------------
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_CONSTS:
            return _ALLOWED_CONSTS[node.id]
        raise ValueError(f"unknown symbol {node.id!r}")

    # --- unary / binary arithmetic -------------------------------------
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))

    # --- function calls -------------------------------------------------
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("illegal function call")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)

    # --- TODO 3: comparisons --------------------------------------------
    # `1 < 2` is parsed into ast.Compare(left=1, ops=[Lt()], comparators=[2]).
    # Python allows CHAINED comparisons: `1 < 2 < 3` is ONE Compare node with
    # ops=[Lt(), Lt()] and comparators=[2, 3], meaning (1 < 2) and (2 < 3).
    # Use _ALLOWED_CMP_OPS. Reject operators that are not in the dict.
    if isinstance(node, ast.Compare):
        raise NotImplementedError("TODO 3: comparisons are not supported yet")

    # --- TODO 3: and / or -----------------------------------------------
    # `a and b and c` is ONE ast.BoolOp(op=ast.And(), values=[a, b, c]).
    # `a or b` is ast.BoolOp(op=ast.Or(), values=[a, b]).
    # Decide (and document in protocol.md) whether you short-circuit like
    # Python does, and what `1 and 2` should evaluate to.
    if isinstance(node, ast.BoolOp):
        raise NotImplementedError("TODO 3: and / or are not supported yet")

    raise ValueError("illegal expression")


def safe_eval_expr(expr: str):
    """
    Parse `expr` and evaluate it safely (no eval()).

    Raises SyntaxError (cannot parse) or ValueError (parsed, but not allowed)
    - both are turned into an error response by handle_request().

    TODO 4: the code below forces every result to float, so
    `1 < 2` would come back as 1.0. Decide how a boolean result travels in
    your protocol (JSON true/false? 1/0? a string?) and make sure calc
    results of BOTH kinds are returned consistently. Document the choice.

    Edge cases worth a thought (the spec cannot list them all): very long
    expressions, `9**9**9`, division by zero, sqrt(-1), empty string ...
    """
    tree = ast.parse(expr, mode="eval")
    return float(_eval_node(tree.body))


# ======================================================================
# GPT component (GIVEN stub, optional real implementation)
# ======================================================================
def call_gpt(prompt: str) -> str:
    """
    Default fallback so the whole system runs WITHOUT an API key.

    TODO 5 (optional): replace the body with a real call to a model of your
    choice. Load the key from .env (python-dotenv) - never hard-code it and
    never put .env in the ZIP. Keep the stub as a fallback when no key is set,
    and never send personal data to an external service.
    """
    return f"[GPT-STUB] Received a prompt of {len(prompt)} characters."


# ======================================================================
# Request handling (GIVEN - adjust if you change the protocol)
# ======================================================================
# make_error / make_meta live in common.py: the proxy builds the same responses.


def handle_request(msg: Dict[str, Any], cache: LRUCache) -> Dict[str, Any]:
    """
    Take ONE parsed request dict and return ONE response dict.
    Pure application logic: no sockets here, which makes it easy to test.
    """
    if not isinstance(msg, dict):
        return make_error("BAD_REQUEST", "Bad request: expected a JSON object")

    mode = msg.get("mode")
    data = msg.get("data") or {}
    options = msg.get("options") or {}
    use_cache = bool(options.get("cache", True))

    started = time.time()
    # Note: this key includes `options` as well. Is that the right choice?
    # (You will face the same question in proxy.py - document your answer.)
    cache_key = json.dumps(msg, sort_keys=True)

    if use_cache:
        hit = cache.get(cache_key)
        if hit is not None:
            took = int((time.time() - started) * 1000)
            return {"ok": True, "result": hit, "meta": make_meta(True, took)}

    try:
        if mode == "calc":
            expr = data.get("expr")
            if not expr or not isinstance(expr, str):
                return make_error("BAD_REQUEST", "Bad request: 'expr' is required (string)")
            result = safe_eval_expr(expr)
        elif mode == "gpt":
            prompt = data.get("prompt")
            if not prompt or not isinstance(prompt, str):
                return make_error("BAD_REQUEST", "Bad request: 'prompt' is required (string)")
            result = call_gpt(prompt)
        else:
            return make_error("UNKNOWN_MODE", f"Bad request: unknown mode {mode!r}")
    except NotImplementedError as e:
        # Temporary: the evaluator still has stubs; this clause is removed in step 6 - see protocol.md §5
        return make_error("INTERNAL_ERROR", f"Not implemented: {e}")
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        return make_error("BAD_EXPR", f"Bad expression: {e}")

    took = int((time.time() - started) * 1000)
    if use_cache:
        cache.set(cache_key, result)
    return {"ok": True, "result": result, "meta": make_meta(False, took)}


# ======================================================================
# Framing and per-connection loop (TODO 2)
# ======================================================================
# send_json / recv_line live in common.py: the proxy uses the same framing.


def handle_client(conn: socket.socket, addr, cache: LRUCache) -> None:
    """
    Serve ONE client for the whole lifetime of its connection - see protocol.md §8.

    The connection stays open after every response. It is closed only when the
    client sends FIN, disconnects in the middle of a message, or sends a message
    over 64 KiB. Every complete request gets exactly one response.
    """
    print(f"[server] + connection from {addr}")
    buf = b""
    with conn:
        try:
            while True:
                try:
                    line, buf = recv_line(conn, buf)
                except ValueError as e:
                    # The newline never arrived, so the stream is out of sync: answer and close - see protocol.md §2.3
                    send_json(conn, make_error("MESSAGE_TOO_LARGE", str(e)))
                    break
                if line is None:
                    if buf:
                        # A partial message followed by FIN can never be completed - see protocol.md §8.3
                        print(f"[server] {addr} disconnected mid-message, discarded {len(buf)} bytes")
                    break

                # A bad line keeps the connection open: the "\n" bounds it - see protocol.md §8.2
                try:
                    text = line.decode("utf-8")
                except UnicodeDecodeError:
                    send_json(conn, make_error("BAD_ENCODING", "request is not valid UTF-8"))
                    continue
                try:
                    msg = json.loads(text)
                except (json.JSONDecodeError, RecursionError):
                    # RecursionError: JSON nested too deeply for Python's parser
                    send_json(conn, make_error("BAD_JSON", "request is not valid JSON"))
                    continue

                try:
                    resp = handle_request(msg, cache)
                except Exception as e:
                    # Safety net: a bug must not kill the thread or skip the response - see protocol.md §5
                    print(f"[server] internal error for {addr}: {e!r}")
                    resp = make_error("INTERNAL_ERROR", "unexpected server error")
                send_json(conn, resp)
        except OSError as e:
            # Reset or another socket failure: log and clean up, never crash - see protocol.md §8.5
            print(f"[server] socket error with {addr}: {e}")
    print(f"[server] - connection from {addr} closed")


# ======================================================================
# Accept loop (GIVEN)
# ======================================================================
def serve(host: str, port: int, cache_size: int) -> None:
    cache = LRUCache(cache_size)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(16)
        print(f"[server] listening on {host}:{port} (cache size={cache_size})")
        try:
            while True:
                conn, addr = srv.accept()
                threading.Thread(target=handle_client, args=(conn, addr, cache), daemon=True).start()
        except KeyboardInterrupt:
            # Scenario 3 in the assignment asks you to shut the server down
            # while the proxy keeps running - Ctrl+C here is enough.
            print("\n[server] shutting down")


def main() -> None:
    ap = argparse.ArgumentParser(description="EX2 JSON-over-TCP server (calc / gpt)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--cache-size", type=int, default=128)
    args = ap.parse_args()
    serve(args.host, args.port, args.cache_size)


if __name__ == "__main__":
    main()
