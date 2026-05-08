#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# 上游 pinbo/SNP_Primer_Pipeline/bin/getflanking.py 的 Py3 移植版本。
# 算法逻辑保持一字不动；只把 sys.argv 入口包装成函数。

"""
解析 BLAST tabular 输出（多两列：qseq / sseq / slen），按 ploidy 过滤，
得到每个 marker 在主基因组上的命中区域，写入 outfile。
"""

import re
import sys
from collections import Counter


def _extract_chrom_short(subject):
	"""
	从 BLAST subject 名提取 2 字符的染色体短名（如 "7A"、"Un"）。

	兼容两种格式：
	- 上游注释里说的 "chr6A" 这种短名 → 直接取末 2 个字符
	- wheatomics 用的 "chr7A_Chinese_Spring1.0" 这种长名 →
	  取 "chr" 后面 2 个字符
	"""
	if subject.startswith("chr"):
		rest = subject[3:]
		m = re.match(r"^([A-Za-z0-9]{1,3})(?:_|$|\.)", rest)
		if m:
			return m.group(1)[:2]
	return subject[-2:]


def find(s, ch):
    """返回字符 ch 在 s 中的 1-based 位置列表。"""
    return [i + 1 for i, ltr in enumerate(s) if ltr == ch]


def _parse_polymarker_for_pos(polymarker_input):
    """解析 polymarker 输入，返回 {snp_name: snp_pos_in_query}（1-based）。"""
    snp_pos = {}
    with open(polymarker_input, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            # 兼容首列行号
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and "," in parts[1]:
                line = parts[1]
            snp, chrom, seq = line.replace(" ", "").split(",")
            snp = snp.replace("_", "-")
            seq = seq.strip()
            snp_pos[snp] = seq.find("[") + 1
    return snp_pos


def flanking(polymarker_input, blast_file, outfile, genome_number):
    """
    polymarker_input: parse_polymarker 的原始输入
    blast_file: blastn 输出（outfmt "6 std qseq sseq slen"）
    outfile: 输出文件 temp_range.txt
    genome_number: 1/2/3，对应 A / AB / ABD
    """
    if genome_number not in [1, 2, 3]:
        raise ValueError("genome_number must be 1, 2, or 3")

    genomes = "ABD"
    genomes = genomes[:genome_number] + "n"  # 加上 chrUn

    snp_pos = _parse_polymarker_for_pos(polymarker_input)

    xstream = 500  # 上下游各 500bp，做 dCAPS 用

    snpinfo = {}
    snp_list = []
    range_list = []
    snp_size_list = []
    min_align = 50  # 后续可能被覆盖

    with open(blast_file, "r", encoding="utf-8") as fin:
        for line in fin:
            if line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 15:
                continue
            query, subject = fields[:2]
            snp, qchrom = query.split("_")[0:2]
            qchrom = qchrom[0:2]
            schrom = _extract_chrom_short(subject)
            if schrom[1] not in genomes:
                continue
            pct_identity = 100 - (float(fields[4]) + float(fields[5])) / float(fields[3]) * 100
            align_length = int(fields[3])
            if snp not in snp_size_list:
                snp_size_list.append(snp)
                min_align = max(50, align_length * 0.9)
            if pct_identity > 88 and align_length > min_align:
                qstart, qstop, sstart, sstop = [int(x) for x in fields[6:10]]
                qseq, sseq = fields[12:14]
                slen = int(fields[14])
                if snp_pos[snp] < qstart or snp_pos[snp] > qstop:
                    continue
                qgap = find(qseq, "-")
                sgap = find(sseq, "-")
                temp = snp_pos[snp] - qstart
                nqgap = nsgap = 0
                for n in qgap:
                    if n < temp:
                        nqgap += 1
                        temp += 1
                for n in sgap:
                    if n < temp:
                        nsgap += 1
                pos = sstart + (temp - nsgap)
                strand = "plus"
                if sstart > sstop:
                    strand = "minus"
                    pos = sstart - (temp - nsgap)
                up = max(1, pos - xstream)
                down = min(slen, pos + xstream)
                pos2 = pos - up + 1
                if sstart > sstop:
                    pos2 = down - pos + 1
                if qchrom == schrom:
                    snpinfo[query] = query + "_" + str(pos2)
                snp_list.append(query)
                range_list.append("\t".join([subject, str(up) + "-" + str(down), strand]))

    max_hit = 6
    ct = Counter(snp_list)
    for i in ct:
        print(i, "has hits", ct[i])

    with open(outfile, "w", encoding="utf-8") as out:
        for i in range(len(snp_list)):
            snp = snp_list[i]
            if ct[snp] > max_hit:
                continue
            if snp not in snpinfo:
                # query 染色体上没有命中，没有 snpinfo —— 上游会 KeyError，这里保留
                continue
            rg = range_list[i]
            out.write(snpinfo[snp] + "\t" + rg + "\n")


def main():
    flanking(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
