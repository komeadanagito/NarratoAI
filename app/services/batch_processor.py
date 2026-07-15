"""Background orchestration for batch video jobs.

The public ``concurrency`` value is intentionally not capped by a server-wide
worker limit.  Each accepted batch may run exactly as many jobs in parallel as
the caller requested (up to the number of videos in that batch).
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Condition, RLock, Thread, current_thread
from typing import Any
from uuid import UUID, uuid4

from app.models.batch_schema import (
    Batch,
    BatchCreateRequest,
    BatchStatus,
    Error,
    JobStage,
    JobStatus,
    VideoJob,
)
from app.services.deduplication_service import DeduplicationService
from app.services.narration_pipeline import NarrationPipeline


class BatchProcessorError(RuntimeError):
    """A synchronous batch-creation error suitable for the HTTP mapper."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class _PendingJob:
    job_id: UUID
    upload: Any
    # A slot represents a queued (not running) job. Running threads are not
    # limited, per the public API contract.
    queued_slot: bool = False


@dataclass(slots=True)
class _BatchContext:
    batch_id: UUID
    request: BatchCreateRequest
    output_directory: Path
    pending: deque[_PendingJob]
    concurrency: int
    active: int = 0


class BatchProcessor:
    """Run each batch with its requested, uncapped level of concurrency.

    ``queue_capacity`` only bounds jobs waiting behind a batch's active jobs;
    it never caps the number of running threads. ``max_workers`` is accepted as
    a deprecated compatibility argument and deliberately ignored.
    """

    def __init__(
        self,
        *,
        upload_service: Any,
        batch_store: Any,
        artifact_service: Any,
        deduplication_service: Any | None = None,
        narration_pipeline: Any | None = None,
        max_workers: int | None = None,
        queue_capacity: int = 32,
    ) -> None:
        if queue_capacity < 0:
            raise ValueError("queue_capacity cannot be negative")
        self.upload_service = upload_service
        self.batch_store = batch_store
        self.artifact_service = artifact_service
        self.deduplication_service = deduplication_service or DeduplicationService()
        self.narration_pipeline = narration_pipeline or NarrationPipeline()
        self.queue_capacity = int(queue_capacity)
        # Keep the attribute for callers that introspect older deployments,
        # but never use it to clamp request concurrency.
        self.max_workers = None
        _ = max_workers
        self._slots = BoundedSemaphore(self.queue_capacity)
        self._lock = RLock()
        self._idle = Condition(self._lock)
        self._contexts: dict[UUID, _BatchContext] = {}
        self._threads: set[Thread] = set()
        self._shutdown = False
        self._cancel_pending = False

    def create_batch(self, request: BatchCreateRequest) -> Batch:
        """Validate, initialize, enqueue, and immediately return a snapshot."""

        if not isinstance(request, BatchCreateRequest):
            request = BatchCreateRequest.model_validate(request)
        request = request.model_copy(deep=True)

        with self._lock:
            if self._shutdown:
                raise BatchProcessorError("SERVICE_UNAVAILABLE", "Batch processor is stopping", 503)

        if request.narration.enabled:
            validate_provider = getattr(self.narration_pipeline, "validate_configuration", None)
            if callable(validate_provider):
                validate_provider(request.narration)

        uploads = []
        for upload_id in request.upload_ids:
            upload = self.upload_service.get_upload(upload_id)
            if upload is None:
                raise BatchProcessorError("UPLOAD_NOT_FOUND", "Upload not found", 404)
            uploads.append(upload)

        output_directory = self.artifact_service.resolve_output_directory(
            request.output_directory,
            create=True,
        )
        queued_count = max(0, len(uploads) - int(request.concurrency))
        if not self._reserve_slots(queued_count):
            raise BatchProcessorError("QUEUE_FULL", "Batch processing queue is full", 429)

        batch_id = uuid4()
        jobs = [
            VideoJob(
                id=uuid4(),
                upload_id=upload.id,
                file_name=upload.file_name,
                status=JobStatus.queued,
                stage=JobStage.queued,
                progress=0,
                message="等待处理",
            )
            for upload in uploads
        ]
        batch = Batch(
            id=batch_id,
            status=BatchStatus.queued,
            progress=0,
            total=len(jobs),
            succeeded=0,
            failed=0,
            jobs=jobs,
        )

        context: _BatchContext | None = None
        context_registered = False
        try:
            with self._lock:
                # Close the race between the early validation and executor
                # shutdown while uploads/output paths were being resolved.
                if self._shutdown:
                    raise BatchProcessorError(
                        "SERVICE_UNAVAILABLE", "Batch processor is stopping", 503
                    )
                snapshot = self.batch_store.create_batch(batch)
                context = _BatchContext(
                    batch_id=batch_id,
                    request=request,
                    output_directory=output_directory,
                    pending=deque(
                        _PendingJob(
                            job_id=job.id,
                            upload=upload,
                            queued_slot=index >= request.concurrency,
                        )
                        for index, (job, upload) in enumerate(
                            zip(jobs, uploads, strict=True)
                        )
                    ),
                    concurrency=request.concurrency,
                )
                self._contexts[batch_id] = context
                context_registered = True
                self._schedule_available_locked(context)
            return snapshot
        except Exception:
            # Once registered, scheduling owns every queued reservation and
            # will release it when the job starts or is cancelled.
            if not context_registered:
                self._release_slots(queued_count)
            raise

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting batches and optionally finish every accepted job."""

        with self._idle:
            self._shutdown = True
            if not wait:
                self._cancel_pending = True
                for context in list(self._contexts.values()):
                    while context.pending:
                        pending = context.pending.popleft()
                        if pending.queued_slot:
                            self._slots.release()
                        self._mark_cancelled(context.batch_id, pending.job_id)
                    if context.active == 0:
                        self._contexts.pop(context.batch_id, None)
                self._idle.notify_all()
                return
            self._idle.wait_for(lambda: not self._contexts)

    def _reserve_slots(self, count: int) -> bool:
        acquired = 0
        for _ in range(count):
            if not self._slots.acquire(blocking=False):
                for _ in range(acquired):
                    self._slots.release()
                return False
            acquired += 1
        return True

    def _release_slots(self, count: int) -> None:
        for _ in range(count):
            self._slots.release()

    def _schedule_available_locked(self, context: _BatchContext) -> None:
        while (
            not self._cancel_pending
            and context.pending
            and context.active < context.concurrency
        ):
            pending_job = context.pending.popleft()
            context.active += 1
            worker = Thread(
                target=self._execute_and_continue,
                args=(context, pending_job),
                name=f"narrato-{str(pending_job.job_id)[:8]}",
                daemon=False,
            )
            self._threads.add(worker)
            try:
                worker.start()
            except Exception:
                self._threads.discard(worker)
                context.active -= 1
                if pending_job.queued_slot:
                    self._slots.release()
                self._update(
                    context.batch_id,
                    pending_job.job_id,
                    status=JobStatus.failed,
                    progress=100,
                    message="处理失败",
                    error=Error(code="PROCESSING_FAILED", message="视频处理失败"),
                )
                continue
            if pending_job.queued_slot:
                # The job is now running, so it no longer consumes pending
                # queue capacity.
                self._slots.release()

    def _execute_and_continue(self, context: _BatchContext, pending: _PendingJob) -> None:
        try:
            self._process_job(context, pending)
        finally:
            with self._idle:
                self._threads.discard(current_thread())
                context.active -= 1
                self._schedule_available_locked(context)
                if not context.pending and context.active == 0:
                    self._contexts.pop(context.batch_id, None)
                    self._idle.notify_all()

    def _mark_cancelled(self, batch_id: UUID, job_id: UUID) -> None:
        try:
            self._update(
                batch_id,
                job_id,
                status=JobStatus.failed,
                progress=100,
                message="服务正在关闭",
                error=Error(code="PROCESSING_FAILED", message="视频处理已取消"),
            )
        except Exception:
            # Shutdown must continue even if a store implementation rejects a
            # terminal update. Running jobs are unaffected.
            pass

    def _process_job(self, context: _BatchContext, pending: _PendingJob) -> None:
        request = context.request
        batch_id = context.batch_id
        job_id = pending.job_id
        source_path = Path(pending.upload.stored_path)
        current_input = source_path

        try:
            if request.narration.enabled:
                self._update(
                    batch_id,
                    job_id,
                    status=JobStatus.processing,
                    stage=JobStage.analyzing,
                    progress=1,
                    message="正在分析视频",
                )

                def narration_progress(value: float, message: str) -> None:
                    numeric = max(0.0, min(100.0, float(value)))
                    stage = JobStage.analyzing if numeric < 80 else JobStage.synthesizing
                    self._update(
                        batch_id,
                        job_id,
                        status=JobStatus.processing,
                        stage=stage,
                        progress=min(70, 5 + int(numeric * 0.65)),
                        message=message,
                    )

                current_input = Path(
                    self.narration_pipeline.process(
                        source_path,
                        task_id=f"{batch_id}/{job_id}",
                        options=request.narration,
                        progress_callback=narration_progress,
                    )
                )
                transform_start = 70
            else:
                self._update(
                    batch_id,
                    job_id,
                    status=JobStatus.processing,
                    stage=JobStage.processing,
                    progress=5,
                    message="正在处理视频",
                )
                transform_start = 10

            verified_output_directory = self.artifact_service.resolve_output_directory(
                str(context.output_directory),
                create=False,
            )
            if verified_output_directory != context.output_directory:
                raise BatchProcessorError(
                    "INVALID_REQUEST", "Output directory changed during processing", 400
                )
            destination = verified_output_directory / self._output_file_name(
                pending.upload.file_name,
                job_id,
            )

            def transform_progress(value: int, message: str) -> None:
                numeric = max(0.0, min(100.0, float(value)))
                mapped = transform_start + int(numeric * (95 - transform_start) / 100)
                self._update(
                    batch_id,
                    job_id,
                    status=JobStatus.processing,
                    stage=JobStage.processing,
                    progress=mapped,
                    message=message,
                )

            final_path = self.deduplication_service.apply(
                str(current_input),
                str(destination),
                request.deduplication,
                progress_callback=transform_progress,
            )
            self._update(
                batch_id,
                job_id,
                status=JobStatus.processing,
                stage=JobStage.processing,
                progress=98,
                message="正在注册处理结果",
            )
            artifact = self.artifact_service.register(
                final_path,
                file_name=Path(final_path).name,
                media_type="video/mp4",
            )
            self._update(
                batch_id,
                job_id,
                status=JobStatus.succeeded,
                stage=JobStage.completed,
                progress=100,
                message="处理成功了",
                output_path=str(Path(final_path).resolve()),
                artifact_id=artifact.id,
                error=None,
            )
        except Exception as exc:
            code, message = self._public_error(exc)
            try:
                self._update(
                    batch_id,
                    job_id,
                    status=JobStatus.failed,
                    progress=100,
                    message="处理失败",
                    error=Error(code=code, message=message),
                )
            except Exception:
                # The original failure is already represented as far as the
                # store permits; never terminate another job in this batch.
                pass

    def _update(self, batch_id: UUID, job_id: UUID, **changes: Any) -> Batch:
        return self.batch_store.update_job(batch_id, job_id, **changes)

    @staticmethod
    def _output_file_name(source_name: str, job_id: UUID) -> str:
        stem = Path(str(source_name)).stem
        safe = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._")
        safe = safe[:80] or "video"
        return f"{safe}_{str(job_id)[:8]}.mp4"

    @staticmethod
    def _public_error(exc: Exception) -> tuple[str, str]:
        code = str(getattr(exc, "code", "PROCESSING_FAILED") or "PROCESSING_FAILED")
        if code not in {
            "INVALID_REQUEST",
            "UNSUPPORTED_MEDIA",
            "PROVIDER_NOT_CONFIGURED",
            "UPSTREAM_FAILED",
            "PROCESSING_FAILED",
        }:
            code = "PROCESSING_FAILED"
        messages = {
            "INVALID_REQUEST": "视频处理参数或输出路径无效",
            "UNSUPPORTED_MEDIA": "上传文件不是可处理的视频",
            "PROVIDER_NOT_CONFIGURED": "AI 解说服务未完整配置",
            "UPSTREAM_FAILED": "AI 解说上游服务调用失败",
            "PROCESSING_FAILED": "视频处理失败",
        }
        return code, messages[code]


__all__ = ["BatchProcessor", "BatchProcessorError"]
