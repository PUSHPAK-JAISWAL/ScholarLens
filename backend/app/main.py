"""ScholarLens API — application entry point.

Run locally:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

app = FastAPI(
    title="ScholarLens API",
    version="0.1.0",
    description="Backend for the ScholarLens scholarship-eligibility assistant.",
)


@app.get("/")
def root() -> dict[str, str]:
    """Basic index route."""
    return {"service": "scholarlens-api", "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness/readiness probe used by the platform health check."""
    return {"status": "healthy"}
