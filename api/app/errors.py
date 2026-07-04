"""Uniform API error envelope.

All API errors use the shape ``{"error": {"code": "...", "message": "..."}}``
(DESIGN.md §5). Routes raise :class:`ApiError`; the handlers registered by
:func:`register_exception_handlers` also convert framework exceptions
(validation errors, bare HTTPExceptions) into the same envelope.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def error_envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


# Canonical code per status (DESIGN.md §5).
STATUS_CODES = {
    400: "invalid_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "invalid_request",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal",
}


class ApiError(Exception):
    """An error the API reports deliberately, carried as status + envelope."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=error_envelope(self.code, self.message),
        )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        msg = first.get("msg", "invalid request")
        return JSONResponse(
            status_code=422,
            content=error_envelope("validation_error", f"{loc}: {msg}" if loc else msg),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "internal")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code, str(exc.detail)),
        )
