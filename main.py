"""FastAPI application entry point.

Wires together all API routers, configures CORS, and initialises LangSmith
tracing on startup. Run with:

    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

The app is intentionally thin — all business logic lives in agent/ and
integrations/. Routes delegate to the agent graph immediately.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.health import router as health_router
from api.routes.invoice import router as invoice_router
from api.routes.slack_webhook import router as slack_router
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — runs setup on startup, teardown on shutdown.

    Injects LangSmith and OpenAI configuration into the environment so that
    LangChain picks them up regardless of import order.
    """
    os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    yield


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application.

    Returns:
        A fully configured FastAPI instance ready for Uvicorn.
    """
    app = FastAPI(
        title="Invoice Risk Intelligence Agent",
        description=(
            "LangGraph-powered agent that validates, scores, and routes invoices "
            "through 5 fraud-detection gates with full LangSmith observability."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
    )

    # ------------------------------------------------------------------
    # CORS
    # In production, restrict origins to your frontend domain.
    # ------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(health_router, tags=["Health"])
    app.include_router(invoice_router, prefix="/invoices", tags=["Invoices"])
    app.include_router(slack_router, prefix="/slack", tags=["Slack"])

    return app


app = create_app()
