# EX2 Application-Layer Protocol

This document defines the protocol spoken by the client, the proxy and the server of EX2.
All three components implement it identically. Sections are numbered so that code comments
can reference them, for example `# Default cache depends on mode - see protocol.md §3.3`.
Decision tags such as (D17) identify the design decision behind a rule.

Every decision is followed by **Why:** (the reasoning) and **Alternative considered:**
(what was rejected and why).

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

### §1.3 Robustness principle (D6)

Components are **liberal in what they accept and strict in what they send** (the robustness
principle, also known as Postel's law). "Liberal" has a precise boundary in this protocol:

- A field that is **absent** receives a documented default (§3.3).
- Variation **without meaning** is normalized: leading and trailing whitespace in `expr` and
  `prompt` is removed (§3.5).
- A value that is **present but invalid or ambiguous** is never guessed. It is rejected with
  `BAD_REQUEST` (§3.4). This covers wrong types, `null`, and unknown fields.
- A component that **receives responses** (the client, and the proxy reading from the server)
  ignores response fields it does not know (§4.5).

Responses are produced by our own code, so they always have the full documented shape.

"A consistent format across the system", as the assignment requires, means that the client,
the proxy and the server all follow this one document identically. It does not mean that
every request field must always be present.

**Why:** Requests can come from any client, so optional fields with sensible defaults avoid
forcing a client to send values it does not care about. Responses come from our own code, so
there is no reason for them to vary. The boundary exists because guessing the meaning of a
value that was actually sent can silently do the opposite of what the client intended: in
Python, `bool("false")` is `True`. Rejecting such a value lets the client discover the mistake
immediately.

**Alternative considered:** Interpreting ambiguous values leniently (for example, accepting
the string `"false"` as the boolean `false`). Rejected because a wrong guess fails silently,
while a rejection is visible.

---

## §2 Transport and framing

### §2.1 Message boundaries (D7)

Each message is a single JSON object (RFC 8259), encoded in UTF-8 and terminated by one line
feed byte (`\n`, 0x0A). Senders serialize compactly (`json.dumps` without indentation), so a
message never contains a raw line feed. Line feeds inside strings are escaped as `\n` by the
JSON encoder. Requests and responses use the same framing in both directions.

**Why:** TCP provides a reliable, ordered **byte stream** without message boundaries. The
sender's TCP stack may split one `send()` into several segments or merge several sends into
one segment, and the receiver's `recv()` returns whatever bytes have arrived. One `recv()`
can therefore return part of a message, exactly one message, or one and a half messages. The
application layer must mark where each message ends. A newline is a safe delimiter because a
compact JSON encoder never emits a raw newline inside a message. In addition, each message
appears as one readable line in Wireshark, and the skeleton already uses this framing
(`send_json`), so no change is needed across the files.

**Alternative considered:** A 4-byte length prefix before each message. It is more robust
(binary-safe, and the receiver knows the size in advance) but requires changing the framing
in every file of the skeleton and makes captures harder to read.

### §2.2 Receiving (the `recv_line` contract)

The receiver keeps a buffer per connection. It returns one complete message (without the
`\n`) as soon as the buffer contains a newline, and keeps the remaining bytes for the next
call. If no newline is buffered yet, it calls `recv()` again. A partial message while the
connection is still open is normal and simply stays in the buffer.

### §2.3 Maximum message size (D23)

A message may be at most **65,536 bytes (64 KiB)**, not counting the terminating `\n`. Every
component enforces the same limit when receiving:

| Receiver | Action when the limit is exceeded before a `\n` arrives |
|---|---|
| Server, or proxy reading from a client | Send `MESSAGE_TOO_LARGE` (§5), then close the connection |
| Client reading a response | Report the problem locally and close the connection; then §8.8 applies |
| Proxy reading from the server | Treat as a server failure: `SERVER_UNAVAILABLE` (§10.5) |

Delivery of `MESSAGE_TOO_LARGE` is **best effort**. When a socket is closed while received
data is still unread, the operating system sends a TCP RST instead of a FIN. The RST can make
the peer discard data it has received but not yet read, including the error message.

**Why:** Without a limit, a peer that sends bytes without a newline makes the receiver buffer
them forever and exhaust its memory. When the limit is reached, the newline has not arrived,
so the receiver cannot know where the oversized message ends. Synchronization with the
stream is lost, and the only safe action is to close the connection. This is the same logic
as a client timeout (§8.6), and it does not contradict §8.2: there, the newline bounds the
malformed line, so the stream stays synchronized. The dedicated code tells the client why the
connection was closed whenever the message does arrive. Guaranteed delivery is not pursued
because the case occurs only when someone deliberately sends a huge message without a
newline, never in normal use, so it does not justify extra code and a thread that waits.

**Alternatives considered:**
- Discarding bytes up to the next newline, answering with an error and keeping the connection
  open. Rejected because the receiver cannot know whether the next newline will ever arrive.
- After sending the error, calling `shutdown(SHUT_WR)` and draining the peer's data for a
  short time before closing, so that the error is more likely to be read. Rejected as not
  justified for a case that never occurs in normal use.
- No limit. Rejected because it allows a memory-exhaustion denial of service.

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

### §3.2 `data` per mode (D29)

| `mode` | Fields of `data` | Type | Meaning |
|---|---|---|---|
| `calc` | `expr` (required, only field) | string | Expression to evaluate (§6) |
| `gpt` | `prompt` (required, only field) | string | Text prompt (§7) |

### §3.3 Default of `options.cache` (D1)

If `options` or `options.cache` is absent, the default is `true` for `calc` and `false` for
`gpt`. An explicit value always overrides the default.

Our client sends no `options` at all unless the user has explicitly changed the cache setting,
with a command-line flag or the menu toggle (D48).

**Why:** `calc` is deterministic, because `1+2` is always `3`, so reusing a cached answer is
always correct. `gpt` is not deterministic: the same prompt may deserve a new answer, so
caching it is opt-in. A per-mode default means the client sends the field only to change the
default, and is never forced to send it on every request. For the same reason our client
omits the field by default: a client that always sent an explicit `cache` value would mean
that the per-mode default never actually takes effect.

**Alternatives considered:**
- A single default of `true` for both modes, as in the skeleton. Rejected because it would
  cache non-deterministic `gpt` answers without the client asking for it.
- Making `options.cache` required. Rejected because a sensible per-mode default exists.

### §3.4 Validation (D11, D12, D29)

A field is either absent or present with a value of the correct type. Anything else is
rejected:

| Case | Example | Result |
|---|---|---|
| Wrong type | `"cache": "false"`, `"cache": 0`, `"data": [1]` | `BAD_REQUEST` |
| `null` for any field | `"options": null`, `"cache": null` | `BAD_REQUEST` |
| Unknown field at any level | `"extra": 5`, `"data": {"expr": "1", "x": 1}`, `"options": {"cahce": false}` | `BAD_REQUEST` |
| Field of the other mode | `{"mode": "gpt", "data": {"prompt": "x", "expr": "1"}}` | `BAD_REQUEST` |

Checks run in a fixed order, and the first failing check determines the error. The server
and the proxy share the same implementation of steps 1-10:

1. Message larger than 64 KiB: `MESSAGE_TOO_LARGE` (§2.3).
2. Bytes are not valid UTF-8: `BAD_ENCODING`.
3. Text is not valid JSON: `BAD_JSON`.
4. The JSON value is not an object: `BAD_REQUEST`.
5. Unknown top-level field: `BAD_REQUEST`.
6. `mode` is missing or not a string: `BAD_REQUEST`.
7. `mode` is not `"calc"` or `"gpt"`: `UNKNOWN_MODE`.
8. `data` is missing or not an object, or does not contain exactly the mode's string field: `BAD_REQUEST`.
9. `options` is present but not an object, contains a field other than `cache`, or `cache` is not a boolean: `BAD_REQUEST`.
10. After removing surrounding whitespace (§3.5), `expr` or `prompt` is empty: `BAD_REQUEST`.

The remaining checks belong to the server only: §6.5 for `calc`, §7 for `gpt`.

**Why (wrong types, D11):** This refines the robustness principle (§1.3) rather than
contradicting it. The protocol is lenient when something is missing, because a missing field
gets a default. It does not guess when an ambiguous value is sent, because a wrong guess can
silently do the opposite of the client's intent: `bool("false") == True` would cache a
request whose sender asked for no caching. Rejection lets the client discover the mistake
immediately.

**Why (`null`, D12):** One rule for every optional field: it is either absent or present with
the correct type. `null` is not the correct type. This avoids a special rule for `cache` and
another for `options`, and is consistent with D11.

**Why (unknown fields, D29):** An unknown field is a field that was sent, so by the boundary
in §1.3 it is not accepted silently. A typo such as `"cahce": false` is detected immediately
instead of letting the system silently cache a request whose sender asked for no caching.
One rule applies at every level.

**Alternatives considered:**
- Interpreting known strings (`"true"`, `"false"`). Rejected as guessing a sent value.
- Python truthiness, as in the skeleton (`bool(...)`). Rejected because it reverses the intent of `"false"`.
- Treating `null` as absent. Rejected because it would add a second rule.
- Ignoring unknown fields for forward compatibility. Rejected because all components are
  under our control and are updated together, so forward compatibility has no value here.

### §3.5 Whitespace and empty values (D25, D26, D27)

Leading and trailing whitespace is removed from `expr` and `prompt` before any other check.
The stripped value is used everywhere: for evaluation, for the text sent to the model, and
for the cache key (§9.2). Whitespace inside the text is not touched. A value that is empty
after stripping is a missing value: `BAD_REQUEST`, in both modes.

| Input | Result |
|---|---|
| `"expr": " 1+2 "` | Evaluated as `1+2` |
| `"expr": ""` or `"expr": "   "` | `BAD_REQUEST` |
| `"prompt": "  hello  "` | The model receives `hello` |
| `"prompt": "   "` | `BAD_REQUEST` |

**Why:** Surrounding whitespace has no meaning in an expression or a question, so removing
it is not a guess. It is the robustness principle applied where the intent is unambiguous
(§1.3). Without it, `" 1+2"` would fail with Python's unhelpful "unexpected indent" error,
because `ast.parse` does not strip leading whitespace. Applying the same rule to `prompt`
gives one rule for both modes, and requests that differ only in surrounding whitespace share
one cache key. Treating an empty result as a missing value continues what the skeleton
already does for `""`, and prevents a whitespace-only prompt from reaching the model.

**Alternatives considered:**
- Not stripping. Rejected because valid input would fail with an error message users cannot understand.
- Stripping the prompt only for the emptiness check and sending the original text to the
  model. Rejected because it would give two rules, and two cache keys for the same question.
- `BAD_EXPR` for an empty expression and `BAD_REQUEST` for an empty prompt. Rejected in
  favor of one rule for both modes.

### §3.6 Request examples

```json
{"mode": "calc", "data": {"expr": "sin(2+3*4)"}}
{"mode": "calc", "data": {"expr": "1 < 2 and not (3 > 4)"}, "options": {"cache": false}}
{"mode": "gpt", "data": {"prompt": "Write a short summary about computer networks"}, "options": {}}
{"mode": "gpt", "data": {"prompt": "Count to 10"}, "options": {"cache": true}}
```

---

## §4 Responses

### §4.1 Success response (D3)

```json
{"ok": true, "result": <value>, "meta": {"from_cache": false, "took_ms": 7}}
```

`result` is a JSON number or boolean for `calc` (§6.2) and a string for `gpt`.

**Why:** Compatibility. This is the shape of the assignment's example, and the skeleton
(`handle_request`) and the provided tests already rely on it. There is no reason to change a
shape that works.

**Alternative considered:** None. The example shape was adopted as is.

### §4.2 Error response (D4)

```json
{"ok": false, "error": {"code": "BAD_EXPR", "message": "division by zero"}, "meta": {"from_cache": false, "took_ms": 0}}
```

| Field | Type | Meaning |
|---|---|---|
| `error.code` | string | Fixed, machine-readable identifier from §5 |
| `error.message` | string | Human-readable explanation of what happened. The wording is not part of the protocol |

**Why:** A fixed code lets the proxy and the client act on the type of an error without
parsing free text. The message explains the specific problem to a human.

**Alternative considered:** A plain error string, as in the skeleton (`"error": "<text>"`).
Rejected because a program would have to parse the text to know what kind of error occurred.

### §4.3 `meta` in every response (D5)

Every response, success or error, contains `meta` with all of its fields. In an error that
did not come from a cache, `from_cache` is `false`.

**Why:** Consistency: a client never needs to check whether `meta` exists. A shorter error
message brings no real benefit. `took_ms` is useful in errors too, for example to show that
the proxy waited for a timeout. `from_cache: false` in an error is simply true when the error
did not come from a cache, and it becomes fully meaningful because deterministic errors can
be cached (§9.3).

**Alternatives considered:**
- Omitting `meta` from errors. Rejected for consistency.
- Including only `took_ms` in error responses. Rejected because the shape of `meta` would
  then depend on the type of response.

### §4.4 `meta` fields

| Field | Type | Present | Meaning |
|---|---|---|---|
| `from_cache` | boolean | always | `true` if the **server** answered from its own cache. In a response served from the proxy cache, it keeps the value from when the response was stored |
| `took_ms` | integer | always | Milliseconds spent by the component that **sends** this response (§10.6) |
| `proxy_cache` | boolean | in every response sent by the proxy | `true` if the **proxy** answered from its own cache, `false` otherwise, including errors the proxy generates (§10.6) |

### §4.5 Unknown fields in responses (D32)

A component that receives responses ignores response fields it does not know. The strict
rule of §3.4 applies to requests only.

**Why:** This is the robustness principle (§1.3) from the receiving side: the client receives
responses, so it is liberal in what it accepts. It is what allows the proxy to add
`meta.proxy_cache` without breaking a client that does not know the field.

**Alternative considered:** Rejecting unknown response fields. Rejected because it would
break the client as soon as the proxy adds its hit marker.

---

## §5 Error codes (D8)

| Code | Meaning | Emitted by | Connection afterwards | Cached (§9.3) |
|---|---|---|---|---|
| `BAD_ENCODING` | The bytes are not valid UTF-8; decoding failed before JSON parsing | server, proxy | stays open | no |
| `BAD_JSON` | The text is not valid JSON | server, proxy | stays open | no |
| `BAD_REQUEST` | Valid JSON with the wrong structure or types (§3.4), or an empty value (§3.5) | server, proxy | stays open | no |
| `UNKNOWN_MODE` | `mode` is a string other than `calc` or `gpt` | server, proxy | stays open | no |
| `BAD_EXPR` | Any problem with the expression: syntax error, disallowed construct, failed evaluation, or a limit of §6.5 | server (relayed and cached by the proxy) | stays open | **yes** |
| `GPT_ERROR` | The GPT component failed, or its answer is too large to send (§7) | server | stays open | no |
| `SERVER_UNAVAILABLE` | The proxy had a cache miss and could not obtain a valid response from the server (§10.5) | proxy | stays open | no |
| `MESSAGE_TOO_LARGE` | The received message exceeded 64 KiB (§2.3) | server, proxy | **closed** (best effort delivery) | no |
| `INTERNAL_ERROR` | Unexpected failure; a safety net so that a component never crashes | server, proxy | stays open | no |

**Why one code for all expression errors:** Syntax errors, disallowed constructs and
evaluation failures (`1/0`, `sqrt(-1)`, `sin(1, 2)`) are all deterministic and are handled
identically by the proxy: they are relayed and cached (§9.3). Splitting them would require
extra work (a custom exception class) without real benefit.

**Why a separate `BAD_ENCODING`:** Decoding fails at a different stage (bytes to text) than
JSON parsing (text to object), and the distinction costs only one extra `except` clause.

**Alternatives considered:**
- Separate codes for syntax and evaluation errors. Rejected because they are treated identically.
- Folding encoding errors into `BAD_JSON`. Rejected because the two failures happen at different stages.

### §5.1 Error examples

These examples show responses from the server. A response that passes through the proxy also
contains `"proxy_cache"` in `meta` (§4.4). Message texts are illustrative only.

```json
{"ok": false, "error": {"code": "BAD_ENCODING", "message": "request is not valid UTF-8"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_JSON", "message": "request is not valid JSON"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_REQUEST", "message": "'options.cache' must be a boolean"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_REQUEST", "message": "unknown field 'options.cahce'"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "UNKNOWN_MODE", "message": "unknown mode 'banana'"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_EXPR", "message": "division by zero"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "BAD_EXPR", "message": "division by zero"}, "meta": {"from_cache": true, "took_ms": 0}}
{"ok": false, "error": {"code": "GPT_ERROR", "message": "response too large"}, "meta": {"from_cache": false, "took_ms": 15}}
{"ok": false, "error": {"code": "SERVER_UNAVAILABLE", "message": "cache miss and the server could not be reached: connection refused"}, "meta": {"from_cache": false, "took_ms": 2004, "proxy_cache": false}}
{"ok": false, "error": {"code": "MESSAGE_TOO_LARGE", "message": "message exceeds 65536 bytes; closing connection"}, "meta": {"from_cache": false, "took_ms": 0}}
{"ok": false, "error": {"code": "INTERNAL_ERROR", "message": "unexpected server error"}, "meta": {"from_cache": false, "took_ms": 1}}
```

---

## §6 `calc` semantics

### §6.1 Expression language

Expressions use Python syntax and are evaluated from the parse tree (`ast`). `eval()` is
never called. Anything not listed below is a disallowed construct and returns `BAD_EXPR`.

| Category | Allowed |
|---|---|
| Numbers | integer and floating-point literals |
| Constants | `pi`, `e`, `True`, `False` |
| Arithmetic | `+`, `-`, `*`, `/`, `//`, `%`, `**`, unary `-` and `+` |
| Comparisons | `<`, `<=`, `==`, `!=`, `>`, `>=`, including chains such as `1 < 2 < 3` |
| Logic | `and`, `or`, `not` |
| Functions | `sin`, `cos`, `tan`, `sqrt`, `log`, `exp`, `max`, `min`, `abs` |

### §6.2 Result types (D16, D17)

A logical result is returned as a JSON boolean (`true` or `false`). A numeric result is
returned in the type Python computes, without conversion.

| Expression | `result` |
|---|---|
| `1+2` | `3` |
| `7/2` | `3.5` |
| `sqrt(16)` | `4.0` |
| `1 < 2` | `true` |
| `1 < 2 < 1` | `false` |
| `max(1<2, 0)` | `true` |
| `(1<2) + 1` | `2` |

**Why (booleans, D16):** If booleans travel as numbers, `1<2` is indistinguishable from
`2-1`. Distinguishing a logical result from a numeric one is the reason the skeleton's TODO
exists. Because Python's `bool` is a subclass of `int`, the implementation must take care
that a boolean is never converted into a number on the way out.

**Why (no numeric conversion, D17):** Forcing every result to `float`, as the skeleton does,
loses precision for large integers and even fails calculations that succeeded: `10**400`
cannot be converted to `float`. JSON has a single number type, so returning `3` for one
expression and `3.5` for another creates no inconsistency in the protocol. Returning what
Python computes also explains `max(1<2, 0)`: the maximum of true and 0 is true. Size limits
are defined in §6.5.

**Alternatives considered:**
- Booleans as `1.0` and `0.0`, the skeleton's behavior. Rejected because logical and numeric
  results become indistinguishable.
- Always converting numbers to `float`. Rejected because of lost precision and failed results.
- Converting boolean arguments of functions to numbers, so that `max(1<2, 0)` gives `1`.
  Rejected as a conversion that contradicts D17.

### §6.3 Logic (D18, D19)

- Zero (`0`, `0.0`) is false. Every other number is true.
- `and` and `or` **short-circuit**, and **always return a boolean**: `1 and 2` is `true`, and
  `0 and 1/0` is `false` without an error.
- `not` returns a boolean.
- A chained comparison `a < b < c` means `(a < b) and (b < c)`, with the same short-circuit:
  `1 < 0 < 1/0` is `false` without an error.
- In arithmetic and in comparisons, `True` counts as `1` and `False` as `0`, as in Python.
  For example, `(1<2) + 1` is `2` and `(1<2) == 1` is `true`.
- The literals `True` and `False` are allowed in Python spelling only. `true` and `false`
  return `BAD_EXPR` with a clear message.

**Why (D18):** A logical operator that returns a number (`1 and 2` returning `2`, as in
Python) is confusing and contradicts §6.2, where a logical result is `true` or `false`.
Treating zero as false does not contradict the no-guessing rule of §1.3: "zero is false" is
a uniform, unambiguous convention in almost every language, not a guess about an unclear
value. Short-circuit evaluation behaves as in every programming language, so that
`0 and 1/0` returns `false` instead of an error. Chains short-circuit too, because the
skeleton defines a chain as a conjunction of comparisons. Counting booleans as 1 and 0 gives
one rule for arithmetic and comparisons.

**Why (D19):** Expressions are written in Python syntax (`sqrt`, `**`), so Python's spelling
of the literals is natural. Accepting two spellings for the same value would add complexity
without benefit.

**Alternatives considered:**
- Full Python semantics, where `and` and `or` return an operand. Rejected because logical
  operators would return numbers.
- A strict mode where operands must be booleans. Rejected in favor of the uniform
  zero-is-false convention.
- Rejecting the literals `True` and `False`. Rejected because Python syntax is natural here.
- Accepting both `True` and `true`. Rejected because two spellings add complexity.

### §6.4 Order of processing

1. Strip surrounding whitespace. If the result is empty: `BAD_REQUEST` (§3.5).
2. Longer than 1000 characters: `BAD_EXPR` (§6.5).
3. Parse the expression; a syntax error gives `BAD_EXPR`.
4. Evaluate, with the exponentiation check of §6.5 applied during evaluation.
5. Check the final result (§6.5).

### §6.5 Limits on dangerous input and output (D20, D21, D22, D24)

| Rule | Example | Result |
|---|---|---|
| Expression longer than 1000 characters (after stripping) | 1001 characters | `BAD_EXPR` |
| Nesting too deep for the evaluator | 3000 consecutive unary minus signs | `BAD_EXPR` (a caught `RecursionError`) |
| Integer exponentiation whose estimated result exceeds 4300 digits, **checked before computing** | `9**9**9` | `BAD_EXPR` |
| Final integer result with more than 4300 digits | `10**4000 * 10**4000` | `BAD_EXPR` |
| Final result is not a finite real number | `1e308*10` (inf), `1e999 - 1e999` (nan), `(-8)**0.5` (complex) | `BAD_EXPR` |

The 4300-digit limit is enforced in two places: on every integer exponentiation (before
computing) and on the final result. Intermediate products may exceed it, so
`10**4000 * 10**4000 // 10**4000` succeeds because its final result has 4001 digits. This is
consistent with the rule that intermediate values are allowed. The number of multiplications
is bounded anyway by the 1000-character limit. Intermediate infinite values are allowed:
`1e999` is accepted as input, and `1e999 > 5` is `true`. Only a non-finite **result** is
rejected.

**Why (exponentiation check, D20):** Python computes `9**9**9` exactly, a number of roughly
370 million digits. It does not fail; it blocks the thread and consumes a large amount of
memory. Estimating the size of the result before computing is cheap and immediate, and it
gives the same outcome on every run, which matters for caching (§9).

**Why (final digits, D21):** Python 3.10 refuses to convert an integer of more than 4300
digits to text, so `json.dumps` would fail in `send_json`, outside any error handling. The
thread would die without answering. Checking the result before sending turns Python's
built-in limit into a documented limit of the protocol. The limit is not raised, because it
exists as a defense against CVE-2020-10735, a denial of service through slow integer-to-text
conversion. Raising it would mean disabling a security protection.

**Why (finite real result, D22):** "Strict in what you send" (§1.3) applies to the response,
so the check is made on the final result. `json.dumps` writes `inf` and `nan` as `Infinity`
and `NaN`, which are not valid JSON, and it cannot serialize a complex number at all.
Checking only the final result keeps every response valid JSON while letting mathematically
valid expressions pass.

**Why (length and recursion, D24):** The length limit is explicit and documented. Catching
`RecursionError` is a safety net, because even an expression shorter than 1000 characters can
be nested deeply enough to exhaust the recursion of the evaluator.

**Alternatives considered:**
- A time limit on evaluation. Rejected because Python cannot kill a thread, and the outcome
  would depend on machine load.
- Computing large powers as `float`. Rejected because it contradicts D17.
- Raising Python's digit limit. Rejected because it disables a security fix.
- Rejecting infinite values at every intermediate step. Rejected because the check belongs to
  the response, and valid expressions such as `1/1e999` would fail.
- Using only one of the length limit and the recursion check. Rejected because each covers a
  case the other misses.

---

## §7 `gpt` semantics

- The prompt is stripped of surrounding whitespace and must not be empty (§3.5).
- Without an API key, the server answers with a built-in stub, so the system runs without
  external services. A real model call is optional. Its key is read from `.env` and is never
  committed or submitted.
- If a real model is used, the API call has a timeout of **20 seconds** (§8.9).
- Any failure of the GPT component returns `GPT_ERROR`.
- Before sending, the server checks the size of the encoded response. A response larger than
  64 KiB is replaced by `GPT_ERROR` with the message "response too large".
- `gpt` answers are cached only when the request sets `"cache": true` (§3.3, §9.3).

**Why (size check, D46):** "Strict in what you send" (§1.3): the server never sends a message
that the receiver would reject (§2.3). The client receives an orderly, accurate error instead
of a misleading `SERVER_UNAVAILABLE` or a closed connection.

**Alternative considered:** Not checking in the server and leaving the receiver to handle an
oversized response. Rejected because the client would see a misleading failure.

**Why (20-second API timeout, D47):** Each layer finishes before the layer above it (§8.9),
so every failure reaches the client as an orderly error with the correct code: `GPT_ERROR`
from the server rather than `SERVER_UNAVAILABLE` from the proxy.

**Alternative considered:** No API timeout, or one of 25 seconds or more. Rejected because a
slow model call would then appear to the client as `SERVER_UNAVAILABLE`.

---

## §8 Connection behavior

### §8.1 Persistent connections

A connection carries any number of requests. Each complete request receives exactly one
response, and responses are sent in request order. A client sends its next request only
after it has received the response to the previous one. The server and the proxy keep a
connection open until the client closes it.

### §8.2 Malformed line (D9)

A line that fails steps 2-10 of §3.4 receives an error response, and the connection stays
**open**.

**Why:** Mistakes happen, and there is no reason to drop the connection over one bad
message. The `\n` delimiter bounds the bad line, so it does not corrupt the messages that
follow it.

**Alternative considered:** Closing the connection after a malformed message. Rejected
because the stream is still synchronized.

### §8.3 Disconnect in the middle of a message (D10)

If the peer closes the connection (`recv()` returns `b""`) while the buffer holds a partial
message, the partial data is discarded, the event is logged, and the connection is closed.
No response is sent.

**Why:** TCP is reliable and retransmits lost segments below the application, so a lost
packet never appears as a gap in the stream. A partial message followed by end-of-file means
the peer has finished sending. The FIN says that no more bytes will arrive (the peer may
still be able to receive, after a half-close), so the partial message can never be completed.
There is no complete request, and therefore no obligation to respond under the
one-response-per-request rule.

**Alternative considered:** Answering the partial data with an error. Rejected because there
is no complete request to answer.

### §8.4 Oversized message

See §2.3: the receiver sends `MESSAGE_TOO_LARGE` (best effort) and closes the connection.

### §8.5 Socket errors

A socket error such as a connection reset never crashes a server or proxy thread. It is
logged, and the connection is cleaned up. An unexpected exception while processing a request
is answered with `INTERNAL_ERROR` (§5).

### §8.6 Client timeout (D13)

If a response does not arrive within the client's timeout (30 seconds, §8.9), the client
reports it to the user and **closes** the connection.

**Why:** A timeout is not a user mistake, unlike a malformed message (§8.2). It is a loss of
synchronization. The response to the previous request may still be on its way, and without a
request identifier there is no safe way to know which request a later response belongs to.
The client therefore closes the connection and continues on a clean one. This matches common
practice in request-response protocols of the same family, which answer requests in order and
without identifiers, such as HTTP/1.1 and Redis: a connection that had a timeout is
discarded. Because the proxy's timeouts are shorter than the client's (§8.9), a slow or
stopped server produces an orderly `SERVER_UNAVAILABLE`, and a client timeout happens only
when something is truly broken. Thanks to §8.8, the user can continue immediately.

**Alternatives considered:**
- **A request identifier (`id`) field**, as in HTTP/2, DNS and JSON-RPC. An identifier is
  needed when the order of arrival does not identify the response: concurrent requests on one
  connection (HTTP/2, JSON-RPC), or a transport that does not preserve order (DNS over UDP).
  Here TCP preserves order and there is never more than one outstanding request. The field
  would also require changes in every file and in the cache key.
- **Keeping the connection open and discarding the late response by counting.** Rejected as
  fragile: one counting mistake shifts every later response. Counting also assumes that the
  late response will eventually arrive. If the server hung or crashed while processing the
  request, it never will. The client would wait to discard a response that does not exist,
  and would discard the real response to its next request instead.

### §8.7 Client receives a line that is not JSON (D14)

The client reports the problem and keeps the connection **open**.

**Why:** This mirrors §8.2. The `\n` delimiter bounds the bad line, and that line is itself
the single response to the request, so synchronization is preserved. This is exactly the
difference from a timeout.

**Alternative considered:** Closing the connection. Rejected because synchronization is intact.

### §8.8 Interactive client after the connection closes (D15)

When the interactive client finds that the connection has closed (including after §2.3 or
§8.6), it tells the user and asks whether to reconnect (yes or no). It never resends a
request automatically; the user sends it again if they want.

**Why:** The user continues without restarting the client, as the assignment requires
(section 4). There is no risk of executing a request twice, which matters for `gpt`. The
failure stays visible to the user and in captures.

**Alternatives considered:**
- Exiting. Rejected because the user would have to restart the client.
- Reconnecting and resending automatically. Rejected because a request the server already
  processed could run twice, and the failure would be hidden.

### §8.9 Timeouts (D38, D47)

| Layer | Timeout |
|---|---|
| Server: real GPT API call (optional) | 20 s |
| Proxy: connecting to the server | 3 s |
| Proxy: reading the server's response | 25 s |
| Client: waiting for a response | 30 s |

Each layer gives up before the layer above it. The proxy's worst case (3 + 25 = 28 s) is
below the client's 30 s.

**Why (D38):** A stopped server is detected quickly because the connection attempt itself
fails, which matters for scenario 3. A server that is alive but slow, such as a real GPT
call, gets enough time to answer. Because the proxy gives up before the client does, the
client always receives an orderly `SERVER_UNAVAILABLE` before its own timeout expires (§8.6).

**Alternatives considered:**
- One short timeout for both connecting and reading (5 s). Rejected because a slow but
  working server would be reported as unavailable.
- One long timeout for both (25 s). Rejected because a stopped server would be detected slowly.

---

## §9 Caching

Both the server and the proxy have a cache. They follow the same rules.

### §9.1 Meaning of `options.cache` (D2)

`"cache": false` means that the request does not touch any cache: neither the proxy's nor
the server's cache is looked up, and the response is stored in neither.

**Why:** `false` means "I want a fresh answer end to end", not only "skip the proxy". Not
storing the response keeps the meaning simple, "this request does not touch the cache at
all", and is required by §3.3. If a bypassing request stored its answer, every `gpt` answer
(whose default is `false`) would be cached without anyone asking, contradicting the opt-in
rule for `gpt`.

**Alternatives considered:**
- `false` bypassing only the proxy cache. Rejected because the client asked for a fresh answer end to end.
- `false` skipping the lookup but storing the new answer (a refresh). Rejected because it
  would cache `gpt` answers by default.

### §9.2 Cache key (D28, D30, D31, D33)

The key is built explicitly from the extracted fields: `(mode, expr)` for `calc` and
`(mode, prompt)` for `gpt`, where the text has its surrounding whitespace removed (§3.5).
`options` are not part of the key. The server and the proxy use the same definition. Keys
are computed only **after** validation and normalization, so a malformed request never looks
up a cache.

| Requests | Same key? |
|---|---|
| `{"mode":"calc","data":{"expr":"1+2"}}`, the same with `"options":{}`, and with `"options":{"cache":true}` | yes |
| The same request with fields in a different order | yes |
| `" 1+2 "` and `"1+2"` | yes |
| `"1+2"` and `"1 + 2"` | **no** |

If a future option changes the result of a request, it must be added to the key.

**Why (no `options`, D28):** Under §9.1, `"cache": false` bypasses the cache completely, so
every request that reaches a cache lookup effectively has `cache: true`. `options` then carry
no information that distinguishes one cached answer from another. Excluding them gives
requests with identical meaning a single key.

**Why (explicit construction, D30):** After D28 and D29 the key must contain exactly the mode
and the input text. Building it explicitly from those fields states this clearly, and field
order cannot matter by construction.

**Why (exact text, D31):** The only cost of a miss is efficiency: the answer is still
correct, it simply comes from the server.

**Why (same key in the server, D33):** One documented definition of "the same request" in
both layers. Keeping the whole message as the server's key would contradict D28, and a
malformed request should not look up a cache.

**Alternatives considered:**
- The whole message, including `options`, as the key (the skeleton's server behavior).
  Rejected because identical requests would get different keys.
- Canonical JSON with sorted keys. Rejected because explicit construction is clearer.
- Removing all whitespace from the text. Rejected because the cache could return a **wrong**
  answer: `"1 2"` is a syntax error, but without spaces it becomes `"12"` and would receive
  the cached answer of `12`. A cache that returns a wrong answer is much worse than a cache
  that misses.
- Normalizing by the parse tree (AST). Rejected because the proxy is a protocol-level
  intermediary and should not know the semantics of `calc`. It would mix layers and require
  maintaining the same rules in two places.

### §9.3 What is cached (D34)

Only responses to valid requests whose outcome is fixed are cached: **successes and
`BAD_EXPR` errors**. `GPT_ERROR`, `SERVER_UNAVAILABLE` and `INTERNAL_ERROR` are never cached.
The full response is stored, so a cached error can be returned exactly like a cached success.

**Why:** `BAD_EXPR` is the only error that comes from a structurally valid request, so it has
a cache key, and it is deterministic: `1/0` always fails. Errors such as `BAD_REQUEST` and
`BAD_JSON` fail before a key can be built. A transient error that was cached would keep being
returned after the problem had been fixed. Caching deterministic errors gives concrete meaning
to the single expression error code (§5) and to `from_cache` in an error (§4.3). In scenario
3, an invalid expression that was already asked is answered from the proxy cache even while
the server is down.

**Alternative considered:** Never caching errors. It is simpler, but an invalid expression
would be sent to the server every time, and `from_cache` in an error would always be `false`.

### §9.4 Server cache

The server keeps its cache in the skeleton's `LRUCache` (default capacity 128,
`--cache-size`). Processing order: validate (§3.4), normalize (§3.5), build the key (§9.2),
look up, compute on a miss, store if allowed (§9.1, §9.3).

---

## §10 Proxy behavior

### §10.1 Processing a request

```
client -> proxy: request line
  1. Validate the structure (§3.4, steps 1-10). Invalid: answer the error itself.
  2. "cache": false?   yes: forward (step 4); count as bypassed; do not store
  3. Look up the key (§9.2).
       HIT : answer from the cache, with proxy_cache: true. The server is not contacted.
       MISS: continue.
  4. Forward the original line to the server on a new TCP connection (§10.3, §10.4).
       Failure: answer SERVER_UNAVAILABLE (§10.5).
       Success: store the response if allowed (§9.3), then send it with proxy_cache: false.
```

| Situation | Server contacted? | Client receives |
|---|---|---|
| Cache hit, server up or down | no | the stored response, `proxy_cache: true` |
| Cache miss, server up | yes | the server's response, `proxy_cache: false` |
| Cache miss, server down | attempted | `SERVER_UNAVAILABLE`, `proxy_cache: false` |
| Invalid request | no | the proxy's own error response |

### §10.2 Validation in the proxy (D40)

The proxy validates the structure of every request itself, with the same shared code as the
server (§3.4, steps 1-10), and answers errors in exactly the same format. Only structurally
valid requests are forwarded. Checks on the expression itself (length, syntax, evaluation)
remain in the server.

**Why:** This does not contradict D31. The structure of a request is the protocol itself, and
an application-layer proxy must understand it, just as an HTTP proxy reads HTTP headers. The
semantics of `calc`, meaning which expressions are valid and what they evaluate to, stay in
the server. When the server is down, the client receives the real error (`BAD_REQUEST`)
rather than a misleading `SERVER_UNAVAILABLE`. Key extraction (§9.2) is safe, and a malformed
request never reaches the server.

**Alternatives considered:**
- Validating only what the key needs and forwarding everything else. Rejected because a
  malformed request would receive `SERVER_UNAVAILABLE` while the server is down.
- Answering only encoding and JSON errors and forwarding structurally invalid JSON. Rejected
  for the same reason.

### §10.3 Upstream connection policy (D37)

For every forwarded request, the proxy opens a **new TCP connection** to the server, sends
the request, reads the response and closes the connection. The connection between the client
and the proxy stays persistent (§8.1).

**Why:**
- **Proof in the capture:** in a capture, every miss appears as a separate connection to port
  5555 (SYN through FIN), and a hit opens no connection to the server at all. This is
  unambiguous proof in scenario 2 that the proxy saves a request to the server.
- **No state to manage:** a server that went down and came back works on the next request,
  which matters for scenario 3, and there are no dead connections to detect.
- **No double execution:** a `gpt` request is never executed twice (as in §8.8).
- **Permitted by the assignment:** the assignment states explicitly that the client-proxy
  connection does not have to behave like the proxy-server connection.
- **Cost:** a TCP handshake per miss, which is negligible on localhost.

**Alternatives considered:**
- One persistent upstream connection per client. Rejected because it requires detecting dead
  connections, and recovery could execute a request twice.
- One upstream connection shared by all clients. Rejected because it needs locking and
  causes head-of-line blocking.

### §10.4 What is forwarded (D43)

The proxy forwards the client's original line, byte for byte, after it has passed the
validation of §10.2.

**Why:** Transparency. The capture shows the same payload on the client-proxy leg and on the
proxy-server leg, which makes the comparison easy. `"cache": false` is guaranteed to reach
the server (§9.1), and the proxy does not change the client's data. Normalizing a second time
in the server is harmless.

**Alternatives considered:**
- Re-encoding the parsed object. Rejected because the bytes could differ from the client's.
- Sending a normalized request. Rejected because the proxy would change the client's data.

### §10.5 Server failures (D39, D44)

Every failure to obtain a valid response from the server is reported to the client as
`SERVER_UNAVAILABLE`: connection refused, connect timeout (3 s), read timeout (25 s),
end-of-file or reset before a response, a response larger than 64 KiB, or a response that is
not JSON. `error.message` states the exact cause. These responses are never cached (§9.3).

Internally, `forward_to_server` keeps the skeleton's parameters and returns a pair:
`(response, None)` on success and `(None, "<reason>")` on failure.

**Why (D39):** The `code` + `message` structure (§4.2) carries the exact diagnosis in
`message` without adding an error code that, in practice, would occur only if the server had
a bug. The client needs to know one thing: no valid response was obtained from the server.

**Why (D44):** A returned pair is explicit and simple. It allows the detailed message of D39
without exceptions that callers must remember to catch.

**Alternatives considered:**
- A separate code for a server that answered with a malformed response. Rejected because the
  message already gives the exact cause.
- Raising a dedicated exception on failure. Rejected because callers must remember to catch it.
- Returning `None` as in the skeleton. Rejected because the reason for the failure would be lost.

### §10.6 Hit marker and timing (D41, D42)

Every response sent by the proxy contains `meta.proxy_cache`: `true` when the proxy answered
from its own cache, `false` otherwise, including errors the proxy generates. The server's
`from_cache` is left unchanged. `took_ms` is the time measured by the proxy: the lookup time
on a hit, and the total time in the proxy, including the call to the server, on a miss.

```json
{"ok": true, "result": 4.0, "meta": {"from_cache": false, "took_ms": 3, "proxy_cache": false}}
{"ok": true, "result": 4.0, "meta": {"from_cache": false, "took_ms": 0, "proxy_cache": true}}
```

**Why (D41):** Each layer has its own flag: `from_cache` says whether the server answered
from its cache, and `proxy_cache` says whether the proxy did. In scenario 2 the explanation
is clear-cut: `proxy_cache: true` on the repeated request, and no connection to the server in
the capture. The field does not break the client (§4.5). Including it in every proxy
response, not only in hits, keeps the shape consistent (as in §4.3).

**Why (D42):** `took_ms` describes this response, not an old computation. The difference
between a hit (close to 0) and a miss is further evidence for the report.

**Alternatives considered:**
- Setting `from_cache` to `true` on a proxy hit. Rejected because it loses which cache answered.
- Turning `from_cache` into a string (`"none"`, `"server"`, `"proxy"`). Rejected because it
  changes the field's type, contradicts §4.1, and breaks the existing test.
- Keeping the server's original `took_ms`. Rejected because on a hit it describes a past computation.

### §10.7 Eviction policy and counters (D35, D36)

The proxy cache uses **LRU (least recently used)** eviction, reusing the skeleton's
`LRUCache` (default capacity 64, `--cache-size`).

- **Lookup (`get`):** a hit moves the entry to the most-recently-used end of an `OrderedDict`.
- **Store (`set`):** the entry is inserted at the most-recently-used end. If the capacity is
  exceeded, the entry at the least-recently-used end is removed.
- Both operations are O(1) and protected by a lock, because client threads share the cache.

The proxy counts `hits`, `misses` and `bypassed` (requests with `"cache": false`) and prints
them. The counters are internal; they are not part of the protocol.

**Why (D35):** LRU is a standard policy. It is O(1) with an `OrderedDict`, keeps popular
entries, and is easy to explain and to draw. The skeleton already provides a thread-safe
implementation. Cache pollution by one-time scans is not relevant at the scale of this
assignment.

**Why (D36):** A request that never looked up the cache is not a miss. A separate counter
keeps the hit ratio in the report accurate and the numbers easy to explain.

**Alternatives considered:**
- FIFO. Rejected because it evicts a popular entry only because it is old.
- LFU. Rejected because it is more complex, and an entry that was popular in the past stays forever.
- Counting a bypass as a miss. Rejected because it distorts the hit ratio.

---

## §11 Fields added beyond the assignment's examples

| Field | Where | Why it is needed |
|---|---|---|
| `error` as an object `{code, message}` | error responses | A machine-readable code and a human-readable message (§4.2). The assignment gives no error example |
| `meta` in error responses | error responses | Consistency: every response has the same shape (§4.3) |
| `meta.proxy_cache` | every response sent by the proxy | Shows which layer answered from its cache (§10.6) |

---

## §12 Skeleton changes required by this protocol

Line numbers refer to the tag `skeleton-original`. No code has been changed yet.

### server.py

| Lines | Now | Required | § |
|---|---|---|---|
| 100 | `not` is missing | `ast.Not` returning a boolean; zero is false | 6.3 |
| 106-108 | Comparison table is empty | The six comparison operators | 6.1 |
| 114-119 | `True` passes the `int` check and becomes `1.0` | Recognize `bool` explicitly, before `int`, and keep it a boolean | 6.2, 6.3 |
| 131-132 | Integer exponentiation is unbounded | Estimate the result size first; over 4300 digits gives `BAD_EXPR` | 6.5 |
| 141-147 | `Compare` raises `NotImplementedError` | Evaluate comparisons, including chains, with short-circuit | 6.3 |
| 149-155 | `BoolOp` raises `NotImplementedError` | Short-circuit `and` / `or` that return a boolean | 6.3 |
| 175-176 | `float(...)` on every result; no length or result checks | No conversion; length check before parsing; result checks (digits, finite, real) | 6.2, 6.4, 6.5 |
| 182-191 | Stub only | Optional real call: key from `.env`, 20 s timeout, failure gives `GPT_ERROR`, stub as fallback | 7 |
| 197-199 | `make_error` returns `{"ok": False, "error": "<text>"}` | `error: {code, message}` plus `meta` | 4.2, 4.3 |
| 207-213 | No structural validation; `or {}` hides `null` and empty values; non-object `data` / `options` crash; `bool(...)` on `cache`; default `True` for both modes | Validation steps 4-10 (shared module); per-mode default | 3.3, 3.4 |
| 216-224 | Key from the whole message, before validation | Key `(mode, text)` after validation and normalization | 9.2, 9.4 |
| 228-238 | Text-only errors; no stripping | Strip, empty check, error codes | 3.5, 5 |
| 233-236 | Prompt sent as is; no error handling or size check | Stripped prompt; `GPT_ERROR` on failure or on a response over 64 KiB | 3.5, 7 |
| 239-240 | `NotImplementedError` mapped to an error | Remove the clause; `INTERNAL_ERROR` covers unexpected failures | 5 |
| 241-242 | Text errors; `RecursionError` is not caught | `BAD_EXPR`, including `RecursionError` | 5, 6.5 |
| 244-247 | Only a success `result` is stored | Store full responses of successes and `BAD_EXPR` | 9.3 |
| 264-283 | `recv_line` is a stub | Framing (§2.2) with the 64 KiB limit | 2.2, 2.3 |
| 286-315 | One request handled without error handling | Decode and JSON errors keep the connection open; `MESSAGE_TOO_LARGE` closes it; socket errors are logged; `INTERNAL_ERROR` safety net | 2.3, 8.2-8.5 |

### client.py

| Lines | Now | Required | § |
|---|---|---|---|
| 51-56 | Builders always send `"cache": true`, also for `gpt` | Send no `options` unless the user explicitly changed the cache setting | 3.3 |
| 69-78 | `recv_line` is a stub | Same framing and 64 KiB limit; on overflow, report and close | 2.2, 2.3 |
| 91-93 | Timeout of 10 s | 30 s | 8.9 |
| 96-108 | `request()` is a stub; only `None` ("closed") is documented | Timeout: report and close. Non-JSON line: report, stay open. The return value distinguishes these cases | 8.6, 8.7 |
| 146-158 | `interactive_loop` is a stub; one cache toggle for both modes | Ask whether to reconnect when the connection closes; the menu toggle sets an explicit cache value, and until it is used no `options` are sent | 3.3, 8.8 |
| 171 | Only `--no-cache` | Flags that set an explicit cache value in either direction; without a flag, no `options` are sent | 3.3 |

### proxy.py

| Lines | Now | Required | § |
|---|---|---|---|
| 43-45 | `recv_line` is a stub | Same framing and 64 KiB limit | 2.2, 2.3 |
| 55-67 | `cache_key` is a stub | `(mode, text)` after stripping (shared module) | 9.2 |
| 70-93 | `ProxyCache` is a stub | LRU (reuse `LRUCache`) with `hits`, `misses` and `bypassed` | 10.7 |
| 99-113 | `forward_to_server` is a stub returning `None` on failure | New connection per request; 3 s connect and 25 s read timeouts; return `(response, reason)`; update the docstring | 10.3-10.5 |
| 119-150 | `handle_client` raises `NotImplementedError` | Shared validation; bypass, hit and miss logic; forward the original line; `proxy_cache` and `took_ms`; `SERVER_UNAVAILABLE`; `INTERNAL_ERROR` safety net | 10.1-10.6 |
| 150, 171 | Prints `hits` and `misses` | Also print `bypassed` | 10.7 |

### tests/test_smoke.py

| Lines | Now | Required | § |
|---|---|---|---|
| 113-124 | No assertion on the hit marker | Assert `proxy_cache` is `false` on the first request and `true` on the repeated one | 10.6 |

### New file

| File | Required | § |
|---|---|---|
| Shared module | Framing, structural validation, normalization and cache key used by the server and the proxy | 3.4, 9.2, 10.2 |
