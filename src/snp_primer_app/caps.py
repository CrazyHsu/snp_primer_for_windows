from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

from .models import MarkerMetadata, PrimerPair, RestrictionEnzyme, VariationAnalysis
from .sequence_utils import seq_to_pattern, reverse_complement


def parse_restriction_enzyme_lines(lines: list[str]) -> dict[str, RestrictionEnzyme]:
    enzymes: dict[str, RestrictionEnzyme] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        name, seq = line.split("\t")
        enzymes[name] = RestrictionEnzyme(
            name=name,
            seq=seq.lower(),
            length=len(seq),
            price=int(name.split(",")[-1]),
        )
    return enzymes


def parse_restriction_enzyme_file(path: str | Path) -> dict[str, RestrictionEnzyme]:
    return parse_restriction_enzyme_lines(Path(path).read_text(encoding="utf-8").splitlines())


def string_diff_positions(seq1: str, seq2: str) -> list[int]:
    return [index for index in range(len(seq1)) if seq1[index] != seq2[index]]


def find_substring(substring: str, string: str) -> list[int]:
    return [match.start() for match in re.finditer(substring, string)]


def check_pattern(enzyme: RestrictionEnzyme, wild_seq: str, mut_seq: str) -> RestrictionEnzyme:
    snp_pos = string_diff_positions(wild_seq, mut_seq)[0]
    enzyme_seq = enzyme.seq
    snp_a = wild_seq[snp_pos]
    snp_b = mut_seq[snp_pos]
    for index in range(len(enzyme_seq)):
        pattern = seq_to_pattern(enzyme_seq[:index] + "N" + enzyme_seq[index + 1 :])
        for match in re.finditer(pattern, wild_seq):
            if snp_pos in range(match.start(), match.end()) and not re.search(
                pattern, mut_seq[match.start() : match.end()]
            ):
                change_pos = match.start() + index
                if abs(snp_pos - change_pos) > 1:
                    enzyme.dcaps = "Yes"
                    enzyme.template_seq = wild_seq[:change_pos] + enzyme_seq[index].upper() + wild_seq[change_pos + 1 :]
                    enzyme.change_pos = change_pos + 1
                    enzyme.potential_primer = (
                        enzyme.template_seq[(snp_pos - 20) : snp_pos]
                        + f"[{snp_a}/{snp_b}]"
                        + enzyme.template_seq[(snp_pos + 1) : (snp_pos + 21)]
                    )
                    if change_pos < snp_pos:
                        enzyme.primer_end_pos = list(range(change_pos + 1, snp_pos))
                    else:
                        enzyme.primer_end_pos = list(range(snp_pos + 1, change_pos))
                    return enzyme
    return enzyme


def test_enzyme(enzyme: RestrictionEnzyme, wild_seq: str, mut_seq: str) -> RestrictionEnzyme:
    enzyme_seq = enzyme.seq
    enzyme_seq_rc = reverse_complement(enzyme_seq)
    wild_seq = wild_seq.lower()
    mut_seq = mut_seq.lower()
    wild_allpos = find_substring(seq_to_pattern(enzyme_seq), wild_seq)
    mut_allpos = find_substring(seq_to_pattern(enzyme_seq), mut_seq)
    wild_allpos += find_substring(seq_to_pattern(enzyme_seq_rc), wild_seq)
    mut_allpos += find_substring(seq_to_pattern(enzyme_seq_rc), mut_seq)
    enzyme.allpos = list(set(wild_allpos))
    if len(wild_allpos) != len(mut_allpos):
        enzyme.caps = "Yes"
        enzyme.template_seq = wild_seq
        return enzyme
    enzyme = check_pattern(enzyme, wild_seq, mut_seq)
    if enzyme.dcaps != "Yes":
        enzyme = check_pattern(enzyme, mut_seq, wild_seq)
    if enzyme.dcaps != "Yes" and enzyme_seq_rc != enzyme_seq:
        enzyme.seq = enzyme_seq_rc
        enzyme = check_pattern(enzyme, wild_seq, mut_seq)
    if enzyme.dcaps != "Yes" and enzyme_seq_rc != enzyme_seq:
        enzyme = check_pattern(enzyme, mut_seq, wild_seq)
    return enzyme


