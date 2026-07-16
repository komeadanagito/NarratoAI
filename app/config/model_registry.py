"""Load switchable model profiles from ``config/models.json``."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


MODEL_CONFIG_RELATIVE_PATH = Path("config/models.json")


class ModelConfigError(ValueError):
    pass


def load_model_config(project_root: str | Path) -> dict[str, Any]:
    path = Path(project_root) / MODEL_CONFIG_RELATIVE_PATH
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelConfigError(f"模型配置读取失败: {path}") from exc
    if not isinstance(payload, dict):
        raise ModelConfigError("模型配置根节点必须是 JSON object")
    return payload


def _profile(profiles: dict[str, Any], name: object, kind: str) -> dict[str, Any]:
    profile_name = str(name or "").strip()
    value = profiles.get(profile_name)
    if not profile_name or not isinstance(value, dict):
        raise ModelConfigError(f"active.{kind} 引用了不存在的配置: {profile_name!r}")
    return value


def apply_model_config(config_data: dict[str, Any], project_root: str | Path) -> dict[str, Any]:
    """Overlay active JSON profiles onto the legacy runtime config shape."""
    registry = load_model_config(project_root)
    if not registry:
        return config_data

    result = deepcopy(config_data)
    app = result.setdefault("app", {})
    if not isinstance(app, dict):
        raise ModelConfigError("app 配置必须是 object")

    active = registry.get("active") or {}
    llm_profiles = registry.get("llm_profiles") or {}
    if not isinstance(active, dict) or not isinstance(llm_profiles, dict):
        raise ModelConfigError("active 和 llm_profiles 必须是 object")

    for role in ("vision", "text"):
        profile = _profile(llm_profiles, active.get(role), role)
        provider = str(profile.get("provider") or "openai").strip().lower()
        models = profile.get("models") or {}
        model = models.get(role) if isinstance(models, dict) else None
        model = str(model or profile.get("model") or "").strip()
        base_url = str(profile.get("base_url") or "").strip()
        if not model or not base_url:
            raise ModelConfigError(f"{role} 模型配置缺少 model 或 base_url")

        prefix = f"{role}_{provider}"
        app[f"{role}_llm_provider"] = provider
        app[f"{prefix}_model_name"] = model
        app[f"{prefix}_base_url"] = base_url
        app[f"{prefix}_api_key_env"] = str(profile.get("api_key_env") or "").strip()
        if str(profile.get("api_key") or "").strip():
            app[f"{prefix}_api_key"] = str(profile["api_key"]).strip()

        generation = profile.get("generation") or {}
        if isinstance(generation, dict):
            for key in ("temperature", "top_p", "max_tokens", "thinking_level"):
                if key in generation:
                    app[f"{prefix}_{key}"] = generation[key]

    tts_profiles = registry.get("tts_profiles") or {}
    if not isinstance(tts_profiles, dict):
        raise ModelConfigError("tts_profiles 必须是 object")
    tts_profile = _profile(tts_profiles, active.get("tts"), "tts")
    if str(tts_profile.get("provider") or "").strip() != "seed_audio":
        raise ModelConfigError("当前批量解说仅支持 seed_audio TTS provider")
    result["seed_audio"] = deepcopy(tts_profile)
    return result


__all__ = ["MODEL_CONFIG_RELATIVE_PATH", "ModelConfigError", "apply_model_config", "load_model_config"]
