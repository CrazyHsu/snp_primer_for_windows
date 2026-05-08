#!/usr/bin/env python3
"""
从标准 alignment_raw_*.fa 反推一个迷你 ABD BLAST 库。

每条同源区段（1001 bp，含 SNP 在中间 500 位）两端各 padding 500 N，
保证 BLAST hit ± 500 flanking 不会越界；染色体名加后缀避免 7A 冲突，
但保留 `chrXX_Chinese_Spring1.0_*` 形式让 _extract_chrom_short 仍能提到 7A/7D/4A。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "fixtures" / "expected"
OUT_DIR = HERE / "fixtures" / "mini_abd_db"
PAD = "N" * 500


def parse_alignment_raw(path: Path):
    """返回 [(orig_header, seq), ...]，自动剥掉 MSA gap (`-`) 字符。"""
    records = []
    cur_header = None
    cur_seq: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if cur_header is not None:
                records.append((cur_header, "".join(cur_seq).replace("-", "")))
            cur_header = line[1:].strip()
            cur_seq = []
        else:
            cur_seq.append(line.strip())
    if cur_header is not None:
        records.append((cur_header, "".join(cur_seq).replace("-", "")))
    return records


def chrom_only(orig_header: str) -> str:
    """`chr7A_Chinese_Spring1.0:c40192941-40191941-1` -> `chr7A_Chinese_Spring1.0`."""
    return orig_header.split(":", 1)[0]


SPACER = "N" * 100000  # 100 kb 间隔，让同一染色体上多个 SNP 区段在 BLAST 命中时
                       # 有独立的 sstart/sstop，模拟真实全基因组


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--makeblastdb", default=str(
        Path(__file__).resolve().parent.parent
        / "snp_primer_runtime" / "bin" / "makeblastdb"))
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fa_path = OUT_DIR / "IWB_mini_ABD.fa"

    # 把多个 marker 的同一染色体序列合并到一条，用 100kb N spacer 隔开。
    # 每条用 500N 包左右，保证 ±500 flanking 不越界。
    by_chrom: dict[str, list[str]] = {}
    for src in (EXPECTED / "alignment_raw_IWB50236.fa",
                EXPECTED / "alignment_raw_IWB58849.fa"):
        if not src.exists():
            sys.exit(f"missing {src}")
        for orig, seq in parse_alignment_raw(src):
            cid = chrom_only(orig)
            by_chrom.setdefault(cid, []).append(seq)

    written: list[tuple[str, str]] = []
    for cid, segments in by_chrom.items():
        # 每段独立 padding 500 N，再用 100kb N 拼起来
        padded_segments = [PAD + s + PAD for s in segments]
        merged = SPACER.join(padded_segments)
        written.append((cid, merged))

    with fa_path.open("w", encoding="utf-8") as f:
        for header, seq in written:
            f.write(f">{header}\n")
            for i in range(0, len(seq), 80):
                f.write(seq[i:i + 80] + "\n")

    print(f"wrote {fa_path} with {len(written)} sequences")
    for h, s in written:
        print(f"  {h}\t{len(s)} bp")

    db_prefix = OUT_DIR / "IWB_mini_ABD"
    cmd = [args.makeblastdb, "-in", str(fa_path), "-dbtype", "nucl",
           "-parse_seqids", "-out", str(db_prefix)]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"OK -> {db_prefix}")


if __name__ == "__main__":
    main()
