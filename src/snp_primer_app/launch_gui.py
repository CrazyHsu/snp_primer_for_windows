from __future__ import annotations

import os
import traceback
from pathlib import Path


def _runtime_home() -> Path:
    env_value = os.environ.get("SNP_PRIMER_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return Path(__file__).resolve().parents[2] / "snp_primer_runtime"


def _error_log_path() -> Path:
    runtime_home = _runtime_home()
    runtime_home.mkdir(parents=True, exist_ok=True)
    return runtime_home / "desktop_startup_error.log"


def main() -> None:  # pragma: no cover - wrapper entry point
    try:
        # 用绝对 import，而不是 ``from .desktop import``：PyInstaller 打包后把本
        # 文件当 ``__main__`` 直接执行，``__package__`` 为空，相对 import 会抛
        # ``ImportError: attempted relative import with no known parent package``。
        # 绝对 import 在 ``python -m snp_primer_app.launch_gui`` 与 PyInstaller
        # bundle 两种场景下都成立。
        from snp_primer_app.desktop import main as desktop_main

        desktop_main()
    except Exception:
        error_log = _error_log_path()
        error_log.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":  # pragma: no cover - wrapper entry point
    main()
