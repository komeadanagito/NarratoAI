from pathlib import Path

from app.services.backend_settings import BackendSettings


def test_backend_settings_defaults_are_project_scoped(monkeypatch):
    monkeypatch.setattr("app.services.backend_settings.config.backend", {})
    settings = BackendSettings.load()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.upload_directory.is_absolute()
    assert settings.allowed_output_roots[0].is_absolute()
    assert settings.upload_directory == Path("storage/uploads").resolve()
    assert settings.allowed_video_extensions == (".mov", ".mp4")


def test_backend_settings_honors_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NARRATO_BACKEND_PORT", "9001")
    monkeypatch.setenv("NARRATO_BACKEND_ALLOWED_OUTPUT_ROOTS", str(tmp_path))
    settings = BackendSettings.load()

    assert settings.port == 9001
    assert settings.allowed_output_roots == (tmp_path.resolve(),)
    assert not hasattr(settings, "max_batch_workers")
