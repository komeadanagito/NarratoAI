from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.models.batch_schema import (
    Batch,
    BatchStatus,
    Error,
    JobStage,
    JobStatus,
    VideoJob,
)
from app.services.batch_store import BatchStore, BatchStoreError


def make_job(file_name: str = "video.mp4") -> VideoJob:
    return VideoJob(
        id=uuid4(),
        upload_id=uuid4(),
        file_name=file_name,
        status=JobStatus.queued,
        stage=JobStage.queued,
        progress=0,
    )


def make_batch(*jobs: VideoJob) -> Batch:
    selected_jobs = list(jobs) or [make_job()]
    return Batch(
        id=uuid4(),
        status=BatchStatus.queued,
        progress=0,
        total=len(selected_jobs),
        succeeded=0,
        failed=0,
        jobs=selected_jobs,
    )


class BatchStoreTests(unittest.TestCase):
    def test_create_and_get_return_deep_snapshots(self) -> None:
        store = BatchStore()
        source = make_batch()

        created = store.create_batch(source)
        created.jobs[0].message = "mutated result"
        source.jobs[0].message = "mutated source"

        fetched = store.get_batch(source.id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertIsNone(fetched.jobs[0].message)
        fetched.jobs[0].message = "mutated fetch"
        self.assertIsNone(store.get_batch(source.id).jobs[0].message)  # type: ignore[union-attr]

    def test_update_job_aggregates_partial_success_and_terminal_progress(self) -> None:
        store = BatchStore()
        first, second = make_job("first.mp4"), make_job("second.mp4")
        batch = store.create_batch(make_batch(first, second))

        processing = store.update_job(
            batch.id,
            first.id,
            status=JobStatus.processing,
            stage=JobStage.processing,
            progress=50,
        )
        self.assertEqual(processing.status, BatchStatus.processing)
        self.assertEqual(processing.progress, 25)

        with_failure = store.update_job(
            batch.id,
            second.id,
            status=JobStatus.failed,
            progress=20,
            error=Error(code="PROCESSING_FAILED", message="failed"),
        )
        self.assertEqual(with_failure.failed, 1)
        self.assertEqual(with_failure.status, BatchStatus.processing)

        artifact_id = uuid4()
        finished = store.update_job(
            batch.id,
            first.id,
            status=JobStatus.succeeded,
            stage=JobStage.completed,
            progress=100,
            message="处理成功了",
            output_path="/allowed/result.mp4",
            artifact_id=artifact_id,
        )
        self.assertEqual(finished.status, BatchStatus.partially_succeeded)
        self.assertEqual(finished.progress, 100)
        self.assertEqual(finished.succeeded, 1)
        self.assertEqual(finished.failed, 1)

    def test_all_failed_batch_is_terminal_at_one_hundred(self) -> None:
        store = BatchStore()
        first, second = make_job(), make_job()
        batch = store.create(make_batch(first, second))
        store.update_job(batch.id, first.id, status=JobStatus.failed, progress=4)
        finished = store.update_job(batch.id, second.id, status=JobStatus.failed, progress=9)

        self.assertEqual(finished.status, BatchStatus.failed)
        self.assertEqual(finished.progress, 100)
        self.assertEqual(finished.failed, 2)

    def test_job_and_batch_progress_never_regress(self) -> None:
        store = BatchStore()
        batch = store.create_batch(make_batch())
        job_id = batch.jobs[0].id
        store.update_job(
            batch.id,
            job_id,
            status=JobStatus.processing,
            stage=JobStage.processing,
            progress=80,
        )
        snapshot = store.update_job(batch.id, job_id, progress=20)

        self.assertEqual(snapshot.jobs[0].progress, 80)
        self.assertEqual(snapshot.progress, 80)

    def test_concurrent_updates_do_not_lose_highest_progress(self) -> None:
        store = BatchStore()
        batch = store.create_batch(make_batch())
        job_id = batch.jobs[0].id

        def update(progress: int) -> None:
            store.update_job(
                batch.id,
                job_id,
                status=JobStatus.processing,
                stage=JobStage.processing,
                progress=progress,
            )

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(update, range(1, 100)))

        snapshot = store.get_batch(batch.id)
        assert snapshot is not None
        self.assertEqual(snapshot.jobs[0].progress, 99)
        self.assertEqual(snapshot.progress, 99)

    def test_rejects_invalid_create_update_and_terminal_transition(self) -> None:
        store = BatchStore()
        invalid_total = make_batch()
        invalid_total.total = 2
        with self.assertRaises(BatchStoreError):
            store.create_batch(invalid_total)

        batch = store.create_batch(make_batch())
        job_id = batch.jobs[0].id
        with self.assertRaises(BatchStoreError) as missing_batch:
            store.update_job(uuid4(), job_id, progress=1)
        self.assertEqual(missing_batch.exception.code, "BATCH_NOT_FOUND")
        with self.assertRaises(BatchStoreError) as missing_job:
            store.update_job(batch.id, uuid4(), progress=1)
        self.assertEqual(missing_job.exception.status_code, 404)

        store.update_job(
            batch.id,
            job_id,
            status=JobStatus.succeeded,
            stage=JobStage.completed,
            progress=100,
        )
        with self.assertRaises(BatchStoreError):
            store.update_job(batch.id, job_id, status=JobStatus.processing)

    def test_failed_job_cannot_enter_completed_stage(self) -> None:
        store = BatchStore()
        batch = store.create_batch(make_batch())
        with self.assertRaises(BatchStoreError):
            store.update_job(
                batch.id,
                batch.jobs[0].id,
                status=JobStatus.failed,
                stage=JobStage.completed,
            )


if __name__ == "__main__":
    unittest.main()
