#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从标准 (My_CAPS_539 / My_KASP_539) 输出反推 fixture：

1. 把 alignment_raw_<MARKER>.fa 里每条记录头去掉 ``-N`` 后缀、序列去掉 gap，
   按 N 升序排好，写到对应的 flanking_temp_marker_<query>_<chr>_<allele>_<pos>.fa。
   ``query``/``chr``/``allele``/``pos`` 通过 polymarker 输入 + 标准 BLAST 输出推算。
2. 把标准的 IWB50236_blast_out.txt 和 IWB58849_blast_out.txt 合并成 fixture
   ``blast_out.txt``。

输出目录： ``tests/fixtures/flanking/``、``tests/fixtures/blast_out.txt``、
``tests/fixtures/expected/``（标准的 selected_*.txt / alignment_raw_*.fa）。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FIXTURES_FLANK = FIXTURES / "flanking"
FIXTURES_EXPECT = FIXTURES / "expected"
EXTRACT_TMP = FIXTURES / "_tmp"

PRINER_DESIGN_DIR = Path(__file__).resolve().parents[3]
CAPS_TAR = PRINER_DESIGN_DIR / "My_CAPS_539.tar.gz"
KASP_TAR = PRINER_DESIGN_DIR / "My_KASP_539.tar.gz"
INPUT_TXT = PRINER_DESIGN_DIR / "primer_design_input.txt"


def _read_fasta(path):
    """返回 [(header_no_>, seq_full_string), ...]，保留出现顺序。"""
    records = []
    name, parts = None, []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(parts)))
                name = line[1:].split()[0]
                parts = []
            else:
                parts.append(line)
        if name is not None:
            records.append((name, "".join(parts)))
    return records


def _strip_suffix_and_gaps(records):
    """records 里每条记录 header 是 '...-N' 形式，把 -N 去掉、gap 去掉，
    并按 N 升序返回。"""
    out = []
    for header, seq in records:
        # 找最后一个 '-N' 后缀
        m = re.search(r"-(\d+)$", header)
        if not m:
            raise ValueError(f"header 没有 -N 后缀: {header}")
        n = int(m.group(1))
        clean_header = header[:m.start()]
        clean_seq = seq.replace("-", "")
        out.append((n, clean_header, clean_seq))
    out.sort(key=lambda x: x[0])
    return [(h, s) for _n, h, s in out]


def _parse_polymarker(path):
    """返回 [(snpname, chrom, snp_pos_1based_in_query, IUPAC), ...]"""
    iupac = {
        "[A/G]": "R", "[G/A]": "R",
        "[C/T]": "Y", "[T/C]": "Y",
        "[G/C]": "S", "[C/G]": "S",
        "[A/T]": "W", "[T/A]": "W",
        "[G/T]": "K", "[T/G]": "K",
        "[A/C]": "M", "[C/A]": "M",
    }
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and "," in parts[1]:
                line = parts[1]
            snp, chrom, seq = line.replace(" ", "").split(",")
            snp = snp.replace("_", "-")
            seq = seq.strip()
            pos = seq.find("[") + 1  # 1-based
            ambig = iupac[seq[seq.find("["):seq.find("[") + 5]]
            out.append((snp, chrom, pos, ambig))
    return out


def _extract_chrom_short(subject):
    if subject.startswith("chr"):
        rest = subject[3:]
        m = re.match(r"^([A-Za-z0-9]{1,3})(?:_|$|\.)", rest)
        if m:
            return m.group(1)[:2]
    return subject[-2:]


