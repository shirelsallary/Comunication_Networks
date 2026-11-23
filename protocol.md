# EX2 Application-Layer Protocol

This document defines the protocol spoken by the client, the proxy and the server of EX2.
All three components implement it identically. Sections are numbered so that code comments
can reference them, for example `# Default cache depends on mode - see protocol.md §3.3`.

---

## §1 Overview

### §1.1 Components

```
client  <--TCP-->  proxy (default port 5554)  <--TCP-->  server (default port 5555)
```

- **Server:** evaluates `calc` requests and answers `gpt` requests. Keeps its own cache.
- **Proxy:** speaks the same protocol as the server, so a client cannot tell them apart.
  Answers repeated requests from its own cache and forwards the rest to the server.
- **Client:** sends requests and prints responses. It works the same way against the server
  or the proxy; only the port differs.

### §1.2 Message types

There are two request types, selected by the `mode` field: `calc` (evaluate an arithmetic
or logical expression) and `gpt` (answer a free-text prompt). Every request receives exactly
one response, which is either a success response or an error response (§4).

### §1.3 Robustness principle

Components are **liberal in what they accept and strict in what they send**:

- A field that is **absent** receives a documented default (§3.3).
- Variation **without meaning** is normalized: surrounding whitespace in `expr` and `prompt`
  is removed (§3.5).
- A value that is **present but invalid** is never guessed; it is rejected with `BAD_REQUEST`
  (§3.4). This covers wrong types, `null` and unknown fields.
- Responses always have the full documented shape. A component that receives responses
  ignores response fields it does not know (§4.5).

**Why:** a missing field has an obvious default, but guessing the meaning of a value that was
actually sent can silently do the opposite of what the client meant: in Python,
`bool("false")` is `True`. A rejection lets the client see the mistake immediately.

---

## §2 Transport and framing

### §2.1 Message boundaries

Each message is a single JSON object, encoded in UTF-8 and terminated by one line feed byte
(`\n`, 0x0A). Senders serialize compactly (`json.dumps` without indentation), so a message
never contains a raw line feed; line feeds inside strings are escaped as `\n` by the JSON
encoder. Requests and responses use the same framing in both directions.

**Why a delimiter is needed:** TCP provides a reliable, ordered **byte stream** without
message boundaries. The sender's TCP stack may split one `send()` into several segments or
merge several sends into one segment, and the receiver's `recv()` returns whatever bytes have
arrived. One `recv()` can therefore return part of a message, exactly one message, or one and
a half messages. The application layer must mark where each message ends.

**Why a newline:** a compact JSON encoder never emits a raw newline, so the delimiter can
never appear inside a message. Each message also appears as one readable line in Wireshark,
and the skeleton already uses this framing (`send_json`).

**Alternative considered:** a 4-byte length prefix. It is binary-safe and the receiver knows
the size in advance, but it requires changing the framing in every skeleton file and makes
captures harder to read.

### §2.2 Receiving

The receiver keeps a buffer per connection. When the buffer contains a `\n`, it returns one
complete message (without the `\n`) and keeps the remaining bytes for the next call.
Otherwise it calls `recv()` again. A partial message is normal and simply stays in the buffer.

### §2.3 Maximum message size

A message may be at most **65,536 bytes (64 KiB)**, not counting the `\n`. If the buffer
exceeds this limit before a `\n` arrives:

| Receiver | Action |
|---|---|
| Server, or proxy reading from a client | Send `MESSAGE_TOO_LARGE`, then close the connection |
| Client reading a response | Report the problem and close the connection (§8.8) |
| Proxy reading from the server | `SERVER_UNAVAILABLE` to the client (§10.5) |

**Why:** without a limit, a peer that never sends a newline makes the receiver buffer data
forever. Since the newline has not arrived, the receiver cannot know where the message ends,
so the stream is out of sync and the only safe action is to close the connection.

Delivery of `MESSAGE_TOO_LARGE` is best effort: closing a socket that still has unread
incoming data makes the OS send a TCP RST instead of a FIN, and the peer may discard the
error message before reading it.

