from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .alignment import (
    analyze_alignment,
    parse_fasta_file,
    parse_flanking_fasta_file,
    parse_marker_metadata,
)
from .models import MarkerMetadata, Primer, PrimerPair, VariationAnalysis
from .primer3_parser import parse_primer3_output_file
from .sequence_utils import IUPAC_ALLELES, reverse_complement


def build_kasp_settings_common(
    seq_template: str,
    max_tm: int,
    max_size: int,
    pick_anyway: bool,
) -> str:
    return (
        "PRIMER_TASK=generic\n"
        f"SEQUENCE_TEMPLATE={seq_template}\n"
        "PRIMER_PRODUCT_SIZE_RANGE=40-70 70-100 100-120 120-150 150-200 200-250\n"
        f"PRIMER_MAX_SIZE={max_size}\n"
        "PRIMER_MIN_TM=57.0\n"
        "PRIMER_OPT_TM=62.0\n"
        f"PRIMER_MAX_TM={max_tm}\n"
        "PRIMER_PAIR_MAX_DIFF_TM=5.0\n"
        "PRIMER_FIRST_BASE_INDEX=1\n"
        "PRIMER_LIBERAL_BASE=1\n"
        "PRIMER_NUM_RETURN=5\n"
        "PRIMER_EXPLAIN_FLAG=1\n"
        f"PRIMER_PICK_ANYWAY={1 if pick_anyway else 0}\n"
    )


def format_primer_with_variation(primer: Primer, variation: list[int]) -> Primer:
    if primer.start < primer.end:
        start = primer.start
        end = primer.end
        seq = primer.seq.lower()
    else:
        start = primer.end
        end = primer.start
        seq = reverse_complement(primer.seq.lower())

    primer_range = range(start - 1, end)
    var_sites = set(variation).intersection(primer_range)
    for relative_index in sorted(i - start + 1 for i in var_sites):
        seq = seq[:relative_index] + seq[relative_index].upper() + seq[relative_index + 1 :]

    primer.seq = seq if primer.start < primer.end else reverse_complement(seq)
    primer.difnum = len(var_sites)
    return primer


def prepare_kasp_analysis(seqfile: str | Path, aligned_fasta_path: str | Path) -> tuple[MarkerMetadata, VariationAnalysis]:
    metadata = parse_marker_metadata(seqfile)
    fasta_raw, target, ids = parse_flanking_fasta_file(seqfile, metadata.chrom)
    if not target:
        raise ValueError(f"Could not find target chromosome {metadata.chrom} in {seqfile}")

    alignment_fasta = parse_fasta_file(aligned_fasta_path)
    if target not in alignment_fasta:
        raise ValueError(f"Aligned FASTA does not contain target sequence {target}")

    analysis = analyze_alignment(alignment_fasta, target, ids, metadata.pos - 1)
    return metadata, analysis


def write_renamed_flanking_fasta(seqfile: str | Path, output_path: str | Path) -> tuple[Path, str, list[str]]:
    metadata = parse_marker_metadata(seqfile)
    fasta_raw, target, ids = parse_flanking_fasta_file(seqfile, metadata.chrom)
    output = Path(output_path)
    with output.open("w", encoding="utf-8") as handle:
        for sequence_name, sequence in fasta_raw.items():
            handle.write(f">{sequence_name}\n{sequence}\n")
    return output, target, ids


def build_kasp_primer3_input(
    metadata: MarkerMetadata,
    analysis: VariationAnalysis,
    max_tm: int,
    max_size: int,
    pick_anyway: bool,
) -> str:
    snp_site = metadata.pos - 1
    seq_template = analysis.seq_template
    alt_allele = IUPAC_ALLELES[metadata.allele][0]
    product_max = 250
    if alt_allele in "ATat":
        seq_template = seq_template[:snp_site] + alt_allele + seq_template[snp_site + 1 :]

    settings_common = build_kasp_settings_common(seq_template, max_tm, max_size, pick_anyway)
    chunks: list[str] = []

    if not analysis.homeolog_ids:
        chunks.append(
            settings_common
            + f"SEQUENCE_ID={metadata.snpname}-left\n"
            + f"SEQUENCE_FORCE_LEFT_END={snp_site + 1}\n"
            + "=\n"
        )
        chunks.append(
            settings_common
            + f"SEQUENCE_ID={metadata.snpname}-right\n"
            + f"SEQUENCE_FORCE_RIGHT_END={snp_site + 1}\n"
            + "=\n"
        )
        return "\n".join(chunks)

    for index in analysis.variation:
        if index == snp_site:
            continue
        if index < snp_site:
            left_end = index
            right_end = snp_site
        else:
            left_end = snp_site
            right_end = index
        if right_end - left_end > product_max - 35:
            continue
        chunks.append(
            settings_common
            + f"SEQUENCE_ID={metadata.snpname}-{index + 1}\n"
            + f"SEQUENCE_FORCE_LEFT_END={left_end + 1}\n"
            + f"SEQUENCE_FORCE_RIGHT_END={right_end + 1}\n"
            + "=\n"
        )
    return "\n".join(chunks)


