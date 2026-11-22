# EX2 TODO map (Stage 0)

Line numbers refer to the tag `skeleton-original`.

- There is one row for every line containing `TODO`, so headers and reminders appear next to the real work.
- **Bold** summaries mark the place where the work of each numbered task is described.
- `Qn` points to [Questions for protocol.md](#questions-for-protocolmd).
- TODO numbers restart in every file, so they are written as "server 3", "client 3", "proxy 3".

| File | Lines with TODO | Numbered tasks |
|---|---:|---:|
| server.py | 20 | 5 (TODO 5 is optional) |
| client.py | 17 | 4 |
| proxy.py | 23 | 5 |
| tests/test_smoke.py | 2 | 0 |
| README.md | 3 | 0 |
| requirements.txt, .example.env | 0 | 0 |
| **Total** | **65** | **14 (13 required, 1 optional)** |

## server.py

| Line | Function / class | What is required | protocol.md questions |
|---:|---|---|---|
| 21 | module docstring | Header of the task list | - |
| 22 | module docstring | Index: server 1, framing | - |
| 23 | module docstring | Index: server 2, connection loop | - |
| 24 | module docstring | Index: server 3, comparisons and logic | - |
| 25 | module docstring | Index: server 4, boolean result format | Q11 |
| 26 | module docstring | Index: server 5, optional real GPT call, key only in `.env` | - |
| 83 | evaluator section banner | Arithmetic is given, boolean logic is not | - |
| 100 | `_ALLOWED_OPS` | **server 3:** support `not` (`ast.UnaryOp` with `ast.Not`) | Q15 |
| 103 | `_ALLOWED_CMP_OPS` | **server 3:** map the six comparison AST classes to `operator` functions | - |
| 141 | `_eval_node` | **server 3:** evaluate `ast.Compare`, including chains, and reject other operators | - |
| 147 | `_eval_node` | Placeholder raise for comparisons | - |
| 149 | `_eval_node` | **server 3:** evaluate `ast.BoolOp` (`and`, `or`) with any number of operands | Q13, Q14 |
| 155 | `_eval_node` | Placeholder raise for `and` / `or` | - |
| 167 | `safe_eval_expr` | **server 4:** stop forcing booleans to float, return both result kinds consistently, consider edge cases | Q11, Q16 |
| 186 | `call_gpt` | **server 5 (optional):** real model call, stub fallback without a key, no personal data | - |
| 251 | framing section banner | Banner for server 1 and 2 | - |
| 277 | `recv_line` | **server 1:** return one complete line plus leftover bytes, handle partial reads and EOF | Q3, Q4, Q5 |
| 283 | `recv_line` | Placeholder raise | - |
| 290 | `handle_client` | **server 2:** many requests per socket, exactly one response each, survive bad input and socket errors | Q7, Q8 |
| 309 | `handle_client` | **server 2:** catch JSON and UTF-8 decode errors, answer with `make_error` | Q6, Q7 |

## client.py

| Line | Function / class | What is required | protocol.md questions |
|---:|---|---|---|
| 24 | module docstring | Header of the task list | - |
| 25 | module docstring | Index: client 1, framing | - |
| 26 | module docstring | Index: client 2, request and response | - |
| 27 | module docstring | Index: client 3, clean close (FIN visible in Wireshark) | - |
| 28 | module docstring | Index: client 4, interactive menu | - |
| 37 | `PRESET_EXPRESSIONS` comment | Reminder: logical presets need server 3 | - |
| 67 | framing section banner | Banner for client 1 | - |
| 75 | `recv_line` | **client 1:** same framing contract as the server, may live in a shared module | Q3, Q4, Q5 |
| 78 | `recv_line` | Placeholder raise | - |
| 82 | connection section banner | Banner for client 2 and 3 | - |
| 101 | `Connection.request` | **client 2:** frame and send, read one reply, keep the buffer, handle garbage, timeout and EOF | Q9 |
| 108 | `Connection.request` | Placeholder raise | - |
| 112 | `Connection.close` | **client 3:** shutdown and close, safe to call twice | - |
| 116 | `Connection.close` | Placeholder raise | - |
| 133 | interactive section banner | Banner for client 4 | - |
| 148 | `interactive_loop` | **client 4:** presets, typed input, prompt, cache toggle and quit on one connection, survive bad input and Ctrl+C/D | Q10 |
| 158 | `interactive_loop` | Placeholder raise | - |

## proxy.py

| Line | Function / class | What is required | protocol.md questions |
|---:|---|---|---|
| 26 | module docstring | Header of the task list | - |
| 27 | module docstring | Index: proxy 1, framing | - |
| 28 | module docstring | Index: proxy 2, cache key | Q17 |
| 29 | module docstring | Index: proxy 3, cache and eviction | Q22 |
| 30 | module docstring | Index: proxy 4, forwarding | - |
| 31 | module docstring | Index: proxy 5, hit / miss / server-down logic | - |
| 41 | framing section banner | Banner for proxy 1 | - |
| 44 | `recv_line` | **proxy 1:** same framing contract as the server | Q3, Q4, Q5 |
| 45 | `recv_line` | Placeholder raise | - |
| 53 | cache section banner | Banner for proxy 2 and 3 | - |
| 59 | `cache_key` | **proxy 2:** define and document when two requests are the same | Q17, Q18, Q19, Q20 |
| 67 | `cache_key` | Placeholder raise | - |
| 74 | `ProxyCache` | **proxy 3:** thread-safe bounded cache, explainable eviction, visible hit / miss counters | Q22 |
| 87 | `ProxyCache.__init__` | **proxy 3:** choose the data structure | Q22 |
| 90 | `ProxyCache.get` | Placeholder raise for lookup | - |
| 93 | `ProxyCache.put` | Placeholder raise for insert and evict | - |
| 97 | upstream section banner | Banner for proxy 4 | - |
| 105 | `forward_to_server` | **proxy 4:** one request upstream and one reply back, `None` on refusal, timeout or disconnect | Q24 |
| 113 | `forward_to_server` | Placeholder raise | - |
| 117 | per-client section banner | Banner for proxy 5 | - |
| 124 | `handle_client` | **proxy 5:** parse, answer hits locally, forward misses, return an error when the server is down | Q20, Q23, Q25, Q26, Q27 |
| 148 | `handle_client` | **proxy 5:** the place in the loop where that logic goes | - |
| 149 | `handle_client` | Placeholder raise | - |

## tests

| Line | Function / class | What is required | protocol.md questions |
|---:|---|---|---|
| 11 | module docstring | Reminder: tests fail until the TODOs are done and are not proof of correctness | - |
| 70 | `test_boolean_expression` | Needs server 3 and 4 per its docstring, adjust if booleans are represented differently | Q11 |

Two requests in this file have no TODO label: update imports after a rename (line 13), and
assert the proxy hit marker once it is designed (lines 115-116, Q27).

## other

| Line | File and section | What is required | protocol.md questions |
|---:|---|---|---|
| 10 | README.md, introduction | Explains the given / TODO markers | - |
| 24 | README.md, Files | Says each TODO explains the work and the questions to answer | All |
| 62 | README.md, Tests | Reminder: tests are a checklist, scenario 3 is manual | - |

README.md also asks, without a TODO label, for a new `protocol.md` (lines 67-81) and for the README
to be updated to match the implementation (lines 54 and 87).

## GIVEN code (no need to rewrite)

The skeleton permits changing given code as long as the requirements still hold.

### server.py

| Name | Marked given at | Note |
|---|---|---|
| `LRUCache` (`__init__`, `get`, `set`, `__len__`) | 14, 45 | Complete |
| `safe_eval_expr`, `_eval_node`, operator / function / constant tables | 15, 83 | Given for arithmetic only, extended by server 3 and 4 |
| `call_gpt` | 16, 180 | Complete stub, server 5 is optional |
| `make_error` | 195 | Adjust only if the protocol changes |
| `handle_request` | 17, 195 | Adjust only if the protocol changes |
| `send_json` | 18 | Change only together with the framing |
| `serve` | 19, 319 | Complete |
| `main` | 319 (same section) | Complete |

### client.py

| Name | Marked given at | Note |
|---|---|---|
| `build_calc_request`, `build_gpt_request` | 19, 49 | Keep in sync with protocol.md |
| `PRESET_EXPRESSIONS` | 20 | Complete |
| `print_response` | 21 | Complete |
| `main` | 22, 162 | Complete |
| `MENU` | README.md line 17 | Menu text only, the loop is client 4 |

Already written but not labeled GIVEN: `Connection.__init__`, `__enter__`, `__exit__`, and the one-shot `request()`.

### proxy.py

| Name | Marked given at | Note |
|---|---|---|
| `main` (argument parsing) | 23, 154 | Complete |
| `serve` (listening socket, one thread per client) | 23, 154 | Complete |
| `handle_client` | 24 | Only the loop's shape is given, the body is proxy 5 |

Already written but not labeled GIVEN: `send_json`, and `ProxyCache.__init__` apart from its data structure.

### tests/test_smoke.py

README.md line 19 lists the whole file as given: `_start_system_once` and the seven tests.

## Questions for protocol.md

Deduplicated from the TODOs, the comments next to them, and README.md.
In the last column, **yes** means the skeleton explicitly asks for the answer to be documented.
"decide" means it raises the question without saying where to answer it.

| ID | Question | Source | Must document |
|---|---|---|---|
| | **Messages and framing** | | |
| Q1 | What are the message types and, for every field, its name, type, meaning and required / optional status? | README 69-70 | yes |
| Q2 | What is the exact shape of a success response? | README 74 | yes |
| Q3 | What marks the end of a message (newline, length prefix, other)? | README 71-73, server 256-259 | yes |
| Q4 | Why is one `send()` not one `recv()`? | README 71-72, server 273-275 | yes |
| Q5 | What happens when the peer closes in the middle of a message? | server 280-281 | decide |
| | **Errors and connections** | | |
| Q6 | What is the exact shape of an error response? | README 74, server 198 | yes |
| Q7 | After malformed JSON, does the connection stay open or close? | server 293-294 | decide |
| Q8 | How are socket errors logged and cleaned up while keeping one response per request? | server 297-299 | decide |
| Q9 | What does the client report on a timeout or a garbage response? | client 105-106 | decide |
| Q10 | When the other side closes, does the interactive client stop or reconnect? | client 154-155 | yes |
| | **Expression semantics** | | |
| Q11 | How does a boolean result travel (true/false, 1/0, string), consistently with numeric results? | server 167-170, README 75, test 70-71 | yes |
| Q12 | Are `True` / `False` literals accepted as input? | server 117-118 | yes |
| Q13 | Do `and` / `or` short-circuit like Python? | server 152-153 | yes |
| Q14 | What does `1 and 2` evaluate to? | server 152-153 | yes |
| Q15 | Where does `not` belong in the evaluator? | server 100 | decide |
| Q16 | How are long expressions, `9**9**9`, division by zero, `sqrt(-1)` and empty strings handled? | server 172-173 | decide |
| | **Caching** | | |
| Q17 | What is the proxy key? Are `mode` and `data` enough, or do `options` belong in it? | proxy 60, README 76-77 | yes |
| Q18 | Do objects with the same fields in a different order get the same key? | proxy 61-62 | yes |
| Q19 | Is `1+2` the same request as `1 + 2`, and must it be? | proxy 63 | yes |
| Q20 | What does `options.cache = false` mean (no lookup, no store), and where is it enforced? | proxy 64-65, README 77 | yes |
| Q21 | Should the server's own cache key include `options`? | server 216-217 | yes |
| Q22 | Which eviction policy does the proxy use, how does it work, why was it chosen, and how is it thread-safe? | proxy 74-76, README 78 | yes |
| Q23 | Are `ok=false` responses cached? | proxy 133-134 | decide |
| | **Proxy behavior** | | |
| Q24 | Is there a new upstream connection per request or one per client, and why? | proxy 106-109 | yes |
| Q25 | Does the proxy answer invalid JSON itself or forward it? | proxy 125-126 | yes |
| Q26 | What does the client receive on a miss while the server is down? | proxy 131-132, README 79-80 | yes |
| Q27 | What does the client see on a proxy hit, given the stored `from_cache: false`? Is there a hit marker? | proxy 135-138, test 115-116 | decide |
| Q28 | Which extra fields were added, and why are they needed? | README 81 | yes |

## Baseline test results

- Date: 2026-11-22
- Environment: Windows, Python 3.15.0, pytest 9.2.0
- Command: `python -m pytest tests/ -v`, using the interpreter in `.venv`
- Result: **7 failed, 0 passed**, 7 warnings

| Test | Result | First error | TODOs needed to pass |
|---|---|---|---|
| `test_calc_arithmetic_direct` | FAIL | client 2, `request()` is a stub | client 1-3, server 1 |
| `test_persistent_connection_and_server_cache` | FAIL | client 2, `request()` is a stub | client 1-3, server 1 |
| `test_boolean_expression` | FAIL | client 2, `request()` is a stub | client 1-3, server 1, server 3 (see note on server 4) |
| `test_gpt_stub` | FAIL | client 2, `request()` is a stub | client 1-3, server 1 |
| `test_bad_requests_get_error_responses` | FAIL | client 2, `request()` is a stub | client 1-3, server 1 |
| `test_malformed_json_does_not_kill_the_server` | FAIL | client 1, `recv_line()` is a stub | client 1-3, server 1, server 2 |
| `test_proxy_forwards_and_caches` | FAIL | client 2, `request()` is a stub | client 1-3, server 1, proxy 1-5 |

The "first error" column was observed. The last column was derived by reading the code paths.

- **Masked errors:** pytest's summary reports client 3 for all seven tests, because `Connection.__exit__`
  calls the unimplemented `close()` while the first error is propagating.
- **server 4 is not enforced:** the boolean test accepts `1.0` and `0.0`, so it can pass without server 4.
- **Proxy caching is not enforced:** the proxy test checks only the results, so it would also pass if every request were forwarded.
- **Not exercised by any test:** client 4, server 5, scenario 3 (server shut down).
- **The 7 warnings:** each is a server thread dying on the server 1 stub (`recv_line`), one per failed test.
