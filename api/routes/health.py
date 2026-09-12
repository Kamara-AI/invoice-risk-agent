"""Health check route.

Used by load balancers, Docker HEALTHCHECK, and uptime monitors.
Returns immediately with no DB or external API calls — this is an
application-level liveness check only, not a readiness probe.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return a simple liveness response.

    Returns:
        A dict with a single 'status' key set to 'ok'.
    """
    return {"status": "ok"}
