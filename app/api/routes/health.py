"""Health-check route."""

from fastapi import APIRouter

from app.models.batch_schema import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    operation_id="getHealth",
    response_model=HealthResponse,
    summary="健康检查",
)
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok")
