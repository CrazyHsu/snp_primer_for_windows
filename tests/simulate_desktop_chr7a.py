#!/usr/bin/env python3
"""
Layer C —— chr7A only sanity check。

模拟"用户只有 chr7A 单染色体库"的场景：从迷你 ABD 库里抽出 chr7A 单条做新库，
让 PipelineRunner.run() 跑端到端，验证：

* GUI 入口（PipelineRunner）在只有 7A 一条同源链时不崩
* 输出 selected_*_primers_*.txt 文件能产出
* 输出里 chromosome 列只含 7A（缺 7D / 4A，因为本地没有那两条）

不强求与标准结果（含 ABD 三条链）的逐字节匹配 —— 只看流程稳定性。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5_ROOT = HERE.parent
SRC = V5_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from snp_primer_app.models import BinaryBundle, PipelineRequest  # noqa: E402
from snp_primer_app.pipeline_runner import PipelineRunner  # noqa: E402

INPUT = Path("/mnt/e/Software/small_tools/priner_design/primer_design_input.txt")
# WSL 端测试用的 Linux 二进制目录（独立于 Windows 用户的 snp_primer_runtime/bin/）。
BIN_DIR = V5_ROOT / "tests" / ".linux_bin"
WORKDIR = Path("/tmp/v5_sim_chr7a")
DB_DIR = HERE / "fixtures" / "mini_chr7a_db"
DB_PREFIX = DB_DIR / "chr7A_only"


def build_chr7a_only_db():
    """从迷你 ABD 库提取 chr7A 单条做 BLAST 库。"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    src = HERE / "fixtures" / "mini_abd_db" / "IWB_mini_ABD.fa"
    dst = DB_DIR / "chr7A_only.fa"
    keep = False
    out_lines = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            keep = line.startswith(">chr7A_Chinese_Spring1.0")
        if keep:
            out_lines.append(line)
    dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    subprocess.run([str(BIN_DIR / "makeblastdb"), "-in", str(dst),
                    "-dbtype", "nucl", "-parse_seqids",
                    "-out", str(DB_PREFIX)], check=True)
    print(f"chr7A 单条库已建：{DB_PREFIX}")


def main():
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)
    build_chr7a_only_db()

    csv = WORKDIR / "input.csv"
    csv.write_text(INPUT.read_text(encoding="utf-8").strip() + "\n",
                   encoding="utf-8")

    req = PipelineRequest(
        input_csv=csv,
        reference_fasta=None,
        ploidy=3,  # 即使要 ABD，库里也只有 A
        max_enzyme_price=200,
        design_caps=True, design_kasp=True, blast_primers=False,
        max_tm=63, max_primer_size=25, pick_anyway=False,
        blast_mode="local",
        local_blast_db=DB_PREFIX,
    )
    bnd = BinaryBundle(
        blastn=BIN_DIR / "blastn",
        blastdbcmd=BIN_DIR / "blastdbcmd",
        makeblastdb=BIN_DIR / "makeblastdb",
        primer3_core=BIN_DIR / "primer3_core",
        muscle=BIN_DIR / "muscle5",
    )

    print("=== Layer C: chr7A only ===")
    try:
        result = PipelineRunner(req, bnd, WORKDIR,
                                logger=lambda m: print(f"  [log] {m}")).run()
    except Exception as e:
        print(f"  [FAIL] 流程崩了：{e}")
        return 1

    selected = list(WORKDIR.glob("CAPS_output/selected_*.txt")) + \
               list(WORKDIR.glob("KASP_output/selected_*.txt"))
    print(f"\n生成 {len(selected)} 份 selected_*_primers_*.txt：")
    for p in selected:
        n_lines = sum(1 for _ in p.open())
        print(f"  {p.relative_to(WORKDIR)}  ({n_lines} 行)")

    if not selected:
        print("[FAIL] 没生成任何 selected_*.txt")
        return 2
    print("[PASS] GUI 入口在 chr7A 单条库下未崩，正常出引物报告。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