---

## §3 Requests

### §3.1 Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `mode` | string | yes | `"calc"` or `"gpt"` |
| `data` | object | yes | The input. Its single field depends on `mode` (§3.2) |
| `options` | object | no | Processing options |
| `options.cache` | boolean | no | Whether caches may be used for this request. Default depends on `mode` (§3.3) |

No other fields are allowed at any level (§3.4).

### §3.2 `data` per mode

| `mode` | Field of `data` (required, only field) | Type | Meaning |
|---|---|---|---|
| `calc` | `expr` | string | Expression to evaluate (§6) |
| `gpt` | `prompt` | string | Text prompt (§7) |

### §3.3 Default of `options.cache`

If `options` or `options.cache` is absent, the default is **`true` for `calc`** and
**`false` for `gpt`**. An explicit value always overrides the default. Our client sends no
`options` unless the user explicitly changed the cache setting (command-line flag or menu
toggle).

**Why:** `calc` is deterministic (`1+2` is always `3`), so reusing a cached answer is always
correct. `gpt` is not deterministic, so caching it is opt-in.

### §3.4 Validation

A field is either absent or present with a value of the correct type. Anything else is
rejected with `BAD_REQUEST`:

| Case | Example |
|---|---|
| Wrong type | `"cache": "false"`, `"cache": 0`, `"data": [1]` |
| `null` for any field | `"options": null`, `"cache": null` |
| Unknown field at any level | `"extra": 5`, `"options": {"cahce": false}` |
| Field of the other mode | `{"mode": "gpt", "data": {"prompt": "x", "expr": "1"}}` |

Checks run in a fixed order; the first failing check determines the error. The server and
the proxy share the same implementation of steps 1-10:

1. Message larger than 64 KiB: `MESSAGE_TOO_LARGE` (§2.3).
2. Bytes are not valid UTF-8: `BAD_ENCODING`.
3. Text is not valid JSON: `BAD_JSON`.
4. The JSON value is not an object: `BAD_REQUEST`.
5. Unknown top-level field: `BAD_REQUEST`.
6. `mode` is missing or not a string: `BAD_REQUEST`.
7. `mode` is not `"calc"` or `"gpt"`: `UNKNOWN_MODE`.
8. `data` is missing, not an object, or does not contain exactly the mode's string field: `BAD_REQUEST`.
9. `options` is present but not an object, contains a field other than `cache`, or `cache` is not a boolean: `BAD_REQUEST`.
10. After stripping (§3.5), `expr` or `prompt` is empty: `BAD_REQUEST`.

The remaining checks belong to the server only: §6.5 for `calc`, §7 for `gpt`.

### §3.5 Whitespace and empty values

Leading and trailing whitespace is removed from `expr` and `prompt` before any other check.
The stripped value is used everywhere: for evaluation, for the text sent to the model and
for the cache key (§9.2). Whitespace inside the text is not touched. A value that is empty
after stripping is treated as missing: `BAD_REQUEST`.

**Why:** surrounding whitespace has no meaning, so removing it is not a guess. Without it,
`" 1+2"` would fail with Python's "unexpected indent" error from `ast.parse`.

### §3.6 Request examples

```json
{"mode": "calc", "data": {"expr": "sin(2+3*4)"}}
{"mode": "calc", "data": {"expr": "1 < 2 and not (3 > 4)"}, "options": {"cache": false}}
{"mode": "gpt", "data": {"prompt": "Write a short summary about computer networks"}, "options": {}}
{"mode": "gpt", "data": {"prompt": "Count to 10"}, "options": {"cache": true}}
```

---

## §4 Responses

### §4.1 Success response

```json
{"ok": true, "result": <value>, "meta": {"from_cache": false, "took_ms": 7}}
```

`result` is a JSON number or boolean for `calc` (§6.2) and a string for `gpt`. This is the
shape of the assignment's example, unchanged.

### §4.2 Error response

