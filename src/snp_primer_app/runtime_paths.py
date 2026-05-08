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


def ensure_runtime_dirs() -> dict[str, Path]:
    root = app_home()
    paths = {
        "home": root,
        "bin": Path(os.environ.get("SNP_PRIMER_BINARY_ROOT", root / "bin")),
        "workspace": Path(os.environ.get("SNP_PRIMER_WORKDIR", root / "workspace")),
        "references": root / "references",
        "logs": root / "logs",
    }
    for key in ("home", "bin", "workspace", "references", "logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
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
