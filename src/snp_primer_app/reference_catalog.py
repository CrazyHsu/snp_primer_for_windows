from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from .models import ReferenceGenome


def _read_catalog_text(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    parsed = urlparse(str(source))
    if parsed.scheme in {"http", "https"}:
        with urlopen(str(source)) as response:  # noqa: S310
            return response.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


def load_reference_catalog(source: str | Path) -> list[ReferenceGenome]:
    payload = json.loads(_read_catalog_text(source))
    references = []
    for item in payload.get("references", []):
        references.append(
            ReferenceGenome(
                reference_id=item["id"],
                display_name=item["display_name"],
                ploidy_modes=list(item.get("ploidy_modes", [])),
                fasta_url=item.get("fasta_url"),
                blast_db_url=item.get("blast_db_url"),
                sha256=item.get("sha256"),
                install_subdir=item.get("install_subdir"),
                size_bytes=item.get("size_bytes"),
                enabled=bool(item.get("enabled", True)),
                notes=item.get("notes"),
            )
        )
    return references