```json
{"ok": false, "error": {"code": "BAD_EXPR", "message": "division by zero"}, "meta": {"from_cache": false, "took_ms": 0}}
```

| Field | Type | Meaning |
|---|---|---|
| `error.code` | string | Fixed, machine-readable identifier from §5 |
| `error.message` | string | Human-readable explanation. The wording is not part of the protocol |

**Why:** a fixed code lets the proxy and the client act on the type of error without parsing
free text; the message explains the specific problem to a human.

### §4.3 `meta` in every response

Every response, success or error, contains `meta` with all of its fields, so a client never
needs to check whether `meta` exists. `took_ms` is useful in errors too, for example to show
that the proxy waited for a timeout.

### §4.4 `meta` fields

| Field | Type | Present | Meaning |
|---|---|---|---|
| `from_cache` | boolean | always | `true` if the **server** answered from its own cache. A response served from the proxy cache keeps the value it had when stored |
| `took_ms` | integer | always | Milliseconds spent by the component that **sends** this response |
| `proxy_cache` | boolean | in every response sent by the proxy | `true` if the **proxy** answered from its own cache (§10.6) |

### §4.5 Unknown fields in responses

A component that receives responses ignores response fields it does not know. This is what
allows the proxy to add `meta.proxy_cache` without breaking the client. The strict rule of
§3.4 applies to requests only.

---

## §5 Error codes

| Code | Meaning | Emitted by | Connection afterwards | Cached (§9.3) |
|---|---|---|---|---|
| `BAD_ENCODING` | The bytes are not valid UTF-8 | server, proxy | stays open | no |
| `BAD_JSON` | The text is not valid JSON | server, proxy | stays open | no |
| `BAD_REQUEST` | Valid JSON with the wrong structure or types (§3.4), or an empty value (§3.5) | server, proxy | stays open | no |
| `UNKNOWN_MODE` | `mode` is a string other than `calc` or `gpt` | server, proxy | stays open | no |
| `BAD_EXPR` | Any problem with the expression: syntax error, disallowed construct, failed evaluation, or a limit of §6.5 | server (relayed by the proxy) | stays open | **yes** |
| `GPT_ERROR` | The GPT component failed, or its answer is too large (§7) | server | stays open | no |
| `SERVER_UNAVAILABLE` | Cache miss, and the proxy could not get a valid response from the server (§10.5) | proxy | stays open | no |
| `MESSAGE_TOO_LARGE` | The received message exceeded 64 KiB (§2.3) | server, proxy | **closed** | no |
| `INTERNAL_ERROR` | Unexpected failure; a safety net so that a component never crashes | server, proxy | stays open | no |

All expression errors share one code because they are all deterministic and handled the same
way: relayed and cached (§9.3).

### §5.1 Error examples

Message texts are illustrative. A response that passes through the proxy also contains
`proxy_cache` in `meta`.

```json
{"ok": false, "error": {"code": "BAD_JSON", "message": "request is not valid JSON"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_REQUEST", "message": "unknown field 'options.cahce'"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "UNKNOWN_MODE", "message": "unknown mode 'banana'"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_EXPR", "message": "division by zero"}, "meta": {"from_cache": true, "took_ms": 0}}
{"ok": false, "error": {"code": "SERVER_UNAVAILABLE", "message": "cache miss and the server could not be reached: connection refused"}, "meta": {"from_cache": false, "took_ms": 2, "proxy_cache": false}}
{"ok": false, "error": {"code": "MESSAGE_TOO_LARGE", "message": "message exceeds 65536 bytes; closing connection"}, "meta": {"from_cache": false, "took_ms": 0}}
```

---

## §6 `calc` semantics

### §6.1 Expression language

Expressions use Python syntax and are evaluated from the parse tree (`ast`); `eval()` is
never called. Anything not listed below returns `BAD_EXPR`.

