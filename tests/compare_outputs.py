#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对比 v5 跑出的 selected_*.txt 与标准 fixture 中的 selected_*.txt。

由于以下两个无法精确复现的因素，本脚本采用"宽松"对比：

1. **上游 Py2 dict 遍历是随机的** ⇒ 标准结果里行顺序 / PrimerID（L1/R13 这种
   计数器编号）不可复现。
2. **primer3 binary 版本/编译参数差异** ⇒ 同一 SEQUENCE_ID 下，primer3 会因
   惩罚权重的细微差别选 length 23 vs 25 这样不同的引物长度（penalty / Tm /
   start 列也跟着变）。

所以本脚本的 PASS 标准放宽为：

* 第一关：作为"严格对比"，比较前 16 列（index..ReverseComplement）；
* 第二关：作为"位点对比"，把每个 SNP × varsite × type (LEFT/RIGHT) 当作一个
  设计位点，看两边覆盖的位点集是否一致。
* 第三关："Sites that can differ all" 必须完全一致。

CAPS 一般能过严格对比；KASP 能过位点对比。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "fixtures" / "expected"

# 不参与比对的列：PrimerID（col 20，0-based）和 matched_chromosomes（col 20 之后）
# 因为后者跟用的是不是真实 BLAST 库相关
PRIMER_ID_COL = 19   # 0-based
MATCHED_COL = 20


def parse_primer_table(path):
    """
    解析一个 selected_*.txt。

    返回 (rows_strict, design_sites, sites_str)：
    * rows_strict：所有引物行的 (col0..col15) 元组集合（严格对比用）
    * design_sites：所有 (snp, varsite, type) 三元组的集合（位点对比用）
    * sites_str："Sites that can differ all" 行的字符串
    """
    rows = set()
    design_sites = set()
    sites_line = None
    in_sites = False
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                in_sites = False
                continue
            if line.startswith("Sites that can differ all"):
                in_sites = True
                continue
            if in_sites and sites_line is None and line[0].isdigit():
                sites_line = line.strip()
                in_sites = False
                continue
            if line.startswith("CAPS cut information") or line.startswith("Enzyme\t"):
                continue
            # 表头跳过
            if line.startswith("index\t"):
                continue
            fields = line.split("\t")
            if len(fields) < 19:
                continue
            # 必须以 IWB 等 SNP 名开头才算引物行
            if not fields[0] or fields[0].startswith("Enzyme"):
                continue
            # 严格 key：保留 index, product_size, type, start, end, diff_number,
            # 3'differall, length, Tm, GCcontent, any, 3', end_stability,
            # hairpin, primer_seq, ReverseComplement
            key = tuple(fields[:16])
            rows.add(key)
            # 位点 key：从 index 列拆出 SNP_ID、varsite，再加 type
            # CAPS index：IWB50236-{dCAPS|CAPS}-{enzyme},{price}-{seq}-{varsite}-{primer_end}-{p3_idx}
            # KASP index：IWB50236-{varsite}-{p3_idx}-{A|B|Common}
            parts = fields[0].split("-")
            snp = parts[0]
            kind_or_var = parts[1]
            if kind_or_var.lower() in ("dcaps", "caps"):
                # CAPS / dCAPS：第 4 段是 varsite
                if len(parts) >= 5:
                    varsite = parts[4]
                else:
                    varsite = None
            else:
                # KASP：第 1 段就是 varsite
                varsite = kind_or_var
            design_sites.add((snp, varsite, fields[2]))  # (snp, varsite, type)
    return rows, design_sites, sites_line


def diff_sets(name, ours, expected):
    only_ours = ours - expected
    only_exp = expected - ours
    common = ours & expected
    print(f"  {name}: 共同 {len(common)}; 仅 ours {len(only_ours)}; 仅 expected {len(only_exp)}")
    if only_ours and len(only_ours) <= 5:
        print("    仅 ours 例（前 5 行）：")
        for r in list(only_ours)[:5]:
            print("      " + "\t".join(r))
    if only_exp and len(only_exp) <= 5:
        print("    仅 expected 例（前 5 行）：")
        for r in list(only_exp)[:5]:
            print("      " + "\t".join(r))
    return len(only_ours) == 0 and len(only_exp) == 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workdir", required=True,
                   help="跑过 pipeline.run() 的工作目录（应该包含 CAPS_output/、KASP_output/）")
    args = p.parse_args()

    workdir = Path(args.workdir).resolve()
    failures = 0
    for snp in ("IWB50236", "IWB58849"):
        for kind, subdir in (("CAPS", "CAPS_output"), ("KASP", "KASP_output")):
            ours_path = workdir / subdir / f"selected_{kind}_primers_{snp}.txt"
            exp_path = EXPECTED / f"selected_{kind}_primers_{snp}.txt"
            print(f"\n=== {snp} {kind} ===")
            print(f"  ours = {ours_path}")
            print(f"  exp  = {exp_path}")
            if not ours_path.exists():
                print("  [FAIL] ours 不存在")
                failures += 1
                continue
            if not exp_path.exists():
                print("  [SKIP] expected 不存在")
                continue
            ours_rows, ours_design, ours_sites = parse_primer_table(ours_path)
            exp_rows, exp_design, exp_sites = parse_primer_table(exp_path)

            strict_ok = diff_sets("严格对比 (前 16 列)", ours_rows, exp_rows)
            design_ok = diff_sets("设计位点对比 (snp, varsite, type)",
                                  ours_design, exp_design)
            if ours_sites == exp_sites:
                print("  Sites that can differ all: 一致")
                sites_ok = True
            else:
                print("  Sites that can differ all: 不一致")
                print(f"    ours    : {ours_sites}")
                print(f"    expected: {exp_sites}")
                sites_ok = False

            if strict_ok and sites_ok:
                print("  [PASS] 严格匹配")
            elif design_ok and sites_ok:
                print("  [PASS] 位点匹配（primer3 binary 版本差异导致引物长度有微调）")
            else:
                print("  [FAIL]")
                failures += 1

    if failures:
        print(f"\n!! {failures} 个不一致")
        sys.exit(1)
    print("\n** 全部一致 **")


if __name__ == "__main__":
    main()
