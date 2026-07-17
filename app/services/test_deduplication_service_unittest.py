import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.services.deduplication_service import (
    DeduplicationError,
    DeduplicationService,
)


def _probe_payload(*, has_audio=True, width=1920, height=1080, duration=12.5):
    streams = [
        {
            "codec_type": "video",
            "width": width,
            "height": height,
            "duration": str(duration),
        }
    ]
    if has_audio:
        streams.append({"codec_type": "audio"})
    return json.dumps({"streams": streams, "format": {"duration": str(duration)}})


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRunner:
    def __init__(
        self,
        *,
        has_audio=True,
        ffmpeg_returncode=0,
        ffmpeg_stderr="",
        create_output=True,
        input_probe_returncode=0,
        output_probe_returncode=0,
        output_probe_payload=None,
    ):
        self.has_audio = has_audio
        self.ffmpeg_returncode = ffmpeg_returncode
        self.ffmpeg_stderr = ffmpeg_stderr
        self.create_output = create_output
        self.input_probe_returncode = input_probe_returncode
        self.output_probe_returncode = output_probe_returncode
        self.output_probe_payload = output_probe_payload
        self.calls = []
        self.probe_count = 0

    @property
    def ffmpeg_call(self):
        return next(call for call in self.calls if call[0][0] == "ffmpeg")

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == "ffprobe":
            self.probe_count += 1
            if self.probe_count == 1:
                if self.input_probe_returncode:
                    return _Result(self.input_probe_returncode, stderr="bad source")
                return _Result(stdout=_probe_payload(has_audio=self.has_audio))
            if self.output_probe_returncode:
                return _Result(self.output_probe_returncode, stderr="bad output")
            return _Result(
                stdout=self.output_probe_payload
                if self.output_probe_payload is not None
                else _probe_payload(has_audio=self.has_audio)
            )

        if command[0] == "ffmpeg":
            if self.ffmpeg_returncode == 0 and self.create_output:
                Path(command[-1]).write_bytes(b"fake-video")
            return _Result(self.ffmpeg_returncode, stderr=self.ffmpeg_stderr)
        raise AssertionError(f"unexpected binary: {command[0]}")


class _FixedRandom:
    def __init__(self, *, decision=0.25):
        self.decision = decision

    @staticmethod
    def uniform(low, high):
        return low + (high - low) * 0.4

    def random(self):
        return self.decision

    @staticmethod
    def choice(values):
        return values[0]

    @staticmethod
    def getrandbits(bits):
        return 0xA5


class DeduplicationServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.input = self.root / "source video;not-a-command.mp4"
        self.input.write_bytes(b"input")

    def tearDown(self):
        self.temp_directory.cleanup()

    def _service(self, runner, **kwargs):
        return DeduplicationService(
            runner=runner,
            random_source=_FixedRandom(),
            **kwargs,
        )

    def _apply(self, runner, options, *, name="result.mp4", service_kwargs=None, callback=None):
        output = self.root / name
        result = self._service(runner, **(service_kwargs or {})).apply(
            str(self.input),
            str(output),
            options,
            progress_callback=callback,
        )
        return output, result, runner.ffmpeg_call

    def test_no_filters_and_no_reencode_uses_safe_remux(self):
        runner = _FakeRunner()
        events = []
        output, result, (command, kwargs) = self._apply(
            runner,
            {
                "change_file_hash": True,
                "reencode": False,
                "border_mode": "none",
            },
            callback=lambda progress, message: events.append((progress, message)),
        )

        self.assertEqual(result, str(output.resolve()))
        self.assertTrue(output.is_file())
        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertNotIn("-filter_complex", command)
        self.assertIn("0:a:0", command)
        self.assertIn(str(self.input.resolve()), command)
        self.assertEqual(command.count(str(self.input.resolve())), 1)
        self.assertIn("-metadata", command)
        self.assertTrue(command[command.index("-metadata") + 1].startswith("comment=NarratoAI dedup "))
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 3600)
        self.assertEqual([event[0] for event in events], [0, 10, 90, 100])
        self.assertTrue(all(isinstance(call[0], list) for call in runner.calls))

    def test_all_visual_filters_and_audio_speed_are_composed_in_one_graph(self):
        sticker_root = self.root / "stickers"
        sticker_root.mkdir()
        sticker = sticker_root / "approved.png"
        sticker.write_bytes(b"png")
        (sticker_root / "ignored.jpg").write_bytes(b"jpg")
        runner = _FakeRunner(has_audio=True)

        _, _, (command, _) = self._apply(
            runner,
            {
                "change_file_hash": False,
                "reencode": False,
                "color_noise_tweak": True,
                "border_mode": "blurred",
                "sticker": True,
                "subtitle_mask": True,
                "crop_scale": True,
                "mirror": True,
                "speed_tweak": True,
            },
            service_kwargs={"sticker_directory": sticker_root},
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("eq=brightness=", graph)
        self.assertIn("noise=alls=", graph)
        self.assertIn("crop=", graph)
        self.assertIn("hflip", graph)
        self.assertIn("boxblur=", graph)
        self.assertIn("overlay=", graph)
        self.assertIn("colorchannelmixer=aa=", graph)
        self.assertIn("setpts=PTS/", graph)
        self.assertIn("[0:a:0]atempo=", graph)
        self.assertIn(str(sticker.resolve()), command)
        self.assertNotIn("-loop", command)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-threads") + 1], "2")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        self.assertNotIn("-metadata", command)

    def test_speed_tweak_without_audio_omits_audio_filter_and_succeeds(self):
        runner = _FakeRunner(has_audio=False)
        output, _, (command, _) = self._apply(
            runner,
            {
                "reencode": False,
                "change_file_hash": False,
                "border_mode": "none",
                "speed_tweak": True,
            },
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/", graph)
        self.assertNotIn("[0:a:0]", graph)
        self.assertIn("-an", command)
        self.assertTrue(output.exists())

    def test_solid_border_forces_video_encoding(self):
        runner = _FakeRunner()
        _, _, (command, _) = self._apply(
            runner,
            {
                "change_file_hash": False,
                "reencode": False,
                "border_mode": "solid",
            },
        )
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("pad=", graph)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")

    def test_sticker_has_builtin_fallback_when_optional_assets_are_absent(self):
        runner = _FakeRunner()
        _, _, (command, _) = self._apply(
            runner,
            {
                "change_file_hash": False,
                "reencode": False,
                "border_mode": "none",
                "sticker": True,
            },
        )
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("drawbox=", graph)
        self.assertEqual(command.count("-i"), 1)

    def test_mirror_false_never_adds_hflip(self):
        runner = _FakeRunner()
        _, _, (command, _) = self._apply(
            runner,
            {
                "change_file_hash": False,
                "reencode": True,
                "border_mode": "none",
                "mirror": False,
            },
        )
        self.assertNotIn("-filter_complex", command)
        self.assertNotIn("hflip", " ".join(command))

    def test_sticker_rejects_non_png_and_symlink_escape(self):
        sticker_root = self.root / "stickers"
        sticker_root.mkdir()
        (sticker_root / "not-approved.jpg").write_bytes(b"jpg")
        outside = self.root / "outside.png"
        outside.write_bytes(b"png")
        try:
            os.symlink(outside, sticker_root / "escape.png")
        except OSError:
            self.skipTest("symlinks are unavailable")
        runner = _FakeRunner()
        with self.assertRaises(DeduplicationError) as context:
            self._apply(
                runner,
                {"border_mode": "none", "sticker": True},
                service_kwargs={"sticker_directory": sticker_root},
            )
        self.assertEqual(context.exception.code, "PROCESSING_FAILED")
        self.assertNotIn("ffmpeg", [call[0][0] for call in runner.calls])

    def test_invalid_options_map_to_invalid_request(self):
        for options in (
            {"border_mode": "rainbow"},
            {"border_mode": "none", "speed_tweak": "yes"},
        ):
            with self.subTest(options=options):
                with self.assertRaises(DeduplicationError) as context:
                    self._service(_FakeRunner()).apply(
                        str(self.input), str(self.root / "out.mp4"), options
                    )
                self.assertEqual(context.exception.code, "INVALID_REQUEST")

    def test_missing_and_invalid_inputs_map_to_unsupported_media(self):
        service = self._service(_FakeRunner())
        with self.assertRaises(DeduplicationError) as missing:
            service.apply(
                str(self.root / "missing.mp4"),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(missing.exception.code, "UNSUPPORTED_MEDIA")

        with self.assertRaises(DeduplicationError) as invalid:
            self._service(_FakeRunner(input_probe_returncode=1)).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(invalid.exception.code, "UNSUPPORTED_MEDIA")

    def test_ffmpeg_failure_maps_to_processing_failed_and_cleans_temp(self):
        runner = _FakeRunner(ffmpeg_returncode=1, ffmpeg_stderr="encoder exploded")
        with self.assertRaises(DeduplicationError) as context:
            self._service(runner).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(context.exception.code, "PROCESSING_FAILED")
        self.assertIn("encoder exploded", context.exception.message)
        self.assertEqual(list(self.root.glob("*.part.mp4")), [])

    def test_success_without_output_file_maps_to_processing_failed(self):
        runner = _FakeRunner(create_output=False)
        with self.assertRaises(DeduplicationError) as context:
            self._service(runner).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(context.exception.code, "PROCESSING_FAILED")
        self.assertEqual(runner.probe_count, 1)

    def test_invalid_generated_media_maps_to_processing_failed(self):
        runner = _FakeRunner(output_probe_returncode=1)
        with self.assertRaises(DeduplicationError) as context:
            self._service(runner).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(context.exception.code, "PROCESSING_FAILED")
        self.assertFalse((self.root / "out.mp4").exists())

    def test_path_validation_prevents_overwrite_and_unsafe_destinations(self):
        existing = self.root / "existing.mp4"
        existing.write_bytes(b"keep-me")
        cases = [
            (str(self.input), str(self.input)),
            (str(self.input), str(existing)),
            (str(self.input), str(self.root / "output.exe")),
            (str(self.input), str(self.root / "missing-dir" / "output.mp4")),
        ]
        for source, destination in cases:
            with self.subTest(destination=destination):
                with self.assertRaises(DeduplicationError) as context:
                    self._service(_FakeRunner()).apply(
                        source, destination, {"border_mode": "none"}
                    )
                self.assertEqual(context.exception.code, "INVALID_REQUEST")
        self.assertEqual(existing.read_bytes(), b"keep-me")

    def test_progress_callback_failure_does_not_fail_processing(self):
        runner = _FakeRunner()

        def broken_callback(_progress, _message):
            raise RuntimeError("UI disconnected")

        output, result, _ = self._apply(
            runner,
            {"border_mode": "none"},
            callback=broken_callback,
        )
        self.assertEqual(result, str(output.resolve()))

    def test_runner_os_error_maps_to_domain_error(self):
        def missing_binary(_command, **_kwargs):
            raise FileNotFoundError("ffprobe")

        with self.assertRaises(DeduplicationError) as context:
            DeduplicationService(runner=missing_binary).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(context.exception.code, "UNSUPPORTED_MEDIA")

    def test_ffmpeg_timeout_maps_to_processing_failed(self):
        runner = _FakeRunner()

        def timeout_on_ffmpeg(command, **kwargs):
            if command[0] == "ffmpeg":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return runner(command, **kwargs)

        with self.assertRaises(DeduplicationError) as context:
            self._service(timeout_on_ffmpeg, process_timeout=30).apply(
                str(self.input),
                str(self.root / "out.mp4"),
                {"border_mode": "none"},
            )
        self.assertEqual(context.exception.code, "PROCESSING_FAILED")


if __name__ == "__main__":
    unittest.main()
