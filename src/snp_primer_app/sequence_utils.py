from __future__ import annotations


IUPAC_ALLELES = {
    "R": "AG",
    "Y": "TC",
    "S": "GC",
    "W": "AT",
    "K": "TG",
    "M": "AC",
}

IUPAC_REGEX = {
    "A": "A",
    "T": "T",
    "G": "G",
    "C": "C",
    "B": "[CGT]",
    "D": "[AGT]",
    "H": "[ACT]",
    "K": "[GT]",
    "M": "[AC]",
    "N": "[ACGT]",
    "R": "[AG]",
    "S": "[CG]",
    "V": "[ACG]",
    "W": "[AT]",
    "Y": "[CT]",
}


def reverse_complement(seq: str) -> str:
    source = "BDHKMNRSVWYATGCbdhkmnrsvwyatgc"
    target = "VHDMKNYSBWRTACGvhdmknysbwrtacg"
    sequence_map = {source[index]: target[index] for index in range(len(source))}
    return "".join(sequence_map[base] for base in reversed(seq))


def tm(seq: str) -> int:
    score = 0
    for base in seq:
        if base in {"A", "T"}:
            score += 2
        elif base in {"C", "G"}:
            score += 4
    return score


def calc_gc(seq: str) -> float:
    if not seq:
        return 0.0
    gc = sum(1 for base in seq if base in {"C", "G"})
    return gc / len(seq) * 100


def find_longest_substring(s1: str, s2: str) -> tuple[int, int, int, int]:
    longest_start = 0
    longest_end = 0
    largest_tm = 0
    start = 0
    gaps = [index for index, char in enumerate(s1) if char == "-" or s2[index] == "-"]
    gaps.append(len(s1))
    for gap in gaps:
        end = gap
        current_tm = tm(s1[start:end])
        if current_tm > largest_tm:
            longest_start = start
            longest_end = end
            largest_tm = current_tm
        start = gap + 1
    left_bases = len(s1[:longest_start].replace("-", ""))
    right_bases = len(s1[longest_end:].replace("-", ""))
    return longest_start, longest_end, left_bases, right_bases


def score_pairwise(
    seq1: str,
    seq2: str,
    gapopen: float = -4.0,
    gapext: float = -1.0,
    match: float = 1.0,
    mismatch: float = -1.0,
) -> float:
    score = 0.0
    gap = False
    for index in range(len(seq1)):
        pair = (seq1[index], seq2[index])
        if not gap:
            if "-" in pair:
                gap = True
                score += gapopen
            elif seq1[index] == seq2[index]:
                score += match
            else:
                score += mismatch
        else:
            if "-" not in pair:
                gap = False
                score += match if seq1[index] == seq2[index] else mismatch
            else:
                score += gapext
    return score


def gap_diff(seq1: str, seq2: str) -> int:
    ngap = 0
    for index in range(len(seq1)):
        pair = seq1[index] + seq2[index]
        if pair.count("-") == 1:
            ngap += 1
    return ngap


def mismatch_count(seq1: str, seq2: str) -> int:
    return sum(base1 != base2 for base1, base2 in zip(seq1, seq2))


def seq_to_pattern(seq: str) -> str:
    return "".join(IUPAC_REGEX[base] for base in seq.upper()).lower()
