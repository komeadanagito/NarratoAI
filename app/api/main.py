"""FastAPI application factory for the batch-processing API."""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.dependencies import AppServices, BackendError, build_default_services
from app.api.routes import artifacts, batches, health, uploads

API_PREFIX = "/api/v1"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message},
    )


def create_app(services: AppServices | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.services = services or build_default_services()
        try:
            yield
        finally:
            processor = getattr(application.state.services, "batch_processor", None)
            shutdown = getattr(processor, "shutdown", None)
            if callable(shutdown):
                result = shutdown()
                if inspect.isawaitable(result):
                    await result

    application = FastAPI(
        title="NarratoAI 批量视频处理 API",
        version="1.0.0",
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(400, "INVALID_REQUEST", "Invalid request")

    @application.exception_handler(BackendError)
    async def backend_exception_handler(
        _request: Request, exc: BackendError
    ) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @application.exception_handler(HTTPException)
    async def http_exception_handler(
        _request: Request, exc: HTTPException
    ) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _error_response(exc.status_code, "INVALID_REQUEST", message)

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        # Processing services may expose their own safe domain-exception class.
        # Accept the same small protocol without leaking arbitrary exception text.
        code = getattr(exc, "code", None)
        status_code = getattr(exc, "status_code", None)
        if isinstance(code, str) and isinstance(status_code, int):
            message = getattr(exc, "message", None)
            if not isinstance(message, str):
                message = "Request failed"
            return _error_response(status_code, code, message)
        return _error_response(500, "INTERNAL_ERROR", "Internal server error")

    for router in (health.router, uploads.router, batches.router, artifacts.router):
        application.include_router(router, prefix=API_PREFIX)

    generated_openapi = application.openapi

    def contract_openapi() -> dict:
        if application.openapi_schema is None:
            schema = generated_openapi()
            # Runtime validation is intentionally mapped to the documented 400
            # response, so FastAPI's generated 422 entries would be misleading.
            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    if isinstance(operation, dict):
                        operation.get("responses", {}).pop("422", None)
            application.openapi_schema = schema
        return application.openapi_schema

    application.openapi = contract_openapi  # type: ignore[method-assign]

    return application


app = create_app()

__all__ = ["API_PREFIX", "app", "create_app"]