def scan_caps_enzymes(
    enzymes: dict[str, RestrictionEnzyme],
    wild_seq: str,
    mut_seq: str,
    max_price: int,
) -> tuple[list[RestrictionEnzyme], list[RestrictionEnzyme]]:
    caps_list: list[RestrictionEnzyme] = []
    dcaps_list: list[RestrictionEnzyme] = []
    for enzyme in enzymes.values():
        if enzyme.price > max_price:
            continue
        tested = test_enzyme(enzyme, wild_seq, mut_seq)
        if tested.caps == "Yes":
            caps_list.append(tested)
        elif tested.dcaps == "Yes":
            dcaps_list.append(tested)
    return caps_list, dcaps_list


def build_caps_settings_common(max_tm: int, max_size: int, pick_anyway: bool) -> str:
    return (
        "PRIMER_TASK=generic\n"
        f"PRIMER_MAX_SIZE={max_size}\n"
        "PRIMER_MIN_TM=57.0\n"
        "PRIMER_OPT_TM=60.0\n"
        f"PRIMER_MAX_TM={max_tm}\n"
        "PRIMER_PAIR_MAX_DIFF_TM=6.0\n"
        "PRIMER_FIRST_BASE_INDEX=1\n"
        "PRIMER_LIBERAL_BASE=1\n"
        "PRIMER_NUM_RETURN=5\n"
        "PRIMER_EXPLAIN_FLAG=1\n"
        f"PRIMER_PICK_ANYWAY={1 if pick_anyway else 0}\n"
    )


def build_caps_primer3_input(
    metadata: MarkerMetadata,
    analysis: VariationAnalysis,
    caps_list: list[RestrictionEnzyme],
    dcaps_list: list[RestrictionEnzyme],
    max_tm: int,
    max_size: int,
    pick_anyway: bool,
    primer3_config_dir: str | Path | None = None,
) -> tuple[str, int]:
    snp_pos = metadata.pos - 1
    common_settings = build_caps_settings_common(max_tm, max_size, pick_anyway)
    thermodynamic_line = (
        f"PRIMER_THERMODYNAMIC_PARAMETERS_PATH={primer3_config_dir}\n"
        if primer3_config_dir
        else ""
    )
    chunks: list[str] = []
    written = 0

    if not analysis.homeolog_ids:
        for enzyme in dcaps_list:
            for primer_end_pos in enzyme.primer_end_pos:
                if primer_end_pos > snp_pos:
                    left_end = -1000000
                    right_end = primer_end_pos + 1
                else:
                    left_end = primer_end_pos + 1
                    right_end = -1000000
                chunks.append(
                    common_settings
                    + f"SEQUENCE_ID={metadata.snpname}-dCAPS-{enzyme.name}-{enzyme.seq}-{primer_end_pos + 1}\n"
                    + f"SEQUENCE_TEMPLATE={enzyme.template_seq}\n"
                    + "PRIMER_PRODUCT_SIZE_RANGE=150-200 200-250 70-150\n"
                    + f"SEQUENCE_FORCE_LEFT_END={left_end}\n"
                    + f"SEQUENCE_FORCE_RIGHT_END={right_end}\n"
                    + "=\n"
                )
                written += 1

        for enzyme in caps_list:
            chunks.append(
                common_settings
                + f"SEQUENCE_ID={metadata.snpname}-CAPS-{enzyme.name}-{enzyme.seq}\n"
                + f"SEQUENCE_TEMPLATE={enzyme.template_seq}\n"
                + "PRIMER_PRODUCT_SIZE_RANGE=300-900\n"
                + thermodynamic_line
                + "SEQUENCE_FORCE_LEFT_END=-1000000\n"
                + "SEQUENCE_FORCE_RIGHT_END=-1000000\n"
                + f"SEQUENCE_TARGET={snp_pos - 20},40\n"
                + "=\n"
            )
            written += 1
        return "\n".join(chunks), written

    for enzyme in dcaps_list:
        for primer_end_pos in enzyme.primer_end_pos:
            for index in analysis.variation:
                if primer_end_pos > snp_pos:
                    left_end = index + 1
                    right_end = primer_end_pos + 1
                else:
                    left_end = primer_end_pos + 1
                    right_end = index + 1
                if right_end - left_end < 35 or right_end - left_end > 315:
                    continue
                chunks.append(
                    common_settings
                    + f"SEQUENCE_ID={metadata.snpname}-dCAPS-{enzyme.name}-{enzyme.seq}-{index + 1}-{primer_end_pos + 1}\n"
                    + f"SEQUENCE_TEMPLATE={enzyme.template_seq}\n"
                    + "PRIMER_PRODUCT_SIZE_RANGE=70-350\n"
                    + thermodynamic_line
                    + f"SEQUENCE_FORCE_LEFT_END={left_end}\n"
                    + f"SEQUENCE_FORCE_RIGHT_END={right_end}\n"
                    + "=\n"
                )
                written += 1

    for enzyme in caps_list:
        for index in analysis.variation:
            if index < snp_pos:
                left_end = index + 1
                right_end = -1000000
            else:
                left_end = -1000000
                right_end = index + 1
            chunks.append(
                common_settings
                + f"SEQUENCE_ID={metadata.snpname}-CAPS-{enzyme.name}-{enzyme.seq}-{index + 1}\n"
                + f"SEQUENCE_TEMPLATE={enzyme.template_seq}\n"
                + "PRIMER_PRODUCT_SIZE_RANGE=300-900\n"
                + thermodynamic_line
                + f"SEQUENCE_FORCE_LEFT_END={left_end}\n"
                + f"SEQUENCE_FORCE_RIGHT_END={right_end}\n"
                + f"SEQUENCE_TARGET={snp_pos - 20},40\n"
                + "=\n"
            )
            written += 1
    return "\n".join(chunks), written


