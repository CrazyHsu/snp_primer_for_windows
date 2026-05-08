#!/usr/bin/env python3
"""
模拟 Windows 桌面用户双击 `Launch SNP Primer Desktop.cmd` 之后的整个端到端流程：

1. 读 polymarker 输入文件 (primer_design_input.txt)
2. 选 "本地 BLAST 库" 模式，库路径 = tests/fixtures/mini_abd_db/IWB_mini_ABD
3. 设置参数：ABD ploidy / 最大酶价 200 / CAPS+KASP / 最大 Tm 63 / 最大 size 25
4. 不开启 pick_anyway，不开启 primer BLAST
5. 通过 PipelineRunner.run() 跑 — 这是桌面 GUI 的 Run Pipeline 按钮真正调到
   的那个函数

跑完后把 selected_*.txt 与标准 fixture 对比。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5_ROOT = HERE.parent
SRC = V5_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from snp_primer_app.models import BinaryBundle, PipelineRequest  # noqa: E402
from snp_primer_app.pipeline_runner import PipelineRunner  # noqa: E402

DEFAULT_INPUT = Path("/mnt/e/Software/small_tools/priner_design/primer_design_input.txt")
DEFAULT_DB = V5_ROOT / "tests" / "fixtures" / "mini_abd_db" / "IWB_mini_ABD"
# WSL 端测试用的 Linux 二进制目录（独立于 Windows 用户的 snp_primer_runtime/bin/）。
DEFAULT_BIN = V5_ROOT / "tests" / ".linux_bin"
DEFAULT_WORKDIR = Path("/tmp/v5_sim_desktop")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEFAULT_INPUT))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--bin", default=str(DEFAULT_BIN))
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    if workdir.exists():
        import shutil
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # 桌面 GUI 在 _build_request 里把输入文本写到 workdir/input.csv，
    # 这里直接复制 polymarker 输入文件过去，行为一致。
    csv = workdir / "input.csv"
    csv.write_text(Path(args.input).read_text(encoding="utf-8").strip() + "\n",
                   encoding="utf-8")

    # 把标准 alignment_raw_*.fa 预放进 workdir，并把 header 改成 muscle
    # 重命名后的格式（`chrXY_Chinese_Spring1.0-N`，N 是 BLAST hit rank），
    # 让 getCAPS/getkasp3 检测到 alignment 已存在跳过 muscle 调用。
    # 这是为了消除 muscle v5（Ubuntu）vs muscle v3（wheatomics）比对差异，
    # 把 GUI 入口 -> BLAST -> getflanking -> primer3 这条链作为重点验证对象。
    expected_dir = HERE / "fixtures" / "expected"
    import re as _re
    for src in expected_dir.glob("alignment_raw_*.fa"):
        out = workdir / src.name
        with src.open(encoding="utf-8") as fi, out.open("w", encoding="utf-8") as fo:
            for line in fi:
                if line.startswith(">"):
                    # `chr7A_Chinese_Spring1.0:c40192941-40191941-1` -> `chr7A_Chinese_Spring1.0-1`
                    h = line[1:].strip()
                    chrom = h.split(":", 1)[0]
                    m = _re.search(r"-(\d+)\s*$", h)
                    rank = m.group(1) if m else "0"
                    fo.write(f">{chrom}-{rank}\n")
                else:
                    fo.write(line)
    n = len(list(workdir.glob("alignment_raw_*.fa")))
    print(f"  (已把 {n} 份标准 alignment_raw 预放进 workdir，并重命名 header)")


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
        blast_mode="local",
        local_blast_db=Path(args.db).resolve(),
    )
    binaries = BinaryBundle(
        blastn=bin_root / "blastn",
        blastdbcmd=bin_root / "blastdbcmd",
        makeblastdb=bin_root / "makeblastdb",
        primer3_core=bin_root / "primer3_core",
        muscle=bin_root / "muscle",
    )

    print("=== 模拟 Windows 桌面 Run Pipeline 按钮 ===")
    print(f"  input    = {csv}")
    print(f"  db       = {request.local_blast_db}")
    print(f"  bin      = {bin_root}")
    print(f"  workdir  = {workdir}")

    result = PipelineRunner(
        request=request, binaries=binaries, working_dir=workdir,
        logger=lambda m: print(f"  [log] {m}"),
    ).run()

    print(f"\nDone. potential_kasp={result.potential_kasp} potential_caps={result.potential_caps}")
    print(f"CAPS reports: {[str(p) for p in result.caps_reports]}")
    print(f"KASP reports: {[str(p) for p in result.kasp_reports]}")


if __name__ == "__main__":
    main()
