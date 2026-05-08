from __future__ import annotations

from pathlib import Path

from .external_tools import LogFn, run_command
from .sequence_utils import mismatch_count


def blast_primers(
    primer_name_by_sequence: dict[str, str],
    blastn_path: str | Path,
    reference_fasta: str | Path,
    output_dir: str | Path,
    output_prefix: str,
    logger: LogFn | None = None,
) -> dict[str, str]:
    workdir = Path(output_dir)
    workdir.mkdir(parents=True, exist_ok=True)
    fasta_path = workdir / f"{output_prefix}_for_blast_primer.fa"
    output_path = workdir / f"{output_prefix}_primer_blast_out.txt"
    with fasta_path.open("w", encoding="utf-8") as handle:
        for sequence, primer_name in primer_name_by_sequence.items():
            handle.write(f">{primer_name}\n{sequence}\n")

    run_command(
        [
            blastn_path,
            "-task",
            "blastn",
            "-db",
            reference_fasta,
            "-query",
            fasta_path,
            "-outfmt",
            "6 std qseq sseq qlen slen",
            "-num_threads",
            "3",
            "-word_size",
            "7",
            "-out",
            output_path,
        ],
        cwd=workdir,
        logger=logger,
    )

    blast_hit: dict[str, str] = {}
    for raw_line in output_path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        fields = raw_line.split("\t")
        query, subject = fields[:2]
        qstart, qstop, sstart = [int(fields[index]) for index in (6, 7, 8)]
        qseq, sseq = fields[12:14]
        qlen = int(fields[14])
        n1 = qlen - qstop
        tail_start = n1 - 4
        if n1 < 2 and mismatch_count(qseq[tail_start:], sseq[tail_start:]) + n1 < 2:
            blast_hit[query] = blast_hit.setdefault(query, "") + f";{subject}:{sstart}"
    return blast_hit
