from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIRNAME = "SNPPrimer"
FASTA_SUFFIXES = (".fa", ".fasta", ".fna")


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_home() -> Path:
    env_value = os.environ.get("SNP_PRIMER_HOME")
    if env_value:
        return Path(env_value).expanduser()
    return package_root() / "snp_primer_runtime"


def _default_bin(home_root: Path) -> Path:
    """决定 bin 目录默认值。

    PyInstaller 模式下，binaries 由 ``--add-binary <src>;bin`` 打进 bundle，
    解压后落在 ``sys._MEIPASS/bin/``（--onefile 临时目录 / --onedir 的
    ``_internal/bin/``）。若该目录存在 → 用它，省去用户再装一遍 BLAST+/primer3/
    muscle 的麻烦。dev 模式（非 frozen）→ 走老路径
    ``snp_primer_runtime/bin/``，由 bootstrap 管理。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled_bin = Path(meipass) / "bin"
            if bundled_bin.is_dir():
                return bundled_bin
    return home_root / "bin"


def ensure_runtime_dirs() -> dict[str, Path]:
    root = app_home()
    paths = {
        "home": root,
        "bin": Path(os.environ.get("SNP_PRIMER_BINARY_ROOT", _default_bin(root))),
        "workspace": Path(os.environ.get("SNP_PRIMER_WORKDIR", root / "workspace")),
        "references": root / "references",
        "logs": root / "logs",
    }
    # mkdir 用 try：bin 在 frozen+bundled 时指向 _MEIPASS（已存在；mkdir 幂等
    # 不会失败）；非 frozen / 用户自定义路径 mkdir 失败也别让 GUI 起不来。
    for key in ("home", "bin", "workspace", "references", "logs"):
        try:
            paths[key].mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            pass
    return paths


def default_catalog_source() -> str:
    env_value = os.environ.get("SNP_PRIMER_CATALOG")
    if env_value:
        return env_value
    runtime_catalog = app_home() / "references" / "catalog.json"
    if runtime_catalog.exists():
        return str(runtime_catalog)
    return str(package_root() / "references" / "catalog.example.json")


def find_reference_fastas(root_dir: str | Path) -> list[Path]:
    root = Path(root_dir)
    if not root.exists():
        return []
    matches: list[Path] = []
    for suffix in FASTA_SUFFIXES:
        matches.extend(root.rglob(f"*{suffix}"))
    return sorted({path.resolve() for path in matches})


def default_reference_fasta() -> str:
    env_value = os.environ.get("SNP_PRIMER_REFERENCE_FASTA")
    if env_value:
        return env_value
    reference_root = app_home() / "references"
    fasta_files = find_reference_fastas(reference_root)
    return str(fasta_files[0]) if fasta_files else ""
