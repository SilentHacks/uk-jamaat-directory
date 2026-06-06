from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=get_request_id(request),
            details=details,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code = "http_error"
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
    elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "unauthorized"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "forbidden"
    elif exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        code = "validation_error"
    elif exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        code = "service_unavailable"

    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return error_response(request=request, status_code=exc.status_code, code=code, message=detail)


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return error_response(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="Request validation failed",
        details=exc.errors(),
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
