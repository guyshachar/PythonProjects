"""
Correlation ID middleware.

Assigns a unique request ID to every HTTP request so that all log lines
emitted while processing that request can be tied together in a log
aggregator (Loki, Datadog, CloudWatch, etc.).

How it works
────────────
1. Read X-Request-Id from the incoming headers.
   If absent, generate a new UUID4.
2. Store the ID in a contextvar so every log record in the same async task
   can read it via RequestIdFilter.
3. Echo the ID back in the X-Request-Id response header.

Logging integration
───────────────────
Add RequestIdFilter to any handler you want annotated.  main.py does this
for the root handler automatically.

Usage in logs:
  %(request_id)s will expand to the current request's ID or "-" if no
  request is active (e.g. during startup/shutdown).
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Module-level contextvar: set per request, read by RequestIdFilter.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that assigns an X-Request-Id to every request.

    Registered in main.py via app.add_middleware(CorrelationIdMiddleware).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id: str = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        token = request_id_var.set(req_id)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-Id"] = req_id
            return response
        finally:
            # Always reset, even if call_next raises, so no ID leaks across tasks.
            request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """
    Logging filter that injects `request_id` into every LogRecord.

    Attach to a handler (not the logger) so it only fires when the handler
    actually emits:

        handler.addFilter(RequestIdFilter())

    Then include %(request_id)s in the handler's format string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")  # type: ignore[attr-defined]
        return True
