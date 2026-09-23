# 13 - Structured logging + correlation IDs

## What

Before this feature, the ScholarLens backend kept no log of its own. When a
student's `/eligibility` request failed, the server returned a tidy 503 or 500
error body and then forgot everything: nothing on the server side recorded
what went wrong, when, or for which request. Uvicorn (the program that runs
the FastAPI app) printed one plain-text line per request, and that was all.

Feature 13 gives the backend a voice. Every log line the app writes is now a
single JSON object with the same field names every time. Every incoming HTTP
request is assigned a **correlation ID**. That ID is stamped on every log line
written while the request is being handled, and it is sent back to the
caller in an `X-Request-ID` response header. When the agent fails (ChromaDB
unreachable, a timeout, a failure to build the agent) or something crashes
outright, the server now writes a WARNING or ERROR line that names the
exception type. It does all this without ever writing a word of what the
student typed.

## Why

Picture the backend deployed on Render with a few hundred students using it.
One of them reports "it said the engine was unavailable." Before this
feature, you had nothing to go on. You couldn't find their request, and you
couldn't tell whether ChromaDB was down, Tavily timed out, or Gemini rejected
the key. Even with plain-text logs you'd be matching timestamps by eye across
interleaved lines from concurrent requests, and hoping.

Three concrete costs of not having this:

- **Failures are invisible.** The old unhandled-exception handler turned a
  crash into a clean `internal_error` envelope, which is good for the user
  but meant the actual exception was thrown away. A bug could fire a thousand
  times and leave no trace.
- **Concurrent requests blur together.** The server handles many requests at
  once, so their log lines interleave. Without a shared ID per request you
  can't reliably say which lines belong to which request.
- **Machines can't read prose.** Phase 4 of the build plan ships these logs to
  Grafana Cloud, adds traces (feature 14) and metrics (feature 15), and builds
  dashboards (16). All of that tooling wants to filter and group by *fields*
  (`level = ERROR`, `path = /eligibility`), not grep English sentences.

There's also a privacy constraint pulling the other way. ScholarLens promises
never to persist or log student profiles. A naive "log everything for
debugging" approach would break that promise the first time it dumped a
request body. This feature has to make the server observable *and* keep
that promise, so a lot of the design is about what it refuses to log.

## Key concepts

### A log, and a logger

A **log** is a running diary a program writes about itself while it runs:
"started", "handled a request", "this failed". Unlike a response to a user,
nobody reads it in the moment. It exists for the person who later has to work
out what happened.

In Python, you don't write to the diary directly. You ask for a **logger**, a
named object, and call methods on it like `logger.info("...")` or
`logger.warning("...")`. The method name is the **level**, how serious the
event is: `DEBUG` < `INFO` < `WARNING` < `ERROR` < `CRITICAL`. A logger
configured at `INFO` silently drops `DEBUG` lines, which is how you make a
program chattier or quieter without touching its code.

Loggers are named with dots, like `app.api.errors`, and those dots form a
tree. `app.api.errors` is a child of `app.api`, which is a child of `app`.
Configure the parent (`app`) and every child inherits the setup. That is
exactly how this feature reaches every module at once.

Where the line ends up (the screen, a file, a network service) is decided by
a **handler**. What it *looks like* is decided by a **formatter**. Think of it
like a newspaper: the logger is the reporter, the formatter is the layout
desk, and the handler is the delivery truck.

### Structured logging

A traditional log line is a sentence:

```text
2026-09-23 21:24:39 INFO GET /health 200 3.64ms
```

A human reads that fine. A machine has to guess where one field ends and the
next begins, and the guess breaks the moment someone reorders the words.

**Structured logging** writes each line as data, here as JSON:

```json
{"timestamp": "2026-09-23T21:24:39.121+00:00", "level": "INFO", "logger": "app.access",
 "message": "request completed", "correlation_id": "13c3cbfe-...", "method": "GET",
 "path": "/health", "status_code": 200, "duration_ms": 3.64}
```

Every field is labeled, so a log tool can answer "show me every request to
`/eligibility` slower than 5 seconds" without any parsing tricks. It's the
difference between a pile of handwritten receipts and a spreadsheet.
**Consistent field names** matter as much as the format. If one module writes
`status` and another writes `status_code`, every query has to know both.

### Correlation ID

A **correlation ID** (also called a request ID) is a random, unique label
given to one request the moment it arrives. It's like the order number on a
restaurant ticket. The kitchen, the bar, and the cashier all write the same
number on their notes, so later you can gather every note about table 12's
order even though they were scribbled at different stations, in between
notes about other tables.

Here the stations are the modules (the access logger, the agent, the error
handlers). Each of them stamps the request's ID on its lines. Search the logs
for one ID and you get that request's whole story, in order.

The ID is also returned to the caller in the `X-Request-ID` header. If a
student (or the frontend) reports a problem and includes that ID, you can jump
straight to their request. A caller can also *send* an `X-Request-ID` header
of its own, so an ID created upstream (say, by a proxy) is reused rather than
replaced.

