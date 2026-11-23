# EX2 Implementation Plan

Changes to the skeleton required by [protocol.md](protocol.md). This file is not part of the
protocol; it is a working list for the implementation stage and for the submission document.

- **Lines:** line numbers refer to the tag `skeleton-original` (`git show skeleton-original:<file>`).
- **§:** points to the relevant section of protocol.md.

## server.py

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
| 216-224 | Key from the whole message, before validation | Key `(mode, text)` after validation and normalization | 9.2 |
| 228-238 | Text-only errors; no stripping | Strip, empty check, error codes | 3.5, 5 |
| 233-236 | Prompt sent as is; no error handling or size check | Stripped prompt; `GPT_ERROR` on failure or on a response over 64 KiB | 3.5, 7 |
| 239-240 | `NotImplementedError` mapped to an error | Remove the clause; `INTERNAL_ERROR` covers unexpected failures | 5 |
| 241-242 | Text errors; `RecursionError` is not caught | `BAD_EXPR`, including `RecursionError` | 5, 6.5 |
| 244-247 | Only a success `result` is stored | Store full responses of successes and `BAD_EXPR` | 9.3 |
| 264-283 | `recv_line` is a stub | Framing with the 64 KiB limit | 2.2, 2.3 |
| 286-315 | One request handled without error handling | Decode and JSON errors keep the connection open; `MESSAGE_TOO_LARGE` closes it; socket errors are logged; `INTERNAL_ERROR` safety net | 2.3, 8.2-8.5 |

## client.py

| Lines | Now | Required | § |
|---|---|---|---|
| 51-56 | Builders always send `"cache": true`, also for `gpt` | Send no `options` unless the user explicitly changed the cache setting | 3.3 |
| 69-78 | `recv_line` is a stub | Same framing and 64 KiB limit; on overflow, report and close | 2.2, 2.3 |
| 91-93 | Timeout of 10 s | 30 s | 8.9 |
| 96-108 | `request()` is a stub; only `None` ("closed") is documented | Timeout: report and close. Non-JSON line: report, stay open. The return value distinguishes these cases | 8.6, 8.7 |
| 146-158 | `interactive_loop` is a stub; one cache toggle for both modes | Ask whether to reconnect when the connection closes; the menu toggle sets an explicit cache value, and until it is used no `options` are sent | 3.3, 8.8 |
| 171 | Only `--no-cache` | Flags that set an explicit cache value in either direction; without a flag, no `options` are sent | 3.3 |

## proxy.py

| Lines | Now | Required | § |
|---|---|---|---|
| 43-45 | `recv_line` is a stub | Same framing and 64 KiB limit | 2.2, 2.3 |
| 55-67 | `cache_key` is a stub | `(mode, text)` after stripping (shared module) | 9.2 |
| 70-93 | `ProxyCache` is a stub | LRU (reuse `LRUCache`) with `hits`, `misses` and `bypassed` counters | 9.4 |
| 99-113 | `forward_to_server` is a stub returning `None` on failure | New connection per request; 3 s connect and 25 s read timeouts; keep the parameters, return `(response, None)` or `(None, "<reason>")`; update the docstring | 10.3, 10.5 |
| 119-150 | `handle_client` raises `NotImplementedError` | Shared validation; bypass, hit and miss logic; forward the original line; `proxy_cache` and `took_ms`; `SERVER_UNAVAILABLE`; `INTERNAL_ERROR` safety net | 10.1-10.6 |
| 150, 171 | Prints `hits` and `misses` | Also print `bypassed` | 9.4 |

## tests/test_smoke.py

| Lines | Now | Required | § |
|---|---|---|---|
| 113-124 | No assertion on the hit marker | Assert `proxy_cache` is `false` on the first request and `true` on the repeated one | 10.6 |

## New file

| File | Required | § |
|---|---|---|
| Shared module | Framing, structural validation, normalization and cache key used by the server and the proxy | 3.4, 9.2, 10.2 |
