from __future__ import annotations

from pathlib import Path


def asset_path(filename: str) -> Path:
    return Path(__file__).with_name("assets") / filename