def select_kasp_primer_pairs(
    primerpairs: dict[str, PrimerPair],
    analysis: VariationAnalysis,
    metadata: MarkerMetadata,
) -> tuple[dict[str, PrimerPair], dict[str, str]]:
    snp_site = metadata.pos - 1
    final_primers: dict[str, PrimerPair] = {}
    primer_names: dict[str, str] = {}
    left_count = 0
    right_count = 0

    if not analysis.homeolog_ids:
        for key, primer_pair in primerpairs.items():
            if primer_pair.product_size == 0:
                continue
            left_primer = primer_pair.left
            right_primer = primer_pair.right
            if left_primer.seq not in primer_names:
                left_count += 1
                left_primer.name = f"L{left_count}"
                primer_names[left_primer.seq] = left_primer.name
            else:
                left_primer.name = primer_names[left_primer.seq]
            if right_primer.seq not in primer_names:
                right_count += 1
                right_primer.name = f"R{right_count}"
                primer_names[right_primer.seq] = right_primer.name
            else:
                right_primer.name = primer_names[right_primer.seq]
            final_primers[key] = primer_pair
        return final_primers, primer_names

    for key, primer_pair in primerpairs.items():
        if primer_pair.product_size == 0:
            continue
        varsite = int(key.split("-")[-2]) - 1
        left_primer = primer_pair.left
        right_primer = primer_pair.right
        dif3all = 1 if varsite in analysis.variation else 0
        if dif3all:
            left_primer.difthreeall = "YES"
            right_primer.difthreeall = "YES"
        if varsite < snp_site:
            common_primer = left_primer
            rr = range(max(common_primer.end - 10, analysis.gap_left), common_primer.end)
        else:
            common_primer = right_primer
            rr = range(
                common_primer.end - 1,
                min(common_primer.end + 9, len(analysis.seq_template) - 20),
            )
        if not rr:
            continue
        primer_pair.score = dif3all * 5.0 + 150.0 / primer_pair.product_size - abs(left_primer.tm - right_primer.tm) / 10.0
        aa = [sum(values) for values in zip(*(analysis.diffarray[position] for position in rr))]
        if aa and min(aa) > 0:
            if left_primer.seq not in primer_names:
                left_count += 1
                left_primer.name = f"L{left_count}"
                primer_names[left_primer.seq] = left_primer.name
            else:
                left_primer.name = primer_names[left_primer.seq]
            if right_primer.seq not in primer_names:
                right_count += 1
                right_primer.name = f"R{right_count}"
                primer_names[right_primer.seq] = right_primer.name
            else:
                right_primer.name = primer_names[right_primer.seq]
            final_primers[key] = primer_pair
    return final_primers, primer_names


def render_kasp_report(
    primerpairs: dict[str, PrimerPair],
    analysis: VariationAnalysis,
    metadata: MarkerMetadata,
    blast_hits: dict[str, str] | None = None,
) -> str:
    blast_hits = blast_hits or {}
    snp_site = metadata.pos - 1
    snp_a, snp_b = IUPAC_ALLELES[metadata.allele]
    lines = [
        "index\tproduct_size\ttype\tstart\tend\tvariation number\t3'diffall\tlength\tTm\tGCcontent\tany\t3'\tend_stability\thairpin\tprimer_seq\tReverseComplement\tpenalty\tcompl_any\tcompl_end\tscore\tPrimerID\tmatched_chromosomes"
    ]

    for key, primer_pair in primerpairs.items():
        left_primer = format_primer_with_variation(deepcopy(primer_pair.left), analysis.variation)
        right_primer = format_primer_with_variation(deepcopy(primer_pair.right), analysis.variation)
        left_primer.direction = "LEFT"
        right_primer.direction = "RIGHT"
        if left_primer.end == snp_site + 1:
            primer_a = deepcopy(left_primer)
            primer_b = deepcopy(left_primer)
            primer_a.seq = primer_a.seq[:-1] + snp_a
            primer_b.seq = primer_b.seq[:-1] + snp_b
            common_primer = right_primer
        else:
            primer_a = deepcopy(right_primer)
            primer_b = deepcopy(right_primer)
            primer_a.seq = primer_a.seq[:-1] + reverse_complement(snp_a)
            primer_b.seq = primer_b.seq[:-1] + reverse_complement(snp_b)
            common_primer = left_primer

        for primer_index, primer in (
            (f"{key}-{snp_a}", primer_a),
            (f"{key}-{snp_b}", primer_b),
            (f"{key}-Common", common_primer),
        ):
            reverse_seq = reverse_complement(primer.seq)
            lines.append(
                "\t".join(
                    [
                        primer_index,
                        str(primer_pair.product_size),
                        primer.direction,
                        str(primer.start),
                        str(primer.end),
                        str(primer.difnum),
                        primer.difthreeall,
                        str(primer.length),
                        str(primer.tm),
                        str(primer.gc),
                        str(primer.anys),
                        str(primer.three),
                        str(primer.end_stability),
                        str(primer.hairpin),
                        primer.seq,
                        reverse_seq,
                        primer_pair.penalty,
                        primer_pair.compl_any,
                        primer_pair.compl_end,
                        str(primer_pair.score),
                        primer.name,
                        blast_hits.get(primer.name, ""),
                    ]
                )
            )

    lines.append("")
    lines.append("")
    lines.append(f"Sites that can differ all for {metadata.snpname}")
    lines.append(", ".join(str(index + 1) for index in analysis.variation))
    lines.append("")
    return "\n".join(lines)


def parse_and_select_kasp_primerpairs(
    primer3_output_path: str | Path,
    primerpair_to_return: int,
    analysis: VariationAnalysis,
    metadata: MarkerMetadata,
) -> dict[str, PrimerPair]:
    primerpairs = parse_primer3_output_file(primer3_output_path, primerpair_to_return)
    final_primers, _ = select_kasp_primer_pairs(primerpairs, analysis, metadata)
    return final_primers
