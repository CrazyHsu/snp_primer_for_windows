from __future__ import annotations

from pathlib import Path

from .models import BlastQueryRecord

IUPAC_MAP = {
    "[A/G]": "R",
    "[G/A]": "R",
    "[C/T]": "Y",
    "[T/C]": "Y",
    "[G/C]": "S",
    "[C/G]": "S",
    "[A/T]": "W",
    "[T/A]": "W",
    "[G/T]": "K",
    "[T/G]": "K",
    "[A/C]": "M",
    "[C/A]": "M",
}


def parse_polymarker_lines(lines: list[str]) -> list[BlastQueryRecord]:
    records: list[BlastQueryRecord] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        name, chromosome, sequence = line.replace(" ", "").split(",", maxsplit=2)
        normalized_name = name.replace("_", "-")
        snp_index = sequence.find("[")
        if snp_index < 0:
            raise ValueError(f"Missing SNP marker in line: {raw_line!r}")
        snp_token = sequence[snp_index : snp_index + 5]
        if snp_token not in IUPAC_MAP:
            raise ValueError(f"Unsupported SNP token {snp_token!r} in line: {raw_line!r}")
        iupac_code = IUPAC_MAP[snp_token]
        blast_sequence = sequence[:snp_index] + iupac_code + sequence[snp_index + 5 :]
        records.append(
            BlastQueryRecord(
                name=normalized_name,
                chromosome=chromosome,
                raw_sequence=sequence,
                snp_index=snp_index,
                iupac_code=iupac_code,
                blast_query_id=f"{normalized_name}_{chromosome}_{iupac_code}",
                blast_sequence=blast_sequence,
            )
        )
    return records


def parse_polymarker_file(path: str | Path) -> list[BlastQueryRecord]:
    return parse_polymarker_lines(Path(path).read_text(encoding="utf-8").splitlines())


def render_blast_fasta(records: list[BlastQueryRecord]) -> str:
    return "".join(
        f">{record.blast_query_id}\n{record.blast_sequence}\n" for record in records
    )


def write_blast_fasta(records: list[BlastQueryRecord], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.write_text(render_blast_fasta(records), encoding="utf-8")
    return output
