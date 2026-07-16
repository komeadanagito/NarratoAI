import os
import socket
import shutil
import tomllib

import tomli_w
from loguru import logger

from app.config.defaults import build_default_app_config, merge_missing_app_defaults
from app.config.model_registry import apply_model_config

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
config_file = f"{root_dir}/config.toml"
version_file = f"{root_dir}/project_version"
def get_version_from_file():
    """从project_version文件中读取版本号"""
    try:
        if os.path.isfile(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return "0.1.0"  # 默认版本号
    except Exception as e:
        logger.error(f"读取版本号文件失败: {str(e)}")
        return "0.1.0"  # 默认版本号


def load_config():
    # fix: IsADirectoryError: [Errno 21] Is a directory: '/NarratoAI/config.toml'
    if os.path.isdir(config_file):
        shutil.rmtree(config_file)

    if not os.path.isfile(config_file):
        _config_ = build_default_config()
        write_config_file(_config_)
        logger.info("create config.toml with shared defaults")
        return apply_model_config(_config_, root_dir)

    logger.info(f"load config from file: {config_file}")

    _config_ = load_toml_file(config_file)
    _config_["app"] = merge_missing_app_defaults(_config_.get("app", {}))
    return apply_model_config(_config_, root_dir)


def load_toml_file(file_path):
    """Load a TOML file and fall back to utf-8-sig when needed."""
    try:
        with open(file_path, "rb") as fp:
            return tomllib.load(fp)
    except Exception as e:
        logger.warning(f"load config failed: {str(e)}, try to load as utf-8-sig")
        with open(file_path, mode="r", encoding="utf-8-sig") as fp:
            _cfg_content = fp.read()
            return tomllib.loads(_cfg_content)


def build_default_config():
    """Build the initial config file content for a fresh installation."""
    example_file = f"{root_dir}/config.example.toml"
    config_data = {}
    if os.path.isfile(example_file):
        config_data = load_toml_file(example_file)

    config_data["app"] = build_default_app_config(config_data.get("app", {}))
    return config_data


def write_config_file(config_data):
    parent_dir = os.path.dirname(config_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with open(config_file, "w", encoding="utf-8") as f:
        f.write(tomli_w.dumps(config_data))


def save_config():
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(
            tomli_w.dumps(
                {
                    "app": app,
                    "seed_audio": seed_audio,
                    "ui": ui,
                    "frames": frames,
                    "fun_asr": fun_asr,
                    "backend": backend,
                }
            )
        )


_cfg = load_config()
app = _cfg.get("app", {})
ui = _cfg.get("ui", {})
frames = _cfg.get("frames", {})
fun_asr = _cfg.get("fun_asr", {})
seed_audio = _cfg.get("seed_audio", {})
backend = _cfg.get("backend", {})

hostname = socket.gethostname()

log_level = _cfg.get("log_level", "DEBUG")
listen_host = _cfg.get("listen_host", "0.0.0.0")
listen_port = _cfg.get("listen_port", 8080)
project_name = _cfg.get("project_name", "NarratoAI")
project_description = _cfg.get(
    "project_description",
    "<a href='https://github.com/linyqh/NarratoAI'>https://github.com/linyqh/NarratoAI</a>",
)
# 从文件读取版本号，而不是从配置文件中获取
project_version = get_version_from_file()
reload_debug = False

imagemagick_path = app.get("imagemagick_path", "")
if imagemagick_path and os.path.isfile(imagemagick_path):
    os.environ["IMAGEMAGICK_BINARY"] = imagemagick_path

_applied_ffmpeg_dir = None


def apply_ffmpeg_path(ffmpeg_binary: str = "") -> None:
    """Apply the configured FFmpeg binary to this Python process."""
    global _applied_ffmpeg_dir

    if not ffmpeg_binary or not os.path.isfile(ffmpeg_binary):
        return

    ffmpeg_binary = os.path.abspath(os.path.expanduser(ffmpeg_binary))
    ffmpeg_dir = os.path.dirname(ffmpeg_binary)
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_binary

    current_paths = os.environ.get("PATH", "").split(os.pathsep)
    normalized_ffmpeg_dir = os.path.normcase(os.path.abspath(ffmpeg_dir))
    normalized_previous_dir = (
        os.path.normcase(os.path.abspath(_applied_ffmpeg_dir))
        if _applied_ffmpeg_dir
        else None
    )
    filtered_paths = []
    for path_item in current_paths:
        if not path_item:
            continue
        normalized_item = os.path.normcase(os.path.abspath(path_item))
        if normalized_item == normalized_ffmpeg_dir:
            continue
        if normalized_previous_dir and normalized_item == normalized_previous_dir:
            continue
        filtered_paths.append(path_item)

    os.environ["PATH"] = os.pathsep.join([ffmpeg_dir, *filtered_paths])
    _applied_ffmpeg_dir = ffmpeg_dir


ffmpeg_path = app.get("ffmpeg_path", "")
apply_ffmpeg_path(ffmpeg_path)

logger.info(f"{project_name} v{project_version}")
