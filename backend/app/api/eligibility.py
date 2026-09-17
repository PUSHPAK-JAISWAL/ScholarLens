"""The public eligibility endpoint."""

from fastapi import APIRouter, HTTPException

from app.agent.agent import EligibilityEngineError, get_agent
from app.agent.models import EligibilityResult
from app.api.errors import ErrorResponse
from app.api.models import EligibilityRequest

router = APIRouter()


@router.post(
    "/eligibility",
    response_model=EligibilityResult,
    # Without these, OpenAPI advertises FastAPI's default error body instead of the envelope.
    responses={
        422: {"model": ErrorResponse, "description": "The request body failed validation."},
        503: {"model": ErrorResponse, "description": "The eligibility engine is not available."},
    },
)
async def check_eligibility(request: EligibilityRequest) -> EligibilityResult:
    """Determine which programs a student may qualify for, with the rule behind each result."""
    try:
        return await get_agent().check_eligibility(request)
    except EligibilityEngineError as exc:
        raise HTTPException(status_code=503) from exc