def _query_pos_to_flanking_pos(blast_file, snp_query_name, snp_pos_in_query):
    """
    从标准 BLAST 输出里找 snp_query_name 在 query 染色体上的最佳命中（同 ploidy
    chromosome 上 query == subject），重现上游 getflanking 的算法计算 pos2。
    """
    snp = snp_query_name.split("_")[0]  # e.g. IWB50236_7A_R → IWB50236
    qchrom = snp_query_name.split("_")[1][:2]  # 7A
    snp_size_min_align = None
    best = None
    with open(blast_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 15:
                continue
            query, subject = fields[:2]
            if query != snp_query_name:
                continue
            schrom = _extract_chrom_short(subject)
            # 对照 getflanking.py: 跳过非主基因组
            # 对 ploidy=3 (ABD)，所有 A/B/D + n 都通过
            pct_identity = 100 - (float(fields[4]) + float(fields[5])) / float(fields[3]) * 100
            align_length = int(fields[3])
            if snp_size_min_align is None:
                snp_size_min_align = max(50, align_length * 0.9)
            if pct_identity > 88 and align_length > snp_size_min_align:
                qstart, qstop, sstart, sstop = [int(x) for x in fields[6:10]]
                qseq, sseq = fields[12:14]
                slen = int(fields[14])
                if snp_pos_in_query < qstart or snp_pos_in_query > qstop:
                    continue
                qgap = [i + 1 for i, c in enumerate(qseq) if c == "-"]
                sgap = [i + 1 for i, c in enumerate(sseq) if c == "-"]
                temp = snp_pos_in_query - qstart
                nqgap = nsgap = 0
                for n in qgap:
                    if n < temp:
                        nqgap += 1
                        temp += 1
                for n in sgap:
                    if n < temp:
                        nsgap += 1
                pos = sstart + (temp - nsgap)
                if sstart > sstop:
                    pos = sstart - (temp - nsgap)
                up = max(1, pos - 500)
                down = min(slen, pos + 500)
                pos2 = pos - up + 1
                if sstart > sstop:
                    pos2 = down - pos + 1
                if qchrom == schrom:
                    return pos2
    raise RuntimeError(f"找不到 {snp_query_name} 在 {qchrom} 上的 BLAST 命中")


def main():
    FIXTURES_FLANK.mkdir(parents=True, exist_ok=True)
    FIXTURES_EXPECT.mkdir(parents=True, exist_ok=True)
    EXTRACT_TMP.mkdir(parents=True, exist_ok=True)

    # 解压两个 tar 到临时目录
    for tar in (CAPS_TAR, KASP_TAR):
        if not tar.exists():
            print(f"找不到 {tar}", file=sys.stderr)
            sys.exit(1)
        with tarfile.open(tar, "r:gz") as tf:
            tf.extractall(EXTRACT_TMP)

    caps_dir = EXTRACT_TMP / "My_CAPS_539"
    kasp_dir = EXTRACT_TMP / "My_KASP_539"

    # 解析 polymarker 输入
    snps = _parse_polymarker(INPUT_TXT)
    print(f"解析 input: {len(snps)} 个 SNP")
    for snp in snps:
        print(f"  {snp}")

    # 选 IWB50236 / IWB58849
    target_snps = [s for s in snps if s[0] in {"IWB50236", "IWB58849"}]

    # 先用 IWB50236_blast_out.txt 等推 flanking pos
    # 标准 BLAST 输出是按 SNP 单独存的：IWB50236_blast_out.txt
    flanking_targets = []  # [(filename, records_list), ...]
    blast_lines = []  # 用于合并 fixture blast_out.txt

    for snp_name, chrom, snp_pos_in_query, allele_iupac in target_snps:
        blast_file = caps_dir / f"{snp_name}_blast_out.txt"
        if not blast_file.exists():
            blast_file = kasp_dir / f"{snp_name}_blast_out.txt"
        # blast 文件其实是以"SNP query name (e.g. IWB50236_7A_R)"为 key 收集所有命中
        # 但每个 SNP 只有一个 query，所以整个文件就是一个 SNP 的全部命中
        # 推 flanking pos：
        snp_query_name = f"{snp_name}_{chrom}_{allele_iupac}"
        pos2 = _query_pos_to_flanking_pos(str(blast_file), snp_query_name,
                                          snp_pos_in_query)
        print(f"  {snp_name}: query 位 {snp_pos_in_query}, flanking 位 {pos2}")

        # 找 alignment_raw 文件
        align_fa = caps_dir / f"alignment_raw_{snp_name}.fa"
        if not align_fa.exists():
            align_fa = kasp_dir / f"alignment_raw_{snp_name}.fa"
        records = _read_fasta(align_fa)
        if not records:
            raise RuntimeError(f"alignment_raw 为空: {align_fa}")
        # 头里去掉 -N，去 gap
        clean = _strip_suffix_and_gaps(records)
        # 写到 fixture flanking
        out_name = f"flanking_temp_marker_{snp_name}_{chrom}_{allele_iupac}_{pos2}.txt.fa"
        out_path = FIXTURES_FLANK / out_name
        with open(out_path, "w", encoding="utf-8") as out:
            for h, s in clean:
                out.write(">" + h + "\n")
                # 60 字符一行（与 blastdbcmd 默认输出一致）
                for i in range(0, len(s), 60):
                    out.write(s[i:i + 60] + "\n")
        flanking_targets.append(out_path)
        print(f"  写出 {out_name}（{len(clean)} 条记录）")

        # 把这个 SNP 的 BLAST 行加入合并 blast_out
        with open(blast_file, "r", encoding="utf-8") as f:
            blast_lines.append(f.read())

    # 合并 BLAST 输出
    blast_out_path = FIXTURES / "blast_out.txt"
    with open(blast_out_path, "w", encoding="utf-8") as out:
        for chunk in blast_lines:
            out.write(chunk)
            if not chunk.endswith("\n"):
                out.write("\n")
    print(f"合并 blast_out -> {blast_out_path}")

    # 把标准的预期输出文件复制到 fixtures/expected/
    for snp_name, _, _, _ in target_snps:
        for src_dir, prefix in [
            (caps_dir, "selected_CAPS_primers_"),
            (kasp_dir, "selected_KASP_primers_"),
        ]:
            src = src_dir / f"{prefix}{snp_name}.txt"
            if src.exists():
                shutil.copyfile(src, FIXTURES_EXPECT / src.name)
        for src_dir in (caps_dir, kasp_dir):
            src = src_dir / f"alignment_raw_{snp_name}.fa"
            if src.exists():
                shutil.copyfile(src, FIXTURES_EXPECT / src.name)
    print("复制 expected 文件完成。")


if __name__ == "__main__":
    main()
