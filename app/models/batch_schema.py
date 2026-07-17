"""Public request and response models for the batch-processing API.

The models in this module intentionally mirror ``docs/backend_api.yaml``.  They
do not expose internal paths or service records used by the processing layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Mapping
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


class ApiModel(BaseModel):
    """Base model that rejects fields not present in the public contract."""

    model_config = ConfigDict(extra="forbid")


class Error(ApiModel):
    code: str
    message: str


class Upload(ApiModel):
    id: UUID
    file_name: str
    size_bytes: Annotated[int, Field(ge=0, json_schema_extra={"format": "int64"})]


class UploadsResponse(ApiModel):
    uploads: list[Upload]


class NarrationOptions(ApiModel):
    enabled: StrictBool = False
    language: str = "zh-CN"
    # These fields are optional (may be omitted) but are not nullable in the
    # OpenAPI contract when explicitly supplied.
    voice_id: str = None  # type: ignore[assignment]
    voice_prompt: Annotated[str, Field(max_length=500)] = None  # type: ignore[assignment]


class BorderMode(str, Enum):
    none = "none"
    blurred = "blurred"
    solid = "solid"
    asset = "asset"


class DeduplicationOptions(ApiModel):
    change_file_hash: StrictBool = True
    reencode: StrictBool = True
    color_noise_tweak: StrictBool = False
    border_mode: BorderMode = BorderMode.none
    sticker: StrictBool = False
    subtitle_mask: StrictBool = False
    crop_scale: StrictBool = False
    mirror: StrictBool = False
    speed_tweak: StrictBool = False


class BatchCreateRequest(ApiModel):
    upload_ids: Annotated[
        list[UUID], Field(min_length=1, json_schema_extra={"uniqueItems": True})
    ]
    output_directory: Annotated[str, Field(min_length=1)]
    concurrency: Annotated[StrictInt, Field(ge=1)] = 1
    narration: NarrationOptions = Field(default_factory=NarrationOptions)
    deduplication: DeduplicationOptions = Field(default_factory=DeduplicationOptions)

    @field_validator("upload_ids")
    @classmethod
    def upload_ids_must_be_unique(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("upload_ids must contain unique values")
        return value


class BatchStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    partially_succeeded = "partially_succeeded"
    failed = "failed"


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


class JobStage(str, Enum):
    queued = "queued"
    analyzing = "analyzing"
    synthesizing = "synthesizing"
    processing = "processing"
    completed = "completed"


class VideoJob(ApiModel):
    id: UUID
    upload_id: UUID
    file_name: str
    status: JobStatus
    stage: JobStage
    progress: Annotated[int, Field(ge=0, le=100)]
    message: str = None  # type: ignore[assignment]
    output_path: str = None  # type: ignore[assignment]
    artifact_id: UUID = None  # type: ignore[assignment]
    error: Error | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_omitted_response_fields(cls, value: Any) -> Any:
        """Keep optional response fields absent when snapshots are rebuilt.

        ``BatchStore`` round-trips models through ``model_dump``.  Pydantic
        includes default ``None`` values in that dictionary, while the OpenAPI
        contract defines these fields as optional rather than nullable.  Treat
        those internal default values exactly like omitted fields.
        """

        if isinstance(value, Mapping):
            normalized = dict(value)
            for name in ("message", "output_path", "artifact_id"):
                if normalized.get(name) is None:
                    normalized.pop(name, None)
            return normalized
        return value


class Batch(ApiModel):
    id: UUID
    status: BatchStatus
    progress: Annotated[int, Field(ge=0, le=100)]
    total: Annotated[int, Field(ge=1)]
    succeeded: Annotated[int, Field(ge=0)]
    failed: Annotated[int, Field(ge=0)]
    jobs: list[VideoJob]


class BatchResponse(ApiModel):
    batch: Batch


class HealthResponse(ApiModel):
    status: Literal["ok"]


__all__ = [
    "Batch",
    "BatchCreateRequest",
    "BatchResponse",
    "BatchStatus",
    "BorderMode",
    "DeduplicationOptions",
    "Error",
    "HealthResponse",
    "JobStage",
    "JobStatus",
    "NarrationOptions",
    "Upload",
    "UploadsResponse",
    "VideoJob",
]
