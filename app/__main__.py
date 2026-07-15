"""NarratoAI local batch API entry point."""

from __future__ import annotations

import argparse
import json


def _run_check() -> None:
    from app.services.llm.manager import LLMServiceManager
    from app.services.llm.providers import register_all_providers

    register_all_providers()
    print(
        json.dumps(
            {
                "status": "ready",
                "mode": "headless",
                "message": "NarratoAI core is ready; no web console is bundled.",
                "providers": LLMServiceManager.get_registered_providers_info(),
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    from app.services.backend_settings import BackendSettings

    settings = BackendSettings.load()
    parser = argparse.ArgumentParser(description="NarratoAI batch video API")
    parser.add_argument("--check", action="store_true", help="只检查核心模块并输出 JSON")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发模式下自动重载")
    args = parser.parse_args()

    if args.check:
        _run_check()
        return

    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