### Context variables: "the current request" without passing it everywhere

The tricky part is getting the ID onto a log line in `agent.py`, which knows
nothing about HTTP. The obvious fix, adding a `request_id` parameter to every
function, would thread one argument through the whole codebase.

Python's **`contextvars`** solve this. A `ContextVar` is like a global
variable, except each concurrently running task sees its *own* value. The
middleware sets it once at the start of a request. Anything that runs as part
of that request, however deep in the call stack, can read it back, and a
second request running at the same moment sees its own value, not this one.
It's like each waiter carrying their own order pad. There's one "current
order number" per waiter, never one shared across the restaurant.

The JSON formatter reads the ID from the context variable on every line. That
is why `agent.py` never mentions correlation IDs, yet its lines carry one.

### Middleware

**Middleware** is code that wraps every request on its way in and every
response on its way out, like airport security that every passenger passes
through regardless of destination. FastAPI (built on the Starlette library)
lets you stack several middlewares. The one registered *last* is the
*outermost* layer: it sees the request first and the response last. The
correlation-ID middleware has to be outermost so it can time the whole
request and stamp every response, including ones the CORS middleware rejects.

### Trust boundaries and log injection

The `X-Request-ID` header comes from whoever is calling the API, so it's
**untrusted input**. It would be written into logs and echoed into a response
header. A malicious value could contain newlines to forge fake log lines, or
header-breaking characters. So an incoming value is reused only if it's
1-128 characters of letters, digits, `-` or `_`. Anything else gets a fresh
UUID (a 128-bit random identifier, such as `13c3cbfe-bff8-4bf0-ac0c-5af71a1c7df0`).

### Logging without leaking

"Log the error" sounds safe, but an error *message* can carry data. A
provider's exception might quote the prompt it was sent, and that prompt
contains the student's description, GPA, and income. So this feature logs the
exception's **type** (`RetrievalUnavailableError`) and, for crashes, the
**stack frames** (which file and line the code was on) but never the
exception's **message**. You learn *where* and *what kind* of thing broke, and
nothing about *whose* request it was beyond an anonymous ID.

## Architecture

```text
 incoming request (maybe with X-Request-ID)
        |
        v
+-----------------------------+   sets request.state.request_id
| CorrelationIdMiddleware     |   sets ContextVar correlation_id
| (outermost, app/api/        |   starts timer
|  middleware.py)             |
+-------------+---------------+
              |
              v
     CORSMiddleware -> router -> /eligibility -> EligibilityAgent
              |                                   |
              |                     failure? -> _log_failure()  --- WARNING
              |                                   |    (app.agent.agent)
              |                     raises EligibilityEngineError -> 503
              v
+-----------------------------+
| CorrelationIdMiddleware     |   adds X-Request-ID response header
| (on the way out)            |   writes 1 access line ------------ INFO
+-----------------------------+   (app.access)       resets ContextVar
              |
              v
   unhandled crash? ServerErrorMiddleware -> unhandled_error() ---- ERROR
   (runs OUTSIDE the middleware above, so it     (app.api.errors)
    reads the ID from request.state instead)

Every line above -> logger tree "app" -> JsonFormatter -> stdout
```

Every one of those log lines goes through the same formatter, which fills in
`timestamp`, `level`, `logger`, `message`, and `correlation_id`, then merges
in the extra fields the caller passed.

## What we actually built

Six files changed, and nothing new was installed. Everything uses Python's
standard `logging`, `contextvars`, `json`, `uuid`, and `re` modules, plus
Starlette's middleware base class, which FastAPI already ships.

### The formatter and the context variable: [`app/logging.py`](../backend/app/logging.py)

The ID lives in one module-level `ContextVar`:

```python
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
```

`default=None` matters: a log line written outside any request (at startup,
say) gets `"correlation_id": null` rather than crashing.

The `JsonFormatter` builds the fixed fields, then merges whatever the caller
passed via `extra={...}`. The trick is telling those extras apart from the two
dozen attributes Python puts on every log record. The answer is to make a
blank record once and remember its attribute names:

```python
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}
...
entry.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
```

So `logger.info("request completed", extra={"status_code": 200})` produces a
flat `"status_code": 200` field, never a nested object. That keeps queries
simple.

`configure_logging()` attaches the JSON handler to the `app` logger only and
sets `propagate = False`. Every `app.*` module becomes JSON, uvicorn's own
startup and access lines are left exactly as they were, and nothing gets
printed twice.

### The middleware: [`app/api/middleware.py`](../backend/app/api/middleware.py)

The whole feature pivots on about twenty lines:

```python
request_id = _request_id(request)          # reuse a safe header, else uuid4
request.state.request_id = request_id
token = set_correlation_id(request_id)
start = time.perf_counter()
status_code = 500
try:
    response = await call_next(request)
    status_code = response.status_code
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
finally:
    _access_logger.info("request completed", extra={...duration_ms...})
    reset_correlation_id(token)
```

Two details are worth noticing:

