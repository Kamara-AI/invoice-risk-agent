"""FastAPI application entry point.

Wires together all API routers, configures CORS, and initialises LangSmith
tracing on startup. Run with:

    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

The app is intentionally thin — all business logic lives in agent/ and
integrations/. Routes delegate to the agent graph immediately.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.health import router as health_router
from api.routes.invoice import router as invoice_router
from api.routes.slack_webhook import router as slack_router
from config import settings


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


@app.on_event("startup")
async def configure_langsmith() -> None:
    """Inject LangSmith configuration into the environment on startup.

    LangChain reads LANGCHAIN_TRACING_V2 and LANGCHAIN_PROJECT from os.environ
    at import time in some code paths, so we set them explicitly here as well
    as relying on the .env file to ensure they are always present.
    """
    os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
