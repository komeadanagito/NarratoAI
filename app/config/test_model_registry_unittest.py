import json
from pathlib import Path

import pytest

from app.config.model_registry import ModelConfigError, apply_model_config


def _write_registry(root: Path, payload: dict) -> None:
    config_dir = root / "config"
    config_dir.mkdir()
    (config_dir / "models.json").write_text(json.dumps(payload), encoding="utf-8")


def test_active_openai_profile_is_flattened_for_existing_llm_services(tmp_path):
    _write_registry(
        tmp_path,
        {
            "active": {"vision": "ark", "text": "ark", "tts": "seed"},
            "llm_profiles": {
                "ark": {
                    "provider": "openai",
                    "api_key_env": "ARK_KEY",
                    "base_url": "https://ark.example/api/v3",
                    "models": {"vision": "vision-model", "text": "text-model"},
                    "generation": {"temperature": 0.2},
                }
            },
            "tts_profiles": {
                "seed": {
                    "provider": "seed_audio",
                    "api_key_env": "SEED_KEY",
                    "api_url": "https://speech.example/api/v3/tts/create",
                    "model": "seed-audio-1.0",
                }
            },
        },
    )

    result = apply_model_config({"app": {}}, tmp_path)

    assert result["app"]["vision_llm_provider"] == "openai"
    assert result["app"]["vision_openai_model_name"] == "vision-model"
    assert result["app"]["text_openai_model_name"] == "text-model"
    assert result["app"]["vision_openai_api_key_env"] == "ARK_KEY"
    assert result["app"]["vision_openai_temperature"] == 0.2
    assert result["seed_audio"]["api_url"].endswith("/api/v3/tts/create")


def test_empty_tts_profile_key_preserves_machine_local_key(tmp_path):
    _write_registry(
        tmp_path,
        {
            "active": {"vision": "ark", "text": "ark", "tts": "seed"},
            "llm_profiles": {
                "ark": {
                    "provider": "openai",
                    "base_url": "https://ark.example/api/v3",
                    "models": {"vision": "vision-model", "text": "text-model"},
                }
            },
            "tts_profiles": {
                "seed": {
                    "provider": "seed_audio",
                    "api_key_env": "SEED_KEY",
                    "api_key": "",
                    "api_url": "https://speech.example/api/v3/tts/create",
                    "model": "seed-audio-1.0",
                }
            },
        },
    )

    result = apply_model_config(
        {"app": {}, "seed_audio": {"api_key": "machine-local-key"}},
        tmp_path,
    )

    assert result["seed_audio"]["api_key"] == "machine-local-key"


def test_unknown_active_profile_fails_fast(tmp_path):
    _write_registry(
        tmp_path,
        {
            "active": {"vision": "missing", "text": "missing", "tts": "missing"},
            "llm_profiles": {},
            "tts_profiles": {},
        },
    )
    with pytest.raises(ModelConfigError, match="不存在"):
        apply_model_config({"app": {}}, tmp_path)
