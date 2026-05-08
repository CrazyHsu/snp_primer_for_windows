from __future__ import annotations

import re
from pathlib import Path

from .models import PrimerPair


DEFAULT_GLOBAL_SETTINGS = """Primer3 File - http://primer3.sourceforge.net
P3_FILE_TYPE=settings

PRIMER_FIRST_BASE_INDEX=1
PRIMER_TASK=generic
P3_FILE_ID=Settings for PCR amplification followed by Sanger sequencing on both strands using PCR primers
PRIMER_MIN_THREE_PRIME_DISTANCE=3
PRIMER_EXPLAIN_FLAG=1

PRIMER_NUM_RETURN=5

PRIMER_MIN_SIZE=18
PRIMER_OPT_SIZE=20
PRIMER_MAX_SIZE=25
PRIMER_MIN_TM=57.0
PRIMER_OPT_TM=60.0
PRIMER_MAX_TM=65.0
PRIMER_PAIR_MAX_DIFF_TM=5.0

PRIMER_MIN_GC=20.0
PRIMER_MAX_GC=90.0
PRIMER_LIBERAL_BASE=1
PRIMER_PICK_ANYWAY=0

=
"""


def parse_primer3_output_text(text: str, primerpair_to_return: int) -> dict[str, PrimerPair]:
    regex = "012345"[:primerpair_to_return]
    regex = f"([{regex}])"
    primerpairs: dict[str, PrimerPair] = {}
    seqid = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "SEQUENCE_ID" in line:
            seqid = line.split("=")[1]
            for index in range(primerpair_to_return):
                primerpairs[f"{seqid}-{index}"] = PrimerPair()
            continue
        if not seqid:
            continue

        if re.search(f"PRIMER_PAIR_{regex}_PENALTY", line):
            match = re.search(f"PRIMER_PAIR_{regex}_PENALTY", line)
            primerpairs[f"{seqid}-{match.group(1)}"].penalty = line.split("=")[1]
        elif re.search(f"PRIMER_PAIR_{regex}_COMPL_ANY", line):
            match = re.search(f"PRIMER_PAIR_{regex}_COMPL_ANY", line)
            primerpairs[f"{seqid}-{match.group(1)}"].compl_any = line.split("=")[1]
        elif re.search(f"PRIMER_PAIR_{regex}_COMPL_END", line):
            match = re.search(f"PRIMER_PAIR_{regex}_COMPL_END", line)
            primerpairs[f"{seqid}-{match.group(1)}"].compl_end = line.split("=")[1]
        elif re.search(f"PRIMER_PAIR_{regex}_PRODUCT_SIZE", line):
            match = re.search(f"PRIMER_PAIR_{regex}_PRODUCT_SIZE", line)
            primerpairs[f"{seqid}-{match.group(1)}"].product_size = int(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_SEQUENCE", line):
            match = re.search(f"PRIMER_LEFT_{regex}_SEQUENCE", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.seq = line.split("=")[1]
        elif re.search(f"PRIMER_LEFT_{regex}=", line):
            match = re.search(f"PRIMER_LEFT_{regex}=", line)
            primer = primerpairs[f"{seqid}-{match.group(1)}"].left
            primer.start = int(line.split("=")[1].split(",")[0])
            primer.length = int(line.split("=")[1].split(",")[1])
            primer.end = primer.start + primer.length - 1
        elif re.search(f"PRIMER_LEFT_{regex}_TM", line):
            match = re.search(f"PRIMER_LEFT_{regex}_TM", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.tm = float(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_GC_PERCENT", line):
            match = re.search(f"PRIMER_LEFT_{regex}_GC_PERCENT", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.gc = float(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_SELF_ANY_TH", line):
            match = re.search(f"PRIMER_LEFT_{regex}_SELF_ANY_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.anys = float(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_SELF_END_TH", line):
            match = re.search(f"PRIMER_LEFT_{regex}_SELF_END_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.three = float(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_HAIRPIN_TH", line):
            match = re.search(f"PRIMER_LEFT_{regex}_HAIRPIN_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.hairpin = float(line.split("=")[1])
        elif re.search(f"PRIMER_LEFT_{regex}_END_STABILITY", line):
            match = re.search(f"PRIMER_LEFT_{regex}_END_STABILITY", line)
            primerpairs[f"{seqid}-{match.group(1)}"].left.end_stability = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_SEQUENCE", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_SEQUENCE", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.seq = line.split("=")[1]
        elif re.search(f"PRIMER_RIGHT_{regex}=", line):
            match = re.search(f"PRIMER_RIGHT_{regex}=", line)
            primer = primerpairs[f"{seqid}-{match.group(1)}"].right
            primer.start = int(line.split("=")[1].split(",")[0])
            primer.length = int(line.split("=")[1].split(",")[1])
            primer.end = primer.start - primer.length + 1
        elif re.search(f"PRIMER_RIGHT_{regex}_TM", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_TM", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.tm = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_GC_PERCENT", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_GC_PERCENT", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.gc = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_SELF_ANY_TH", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_SELF_ANY_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.anys = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_SELF_END_TH", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_SELF_END_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.three = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_HAIRPIN_TH", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_HAIRPIN_TH", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.hairpin = float(line.split("=")[1])
        elif re.search(f"PRIMER_RIGHT_{regex}_END_STABILITY", line):
            match = re.search(f"PRIMER_RIGHT_{regex}_END_STABILITY", line)
            primerpairs[f"{seqid}-{match.group(1)}"].right.end_stability = float(line.split("=")[1])
    return primerpairs


def parse_primer3_output_file(path: str | Path, primerpair_to_return: int) -> dict[str, PrimerPair]:
    return parse_primer3_output_text(Path(path).read_text(encoding="utf-8"), primerpair_to_return)
