from __future__ import annotations

import os
import shutil
import sys
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


def _stage_bundled_binaries_if_needed() -> None:
    """PyInstaller --onefile 模式下，把 bundle 里的 ``_MEIPASS/bin/`` 拷到
    ``<exe_dir>/bin/``，让后续 subprocess 从一个**与 PyInstaller _MEIPASS 完全
    隔离的目录**启动 NCBI .exe。

    为什么需要：``--onefile`` 把整个 bundle 解压到 ``%TEMP%\\_MEIxxxxxx\\``，
    我们的 NCBI binaries 落在 ``_MEIxxxxxx/bin/``，PyInstaller 自己带的
    ``MSVCP140.dll`` / ``VCRUNTIME140.dll`` / ``api-ms-win-*.dll`` 落在
    ``_MEIxxxxxx/`` 根。这两层共享同一个父目录，即便 PATH 把 ``_MEIPASS`` 剔
    掉，Windows DLL search / process loader 在某些情况下仍然把上一层的 DLL
    误吞下去——makeblastdb / blastn 启动时撞 0xC0000005（access violation）
    然后无 stderr。``--onedir`` 模式不出这事是因为 binaries 已经在 ``<exe_dir>/bin/``
    里，跟 ``_internal/`` 是兄弟目录而不是父子。

    解决：第一次启动时把 binaries 从 ``_MEIPASS/bin/`` 拷到 ``<exe_dir>/bin/``，
    以后就跟 onedir 模式一样了。这会让单 .exe 旁边出现 ~55MB 的 ``bin/`` 文件夹，
    但只是一次性的——是 ``--onefile`` 在 Windows 上 reliability 的代价。
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    src = Path(meipass) / "bin"
    if not src.is_dir():
        return  # onedir：binaries 已在 <exe_dir>/bin/，无需 staging
    try:
        exe_dir = Path(sys.executable).resolve().parent
    except OSError:
        return
    dst = exe_dir / "bin"
    if dst.is_dir() and any(dst.iterdir()):
        return  # 已经 stage 过（之前某次启动）
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(str(f), str(dst / f.name))
    except OSError:
        # 拷贝失败也别让 GUI 起不来——_default_bin 还有 _MEIPASS/bin fallback，
        # 即便那条路径还是会撞 0xC0000005，至少 GUI 启得来用户能看 placeholder。
        pass


def main() -> None:  # pragma: no cover - wrapper entry point
    try:
        # PyInstaller --onefile 下需要先把 bundle 里的 NCBI binaries stage 到
        # 稳定目录，否则 makeblastdb 会 0xC0000005 崩溃（详见函数 docstring）。
        _stage_bundled_binaries_if_needed()
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
