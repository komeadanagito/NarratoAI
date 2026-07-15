"""Batch creation and polling routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.dependencies import AppServices, BackendError, get_app_services
from app.models.batch_schema import BatchCreateRequest, BatchResponse, Error

router = APIRouter(tags=["Batches"])


@router.post(
    "/batches",
    operation_id="createBatch",
    response_model=BatchResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
    summary="开始批量处理",
    responses={
        400: {"model": Error, "description": "请求失败"},
        404: {"model": Error, "description": "上传文件不存在"},
        429: {"model": Error, "description": "工作队列已满"},
    },
)
async def create_batch(
    request: BatchCreateRequest,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> BatchResponse:
    batch = services.batch_processor.create_batch(request)
    return BatchResponse(batch=batch)


@router.get(
    "/batches/{batch_id}",
    operation_id="getBatch",
    response_model=BatchResponse,
    response_model_exclude_none=True,
    summary="查询批次进度和结果",
    responses={404: {"model": Error, "description": "批次不存在"}},
)
async def get_batch(
    batch_id: UUID,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> BatchResponse:
    batch = services.batch_store.get_batch(str(batch_id))
    if batch is None:
        raise BackendError("BATCH_NOT_FOUND", "Batch not found", 404)
    return BatchResponse(batch=batch)
