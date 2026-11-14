"""Contract error type and the FastAPI handlers that render it.

Every non-200 response the bot can receive has the same flat body,
{"error_code": ..., "message": ...}, so the Performer logs error_code without
parsing FastAPI's nested {"detail": ...} shape.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from schemas.contract import ErrorCode, ErrorResponse

logger = logging.getLogger(__name__)


class ContractError(Exception):
    """Raised by contract routes to return a specific status + error_code.

    Args:
        status_code: HTTP status (404, 409, 422, 500, 503).
        error_code: Machine-readable code from schemas.contract.ErrorCode.
        message: Human-readable explanation. Must never contain invoice
            contents, email bodies or credentials — it ends up in bot logs.
        headers: Optional extra headers (e.g. Retry-After on 503).
    """

    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.headers = headers


async def _contract_error_handler(_: Request, exc: ContractError) -> JSONResponse:
    body = ErrorResponse(error_code=exc.error_code, message=exc.message)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=exc.headers)


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Keep FastAPI's per-field detail for debugging, but lead with the flat fields.
    content = ErrorResponse(error_code="invalid_request", message="Request failed validation").model_dump()
    # Validation errors can carry exception objects in "ctx"; stringify them.
    content["detail"] = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
    return JSONResponse(status_code=422, content=content)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Anything not anticipated (e.g. Supabase unreachable) is treated as
    # transient: 500 tells the bot to retry. The exception type is safe to
    # expose; its message might not be (it can echo data), so it is only logged.
    logger.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path, exc_info=exc)
    body = ErrorResponse(error_code="internal_error", message=f"Kagua failed ({type(exc).__name__}); safe to retry")
    return JSONResponse(status_code=500, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    """Attach the contract error handlers to an app (called from main.create_app)."""
    app.add_exception_handler(ContractError, _contract_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error_handler)
