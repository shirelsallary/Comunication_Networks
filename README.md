# EX2 - Application Layer Lab (Python 3.10+)

A tiny client / proxy / server system over raw TCP sockets, using a JSON
application-layer protocol **that you define** (`protocol.md`). Everything
below the socket is a byte stream; message structure, framing, error format
and caching semantics are your responsibility.

This directory is the completed project, built on the course skeleton. Every
file's docstring lists what was **given** and what was **completed**.

## Files

| File | Given | Completed / changed by us |
|------|-------|---------------------------|
| `server.py` | safe arithmetic evaluator (`ast`, no `eval`), GPT stub, request dispatch, accept loop | persistent connection + error handling, comparisons and `and/or/not` (booleans as JSON `true`/`false`), validation and error codes, input limits, optional Groq model with the stub as fallback |
| `client.py` | request builders, preset expressions, menu text, CLI parsing | `Connection.request()` / `close()` with timeout and error handling, interactive loop over one connection (asks before reconnecting), `options` sent only when chosen (`--cache` / `--no-cache`, menu toggle) |
| `proxy.py` | CLI parsing, listening socket, thread per client, shape of the per-client loop | LRU cache with counters, hit / miss / bypass logic, forwarding on a new connection per request, `SERVER_UNAVAILABLE`, `meta.proxy_cache` |
| `common.py` | - (new; `send_json` and `LRUCache` came from the skeleton) | code shared by all components: framing, request validation, cache key, error responses, `LRUCache` |
| `tests/test_smoke.py` | smoke tests for server and proxy | assertion on the proxy hit marker (`proxy_cache`) |
| `requirements.txt` | optional deps for a real GPT call, pytest | `groq` + `python-dotenv` (optional real model), pytest |
| `.example.env` | example API-key variable | `GROQ_API_KEY`; copy to `.env` only for the real model, never submit `.env` |
| `protocol.md` | - | the full protocol specification |

Code comments reference the `protocol.md` sections (§) that explain each decision.

## Quick start

```bash
pip install -r requirements.txt          # optional (real model / pytest)

# terminal 1 - server
python server.py --host 127.0.0.1 --port 5555 --cache-size 128

# terminal 2 - one-shot client, directly against the server
python client.py --host 127.0.0.1 --port 5555 --mode calc --expr "1+2*3"
python client.py --host 127.0.0.1 --port 5555 --mode gpt  --prompt "count to 10"
# --cache / --no-cache force options.cache; without them no options are sent
# and the per-mode default applies (calc: cached, gpt: not cached)

# interactive client (menu, many requests over ONE connection)
python client.py --host 127.0.0.1 --port 5555
```

### With the proxy

```bash
# terminal 3 - proxy in front of the server
python proxy.py --listen-port 5554 --server-port 5555 --cache-size 64

# the client only changes the port
python client.py --host 127.0.0.1 --port 5554 --mode calc --expr "sqrt(16)"
python client.py --host 127.0.0.1 --port 5554 --mode gpt  --prompt "count to 10" --cache
python client.py --host 127.0.0.1 --port 5554
```

How the proxy works (details in `protocol.md` §9-§10):

* It validates every request with the same code as the server (`common.py`),
  so an invalid request gets its real error even while the server is down.
* Cache key: `(mode, expr)` or `(mode, prompt)` after stripping surrounding
  whitespace; `options` are not part of the key. Eviction: LRU, capacity
  `--cache-size` (default 64).
* `"cache": false` (the default for `gpt`) bypasses the cache: forwarded, never stored.
* Hit: answered from the cache, the server is not contacted.
  Miss: forwarded on a **new TCP connection** per request (the client's original
  line), then stored if it is a success or a `BAD_EXPR` error.
* If the server cannot give a valid response (stopped, timeout, invalid reply),
  the client receives `SERVER_UNAVAILABLE`; cached requests are still answered.
* Every response from the proxy carries `meta.proxy_cache` (`true` on a hit).
  The proxy logs one line per request (`HIT` / `MISS` / `BYPASS` /
  `SERVER_UNAVAILABLE` / `invalid`) with the `hits` / `misses` / `bypassed` counters.

### Enabling a real model (Groq)

Without a key, `gpt` requests are answered by the built-in stub. To use a real
model (`openai/gpt-oss-20b` on Groq):

1. `pip install -r requirements.txt`
2. Copy `.example.env` to `.env` (in the project root) and replace the placeholder:
   `GROQ_API_KEY=<your key>` (no quotes).
3. Restart the server. Only the prompt is sent; any failure of the call
   (bad key, timeout of 20 s) returns `GPT_ERROR`.

**Never commit or submit `.env`** - it is in `.gitignore`; only `.example.env` goes in the ZIP.

If your command-line interface ends up slightly different, update this README.

## Tests

```bash
python -m pytest tests/        # or: python tests/test_smoke.py
```

All tests pass. They are a checklist, not a proof:
the assignment asks for more than they check (e.g. scenario 3, where the
server is shut down and the proxy keeps answering from its cache, must be
done by hand and captured with Wireshark).

## protocol.md - what it must contain

* The message types (`calc`, `gpt`) and every field: name, type, meaning,
  required / optional.
* **Framing**: what marks the end of a message and why one `send()` is not one
  `recv()`. The skeleton suggests one JSON object per line terminated by `\n`;
  if you choose something else, change `send_json` / `recv_line` everywhere.
* The exact shape of a success response and of an error response.
* How a **boolean** calc result is returned (`1 < 2`, `not (3 > 4)` ...).
* The proxy **cache key**: what makes two requests "the same", whether
  `options` are part of it, what `options.cache = false` means.
* The **eviction policy** of the proxy cache and how it works.
* What the client receives when the proxy has a cache miss and the server is
  down.
* Any extra fields you added and why they are needed.

## Deliverables (see the assignment PDF for the full list)

* All code (client, server, proxy), including every change to the skeleton.
* `protocol.md`.
* This README, updated to match your implementation.
* At least three `.pcapng` captures (server only / server + proxy / server shut down).
* Your Dashboard project from assignment 1, extended to version 2.
* A PDF with screenshots **and explanations**, cache hit / miss diagrams,
  capture analysis, and the main AI prompts you used.
* Never include `.env`, API keys, passwords or personal data in the ZIP.