- `status_code = 500` starts as a pessimistic default. If the app crashes,
  `call_next` raises, and the `finally` block still writes an access line
  recording a 500. So a crash is never missing from the access log.
- `reset_correlation_id(token)` puts the context variable back the way it was.
  The `token` is a receipt from `set()` that makes an exact undo possible.

It's registered in [`app/main.py`](../backend/app/main.py) *after*
`CORSMiddleware`, with a comment explaining why: registered last means
outermost.

### The bug-in-waiting: where the 500 handler actually runs

This one was caught mid-build, and it's the kind of thing you only learn by
getting it wrong. The plan was simple: the unhandled-exception handler in
[`app/api/errors.py`](../backend/app/api/errors.py) logs an ERROR, and the
formatter picks up the correlation ID from the context variable like
everywhere else.

But Starlette registers the catch-all `Exception` handler in a special
`ServerErrorMiddleware` that sits *outside* every user middleware, ours
included. By the time it runs, our `finally` block has already reset the
context variable. The error line would have said `"correlation_id": null`,
the one line you most need to trace.

The fix: the middleware also stores the ID on `request.state`, which belongs
to the request itself rather than the running task, and the handler reads it
from there:

```python
request_id = getattr(request.state, "request_id", None)
_logger.error("unhandled exception", extra={"correlation_id": request_id, ...})
```

The same handler also sets `X-Request-ID` on the 500 response itself, since
the middleware never got to.

### What the errors log, and what they refuse to

[`app/agent/agent.py`](../backend/app/agent/agent.py) gained one helper,
called in each failure branch of `check_eligibility_measured` and in
`get_agent()`:

```python
def _log_failure(message: str, exc: Exception) -> None:
    # Only the type: a provider exception's message can echo the prompt or tool query.
    _logger.warning(message, extra={"error_type": type(exc).__name__})
```

The code review changed two things here:

1. **The 500 handler first logged `exc_info`, the full traceback including
   the exception message.** The reviewer spotted the inconsistency: the agent
   carefully logged only the type, while the crash handler dumped messages
   wholesale. It now logs `traceback.format_tb(...)`, the stack frames
   without the message line.
2. **A runtime engine failure produced two WARNING lines**, one from the agent
   and one from the API's `HTTPException` handler. The API one only ever said
   `EligibilityEngineError`, which added nothing. It was removed. Instead,
   `get_agent()`, which previously failed silently when the agent couldn't be
   built (for example, no API key), got its own agent-level line. Now every
   503 has exactly one WARNING that names the real cause.

4xx responses (validation errors, 404s) deliberately get no error line. A
student typing a GPA of 7 isn't a server fault, and the access line already
records the 422.

### A typed log level: [`app/config.py`](../backend/app/config.py)

```python
log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
```

This started life as a plain `str`, which meant `LOG_LEVEL=verbose` would
pass settings validation and then crash the server on import when Python's
logger rejected it. With `Literal`, Pydantic refuses the bad value up front,
with a message listing the five allowed ones.

### How we know it works

No test runner is configured, so the evidence is manual, all against a real
uvicorn server or FastAPI's in-process `TestClient`:

- `curl -i /health` returned an `X-Request-ID` header, and the server wrote
  exactly one `app.access` JSON line with the same ID.
- `X-Request-ID: abc-123` was reused as-is; `X-Request-ID: bad value!` was
  replaced with a fresh UUID.
- `POST /eligibility` with ChromaDB not running returned 503 with one
  `WARNING` naming `RetrievalUnavailableError`, sharing the request's ID. A
  marker word planted in the student description appeared **zero** times in
  the server log.
- A throwaway route raising `RuntimeError("SECRETSTUDENT kaboom")` returned
  500 with its ID echoed. The ERROR line carried the stack frames, and the
  marker word was absent.
- `LOG_LEVEL=verbose` failed at startup with a clear Pydantic error.
- `ruff check .` passed throughout.

## What's next

This feature is the foundation Phase 4 stands on:

- **14 - OpenTelemetry instrumentation.** Traces break a request into timed
  **spans** (the agent run, each retrieval, each LLM call). OpenTelemetry has
  its own *trace ID*, and a natural follow-up is putting it on these log lines
  (or using it as the correlation ID) so a log line jumps straight to its trace
  in Grafana Tempo. The "never log student data" rules here apply to span
  attributes too.
- **15 - Prometheus metrics.** The access line already measures
  `duration_ms` and `status_code` per request. Metrics count and aggregate the
  same facts (request rate, latency percentiles, error rate) instead of
  recording each one.
- **16 / 17 - dashboards and `/ops`.** The consistent field names chosen here
  (`path`, `status_code`, `error_type`) become the dimensions those panels
  filter by.
- **18 - Reliability + security.** Adds a broader log-scrubbing pass. This
  feature avoided leaks by construction in the places it touched; 18 hardens
  the rest. The frontend could also start *showing* the `X-Request-ID` in its
  error state, so a student can quote it in a bug report. That needs CORS
  `expose_headers`, which was deliberately left out here as unrequested scope.
