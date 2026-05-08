from __future__ import annotations

from pathlib import Path

from .models import MarkerMetadata, VariationAnalysis
from .sequence_utils import find_longest_substring, gap_diff, score_pairwise


def parse_fasta_text(text: str) -> dict[str, str]:
    fasta: dict[str, str] = {}
    sequence_name = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            sequence_name = line.lstrip("> ").split()[0]
            fasta[sequence_name] = ""
        else:
            fasta[sequence_name] += line.replace(" ", "")
    return fasta


def parse_fasta_file(path: str | Path) -> dict[str, str]:
    return parse_fasta_text(Path(path).read_text(encoding="utf-8"))


def parse_flanking_fasta_text(text: str, target_chrom: str) -> tuple[dict[str, str], str, list[str]]:
    fasta: dict[str, str] = {}
    target = ""
    non_target_list: list[str] = []
    suffix = 0
    sequence_name = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            sequence_name = f"{line.split()[0].lstrip('>')}-{suffix}"
            suffix += 1
            if not target and target_chrom in sequence_name:
                target = sequence_name
            else:
                non_target_list.append(sequence_name)
            fasta[sequence_name] = ""
        else:
            fasta[sequence_name] += line.rstrip()
    return fasta, target, non_target_list


def parse_flanking_fasta_file(path: str | Path, target_chrom: str) -> tuple[dict[str, str], str, list[str]]:
    return parse_flanking_fasta_text(Path(path).read_text(encoding="utf-8"), target_chrom)


def parse_marker_metadata(path: str | Path) -> MarkerMetadata:
    parts = Path(path).name.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected marker filename: {path}")
    snpname = parts[-4]
    chrom = parts[-3][:2]
    allele = parts[-2]
    pos = int(parts[-1].split(".")[0])
    return MarkerMetadata(snpname=snpname, chrom=chrom, allele=allele, pos=pos)


def get_homeolog_comparison_sequences(
    fasta: dict[str, str],
    target: str,
    ids: list[str],
    align_left: int,
    align_right: int,
) -> list[str]:
    target_seq = fasta[target]
    seq2comp: list[str] = []
    for homeolog_id in ids:
        homeolog_seq = fasta[homeolog_id]
        target_window = target_seq[align_left : align_right + 1]
        homeolog_window = homeolog_seq[align_left : align_right + 1]
        score1 = score_pairwise(target_window, homeolog_window)
        index_left, index_right, left_bases, right_bases = find_longest_substring(
            target_window, homeolog_window
        )
        index_left += align_left
        index_right += align_left
        seq_left = homeolog_seq[:index_left].replace("-", "")
        seq_right = homeolog_seq[index_right:].replace("-", "")
        if len(seq_left) < left_bases:
            seq_left = "-" * (left_bases - len(seq_left)) + seq_left
        if len(seq_right) < right_bases:
            seq_right = seq_right + "-" * (right_bases - len(seq_right))
        seqk = seq_left[::-1][:left_bases][::-1] + homeolog_seq[index_left:index_right] + seq_right[:right_bases]
        score2 = score_pairwise(target_window.replace("-", ""), seqk)
        if score1 > score2 and gap_diff(target_window, homeolog_window) < 4:
            seqk = "".join(
                homeolog_window[index]
                for index, char in enumerate(target_window)
                if char != "-"
            )
        seq2comp.append(seqk)
    return seq2comp


def analyze_alignment(
    fasta: dict[str, str],
    target: str,
    ids: list[str],
    snp_site: int,
    min_margin: int = 20,
) -> VariationAnalysis:
    alignlen = len(fasta[target])
    template_to_alignment: dict[int, int] = {}
    alignment_to_template: dict[int, int] = {}
    ngap = 0
    for index in range(alignlen):
        if fasta[target][index] == "-":
            ngap += 1
            continue
        template_to_alignment[index - ngap] = index
        alignment_to_template[index] = index - ngap

    seq_template = fasta[target].replace("-", "")
    variation: list[int] = []
    variation_partial: list[int] = []
    diffarray: dict[int, list[int]] = {}
    gap_left = max(len(seq) - len(seq.lstrip("-")) for seq in fasta.values())
    gap_right = min(len(seq.rstrip("-")) for seq in fasta.values())

    for index in range(gap_left, gap_right):
        target_base = fasta[target][index]
        if target_base == "-":
            continue
        pos_template = alignment_to_template[index]
        if pos_template < min_margin or pos_template > len(seq_template) - min_margin:
            continue

        nd = 0
        differ_array = [0] * len(ids)
        if pos_template < snp_site:
            align_left = template_to_alignment[pos_template - (min_margin - 1)]
            align_right = index
        else:
            align_left = index
            align_right = template_to_alignment[pos_template + (min_margin - 1)]

        seq2comp = get_homeolog_comparison_sequences(fasta, target, ids, align_left, align_right)
        for homeolog_index, homeolog_sequence in enumerate(seq2comp):
            homeolog_base = homeolog_sequence[-1] if pos_template < snp_site else homeolog_sequence[0]
            if target_base != homeolog_base:
                nd += 1
                differ_array[homeolog_index] = 1

        diffarray[pos_template] = differ_array
        if nd == len(ids) and pos_template not in variation:
            variation.append(pos_template)
        if nd > 0 and pos_template not in variation_partial:
            variation_partial.append(pos_template)

    return VariationAnalysis(
        target_id=target,
        homeolog_ids=ids,
        seq_template=seq_template,
        variation=variation,
        variation_partial=variation_partial,
        diffarray=diffarray,
        gap_left=gap_left,
        gap_right=gap_right,
    )
