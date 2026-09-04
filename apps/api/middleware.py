"""HTTP middleware: request-id propagation + structured access logging."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from security.logging import bind_request_id, clear_context, get_logger

_log = get_logger("api.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        bind_request_id(request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        status = 500
        try:
            response: Response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            _log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status,
                elapsed_ms=elapsed_ms,
                client=request.client.host if request.client else None,
            )
            clear_context()
