"""Định dạng lỗi chung cho mọi API của Bến (PROJECT.md §13.5).

{"error": {"type": "...", "message": "...", "trace_id": "..."}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ben_common.request_id import get_trace_id

logger = logging.getLogger(__name__)

_HTTP_ERROR_TYPES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    429: "rate_limited",
}


class BenError(Exception):
    """Lỗi có chủ đích, trả về client với type và message rõ ràng."""

    def __init__(self, status_code: int, error_type: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.message = message
        self.extra = extra


def error_body(request: Request, error_type: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "error": {
            "type": error_type,
            "message": message,
            "trace_id": get_trace_id(request),
            **extra,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BenError)
    async def _ben_error(request: Request, exc: BenError) -> JSONResponse:
        body = error_body(request, exc.error_type, exc.message, **exc.extra)
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error_type = _HTTP_ERROR_TYPES.get(exc.status_code, "http_error")
        return JSONResponse(
            error_body(request, error_type, str(exc.detail)),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = error_body(
            request,
            "invalid_request",
            "Request không hợp lệ. Xem details để biết trường nào sai.",
            details=jsonable_encoder(exc.errors()),
        )
        return JSONResponse(body, status_code=400)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Lỗi không xử lý", exc_info=exc)
        body = error_body(
            request,
            "internal_error",
            "Lỗi nội bộ. Gửi trace_id cho đội platform để điều tra.",
        )
        return JSONResponse(body, status_code=500)
