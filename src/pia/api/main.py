"""Application factory. Run with: uvicorn pia.api.main:create_app --factory"""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pia import __version__
from pia.api.routers import admin, agents, health, insight, reviews
from pia.api.state import build_state
from pia.cost import BudgetExceeded
from pia.guardrails.output import GuardrailViolation
from pia.guardrails.sql import SQLViolation
from pia.llm.structured import StructuredOutputError
from pia.logging_setup import configure_logging
from pia.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = build_state(settings)

    app = FastAPI(
        title="PIA AI Platform",
        version=__version__,
        docs_url=None if settings.env == "prod" else "/docs",
        openapi_url=None if settings.env == "prod" else "/openapi.json",
        redoc_url=None,
    )
    app.state.ctx = state

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        state.metrics.observe("http_request_seconds", time.perf_counter() - start, {"route": path})
        state.metrics.inc("http_requests_total", {"route": path, "status": str(response.status_code)})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if settings.env != "dev":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    def _error(code: str, status: int, guard: str | None = None):
        async def handler(request: Request, exc: Exception):
            if guard:
                state.metrics.inc("guardrail_blocked_total", {"guard": guard})
            return JSONResponse({"error": code}, status_code=status)

        return handler

    app.add_exception_handler(GuardrailViolation, _error("guardrail_violation", 422, "output"))
    app.add_exception_handler(SQLViolation, _error("sql_rejected", 422, "sql"))
    app.add_exception_handler(BudgetExceeded, _error("budget_exceeded", 429, "budget"))
    app.add_exception_handler(StructuredOutputError, _error("model_output_invalid", 502, "schema"))

    for module in (health, insight, reviews, agents, admin):
        app.include_router(module.router)
    return app
