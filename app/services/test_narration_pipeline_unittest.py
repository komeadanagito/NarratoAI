import json
from pathlib import Path

import pytest

from app.models.batch_schema import NarrationOptions
from app.services.narration_pipeline import NarrationPipeline, NarrationPipelineError


class FakeFrameService:
    async def generate_documentary_script(self, **kwargs):
        kwargs["progress_callback"](50, "half")
        return [
            {
                "_id": 7,
                "timestamp": "00:00:00,000-00:00:01,000",
                "picture": "测试画面",
                "narration": "测试解说",
            }
        ]


def test_narration_pipeline_builds_seed_audio_params(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "combined.mp4"
    captured = {}

    def runner(task_id, params):
        captured["task_id"] = task_id
        captured["params"] = params
        output.write_bytes(b"result")
        return {"videos": [str(output)]}

    progress = []
    pipeline = NarrationPipeline(
        frame_service=FakeFrameService(),
        task_runner=runner,
        task_dir_factory=lambda task_id: str(tmp_path / task_id),
    )
    result = pipeline.process(
        source,
        task_id="job-1",
        options=NarrationOptions(
            enabled=True,
            language="zh-TW",
            voice_id="voice-a",
            voice_prompt="克制",
        ),
        progress_callback=lambda value, message: progress.append((value, message)),
    )

    assert result == output.resolve()
    params = captured["params"]
    assert params.tts_engine == "seed_audio"
    assert params.video_language == "zh-TW"
    assert params.voice_name == "voice-a"
    assert params.voice_prompt == "克制"
    script = json.loads(Path(params.video_clip_json_path).read_text(encoding="utf-8"))
    assert script[0]["OST"] == 2
    assert progress[-1][0] == 100


def test_narration_pipeline_rejects_empty_script(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    class EmptyFrameService:
        async def generate_documentary_script(self, **_kwargs):
            return []

    pipeline = NarrationPipeline(
        frame_service=EmptyFrameService(),
        task_runner=lambda *_args: {},
        task_dir_factory=lambda task_id: str(tmp_path / task_id),
    )
    with pytest.raises(NarrationPipelineError, match="没有返回"):
        pipeline.process(source, task_id="job-2", options=NarrationOptions(enabled=True))


@pytest.mark.parametrize(
    "timestamp",
    [
        "../../outside",
        "00:00:02,000-00:00:01,000",
        "00:00:00,000/../x-00:00:01,000",
    ],
)
def test_narration_pipeline_rejects_unsafe_timestamps(tmp_path, timestamp):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    class InvalidFrameService:
        async def generate_documentary_script(self, **_kwargs):
            return [{"timestamp": timestamp, "narration": "text"}]

    pipeline = NarrationPipeline(
        frame_service=InvalidFrameService(),
        task_runner=lambda *_args: {},
        task_dir_factory=lambda task_id: str(tmp_path / task_id),
    )
    with pytest.raises(NarrationPipelineError, match="时间戳|结束时间"):
        pipeline.process(source, task_id="job-3", options=NarrationOptions(enabled=True))


def test_narration_pipeline_rejects_overlapping_segments(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    class OverlapFrameService:
        async def generate_documentary_script(self, **_kwargs):
            return [
                {"timestamp": "00:00:00,000-00:00:02,000", "narration": "one"},
                {"timestamp": "00:00:01,000-00:00:03,000", "narration": "two"},
            ]

    pipeline = NarrationPipeline(
        frame_service=OverlapFrameService(),
        task_runner=lambda *_args: {},
        task_dir_factory=lambda task_id: str(tmp_path / task_id),
    )
    with pytest.raises(NarrationPipelineError, match="不能重叠"):
        pipeline.process(source, task_id="job-4", options=NarrationOptions(enabled=True))


def test_configuration_allows_request_voice_override(monkeypatch):
    monkeypatch.setattr(
        "app.services.narration_pipeline.config.app",
        {
            "vision_llm_provider": "openai",
            "vision_openai_api_key": "test",
            "vision_openai_model_name": "vision",
            "text_llm_provider": "openai",
            "text_openai_api_key": "test",
            "text_openai_model_name": "text",
        },
    )
    provider = type(
        "Provider",
        (),
        {"app_id": "app", "access_token": "token", "voice_type": ""},
    )()
    monkeypatch.setattr(
        "app.services.narration_pipeline.SeedAudioProvider.from_config",
        lambda: provider,
    )
    pipeline = NarrationPipeline(frame_service=object(), task_runner=lambda *_args: {})

    pipeline.validate_configuration(NarrationOptions(voice_id="request-voice"))
    with pytest.raises(NarrationPipelineError, match="voice_type"):
        pipeline.validate_configuration(NarrationOptions())
