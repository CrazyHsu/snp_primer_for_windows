#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# 上游 pinbo/SNP_Primer_Pipeline/bin/parse_polymarker_input.py 的 Py3 移植版本。
# 算法逻辑保持与上游一致，但封装成可导入的函数，方便 pipeline.py 调用。

"""
解析 PolyMarker 风格输入并写出 BLAST 用 FASTA。

输入格式（每行）：
    [行号<TAB>]<snpname>,<chrom>,<flanking_left>[A/G]<flanking_right>
其中行号列可选；wheatomics 网站给的标准输入会带行号。
"""

import sys

iupac = {
    "[A/G]": "R", "[G/A]": "R",
    "[C/T]": "Y", "[T/C]": "Y",
    "[G/C]": "S", "[C/G]": "S",
    "[A/T]": "W", "[T/A]": "W",
    "[G/T]": "K", "[T/G]": "K",
    "[A/C]": "M", "[C/A]": "M",
}


def _strip_row_index(line):
    """如果首列是数字行号（用 TAB 或空白与后面分隔），去掉它。"""
    parts = line.split(None, 1)
    if len(parts) == 2 and parts[0].isdigit() and "," in parts[1]:
        return parts[1]
    return line


def parse(polymarker_input, outfile="for_blast.fa"):
    """
    把 polymarker_input 转成 BLAST 用 FASTA 写到 outfile。
    返回写入的记录数。
    """
    n = 0
    with open(polymarker_input, "r", encoding="utf-8") as fin, \
         open(outfile, "w", encoding="utf-8") as out:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            line = _strip_row_index(line)
            # 上游用 line.replace(" ","").split(",") —— 把空格删掉后按逗号切
            snpname, chrom, seq = line.replace(" ", "").split(",")
            snpname = snpname.replace("_", "-")
            seq = seq.strip()
            pos = seq.find("[")
            snp = iupac[seq[pos:pos + 5]]
            seq2 = seq[:pos] + snp + seq[pos + 5:]
            out.write(">" + snpname + "_" + chrom + "_" + snp + "\n" + seq2 + "\n")
            n += 1
    return n


def main():
    parse(sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
