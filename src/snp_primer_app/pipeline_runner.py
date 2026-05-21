"""
v5 改造版本：以前的 PipelineRunner 是 v4 自己写的全套实现，已经不用了。

现在 PipelineRunner 是一个**薄壳**，把 PipelineRequest / BinaryBundle 翻译成
:func:`core.pipeline.run` 的参数，直接调用上游忠实移植版本来设计引物。

桌面 GUI（``desktop.py``）不需要改，只要继续 ``from .pipeline_runner
import PipelineRunner`` + ``.run()`` 即可。
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable

# 把 v5 根目录加到 sys.path 上，让 ``import core.pipeline`` 能找到。
# 当通过 ``python -m snp_primer_app.desktop`` 启动时，cwd 通常是 src/，所以
# core 目录在 ../core/。当通过 PyInstaller 打包后，sys._MEIPASS 处理。
_HERE = Path(__file__).resolve().parent
_V5_ROOT = _HERE.parent.parent  # src/snp_primer_app -> src -> v5/
if str(_V5_ROOT) not in sys.path:
    sys.path.insert(0, str(_V5_ROOT))

from core import pipeline as core_pipeline  # noqa: E402

from .external_tools import LogFn, log_message
from .models import BinaryBundle, PipelineRequest, PipelineRunResult


class PipelineRunner:
    def __init__(
        self,
        request: PipelineRequest,
        binaries: BinaryBundle,
        working_dir: str | Path,
        *,
        logger: LogFn | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.request = request
        self.binaries = binaries
        self.working_dir = Path(working_dir)
        self.logger = logger
        self.cancel_event = cancel_event

    def run(self) -> PipelineRunResult:
        self.working_dir.mkdir(parents=True, exist_ok=True)
        log_message(self.logger, f"工作目录：{self.working_dir}")

        # 收集 bin 目录 —— BinaryBundle 给的是单个二进制路径，我们取它们的父目录
        # 作为 core.pipeline 的 bin_dir 参数（要求所有二进制在同一目录）。
        bin_dir = Path(self.binaries.blastn).parent

        # 两个字段分开传给 core.pipeline.run：local_blast_db 已经是 BLAST 库 prefix，
        # reference_fasta 是 raw FASTA（core 会自动 makeblastdb 建索引）。
        # GUI 在 _build_request 已经做过互斥校验，这里照样把"同时给"再挡一次防御。
        reference_db = str(self.request.local_blast_db) if self.request.local_blast_db else None
        reference_fasta = str(self.request.reference_fasta) if self.request.reference_fasta else None

        def _log(msg):
            log_message(self.logger, str(msg))

        # v10: blast_mode 真接入了。"local" 走 blastn + blastdbcmd（v9 行为不变）；
        # "ncbi_online" / "provider_online" 走 src/snp_primer_app/online_blast.py
        # 的 NCBI / EBI HTTP 客户端。在线模式忽略 reference_db / reference_fasta。
        log_message(self.logger, f"BLAST 模式：{self.request.blast_mode}")

        result = core_pipeline.run(
            input_csv=self.request.input_csv,
            workdir=self.working_dir,
            reference_db=reference_db,
            reference_fasta=reference_fasta,
            blast_mode=self.request.blast_mode,
            remote_provider=self.request.remote_provider,
            remote_database=self.request.remote_database,
            remote_fetch_database=self.request.remote_fetch_database,
            remote_email=self.request.remote_email,
            ploidy=int(self.request.ploidy),
            max_price=int(self.request.max_enzyme_price),
            design_caps=bool(self.request.design_caps),
            design_kasp=bool(self.request.design_kasp),
            max_tm=int(self.request.max_tm),
            max_size=int(self.request.max_primer_size),
            pick_anyway=1 if self.request.pick_anyway else 0,
            do_primer_blast=bool(self.request.blast_primers),
            bin_dir=str(bin_dir),
            cancel_event=self.cancel_event,
            log=_log,
        )

        # 把 dict 结果包成 PipelineRunResult
        wd = Path(result["workdir"])
        kasp_reports = sorted(wd.glob("KASP_output/selected_KASP_primers_*.txt"))
        caps_reports = sorted(wd.glob("CAPS_output/selected_CAPS_primers_*.txt"))
        return PipelineRunResult(
            working_dir=wd,
            input_csv=self.request.input_csv,
            blast_fasta=wd / "for_blast.fa",
            blast_output=wd / "blast_out.txt",
            temp_range=wd / "temp_range.txt",
            all_alignment_raw=wd / "All_alignment_raw.fa",
            potential_kasp=Path(result["potential_kasp"]) if result.get("potential_kasp") else None,
            potential_caps=Path(result["potential_caps"]) if result.get("potential_caps") else None,
            kasp_reports=kasp_reports,
            caps_reports=caps_reports,
        )
