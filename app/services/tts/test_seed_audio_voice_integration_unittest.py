import pytest

from app.services import voice
from app.services.tts import SeedAudioError


def test_seed_audio_voice_adapter_does_not_swallow_provider_error(tmp_path):
    class FailingProvider:
        def synthesize(self, *_args, **_kwargs):
            raise SeedAudioError("upstream unavailable")

    with pytest.raises(SeedAudioError, match="upstream unavailable"):
        voice.seed_audio_tts(
            "hello",
            "voice",
            str(tmp_path / "voice.mp3"),
            provider=FailingProvider(),
        )
