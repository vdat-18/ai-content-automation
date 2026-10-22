"""ASGI middleware for Prometheus metrics and log/trace correlation."""

from __future__ import annotations

from time import monotonic

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .metrics import HTTP_DURATION, HTTP_IN_FLIGHT, HTTP_REQUESTS
from .tracing import current_trace_id


class HttpObservabilityMiddleware(BaseHTTPMiddleware):
    """Record bounded HTTP metrics and expose the active trace identifier."""

    def __init__(self, app, service_name: str) -> None:
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        method = request.method
        started = monotonic()
        HTTP_IN_FLIGHT.labels(service=self._service_name, method=method).inc()
        try:
            trace_id = current_trace_id()
            with logger.contextualize(trace_id=trace_id or "untraced"):
                response = await call_next(request)
            if trace_id is not None:
                response.headers["X-Trace-ID"] = trace_id
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(
                service=self._service_name,
                method=method,
                route=route_path,
                status=str(response.status_code),
            ).inc()
            HTTP_DURATION.labels(
                service=self._service_name,
                method=method,
                route=route_path,
            ).observe(monotonic() - started)
            return response
        finally:
            HTTP_IN_FLIGHT.labels(service=self._service_name, method=method).dec()


__all__ = ["HttpObservabilityMiddleware"]
