from __future__ import annotations

import datetime
import json
import os
import queue
import shutil
import threading
import tkinter as tk
import tkinter.font as tkfont
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import BinaryBundle, PipelineRequest
from .parsers import parse_polymarker_lines, render_blast_fasta
from .pipeline_runner import PipelineRunner
from .runtime_paths import default_reference_fasta, ensure_runtime_dirs
from .workflow import build_pipeline_plan


LOCAL_MODE = "Local BLAST DB or FASTA"
NCBI_MODE = "NCBI Online BLAST"
OTHER_ONLINE_MODE = "Other Online Provider"


class DesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SNP Primer Desktop")
        self.root.geometry("1440x980")
        # 全局字体放大：Tk 默认 9pt 在高 DPI 屏上太小。改 named font 一次性影响
        # 所有 ttk.Label / ttk.Entry / ttk.Button / Combobox / Notebook tab 标题。
        # 单独设 Text 字体（用 mono 等宽更适合 polymarker / 引物序列）。
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                     "TkHeadingFont", "TkCaptionFont"):
            try:
                tkfont.nametofont(name).configure(size=11)
            except tk.TclError:
                pass
        try:
            tkfont.nametofont("TkFixedFont").configure(size=11)
        except tk.TclError:
            pass
        # 个别 ttk theme（如 vista / winnative）的 Notebook 标签 / Button 用自己的
        # 字体而不继承 TkDefaultFont，这里显式 Style 配一下。
        _style = ttk.Style()
        _style.configure("TButton", font=("Segoe UI", 11))
        _style.configure("TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        # Notebook 标签视觉分隔：tabmargins 给整组 tab 留白；padding 让每个 tab
        # 变胖；style.map 让选中 tab 白底蓝字 vs 未选灰底深灰，hover 浅蓝高亮。
        _style.configure("TNotebook", tabmargins=[3, 6, 3, 0])
        _style.configure("TNotebook.Tab", padding=[18, 10], font=("Segoe UI", 11))
        _style.map(
            "TNotebook.Tab",
            background=[("selected", "#ffffff"),
                        ("active", "#e8f0fe"),
                        ("!selected", "#dcdcdc")],
            foreground=[("selected", "#1a73e8"),
                        ("!selected", "#444444")],
        )
        self._mono_font = ("Consolas", 12)
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.run_thread: threading.Thread | None = None
        runtime_dirs = ensure_runtime_dirs()

        self.mode_var = tk.StringVar(value=LOCAL_MODE)
        self.reference_path_var = tk.StringVar(value=default_reference_fasta())
        self.local_blast_db_var = tk.StringVar()
        self.remote_provider_var = tk.StringVar(value="ebi")
        self.remote_database_var = tk.StringVar(value="refseq_genomes")
        self.remote_fetch_database_var = tk.StringVar(value="ena_sequence")
        self.remote_email_var = tk.StringVar()
        self.ploidy_var = tk.StringVar(value="3")
        self.max_price_var = tk.StringVar(value="200")
        self.design_caps_var = tk.BooleanVar(value=True)
        self.design_kasp_var = tk.BooleanVar(value=True)
        self.blast_primers_var = tk.BooleanVar(value=False)
        self.max_tm_var = tk.StringVar(value="63")
        self.max_size_var = tk.StringVar(value="25")
        self.pick_anyway_var = tk.BooleanVar(value=False)
        self.working_dir_var = tk.StringVar(value=str(runtime_dirs["workspace"]))
        self.binary_root_var = tk.StringVar(value=str(runtime_dirs["bin"]))
        self.status_var = tk.StringVar(value="Idle")

        # 持久化 GUI 日志：每次启动建一个时间戳文件，便于失败后把整段贴出来排查。
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path: Path = runtime_dirs["logs"] / f"desktop_{ts}.log"
        try:
            self._log_fp = self._log_path.open("a", encoding="utf-8")
        except OSError:
            self._log_fp = None  # 落盘失败也别让 GUI 起不来

        self._build_layout()
        self._refresh_mode_fields()  # 局部模式下会调用 _update_blast_input_lockout 设初始 enabled/disabled
        self.root.after(100, self._drain_ui_queue)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(outer, text="BLAST Source And Runtime", padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="BLAST mode").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.mode_combo = ttk.Combobox(
            top,
            textvariable=self.mode_var,
            values=[LOCAL_MODE, NCBI_MODE, OTHER_ONLINE_MODE],
            state="readonly",
        )
        self.mode_combo.grid(row=0, column=1, sticky=tk.EW, pady=4)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_mode_fields())

        ttk.Label(top, text="Reference FASTA").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.reference_entry = ttk.Entry(top, textvariable=self.reference_path_var, width=90)
        self.reference_entry.grid(row=1, column=1, sticky=tk.EW, pady=4)
        self.reference_browse_button = ttk.Button(top, text="Browse", command=self.choose_reference_fasta)
        self.reference_browse_button.grid(row=1, column=2, padx=6, pady=4)

        ttk.Label(top, text="Local BLAST DB").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.local_db_entry = ttk.Entry(top, textvariable=self.local_blast_db_var, width=90)
        self.local_db_entry.grid(row=2, column=1, sticky=tk.EW, pady=4)
        self.local_db_browse_button = ttk.Button(top, text="Browse", command=self.choose_local_blast_db)
        self.local_db_browse_button.grid(row=2, column=2, padx=6, pady=4)

        # 互斥联动：哪个字段有内容，另一个字段的 Entry+Browse 就 disabled，
        # 直到当前字段被清空才会重新可用。trace_add 在变量任何 .set/键入后触发。
        self.reference_path_var.trace_add("write", self._update_blast_input_lockout)
        self.local_blast_db_var.trace_add("write", self._update_blast_input_lockout)

        ttk.Label(top, text="Online database").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.remote_db_combo = ttk.Combobox(
            top,
            textvariable=self.remote_database_var,
            values=[
                "nt",
                "core_nt",
                "refseq_genomes",
                "refseq_representative_genomes",
                "refseq_rna",
                "wgs",
            ],
        )
        self.remote_db_combo.grid(row=3, column=1, sticky=tk.EW, pady=4)

        ttk.Label(top, text="Other provider").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.remote_provider_combo = ttk.Combobox(
            top,
            textvariable=self.remote_provider_var,
            values=["ebi"],
            state="readonly",
        )
        self.remote_provider_combo.grid(row=4, column=1, sticky=tk.EW, pady=4)

        ttk.Label(top, text="Fetch database").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.remote_fetch_db_entry = ttk.Entry(top, textvariable=self.remote_fetch_database_var, width=90)
        self.remote_fetch_db_entry.grid(row=5, column=1, sticky=tk.EW, pady=4)

        ttk.Label(top, text="Contact email").grid(row=6, column=0, sticky=tk.W, pady=4)
        self.remote_email_entry = ttk.Entry(top, textvariable=self.remote_email_var, width=90)
        self.remote_email_entry.grid(row=6, column=1, sticky=tk.EW, pady=4)

        ttk.Label(top, text="Binary root").grid(row=7, column=0, sticky=tk.W, pady=4)
        self.binary_root_entry = ttk.Entry(top, textvariable=self.binary_root_var, width=90)
        self.binary_root_entry.grid(row=7, column=1, sticky=tk.EW, pady=4)
        self.binary_root_browse_button = ttk.Button(top, text="Browse", command=self.choose_binary_root)
        self.binary_root_browse_button.grid(row=7, column=2, padx=6, pady=4)

        ttk.Label(top, text="Working dir").grid(row=8, column=0, sticky=tk.W, pady=4)
        ttk.Entry(top, textvariable=self.working_dir_var, width=90).grid(row=8, column=1, sticky=tk.EW, pady=4)
        ttk.Button(top, text="Browse", command=self.choose_working_dir).grid(row=8, column=2, padx=6, pady=4)
        top.columnconfigure(1, weight=1)

        form = ttk.LabelFrame(outer, text="Design Options", padding=10)
        form.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(form, text="Ploidy").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Combobox(form, textvariable=self.ploidy_var, values=["3", "2", "1"], width=12, state="readonly").grid(
            row=0, column=1, sticky=tk.W, pady=4
        )
        ttk.Label(form, text="Max enzyme price").grid(row=0, column=2, sticky=tk.W, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.max_price_var,
            values=["200", "400", "600", "800", "1000", "5000"],
            width=12,
            state="readonly",
        ).grid(row=0, column=3, sticky=tk.W, pady=4)
        ttk.Label(form, text="Max primer Tm").grid(row=0, column=4, sticky=tk.W, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.max_tm_var,
            values=["63", "65", "67", "69", "71"],
            width=12,
            state="readonly",
        ).grid(row=0, column=5, sticky=tk.W, pady=4)
        ttk.Label(form, text="Max primer size").grid(row=0, column=6, sticky=tk.W, pady=4)
        ttk.Entry(form, textvariable=self.max_size_var, width=8).grid(row=0, column=7, sticky=tk.W, pady=4)

        ttk.Checkbutton(form, text="Design CAPS/dCAPS", variable=self.design_caps_var).grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        ttk.Checkbutton(form, text="Design KASP", variable=self.design_kasp_var).grid(
            row=1, column=1, sticky=tk.W, pady=4
        )
        ttk.Checkbutton(form, text="Blast primers", variable=self.blast_primers_var).grid(
            row=1, column=2, sticky=tk.W, pady=4
        )
        ttk.Checkbutton(form, text="Pick primer anyway", variable=self.pick_anyway_var).grid(
            row=1, column=3, sticky=tk.W, pady=4
        )

        input_frame = ttk.LabelFrame(outer, text="SNP Input", padding=10)
        # SNP Input 是给用户贴 polymarker 行的，4–6 行就够；不再 expand=True，
        # 让出垂直空间给下面 Notebook 的结果展示。
        input_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        self.snp_text = tk.Text(input_frame, height=5, wrap=tk.WORD, font=self._mono_font)
        self.snp_text.pack(fill=tk.X, expand=False)
        self.snp_text.insert(
            "1.0",
            (
                "IWB50236,7A,cctcctcgtttcaaaagaagtaactcatcaaatgattcaaaaatatcgat[A/G]CTTGGCTGGTGTATCGTGCAGACGACAGTTCGTCCGGTATCAACAGCATT\n"
                "IWB58849,7A,ATGACAATCAGAGCATGGAAGAAGACTTCGAGAAAGGAACCGCGCCCAAG[T/C]GGTTTTGCTACAGCGACTTGGCCATGGCCACCGACAACTTTTCCGACGAT\n"
            ),
        )

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(actions, text="Export FASTA", command=self.export_fasta).pack(side=tk.LEFT)
        ttk.Button(actions, text="Show Run Plan", command=self.show_plan).pack(side=tk.LEFT, padx=8)
        ttk.Button(actions, text="Run Pipeline", command=self.run_pipeline).pack(side=tk.LEFT)
        ttk.Button(actions, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT)
        # 状态条用 tk.Label（ttk.Label 给 foreground 上色受 theme 干扰），加粗大字
        # + 颜色区分：Idle 灰、Running 橙、Completed 绿、Failed 红。
        self.status_label = tk.Label(
            actions, textvariable=self.status_var,
            font=("Segoe UI", 14, "bold"), fg="#666666",
        )
        self.status_label.pack(side=tk.RIGHT, padx=(0, 4))
        ttk.Label(actions, text="Status:").pack(side=tk.RIGHT, padx=(0, 6))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.plan_text = self._add_tab("Plan")
        self.log_text = self._add_tab("Log")
        self.fasta_text = self._add_tab("FASTA Preview")
        self.kasp_text = self._add_tab("KASP")
        self.caps_text = self._add_tab("CAPS")
        self.summary_text = self._add_tab("Summary")

    def _add_tab(self, title: str) -> tk.Text:
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        text = tk.Text(frame, wrap=tk.WORD, font=self._mono_font)
        text.pack(fill=tk.BOTH, expand=True)
        return text

    def choose_reference_fasta(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose reference FASTA",
            filetypes=[
                ("FASTA", "*.fa *.fasta *.fna *.fsa *.fas"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.reference_path_var.set(selected)

    def choose_local_blast_db(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose BLAST DB index file",
            filetypes=[
                ("BLAST DB", "*.nin *.nsq *.nhr *.ndb *.nos *.nog"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            path = Path(selected)
            if path.suffix.lower() in {".nin", ".nsq", ".nhr", ".ndb", ".nos", ".nog"}:
                self.local_blast_db_var.set(str(path.with_suffix("")))
            else:
                self.local_blast_db_var.set(str(path))

    def choose_binary_root(self) -> None:
        selected = filedialog.askdirectory(title="Choose binary root")
        if selected:
            self.binary_root_var.set(selected)

    def choose_working_dir(self) -> None:
        selected = filedialog.askdirectory(title="Choose working directory")
        if selected:
            self.working_dir_var.set(selected)

    def clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)

    def log(self, message: str) -> None:
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        if self._log_fp is not None:
            try:
                self._log_fp.write(f"{message}\n")
                self._log_fp.flush()
            except OSError:
                pass

    def _refresh_mode_fields(self) -> None:
        mode = self.mode_var.get()
        local_enabled = mode == LOCAL_MODE
        online_enabled = mode in {NCBI_MODE, OTHER_ONLINE_MODE}
        other_enabled = mode == OTHER_ONLINE_MODE

        if local_enabled:
            # 本地模式下两个字段的 enabled/disabled 由互斥联动逻辑统一管。
            self._update_blast_input_lockout()
        else:
            # 远端模式：两个 BLAST 输入字段一律禁用。
            for w in (self.reference_entry, self.reference_browse_button,
                      self.local_db_entry, self.local_db_browse_button):
                w.configure(state="disabled")
        self.remote_db_combo.configure(state="normal" if online_enabled else "disabled")
        self.remote_provider_combo.configure(state="readonly" if other_enabled else "disabled")
        self.remote_fetch_db_entry.configure(state="normal" if other_enabled else "disabled")
        self.remote_email_entry.configure(state="normal" if online_enabled else "disabled")
        self.binary_root_entry.configure(state="normal")
        self.binary_root_browse_button.configure(state="normal")

    _STATUS_COLORS = {
        "Idle": "#666666",       # 灰
        "Running": "#d97706",    # 橙
        "Completed": "#16a34a",  # 绿
        "Failed": "#dc2626",     # 红
    }

    def _set_status(self, state: str) -> None:
        """更新状态条文字 + 颜色，让 Running / Completed / Failed 一眼看出来。"""
        self.status_var.set(state)
        color = self._STATUS_COLORS.get(state, "#666666")
        try:
            self.status_label.configure(fg=color)
        except tk.TclError:
            pass

    def _update_blast_input_lockout(self, *_args) -> None:
        """互斥联动：Reference FASTA / Local BLAST DB 哪个有内容，就让另一个置灰。

        仅在 LOCAL 模式下执行（其他模式由 _refresh_mode_fields 统一禁用）。
        两个都空时两边都可用，用户选哪个都行；任一被填后另一个立刻 disabled，
        直到当前字段被清空才会重新可用。"""
        if self.mode_var.get() != LOCAL_MODE:
            return
        has_fasta = bool(self.reference_path_var.get().strip())
        has_db = bool(self.local_blast_db_var.get().strip())
        if has_fasta and not has_db:
            self.reference_entry.configure(state="normal")
            self.reference_browse_button.configure(state="normal")
            self.local_db_entry.configure(state="disabled")
            self.local_db_browse_button.configure(state="disabled")
        elif has_db and not has_fasta:
            self.local_db_entry.configure(state="normal")
            self.local_db_browse_button.configure(state="normal")
            self.reference_entry.configure(state="disabled")
            self.reference_browse_button.configure(state="disabled")
        else:
            for w in (self.reference_entry, self.reference_browse_button,
                      self.local_db_entry, self.local_db_browse_button):
                w.configure(state="normal")

    def _queue_log(self, message: str) -> None:
        self.ui_queue.put(("log", message))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                event_type, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if event_type == "log":
                self.log(str(payload))
            elif event_type == "complete":
                self._handle_run_complete(payload)
            elif event_type == "error":
                self._handle_run_error(str(payload))
        self.root.after(100, self._drain_ui_queue)

    def export_fasta(self) -> None:
        try:
            records = parse_polymarker_lines(self.snp_text.get("1.0", tk.END).splitlines())
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Input Error", str(exc))
            return
        fasta = render_blast_fasta(records)
        self.fasta_text.delete("1.0", tk.END)
        self.fasta_text.insert("1.0", fasta)
        output_path = Path(self.working_dir_var.get()) / "for_blast.fa"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(fasta, encoding="utf-8")
        self.log(f"Wrote FASTA preview to {output_path}")

    def _resolve_binary(self, binary_root: Path, name: str) -> Path:
        suffix = ".exe" if os.name == "nt" else ""
        candidate = binary_root / f"{name}{suffix}"
        if candidate.exists():
            return candidate
        located = shutil.which(name)
        if located:
            return Path(located)
        return candidate

    def _resolve_binary_bundle(self) -> BinaryBundle:
        binary_root = Path(self.binary_root_var.get())
        return BinaryBundle(
            blastn=self._resolve_binary(binary_root, "blastn"),
            blastdbcmd=self._resolve_binary(binary_root, "blastdbcmd"),
            makeblastdb=self._resolve_binary(binary_root, "makeblastdb"),
            primer3_core=self._resolve_binary(binary_root, "primer3_core"),
            muscle=self._resolve_binary(binary_root, "muscle"),
        )

    def _build_request(self) -> PipelineRequest:
        input_path = Path(self.working_dir_var.get()) / "input.csv"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(self.snp_text.get("1.0", tk.END).strip() + "\n", encoding="utf-8")

        mode = self.mode_var.get()
        reference_fasta = Path(self.reference_path_var.get()) if self.reference_path_var.get().strip() else None
        local_db = Path(self.local_blast_db_var.get()) if self.local_blast_db_var.get().strip() else None
        if reference_fasta and local_db:
            raise ValueError(
                "Reference FASTA 和 Local BLAST DB 不能同时填——\n"
                "二选一：要么给 raw FASTA 让程序自动 makeblastdb 建库，"
                "要么给已经建好的 BLAST DB prefix。\n"
                "如果只想用其中一个，把另一个字段清空。"
            )
        blast_mode = "local"
        remote_provider = None
        remote_fetch_database = None
        if mode == NCBI_MODE:
            blast_mode = "ncbi_online"
        elif mode == OTHER_ONLINE_MODE:
            blast_mode = "provider_online"
            remote_provider = self.remote_provider_var.get().strip() or "ebi"
            remote_fetch_database = self.remote_fetch_database_var.get().strip() or None

        return PipelineRequest(
            input_csv=input_path,
            reference_fasta=reference_fasta,
            ploidy=int(self.ploidy_var.get()),
            max_enzyme_price=int(self.max_price_var.get()),
            design_caps=self.design_caps_var.get(),
            design_kasp=self.design_kasp_var.get(),
            blast_primers=self.blast_primers_var.get(),
            max_tm=int(self.max_tm_var.get()),
            max_primer_size=int(self.max_size_var.get()),
            pick_anyway=self.pick_anyway_var.get(),
            blast_mode=blast_mode,
            local_blast_db=local_db,
            remote_provider=remote_provider,
            remote_database=self.remote_database_var.get().strip() or None,
            remote_fetch_database=remote_fetch_database,
            remote_email=self.remote_email_var.get().strip() or None,
        )

    def show_plan(self) -> None:
        try:
            request = self._build_request()
            plan = build_pipeline_plan(
                request=request,
                binaries=self._resolve_binary_bundle(),
                working_dir=self.working_dir_var.get(),
            )
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Plan Error", str(exc))
            return

        payload = {
            "blast_mode": request.blast_mode,
            "reference_fasta": str(request.reference_fasta) if request.reference_fasta else None,
            "local_blast_db": str(request.local_blast_db) if request.local_blast_db else None,
            "remote_provider": request.remote_provider,
            "remote_database": request.remote_database,
            "remote_fetch_database": request.remote_fetch_database,
            "steps": plan.steps,
        }
        self.plan_text.delete("1.0", tk.END)
        self.plan_text.insert("1.0", json.dumps(payload, indent=2, ensure_ascii=False))
        self.notebook.select(0)
        self.log("Generated pipeline plan")

    def run_pipeline(self) -> None:
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showinfo("Pipeline Running", "A pipeline run is already in progress.")
            return
        try:
            request = self._build_request()
            binaries = self._resolve_binary_bundle()
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Run Error", str(exc))
            return

        self._set_status("Running")
        self.summary_text.delete("1.0", tk.END)
        self.kasp_text.delete("1.0", tk.END)
        self.caps_text.delete("1.0", tk.END)
        self.log("Starting pipeline run")
        self.run_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(request, binaries, Path(self.working_dir_var.get())),
            daemon=True,
        )
        self.run_thread.start()

    def _run_pipeline_worker(
        self,
        request: PipelineRequest,
        binaries: BinaryBundle,
        working_dir: Path,
    ) -> None:
        try:
            result = PipelineRunner(
                request=request,
                binaries=binaries,
                working_dir=working_dir,
                logger=self._queue_log,
            ).run()
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))
            return
        self.ui_queue.put(("complete", result))

    def _handle_run_complete(self, result) -> None:
        self._set_status("Completed")
        summary = {
            "working_dir": str(result.working_dir),
            "blast_output": str(result.blast_output),
            "temp_range": str(result.temp_range),
            "potential_kasp": str(result.potential_kasp) if result.potential_kasp else None,
            "potential_caps": str(result.potential_caps) if result.potential_caps else None,
            "kasp_reports": [str(path) for path in result.kasp_reports],
            "caps_reports": [str(path) for path in result.caps_reports],
        }
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert("1.0", json.dumps(summary, indent=2, ensure_ascii=False))
        if result.potential_kasp and result.potential_kasp.exists():
            self.kasp_text.delete("1.0", tk.END)
            self.kasp_text.insert("1.0", result.potential_kasp.read_text(encoding="utf-8"))
        if result.potential_caps and result.potential_caps.exists():
            self.caps_text.delete("1.0", tk.END)
            self.caps_text.insert("1.0", result.potential_caps.read_text(encoding="utf-8"))
        self.notebook.select(self.summary_text.master)
        self.log("Pipeline completed")

    def _handle_run_error(self, message: str) -> None:
        self._set_status("Failed")
        self.log(message)
        full = f"{message}\n\n完整日志见: {self._log_path}"
        messagebox.showerror("Pipeline Failed", full)


def main() -> None:  # pragma: no cover - UI entry point
    try:
        root = tk.Tk()
        app = DesktopApp(root)
        root.mainloop()
    except Exception:  # pragma: no cover - UI entry point
        runtime_dirs = ensure_runtime_dirs()
        error_log = runtime_dirs["home"] / "desktop_startup_error.log"
        error_log.write_text(traceback.format_exc(), encoding="utf-8")
        try:
            messagebox.showerror(
                "SNP Primer Startup Failed",
                f"Desktop startup failed. See:\n{error_log}",
            )
        except Exception:
            pass
        raise
