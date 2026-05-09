"""KASP primer BLAST 比对的解析与渲染。

数据来源：``KASP_output/primer_blast_out_<MARKER>.txt``，由
``core/getkasp3.py:primer_blast`` 用 ``outfmt 6 std qseq sseq qlen slen`` 跑出来。

每行字段（总共 16 列）：

    query subject pident length mismatches gaps qstart qend
    sstart send evalue bitscore qseq sseq qlen slen

``qseq`` / ``sseq`` 已经是 aligned 过的（带 ``-`` 表示 gap），渲染中线只要
zip 比较即可。本模块**不重新跑 blastn**。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class Hit:
    subject: str
    pident: float
    length: int
    mismatches: int
    gaps: int
    qstart: int
    qend: int
    sstart: int
    send: int
    evalue: str
    bitscore: float
    qseq: str
    sseq: str
    qlen: int
    slen: int

    @property
    def strand(self) -> str:
        return "+" if self.send >= self.sstart else "-"


def parse_primer_blast_file(path) -> Dict[str, List[Hit]]:
    """解析一份 ``primer_blast_out_<MARKER>.txt``。

    返回 ``{primer_id: [Hit, ...]}``，按文件出现顺序，例如
    ``{"L1": [...], "R1": [...], "L2": [...]}``。

    primer_id 来自 BLAST 的 query 列（getkasp3 喂 blastn 时 ``>L1\\nseq``，所以
    query 就是 ``L1`` / ``R1`` / 等）。
    """
    p = Path(path)
    grouped: Dict[str, List[Hit]] = {}
    if not p.is_file():
        return grouped
    with open(p, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 16:
                continue
            try:
                hit = Hit(
                    subject=fields[1],
                    pident=float(fields[2]),
                    length=int(fields[3]),
                    mismatches=int(fields[4]),
                    gaps=int(fields[5]),
                    qstart=int(fields[6]),
                    qend=int(fields[7]),
                    sstart=int(fields[8]),
                    send=int(fields[9]),
                    evalue=fields[10],
                    bitscore=float(fields[11]),
                    qseq=fields[12],
                    sseq=fields[13],
                    qlen=int(fields[14]),
                    slen=int(fields[15]),
                )
            except (ValueError, IndexError):
                continue
            grouped.setdefault(fields[0], []).append(hit)
    return grouped


def _midline(qseq: str, sseq: str) -> str:
    """BLAST 风格中线：相同 ``|``，不同空格，任一端 ``-`` 也空格。"""
    out = []
    for q, s in zip(qseq, sseq):
        if q == "-" or s == "-":
            out.append(" ")
        elif q.upper() == s.upper():
            out.append("|")
        else:
            out.append(" ")
    return "".join(out)


def _wrap_alignment(hit: Hit, width: int = 60) -> str:
    """把一个 hit 的 query/midline/subject 按宽度折行排版。"""
    out_lines: list[str] = []
    qseq = hit.qseq
    sseq = hit.sseq
    mid = _midline(qseq, sseq)
    # 计算每段的真实坐标（不包括 gap）。
    q_pos = hit.qstart
    s_pos = hit.sstart
    s_step = 1 if hit.strand == "+" else -1
    # 用于 label 对齐的最大宽度
    label_w = max(len(str(hit.qend)), len(str(hit.send)), len(str(hit.qstart)),
                  len(str(hit.sstart)))
    pos_w = max(label_w, 4)
    for chunk_start in range(0, len(qseq), width):
        chunk_end = chunk_start + width
        q_chunk = qseq[chunk_start:chunk_end]
        s_chunk = sseq[chunk_start:chunk_end]
        m_chunk = mid[chunk_start:chunk_end]
        # 计算这块的起止真实坐标
        q_chunk_nogap = q_chunk.replace("-", "")
        s_chunk_nogap = s_chunk.replace("-", "")
        q_chunk_start = q_pos
        q_chunk_end = q_pos + max(len(q_chunk_nogap) - 1, 0)
        s_chunk_start = s_pos
        s_chunk_end = s_pos + s_step * max(len(s_chunk_nogap) - 1, 0)
        out_lines.append(
            f"Query {q_chunk_start:>{pos_w}}  {q_chunk}  {q_chunk_end}"
        )
        out_lines.append(
            f"      {'':>{pos_w}}  {m_chunk}"
        )
        out_lines.append(
            f"Sbjct {s_chunk_start:>{pos_w}}  {s_chunk}  {s_chunk_end}"
        )
        out_lines.append("")
        q_pos = q_chunk_end + 1
        s_pos = s_chunk_end + s_step
    return "\n".join(out_lines).rstrip() + "\n"


def render_alignment(primer_label: str, primer_seq: str | None,
                     hits: List[Hit]) -> str:
    """把一条 primer 的所有 BLAST hit 拼成 mono 文本。

    primer_label: 比如 ``IWB50236_L1``（用于 tab 标题之外的内部标记）
    primer_seq: 引物序列（``selected_KASP_primers_*.txt`` 里有；可以传 None
        让本模块从 hits[0].qseq 自己推断）
    hits: parse_primer_blast_file 返回的 hit 列表
    """
    out: list[str] = []
    out.append(f"=== Primer {primer_label} ===")
    if primer_seq is None and hits:
        primer_seq = hits[0].qseq.replace("-", "")
    if primer_seq:
        out.append(f"Sequence:  {primer_seq}   ({len(primer_seq)} nt)")
    out.append("")
    if not hits:
        out.append("No BLAST hits for this primer.")
        return "\n".join(out) + "\n"
    out.append("─" * 70)
    for n, hit in enumerate(hits, 1):
        out.append(
            f"Hit {n}  {hit.subject}   identity={hit.pident:.1f}%   "
            f"length={hit.length}   mismatches={hit.mismatches}   "
            f"gaps={hit.gaps}"
        )
        out.append(
            f"       subject {hit.sstart}–{hit.send}  ({hit.strand}strand)"
            f"   evalue={hit.evalue}"
        )
        out.append("")
        out.append(_wrap_alignment(hit))
    return "\n".join(out) + "\n"


def collect_kasp_blast_groups(kasp_dir) -> Dict[str, Dict[str, List[Hit]]]:
    """扫 ``KASP_output/`` 下所有 ``primer_blast_out_<MARKER>.txt``，
    返回 ``{marker: {primer_id: [Hit,...]}}``。
    """
    out: Dict[str, Dict[str, List[Hit]]] = {}
    base = Path(kasp_dir) if kasp_dir else None
    if not base or not base.is_dir():
        return out
    prefix = "primer_blast_out_"
    suffix = ".txt"
    for f in sorted(base.glob(f"{prefix}*{suffix}")):
        marker = f.name[len(prefix):-len(suffix)]
        out[marker] = parse_primer_blast_file(f)
    return out
