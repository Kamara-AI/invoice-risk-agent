"""Application configuration loaded from environment variables.

All settings are validated by Pydantic Settings on startup. If a required
variable is missing, the process exits immediately with a clear error —
no silent defaults that mask misconfiguration in production.

Usage:
    from config import settings
    print(settings.supabase_url)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings resolved from environment variables and .env file.

    Pydantic Settings reads variables from the environment first, then falls
    back to the .env file. This means production deployments can inject
    secrets via environment without needing a .env file on disk.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    openai_api_key: str = Field(..., description="OpenAI API key for the LLM scoring node.")

    # ------------------------------------------------------------------
    # LangSmith — observability
    # ------------------------------------------------------------------
    langchain_api_key: str = Field(..., description="LangSmith API key for trace ingestion.")
    langchain_tracing_v2: str = Field(
        default="true",
        description="Must be 'true' to enable LangSmith tracing. String, not bool.",
    )
    langchain_project: str = Field(
        default="invoice-risk-agent",
        description="LangSmith project name. Traces are grouped under this label.",
    )

    # ------------------------------------------------------------------
    # Gmail — invoice ingestion
    # ------------------------------------------------------------------
    gmail_client_id: str = Field(..., description="OAuth2 client ID for Gmail API access.")
    gmail_client_secret: str = Field(..., description="OAuth2 client secret for Gmail API access.")
    gmail_refresh_token: str = Field(..., description="Long-lived refresh token for Gmail OAuth2 flow.")
    gmail_user_email: str = Field(..., description="The mailbox address the agent monitors.")

    # ------------------------------------------------------------------
    # Slack — human review and alerts
    # ------------------------------------------------------------------
    slack_bot_token: str = Field(..., description="Slack bot user OAuth token (xoxb-...).")
    slack_signing_secret: str = Field(..., description="Used to verify Slack webhook payload signatures.")
    slack_review_channel_id: str = Field(..., description="Channel ID for human review request cards.")
    slack_alert_channel_id: str = Field(..., description="Channel ID for auto-block and system alerts.")

    # ------------------------------------------------------------------
    # Stripe — payment fingerprinting
    # ------------------------------------------------------------------
    stripe_api_key: str = Field(..., description="Stripe secret key for Radar and PaymentMethod lookups.")
    stripe_webhook_secret: str = Field(..., description="Stripe webhook signing secret for payload verification.")

    # ------------------------------------------------------------------
    # OFAC — sanctions screening
    # ------------------------------------------------------------------
    ofac_api_key: str = Field(..., description="API key for the OFAC sanctions screening service.")
    ofac_api_base_url: str = Field(
        default="https://api.ofac-api.com/v4",
        description="Base URL for the OFAC API. Override for sandbox environments.",
    )

    # ------------------------------------------------------------------
    # Supabase — persistence
    # ------------------------------------------------------------------
    supabase_url: str = Field(..., description="Supabase project REST endpoint URL.")
    supabase_key: str = Field(..., description="Supabase service role key. Full DB access — keep secret.")

    # ------------------------------------------------------------------
    # Application server
    # ------------------------------------------------------------------
    app_env: str = Field(
        default="development",
        description="Runtime environment: 'development' | 'staging' | 'production'.",
    )
    app_host: str = Field(default="0.0.0.0", description="Uvicorn bind host.")
    app_port: int = Field(default=8000, description="Uvicorn bind port.")


# Singleton — import this everywhere rather than instantiating Settings() again.
# Pydantic validates and loads all values once at import time.
settings = Settings()