| Category | Allowed |
|---|---|
| Numbers | integer and floating-point literals |
| Constants | `pi`, `e`, `True`, `False` |
| Arithmetic | `+`, `-`, `*`, `/`, `//`, `%`, `**`, unary `-` and `+` |
| Comparisons | `<`, `<=`, `==`, `!=`, `>`, `>=`, including chains such as `1 < 2 < 3` |
| Logic | `and`, `or`, `not` |
| Functions | `sin`, `cos`, `tan`, `sqrt`, `log`, `exp`, `max`, `min`, `abs` |

### §6.2 Result types (boolean results)

A **logical result is returned as a JSON boolean** (`true` / `false`). A numeric result is
returned in the type Python computes, without conversion.

| Expression | `result` |
|---|---|
| `1+2` | `3` |
| `7/2` | `3.5` |
| `sqrt(16)` | `4.0` |
| `1 < 2` | `true` |
| `1 < 2 < 1` | `false` |
| `(1<2) + 1` | `2` |

**Why booleans:** if booleans travel as numbers, `1<2` is indistinguishable from `2-1`.
Because Python's `bool` is a subclass of `int`, the implementation must make sure a boolean
is never converted into a number on the way out.

**Why no numeric conversion:** forcing every result to `float`, as the skeleton does, loses
precision for large integers and fails on values such as `10**400`. JSON has a single number
type, so returning `3` in one case and `3.5` in another is not an inconsistency.

### §6.3 Logic

- Zero (`0`, `0.0`) is false; every other number is true.
- `and`, `or` and `not` **always return a boolean**: `1 and 2` is `true` (unlike Python,
  which returns `2`).
- `and` and `or` **short-circuit**: `0 and 1/0` is `false`, without an error.
- A chain `a < b < c` means `(a < b) and (b < c)`, with the same short-circuit:
  `1 < 0 < 1/0` is `false`.
- In arithmetic and comparisons, `True` counts as `1` and `False` as `0`, as in Python.
- Only Python spelling is accepted: `True` / `False`. `true` returns `BAD_EXPR`.

**Why:** a logical operator that returned a number would contradict §6.2, where a logical
result is `true` or `false`.

### §6.4 Order of processing

1. Strip surrounding whitespace; empty result gives `BAD_REQUEST` (§3.5).
2. Longer than 1000 characters: `BAD_EXPR`.
3. Parse; a syntax error gives `BAD_EXPR`.
4. Evaluate, with the exponentiation check of §6.5.
5. Check the final result (§6.5).

### §6.5 Limits on dangerous input and output

| Rule | Example | Result | Reason |
|---|---|---|---|
| Expression longer than 1000 characters | 1001 characters | `BAD_EXPR` | Bounds the work per request |
| Nesting too deep for the evaluator | 3000 consecutive `-` signs | `BAD_EXPR` | A caught `RecursionError` instead of a crashed thread |
| Integer power whose result would exceed 4300 digits, **checked before computing** | `9**9**9` | `BAD_EXPR` | Python would compute ~370 million digits and block the thread |
| Final integer result over 4300 digits | `10**4000 * 10**4000` | `BAD_EXPR` | Python refuses to convert such an integer to text, so `json.dumps` would fail |
| Final result not a finite real number | `1e308*10`, `(-8)**0.5` | `BAD_EXPR` | `inf`/`nan` are not valid JSON; complex numbers cannot be serialized |

Only the **final** result is checked for size and finiteness; intermediate values may exceed
the limits (`1e999 > 5` is `true`).

---

## §7 `gpt` semantics

- The prompt is stripped and must not be empty (§3.5).
- Without an API key, the server answers with the built-in stub, so the system runs without
  external services. A real model is optional; its key is read from `.env` and is never
  submitted.
- A real API call has a timeout of **20 seconds** (§8.9).
- Any failure of the GPT component returns `GPT_ERROR`.
- A response larger than 64 KiB is replaced by `GPT_ERROR` ("response too large"), so the
  server never sends a message the receiver would reject (§2.3).
- `gpt` answers are cached only when the request sets `"cache": true` (§3.3).

---

## §8 Connection behavior

### §8.1 Persistent connections

A connection carries any number of requests. Each request receives exactly one response,
in request order. A client sends its next request only after receiving the previous
response. The server and the proxy keep the connection open until the client closes it.

