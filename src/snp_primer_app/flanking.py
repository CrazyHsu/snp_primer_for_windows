from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from .models import BlastAlignment, BlastQueryRecord, FlankingTarget


def allowed_subgenomes(genome_number: int) -> str:
    if genome_number not in {1, 2, 3}:
        raise ValueError("genome_number must be 1, 2, or 3")
    return "ABD"[:genome_number] + "n"


def parse_blast_alignment(line: str) -> BlastAlignment:
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 15:
        raise ValueError(f"Expected at least 15 BLAST fields, got {len(fields)}")
    return BlastAlignment(
        query_id=fields[0],
        subject_id=fields[1],
        alignment_length=int(fields[3]),
        mismatches=int(fields[4]),
        gap_opens=int(fields[5]),
        query_start=int(fields[6]),
        query_end=int(fields[7]),
        subject_start=int(fields[8]),
        subject_end=int(fields[9]),
        query_sequence=fields[12],
        subject_sequence=fields[13],
        subject_length=int(fields[14]),
    )


def infer_subject_chromosome(alignment: BlastAlignment) -> str | None:
    if alignment.subject_chromosome:
        return alignment.subject_chromosome

    candidates = [alignment.subject_id, alignment.subject_title or ""]
    patterns = (
        r"\b([1-7][ABD])\b",
        r"(?:chromosome|chr)\s*([1-7][ABD])\b",
    )
    for text in candidates:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).upper()
    return None


def _find_positions(sequence: str, character: str) -> list[int]:
    return [index + 1 for index, base in enumerate(sequence) if base == character]


def _subject_snp_position(
    query_snp_position: int,
    alignment: BlastAlignment,
) -> tuple[int, str]:
    temp = query_snp_position - alignment.query_start
    for gap in _find_positions(alignment.query_sequence, "-"):
        if gap < temp:
            temp += 1

    subject_gap_count = 0
    for gap in _find_positions(alignment.subject_sequence, "-"):
        if gap < temp:
            subject_gap_count += 1

    if alignment.subject_start > alignment.subject_end:
        return alignment.subject_start - (temp - subject_gap_count), "minus"
    return alignment.subject_start + (temp - subject_gap_count), "plus"


def collect_flanking_targets(
    records: list[BlastQueryRecord],
    blast_lines: list[str],
    genome_number: int,
    flank_size: int = 500,
    max_hits: int = 6,
) -> list[FlankingTarget]:
    alignments = [parse_blast_alignment(line) for line in blast_lines if line.strip() and not line.startswith("#")]
    return collect_flanking_targets_from_alignments(
        records,
        alignments,
        genome_number=genome_number,
        flank_size=flank_size,
        max_hits=max_hits,
    )


def collect_flanking_targets_from_alignments(
    records: list[BlastQueryRecord],
    alignments: list[BlastAlignment],
    genome_number: int,
    flank_size: int = 500,
    max_hits: int = 6,
) -> list[FlankingTarget]:
    records_by_query = {record.blast_query_id: record for record in records}
    genomes = allowed_subgenomes(genome_number)
    minimum_alignment_by_name: dict[str, float] = {}
    output_query_id_by_query: dict[str, str] = {}
    raw_targets: list[tuple[str, str, int, int, str]] = []
    target_meta: dict[tuple[str, str, int, int, str], tuple[str | None, str | None]] = {}
    hit_queries: list[str] = []

    for alignment in alignments:
        record = records_by_query.get(alignment.query_id)
        if record is None:
            continue

        query_name = record.name
        query_chr = record.chromosome[:2].upper()
        subject_chr = infer_subject_chromosome(alignment)
        if not subject_chr or subject_chr[-1] not in genomes:
            continue

        minimum_alignment_by_name.setdefault(
            query_name, max(50, alignment.alignment_length * 0.9)
        )
        if alignment.derived_identity <= 88:
            continue
        if alignment.alignment_length <= minimum_alignment_by_name[query_name]:
            continue
        if not (alignment.query_start <= record.snp_index + 1 <= alignment.query_end):
            continue

        subject_pos, strand = _subject_snp_position(record.snp_index + 1, alignment)
        start = max(1, subject_pos - flank_size)
        end = min(alignment.subject_length, subject_pos + flank_size)
        extracted_snp_pos = subject_pos - start + 1
        if strand == "minus":
            extracted_snp_pos = end - subject_pos + 1

        if query_chr == subject_chr:
            output_query_id_by_query[alignment.query_id] = (
                f"{alignment.query_id}_{extracted_snp_pos}"
            )

        hit_queries.append(alignment.query_id)
        raw_target = (alignment.query_id, alignment.subject_id, start, end, strand)
        raw_targets.append(raw_target)
        target_meta[raw_target] = (alignment.subject_title, subject_chr)

    counts = Counter(hit_queries)
    targets: list[FlankingTarget] = []
    for query_id, subject_id, start, end, strand in raw_targets:
        if counts[query_id] > max_hits:
            continue
        output_query_id = output_query_id_by_query.get(query_id)
        if output_query_id is None:
            continue
        subject_title, subject_chr = target_meta[(query_id, subject_id, start, end, strand)]
        targets.append(
            FlankingTarget(
                query_id=query_id,
                output_query_id=output_query_id,
                subject_id=subject_id,
                range_start=start,
                range_end=end,
                strand=strand,
                query_hit_count=counts[query_id],
                subject_title=subject_title,
                subject_chromosome=subject_chr,
            )
        )
    return targets


def render_temp_range_file(targets: list[FlankingTarget]) -> str:
    return "".join(
        (
            f"{target.output_query_id}\t{target.subject_id}\t"
            f"{target.range_start}-{target.range_end}\t{target.strand}\n"
        )
        for target in targets
    )


def write_temp_range_file(targets: list[FlankingTarget], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.write_text(render_temp_range_file(targets), encoding="utf-8")
    return path


def write_marker_batches(targets: list[FlankingTarget], output_dir: str | Path) -> list[Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[FlankingTarget]] = {}
    for target in targets:
        grouped.setdefault(target.output_query_id, []).append(target)

    written_files: list[Path] = []
    for output_query_id, group in grouped.items():
        path = root / f"temp_marker_{output_query_id}.txt"
        path.write_text("".join(target.batch_file_content for target in group), encoding="utf-8")
        written_files.append(path)
    return written_files
