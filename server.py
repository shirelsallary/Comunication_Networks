# server.py
"""
EX2 - Application-layer lab: JSON-over-TCP server (student skeleton)

Run:
    python server.py --host 127.0.0.1 --port 5555 --cache-size 128

The server accepts TCP connections, reads application-layer messages
(the skeleton suggests ONE JSON object per line, terminated by "\\n"),
and answers each one with a single JSON response. Two request types must
be supported: mode="calc" and mode="gpt" (see your protocol.md).

The protocol is defined in protocol.md; comments reference its sections (§).

What is GIVEN (you may keep, change or rewrite it - just keep the requirements):
    LRUCache        - small LRU cache based on OrderedDict (server-side cache).
    safe_eval_expr  - safe ARITHMETIC evaluation using the `ast` module. No eval()!
    call_gpt        - stub that answers without any API key.
    handle_request  - validates a parsed request dict and dispatches to calc / gpt.
    serve           - accept loop, one thread per client connection.

Completed (TODO 1-4):
    recv_line / send_json  framing, in common.py (shared with the proxy) - §2
    handle_client()        persistent connection + error handling - §8
    _eval_node()           comparisons and and / or / not - §6.3
    safe_eval_expr()       results without conversion (booleans stay JSON true / false), limits - §6.2, §6.5
    handle_request()       validation, error codes, server cache - §3.4, §5, §9

Still open:
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

from common import cache_key, make_error, make_meta, recv_line, send_json, validate_request

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
# Safe expression evaluation - see protocol.md §6
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
    # `not` is a unary operator too; operator.not_ always returns a bool and treats zero as false - see protocol.md §6.3
    ast.Not: operator.not_,
}

_ALLOWED_CMP_OPS: Dict[type, Any] = {
    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq,
    ast.NotEq: operator.ne, ast.Gt: operator.gt, ast.GtE: operator.ge,
}


def _eval_node(node: ast.AST) -> Any:
    """Recursively evaluate a restricted AST node."""
    # --- numbers --------------------------------------------------------
    if isinstance(node, ast.Constant):
        # bool is a subclass of int, so True / False pass here and are returned
        # unchanged, as booleans - see protocol.md §6.3
        if isinstance(node.value, (int, float)):
            return node.value
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
        left, right = _eval_node(node.left), _eval_node(node.right)
        # Integer powers are computed exactly (9**9**9 has ~370 million digits), so
        # refuse them before computing if the result would exceed 4300 digits - see protocol.md §6.5
        if isinstance(node.op, ast.Pow) and isinstance(left, int) and isinstance(right, int) \
                and abs(left) > 1 and right > 0 and right * math.log10(abs(left)) > 4300:
            raise ValueError("result would exceed 4300 digits")
        return _ALLOWED_OPS[type(node.op)](left, right)

    # --- function calls -------------------------------------------------
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("illegal function call")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)

    # --- comparisons ----------------------------------------------------
    # `1 < 2 < 3` is ONE Compare node with ops=[Lt(), Lt()] and comparators=[2, 3].
    # A chain means (1 < 2) and (2 < 3), short-circuited like `and`: the first
    # false link returns False without evaluating the rest - see protocol.md §6.3
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left)
        for op, right_node in zip(node.ops, node.comparators):
            if type(op) not in _ALLOWED_CMP_OPS:
                raise ValueError("illegal comparison")
            right = _eval_node(right_node)
            if not _ALLOWED_CMP_OPS[type(op)](left, right):
                return False
            left = right
        return True

    # --- and / or --------------------------------------------------------
    # all() / any() over a generator short-circuit and always return a bool,
    # so `1 and 2` is True and `0 and 1/0` is False - see protocol.md §6.3
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v) for v in node.values)
        return any(_eval_node(v) for v in node.values)

    raise ValueError("illegal expression")


def safe_eval_expr(expr: str):
    """
    Parse `expr` and evaluate it safely (no eval()) - see protocol.md §6.4 for the order.
    `expr` is already stripped and non-empty (validate_request, protocol.md §3.5).

    Returns the result in the type Python computes - int, float or bool, never
    converted - so a logical result stays a JSON true / false (protocol.md §6.2).
    Raises SyntaxError, ValueError or an arithmetic error; handle_request turns
    them into BAD_EXPR.
    """
    # Bounds the work per request - see protocol.md §6.5
    if len(expr) > 1000:
        raise ValueError("expression longer than 1000 characters")
    result = _eval_node(ast.parse(expr, mode="eval").body)
    # Only the final result is checked: it must fit in valid JSON - see protocol.md §6.5
    if isinstance(result, complex) or (isinstance(result, float) and not math.isfinite(result)):
        raise ValueError("result is not a finite real number")
    if isinstance(result, int) and abs(result) >= 10 ** 4300:
        raise ValueError("result exceeds 4300 digits")
    return result


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
    Take ONE parsed request and return ONE response dict.
    Pure application logic: no sockets here, which makes it easy to test.
    Order: validate -> key -> lookup -> compute -> store (protocol.md §9.2-§9.4).
    """
    started = time.time()
    error, mode, text, use_cache = validate_request(msg)
    if error:
        error["meta"]["took_ms"] = int((time.time() - started) * 1000)
        return error

    # Computed only after validation, so a malformed request never looks up the cache - see protocol.md §9.2
    key = cache_key(mode, text)
    # cache: false means no lookup and no store - see protocol.md §9.1
    if use_cache:
        hit = cache.get(key)
        if hit is not None:
            # The stored response may be a success or a BAD_EXPR; both come back marked as hits
            return {**hit, "meta": make_meta(True, int((time.time() - started) * 1000))}

    if mode == "calc":
        try:
            resp = {"ok": True, "result": safe_eval_expr(text)}
        # RecursionError: an expression nested too deeply for the evaluator - see protocol.md §6.5
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError, RecursionError) as e:
            resp = make_error("BAD_EXPR", f"Bad expression: {e}")
    else:
        try:
            resp = {"ok": True, "result": call_gpt(text)}
        except Exception as e:
            # A GPT failure is transient, so it is returned without being cached - see protocol.md §7, §9.3
            return make_error("GPT_ERROR", f"GPT failed: {e}", int((time.time() - started) * 1000))

    resp["meta"] = make_meta(False, int((time.time() - started) * 1000))
    # The server never sends a message the receiver would reject (over 64 KiB) - see protocol.md §7
    if mode == "gpt" and len(json.dumps(resp, ensure_ascii=False).encode("utf-8")) > 65536:
        return make_error("GPT_ERROR", "response too large", resp["meta"]["took_ms"])
    # Successes and BAD_EXPR are deterministic, so both are cached as full responses - see protocol.md §9.3
    if use_cache:
        cache.set(key, resp)
    return resp


# ======================================================================
# Framing and per-connection loop
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
