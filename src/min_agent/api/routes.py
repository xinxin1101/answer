"""System and health-check endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"], summary="Health check")
async def health_check() -> dict[str, str]:
    """Return a lightweight process health status."""
    return {
        "status": "ok",
        "service": "minimal-agent-runtime",
    }