### §8.2 Malformed line

A line that fails steps 2-10 of §3.4 receives an error response, and the connection stays
**open**. The `\n` delimiter bounds the bad line, so the stream stays synchronized.

### §8.3 Disconnect

When `recv()` returns `b""` (the peer sent FIN):

- **Buffer empty:** a normal end of session. The receiver closes its side of the connection.
  This is how a client finishes: it closes the socket, and the server or proxy closes too.
- **Buffer holds a partial message:** the partial data is discarded, the event is logged and
  the connection is closed. No response is sent, since there is no complete request. TCP
  retransmits lost segments, so a partial message followed by FIN can never be completed.

### §8.4 Oversized message

See §2.3.

### §8.5 Socket errors

A socket error, such as a connection reset, never crashes a server or proxy thread. It is
logged and the connection is cleaned up. An unexpected exception while processing a request
is answered with `INTERNAL_ERROR`.

### §8.6 Client timeout

If a response does not arrive within 30 seconds (§8.9), the client reports it and **closes**
the connection.

**Why close:** requests carry no identifier, so the only way to match a response to its
request is order. After a timeout, the late response may still arrive and would be taken as
the answer to the next request. A new connection restores synchronization. This matches
common HTTP/1.1 client behavior.

### §8.7 Client receives a line that is not JSON

The client reports the problem and keeps the connection **open**. Unlike a timeout, the
`\n` bounds the bad line and it is the single response to the request, so the stream stays
synchronized.

### §8.8 Interactive client after the connection closes

When the interactive client finds that the connection has closed, it tells the user and asks
whether to reconnect. It never resends a request automatically, so a request is never
executed twice without the user knowing.

### §8.9 Timeouts

| Layer | Timeout |
|---|---|
| Server: real GPT API call (optional) | 20 s |
| Proxy: connecting to the server | 3 s |
| Proxy: reading the server's response | 25 s |
| Client: waiting for a response | 30 s |

Each layer gives up before the layer above it (proxy worst case 3 + 25 = 28 s < 30 s), so a
failure always reaches the client as an orderly error with the correct code. The short
connect timeout detects a stopped server quickly; the long read timeout gives a slow but
working server time to answer.

---

## §9 Caching

Both the server and the proxy have a cache, and both follow the rules below.

### §9.1 Meaning of `options.cache`

`"cache": false` means the request does not touch any cache: neither the proxy's nor the
server's cache is looked up, and the response is stored in neither.

**Why not store:** otherwise every `gpt` answer (default `false`) would be cached without
anyone asking.

### §9.2 Cache key

The key is `(mode, expr)` for `calc` and `(mode, prompt)` for `gpt`, where the text is
stripped (§3.5). Keys are computed only after validation, so a malformed request never looks
up a cache.

**`options` are not part of the key.** A request with `"cache": false` never reaches a cache
lookup (§9.1), so every request that does reach one effectively has `cache: true`; `options`
carry no information that distinguishes one cached answer from another.

| Requests | Same key? |
|---|---|
| `{"mode":"calc","data":{"expr":"1+2"}}`, the same with `"options":{}`, and with `"options":{"cache":true}` | yes |
| The same request with fields in a different order | yes |
| `" 1+2 "` and `"1+2"` | yes |
| `"1+2"` and `"1 + 2"` | **no** |

**Why inner whitespace is not removed:** the cache could return a **wrong** answer. `"1 2"` is
a syntax error, but without spaces it becomes `"12"` and would receive the cached answer of
`12`. A cache miss only costs a trip to the server; a wrong hit is much worse.

### §9.3 What is cached

Only **successes and `BAD_EXPR` errors** are cached, because their outcome is fixed
(`1/0` always fails). `GPT_ERROR`, `SERVER_UNAVAILABLE` and `INTERNAL_ERROR` are transient and
are never cached. Errors such as `BAD_JSON` and `BAD_REQUEST` fail before a key exists. The
full response is stored, so a cached error is returned exactly like a cached success.

