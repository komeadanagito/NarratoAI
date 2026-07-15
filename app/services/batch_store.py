"""Thread-safe in-memory batch state and progress aggregation."""

from __future__ import annotations

from threading import RLock
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.models.batch_schema import Batch, BatchStatus, JobStatus, VideoJob


class BatchStoreError(Exception):
    """A safe store error suitable for the HTTP error mapper."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class BatchStore:
    """Keep mutable worker state private and expose deep Pydantic snapshots."""

    _TERMINAL_JOB_STATUSES = frozenset({JobStatus.succeeded, JobStatus.failed})

    def __init__(self) -> None:
        self._batches: dict[UUID, Batch] = {}
        self._lock = RLock()

    def create_batch(self, batch: Batch) -> Batch:
        """Register a new batch and return an isolated snapshot."""

        candidate = Batch.model_validate(batch)
        if candidate.total != len(candidate.jobs):
            raise BatchStoreError(
                "INVALID_REQUEST", "Batch total must equal the number of jobs", 400
            )
        if len({job.id for job in candidate.jobs}) != len(candidate.jobs):
            raise BatchStoreError("INVALID_REQUEST", "Job IDs must be unique", 400)
        with self._lock:
            if candidate.id in self._batches:
                raise BatchStoreError("INVALID_REQUEST", "Batch already exists", 400)
            self._batches[candidate.id] = candidate.model_copy(deep=True)
            return self._snapshot(self._batches[candidate.id])

    # The short name is convenient for callers while create_batch remains the
    # explicit API promised to the processor.
    def create(self, batch: Batch) -> Batch:
        return self.create_batch(batch)

    def get_batch(self, batch_id: UUID | str) -> Batch | None:
        normalized = self._parse_uuid(batch_id)
        if normalized is None:
            return None
        with self._lock:
            batch = self._batches.get(normalized)
            return self._snapshot(batch) if batch is not None else None

    def update_job(
        self,
        batch_id: UUID | str,
        job_id: UUID | str,
        **changes: Any,
    ) -> Batch:
        """Apply a validated job update and atomically re-aggregate its batch."""

        normalized_batch_id = self._require_uuid(batch_id, "BATCH_NOT_FOUND", "Batch not found")
        normalized_job_id = self._require_uuid(job_id, "JOB_NOT_FOUND", "Job not found")
        with self._lock:
            batch = self._batches.get(normalized_batch_id)
            if batch is None:
                raise BatchStoreError("BATCH_NOT_FOUND", "Batch not found", 404)

            job_index = next(
                (index for index, job in enumerate(batch.jobs) if job.id == normalized_job_id),
                None,
            )
            if job_index is None:
                raise BatchStoreError("JOB_NOT_FOUND", "Job not found", 404)

            current = batch.jobs[job_index]
            update = dict(changes)
            if "progress" in update:
                try:
                    update["progress"] = max(current.progress, int(update["progress"]))
                except (TypeError, ValueError) as exc:
                    raise BatchStoreError("INVALID_REQUEST", "Invalid job progress", 400) from exc

            data = current.model_dump()
            data.update(update)
            try:
                replacement = VideoJob.model_validate(data)
            except ValidationError as exc:
                raise BatchStoreError("INVALID_REQUEST", "Invalid job update", 400) from exc

            self._validate_status_transition(current, replacement)
            jobs = list(batch.jobs)
            jobs[job_index] = replacement
            self._batches[normalized_batch_id] = batch.model_copy(update={"jobs": jobs})
            aggregated = self._aggregate_locked(normalized_batch_id)
            return self._snapshot(aggregated)

    def aggregate_batch(self, batch_id: UUID | str) -> Batch:
        """Recompute counts, status and monotonic progress for a batch."""

        normalized = self._require_uuid(batch_id, "BATCH_NOT_FOUND", "Batch not found")
        with self._lock:
            if normalized not in self._batches:
                raise BatchStoreError("BATCH_NOT_FOUND", "Batch not found", 404)
            return self._snapshot(self._aggregate_locked(normalized))

    # Alias matching the shorter service operation named in the plan.
    def aggregate(self, batch_id: UUID | str) -> Batch:
        return self.aggregate_batch(batch_id)

    def _aggregate_locked(self, batch_id: UUID) -> Batch:
        batch = self._batches[batch_id]
        jobs = batch.jobs
        succeeded = sum(job.status == JobStatus.succeeded for job in jobs)
        failed = sum(job.status == JobStatus.failed for job in jobs)
        terminal_count = succeeded + failed

        if terminal_count == len(jobs):
            if succeeded == len(jobs):
                status = BatchStatus.succeeded
            elif failed == len(jobs):
                status = BatchStatus.failed
            else:
                status = BatchStatus.partially_succeeded
            computed_progress = 100
        elif all(job.status == JobStatus.queued for job in jobs):
            status = BatchStatus.queued
            computed_progress = sum(job.progress for job in jobs) // len(jobs)
        else:
            status = BatchStatus.processing
            computed_progress = sum(job.progress for job in jobs) // len(jobs)

        replacement = Batch(
            id=batch.id,
            status=status,
            progress=max(batch.progress, computed_progress),
            total=len(jobs),
            succeeded=succeeded,
            failed=failed,
            jobs=jobs,
        )
        self._batches[batch_id] = replacement
        return replacement

    @classmethod
    def _validate_status_transition(cls, current: VideoJob, replacement: VideoJob) -> None:
        if (
            current.status in cls._TERMINAL_JOB_STATUSES
            and replacement.status != current.status
        ):
            raise BatchStoreError("INVALID_REQUEST", "A completed job cannot change status", 400)
        if replacement.status == JobStatus.succeeded and replacement.progress != 100:
            raise BatchStoreError("INVALID_REQUEST", "A successful job must be at 100%", 400)
        if replacement.status == JobStatus.failed and replacement.stage.value == "completed":
            raise BatchStoreError(
                "INVALID_REQUEST", "A failed job cannot enter the completed stage", 400
            )

    @staticmethod
    def _snapshot(batch: Batch) -> Batch:
        return batch.model_copy(deep=True)

    @staticmethod
    def _parse_uuid(value: UUID | str) -> UUID | None:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            return None

    @classmethod
    def _require_uuid(cls, value: UUID | str, code: str, message: str) -> UUID:
        parsed = cls._parse_uuid(value)
        if parsed is None:
            raise BatchStoreError(code, message, 404)
        return parsed


__all__ = ["BatchStore", "BatchStoreError"]
