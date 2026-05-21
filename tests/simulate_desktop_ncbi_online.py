#!/usr/bin/env python3
"""
v10 烟雾测试：模拟用户在桌面 GUI 里选 ``NCBI Online BLAST`` 后整个端到端流程。

跟 simulate_desktop.py 的区别：
- 不用本地 BLAST 库；BLAST 通过 NCBI HTTP API 提交。
- **要联网**。NCBI BLAST 排队时间不定，整跑可能要 1-5 分钟，繁忙时 >10 分钟。
- 强烈建议给一个真实邮箱（``--email`` 或 ``$NCBI_EMAIL``），否则可能被限流。

跑完预期产物：
- ``blast_out.txt`` 非空、每行 15 列 tab 分隔（subject_id 已被前缀为 ``chr{XY}_``）
- ``temp_range.txt`` 非空
- ``flanking_temp_marker_*.txt.fa`` 至少一份非空
- 各一份 ``selected_KASP_primers_*.txt`` / ``selected_CAPS_primers_*.txt``

注意：online 模式跑出来的引物**不会**字节对齐 wheatomics 标准结果，因为命中的 hit
集合 / flanking 序列都来自 NCBI 当下的 RefSeq 版本，而不是 mini ABD 合成 contig。
所以本脚本不跑 compare_outputs.py，只断言"流程跑通 + 关键产物存在"。

用法：
    PYTHONPATH=src python3 tests/simulate_desktop_ncbi_online.py \
        --email you@example.com \
        --database refseq_genomes \
        --limit 2
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V10_ROOT = HERE.parent
SRC = V10_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from snp_primer_app.models import BinaryBundle, PipelineRequest  # noqa: E402
from snp_primer_app.pipeline_runner import PipelineRunner  # noqa: E402


DEFAULT_INPUT = Path("/mnt/e/Software/small_tools/priner_design/primer_design_input.txt")
DEFAULT_BIN = V10_ROOT / "tests" / ".linux_bin"
DEFAULT_WORKDIR = Path("/tmp/v10_sim_desktop_ncbi_online")
DEFAULT_DB = "refseq_genomes"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--bin", default=str(DEFAULT_BIN))
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    ap.add_argument("--database", default=DEFAULT_DB,
                    help="NCBI BLAST database (nt / core_nt / refseq_genomes / ...)")
    ap.add_argument("--email", default=os.environ.get("NCBI_EMAIL", ""),
                    help="Contact email (NCBI strongly recommends one). "
                         "Defaults to $NCBI_EMAIL.")
    ap.add_argument("--limit", type=int, default=2,
                    help="只取输入前 N 行（在线 BLAST 慢，默认 2 行）。0 = 全部。")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    raw_lines = [
        line for line in Path(args.input).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit and args.limit > 0:
        raw_lines = raw_lines[: args.limit]
    csv = workdir / "input.csv"
    csv.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")

    bin_root = Path(args.bin).resolve()
    request = PipelineRequest(
        input_csv=csv,
        reference_fasta=None,
        ploidy=3,
        max_enzyme_price=200,
        design_caps=True,
        design_kasp=True,
        blast_primers=False,
        max_tm=63,
        max_primer_size=25,
        pick_anyway=False,
        blast_mode="ncbi_online",
        local_blast_db=None,
        remote_provider=None,
        remote_database=args.database,
        remote_fetch_database=None,
        remote_email=args.email or None,
    )
    binaries = BinaryBundle(
        blastn=bin_root / "blastn",
        blastdbcmd=bin_root / "blastdbcmd",
        makeblastdb=bin_root / "makeblastdb",
        primer3_core=bin_root / "primer3_core",
        muscle=bin_root / "muscle",
    )

    print("=== 模拟桌面 Run Pipeline 按钮 (NCBI Online BLAST) ===")
    print(f"  input     = {csv} ({len(raw_lines)} marker(s))")
    print(f"  database  = {args.database}")
    print(f"  email     = {args.email or '(none — may be rate-limited)'}")
    print(f"  workdir   = {workdir}")

    result = PipelineRunner(
        request=request, binaries=binaries, working_dir=workdir,
        logger=lambda m: print(f"  [log] {m}"),
    ).run()

    blast_out = workdir / "blast_out.txt"
    temp_range = workdir / "temp_range.txt"
    flankings = sorted(workdir.glob("flanking_temp_marker_*.txt.fa"))

    print("\n=== 断言 ===")
    print(f"  blast_out.txt size       = {blast_out.stat().st_size if blast_out.exists() else 'MISSING'}")
    print(f"  temp_range.txt size      = {temp_range.stat().st_size if temp_range.exists() else 'MISSING'}")
    print(f"  flanking_temp_marker_*  = {len(flankings)} file(s)")
    print(f"  KASP selected reports    = {len(result.kasp_reports)}")
    print(f"  CAPS selected reports    = {len(result.caps_reports)}")

    failures: list[str] = []
    if not blast_out.exists() or blast_out.stat().st_size == 0:
        failures.append("blast_out.txt 缺失或为空")
    else:
        first = blast_out.read_text(encoding="utf-8").splitlines()[0]
        if len(first.split("\t")) < 15:
            failures.append(f"blast_out.txt 列数不够（{len(first.split(chr(9)))}）")
    if not temp_range.exists() or temp_range.stat().st_size == 0:
        failures.append("temp_range.txt 缺失或为空")
    if not flankings:
        failures.append("没有任何 flanking_temp_marker_*.txt.fa")
    if not result.kasp_reports and not result.caps_reports:
        failures.append("KASP / CAPS 报告都为空（设计阶段失败）")

    if failures:
        print("\n*** FAIL ***")
        for msg in failures:
            print(f"  - {msg}")
        return 1
    print("\n** OK ** online NCBI 流程跑通，关键产物都存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