def format_caps_primer_seq(primer, variation: list[int]):
    if primer.start < primer.end:
        start = primer.start
        end = primer.end
        seq = primer.seq
    else:
        start = primer.end
        end = primer.start
        seq = reverse_complement(primer.seq)

    primer_range = range(start - 1, end)
    var_sites = set(variation).intersection(primer_range)
    for relative_index in sorted(i - start + 1 for i in var_sites):
        seq = seq[:relative_index] + seq[relative_index].upper() + seq[relative_index + 1 :]
    primer.seq = seq if primer.start < primer.end else reverse_complement(seq)
    primer.difnum = len(var_sites)
    return primer


def select_caps_primer_pairs(primerpairs: dict[str, PrimerPair]) -> tuple[dict[str, PrimerPair], dict[str, str]]:
    primer_names: dict[str, str] = {}
    final_primers: dict[str, PrimerPair] = {}
    left_count = 0
    right_count = 0
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


def render_caps_report(
    primerpairs: dict[str, PrimerPair],
    variation: list[int],
    caps_list: list[RestrictionEnzyme],
    dcaps_list: list[RestrictionEnzyme],
    metadata: MarkerMetadata,
    blast_hits: dict[str, str] | None = None,
) -> str:
    blast_hits = blast_hits or {}
    lines = [
        "index\tproduct_size\ttype\tstart\tend\tdiff_number\t3'differall\tlength\tTm\tGCcontent\tany\t3'\tend_stability\thairpin\tprimer_seq\tReverseComplement\tpenalty\tcompl_any\tcompl_end\tPrimerID\tmatched_chromosomes"
    ]

    for key, primer_pair in primerpairs.items():
        left_primer = format_caps_primer_seq(deepcopy(primer_pair.left), variation)
        right_primer = format_caps_primer_seq(deepcopy(primer_pair.right), variation)
        left_primer.difthreeall = "YES"
        right_primer.difthreeall = "YES"
        for primer_type, primer in (("LEFT", left_primer), ("RIGHT", right_primer)):
            reverse_seq = reverse_complement(primer.seq)
            lines.append(
                "\t".join(
                    [
                        key,
                        str(primer_pair.product_size),
                        primer_type,
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
                        primer.name,
                        blast_hits.get(primer.name, ""),
                    ]
                )
            )

    lines.append("")
    lines.append("")
    lines.append(f"Sites that can differ all for {metadata.snpname}")
    lines.append(", ".join(str(index + 1) for index in variation))
    lines.append("")
    lines.append("")
    lines.append(f"CAPS cut information for snp {metadata.snpname}")
    lines.append("Enzyme\tEnzyme_seq\tChange_pos\tOther_cut_pos\tChanged_sequence")
    for enzyme in dcaps_list + caps_list:
        lines.append(
            "\t".join(
                [
                    enzyme.name,
                    enzyme.seq,
                    "" if enzyme.change_pos is None else str(enzyme.change_pos),
                    ", ".join(str(position + 1) for position in enzyme.allpos),
                    enzyme.potential_primer,
                ]
            )
        )
    lines.append("")
    return "\n".join(lines)
