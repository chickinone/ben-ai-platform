import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-Id"
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,128}")


def install_request_id(app: FastAPI) -> None:
    """Nhận X-Request-Id hợp lệ từ client hoặc sinh mới, và trả lại trong response."""

    @app.middleware("http")
    async def _request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def get_trace_id(request: Request) -> str:
    """Trace id của OpenTelemetry nếu có span hợp lệ, nếu không thì dùng request id."""
    try:
        from opentelemetry import trace
    except ImportError:
        return get_request_id(request)
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else get_request_id(request)
