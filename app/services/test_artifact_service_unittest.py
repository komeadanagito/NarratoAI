from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services.artifact_service import ArtifactService, ArtifactServiceError


class ArtifactServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.root = self.base / "outputs"
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.service = ArtifactService([self.root])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_registers_regular_file_and_revalidates_on_lookup(self) -> None:
        video = self.root / "batch" / "result.mp4"
        video.parent.mkdir()
        video.write_bytes(b"video")

        artifact = self.service.register(video, file_name="../download.mp4")

        self.assertEqual(artifact.file_name, "download.mp4")
        self.assertEqual(artifact.media_type, "video/mp4")
        self.assertEqual(artifact.path, video.resolve())
        self.assertEqual(self.service.get_artifact(str(artifact.id)), artifact)

        video.unlink()
        self.assertIsNone(self.service.get_artifact(artifact.id))

    def test_rejects_outside_files_directories_and_symlinks(self) -> None:
        outside_file = self.outside / "outside.mp4"
        outside_file.write_bytes(b"video")
        with self.assertRaises(ArtifactServiceError) as outside_error:
            self.service.register(outside_file)
        self.assertEqual(outside_error.exception.code, "OUTPUT_PATH_NOT_ALLOWED")
        self.assertEqual(outside_error.exception.status_code, 400)

        with self.assertRaises(ArtifactServiceError):
            self.service.register(self.root)

        link = self.root / "link.mp4"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(ArtifactServiceError):
            self.service.register(link)

    def test_lookup_rejects_file_replaced_by_outside_symlink(self) -> None:
        video = self.root / "result.mp4"
        video.write_bytes(b"video")
        artifact = self.service.register(video)
        outside_file = self.outside / "replacement.mp4"
        outside_file.write_bytes(b"replacement")
        video.unlink()
        try:
            video.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are unavailable")

        self.assertIsNone(self.service.get_artifact(artifact.id))

    def test_resolve_output_directory_creates_only_allowed_children(self) -> None:
        target = self.service.resolve_output_directory(self.root / "batch" / "nested")
        self.assertEqual(target, (self.root / "batch" / "nested").resolve())
        self.assertTrue(target.is_dir())

        with self.assertRaises(ArtifactServiceError):
            self.service.resolve_output_directory(self.root / "batch" / ".." / "other")
        with self.assertRaises(ArtifactServiceError):
            self.service.resolve_output_directory(self.outside)
        with self.assertRaises(ArtifactServiceError):
            self.service.resolve_output_directory("   ")

        ordinary_file = self.root / "not-a-directory"
        ordinary_file.write_text("x", encoding="utf-8")
        with self.assertRaises(ArtifactServiceError):
            self.service.resolve_output_directory(ordinary_file)

    def test_resolve_output_directory_rejects_escaping_directory_symlink(self) -> None:
        link = self.root / "escape"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(ArtifactServiceError):
            self.service.resolve_output_directory(link / "child")

    def test_concurrent_registration_has_unique_stable_ids(self) -> None:
        files = []
        for index in range(40):
            path = self.root / f"{index}.mp4"
            path.write_bytes(b"video")
            files.append(path)

        with ThreadPoolExecutor(max_workers=8) as executor:
            artifacts = list(executor.map(self.service.register, files))

        self.assertEqual(len({artifact.id for artifact in artifacts}), len(files))
        self.assertTrue(all(self.service.get_artifact(item.id) == item for item in artifacts))


if __name__ == "__main__":
    unittest.main()
