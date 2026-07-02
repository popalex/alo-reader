"""Uniform API error envelope.

All API errors use the shape ``{"error": {"code": "...", "message": "..."}}``.
The exception-to-response wiring is added by the auth work package (WP-02); this
module defines the envelope so later packages share one definition.
"""

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def error_envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}