### §9.4 Eviction: LRU

Both caches use **LRU (least recently used)** eviction, implemented with the skeleton's
`LRUCache` on an `OrderedDict` (default capacity: 128 in the server, 64 in the proxy,
`--cache-size`).

- **Lookup:** a hit moves the entry to the most-recently-used end.
- **Store:** the entry is inserted at the most-recently-used end. If the capacity is
  exceeded, the entry at the least-recently-used end is removed.
- Both operations are O(1) and protected by a lock, because client threads share the cache.

LRU keeps popular entries, unlike FIFO, which evicts an entry only because it is old.

---

## §10 Proxy behavior

### §10.1 Processing a request

```
client -> proxy: request line
  1. Validate (§3.4, steps 1-10). Invalid: answer the error itself.
  2. "cache": false?  yes: forward (step 4), do not store.
  3. Look up the key (§9.2).
       HIT : answer from the cache, proxy_cache: true. The server is not contacted.
       MISS: continue.
  4. Forward the original line to the server on a new TCP connection (§10.3).
       Failure: answer SERVER_UNAVAILABLE (§10.5).
       Success: store the response if allowed (§9.3), send it with proxy_cache: false.
```

| Situation | Server contacted? | Client receives |
|---|---|---|
| Cache hit, server up or down | no | the stored response, `proxy_cache: true` |
| Cache miss, server up | yes | the server's response, `proxy_cache: false` |
| Cache miss, server down | attempted | `SERVER_UNAVAILABLE`, `proxy_cache: false` |
| Invalid request | no | the proxy's own error response |

### §10.2 Validation in the proxy

The proxy validates every request with the same shared code as the server (§3.4, steps
1-10). Checks on the expression itself (length, syntax, evaluation) remain in the server.
This way, a malformed request receives its real error (`BAD_REQUEST`) even while the server
is down, rather than a misleading `SERVER_UNAVAILABLE`.

### §10.3 Upstream connection policy

The client-proxy connection is persistent (§8.1). For every forwarded request, the proxy
opens a **new TCP connection** to the server, sends the request, reads the response and
closes the connection.

**Why:**
- In a capture, every miss appears as a separate connection to port 5555 (SYN to FIN), and a
  hit opens no connection to the server at all. This is clear evidence that the proxy saves
  a request to the server.
- No connection state to manage: a server that was stopped and restarted works on the next
  request, and there are no dead connections to detect.
- The cost, one TCP handshake per miss, is negligible on localhost.

### §10.4 What is forwarded

The proxy forwards the client's original line, byte for byte, so the capture shows the same
payload on both legs and `"cache": false` is guaranteed to reach the server.

### §10.5 Server failures

Every failure to obtain a valid response from the server is reported as
`SERVER_UNAVAILABLE`: connection refused, connect timeout (3 s), read timeout (25 s), FIN or
reset before a response, a response larger than 64 KiB, or a response that is not JSON.
`error.message` states the exact cause.

### §10.6 Hit marker and timing

Every response sent by the proxy contains `meta.proxy_cache`: `true` when the proxy answered
from its own cache, `false` otherwise, including errors the proxy generates. The server's
`from_cache` is left unchanged, so each layer has its own flag. `took_ms` is measured by the
proxy: the lookup time on a hit, and the total time including the call to the server on a
miss.

```json
{"ok": true, "result": 4.0, "meta": {"from_cache": false, "took_ms": 3, "proxy_cache": false}}
{"ok": true, "result": 4.0, "meta": {"from_cache": false, "took_ms": 0, "proxy_cache": true}}
```

---

## §11 Fields added beyond the assignment's examples

| Field | Where | Why it is needed |
|---|---|---|
| `error` as an object `{code, message}` | error responses | A machine-readable code and a human-readable message (§4.2). The assignment gives no error example |
| `meta` in error responses | error responses | Every response has the same shape (§4.3) |
| `meta.proxy_cache` | every response sent by the proxy | Shows which layer answered from its cache (§10.6) |