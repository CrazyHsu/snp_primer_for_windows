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
from .primer_blast_view import collect_kasp_blast_groups, render_alignment
from .runtime_paths import default_reference_fasta, ensure_runtime_dirs
from .workflow import build_pipeline_plan


LOCAL_MODE = "Local BLAST DB or FASTA"
NCBI_MODE = "NCBI Online BLAST"
OTHER_ONLINE_MODE = "Other Online Provider"


class DesktopApp:
    # SNP Input 启动预填 + Example Input 按钮共用同一份示例字符串，避免两处漂移。
    _EXAMPLE_SNP_INPUT = (
        "IWB50236,7A,cctcctcgtttcaaaagaagtaactcatcaaatgattcaaaaatatcgat[A/G]"
        "CTTGGCTGGTGTATCGTGCAGACGACAGTTCGTCCGGTATCAACAGCATT\n"
        "IWB58849,7A,ATGACAATCAGAGCATGGAAGAAGACTTCGAGAAAGGAACCGCGCCCAAG[T/C]"
        "GGTTTTGCTACAGCGACTTGGCCATGGCCACCGACAACTTTTCCGACGAT\n"
    )

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
        # 给 KASP Primer BLAST 子 tab 用的左侧竖排样式
        _style.configure("VerticalKaspBlast.TNotebook", tabposition="wn")
        _style.configure("VerticalKaspBlast.TNotebook.Tab",
                         padding=[14, 8], font=("Segoe UI", 10))
        self._mono_font = ("Consolas", 12)
        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.run_thread: threading.Thread | None = None
        # 协作式取消：每次 Run Pipeline clear()，Stop 按钮 set()，worker 线程
        # 在 step 边界 / online polling 检查（详见 §6.18）。
        self.cancel_event: threading.Event = threading.Event()
        self.stop_button: ttk.Button | None = None  # 在 _build_layout 里赋值
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

        # 快照参数行的默认值，给 Reset Params 按钮用。SNP Input / Log /
        # status_var 不在里面（Clear SNP Input / Clear Log 各自负责）。
        self._param_defaults: dict[str, object] = {
            "mode_var": self.mode_var.get(),
            "reference_path_var": self.reference_path_var.get(),
            "local_blast_db_var": self.local_blast_db_var.get(),
            "remote_provider_var": self.remote_provider_var.get(),
            "remote_database_var": self.remote_database_var.get(),
            "remote_fetch_database_var": self.remote_fetch_database_var.get(),
            "remote_email_var": self.remote_email_var.get(),
            "ploidy_var": self.ploidy_var.get(),
            "max_price_var": self.max_price_var.get(),
            "design_caps_var": self.design_caps_var.get(),
            "design_kasp_var": self.design_kasp_var.get(),
            "blast_primers_var": self.blast_primers_var.get(),
            "max_tm_var": self.max_tm_var.get(),
            "max_size_var": self.max_size_var.get(),
            "pick_anyway_var": self.pick_anyway_var.get(),
            "working_dir_var": self.working_dir_var.get(),
            "binary_root_var": self.binary_root_var.get(),
        }

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

        # Reset Params 第六轮放过 outer 顶端 header（独占一行不好看），第七轮
        # 挪到 Design Options form 的右下空白区（见下面 form 段末）。
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
        # 顺序与 NCBI Web BLAST "Standard databases" 下拉完全一致（2026-05-21 抓
        # 的 HTML，21 个 value）。**不要再加旧 "nt"**——NCBI 当前下拉里没这个
        # value 了，传上去会被服务器静默 fallback 到 core_nt。
        # 详见 §6.20。Combobox normal-state 允许用户手输自定义 db 名（NCBI 偶尔
        # 上新库未收录时备用）。
        self.remote_db_combo = ttk.Combobox(
            top,
            textvariable=self.remote_database_var,
            values=[
                "nt_euk",
                "nt_prok",
                "nt_viruses",
                "nt_others",
                "core_nt",
                "refseq_select",
                "refseq_rna",
                "refseq_reference_genomes",
                "refseq_genomes",
                "nr/nt",
                "wgs",
                "est",
                "sra",
                "tsa",
                "tls",
                "htgs",
                "pat",
                "pdb",
                "refseq_gene",
                "gss",
                "dbsts",
            ],
        )
        self.remote_db_combo.grid(row=3, column=1, sticky=tk.EW, pady=4)
        # 默认 normal-state Combobox 只在点小箭头时弹下拉，留作手输自定义 DB
        # 名仍可。点击 entry 部分也想弹——但不能用 event_generate("<Down>")：
        # key 事件按当前键盘焦点 deliver，widget-level Button-1 binding 触发时
        # 焦点还没移过来，结果 <Down> 误送到上一个被聚焦的 Combobox（例如
        # mode_combo）→ mode 下拉被弹出。改用 Tcl-level ttk::combobox::Post
        # 直接对指定 widget 上 popdown，跟焦点无关。详见 §6.17。
        def _open_remote_db_dropdown(event):
            try:
                event.widget.tk.call("ttk::combobox::Post", event.widget)
            except tk.TclError:
                event.widget.focus_set()
                event.widget.after(
                    1, lambda w=event.widget: w.event_generate("<Down>")
                )
        self.remote_db_combo.bind("<Button-1>", _open_remote_db_dropdown)

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
        ttk.Label(
            top,
            text="(NCBI recommended, EBI required)",
            foreground="#666666",
        ).grid(row=6, column=2, sticky=tk.W, padx=6, pady=4)

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

        # 第七轮：Reset Params 挪到 Design Options form 右下空白处。col=8 设
        # weight=1 让列吃掉剩余水平 space，把按钮推到 form 最右边沿；rowspan=2
        # 让按钮纵跨两行，grid 默认 cell-内 anchor=CENTER 自动垂直居中。
        form.columnconfigure(8, weight=1)
        ttk.Button(form, text="Reset Params", command=self.reset_params).grid(
            row=0, column=8, rowspan=2, sticky=tk.E, padx=(20, 0)
        )

        input_frame = ttk.LabelFrame(outer, text="SNP Input", padding=10)
        # SNP Input 是给用户贴 polymarker 行的，4–6 行就够；不再 expand=True，
        # 让出垂直空间给下面 Notebook 的结果展示。
        input_frame.pack(fill=tk.X, expand=False, pady=(12, 0))
        # Clear SNP Input 按钮贴在文本框右侧。第七轮去掉 anchor=N（之前贴顶
        # 跟 Text 第一行齐，下面 4 行 Text 没视觉对齐）；pack 默认 anchor=CENTER
        # 让按钮在垂直方向居中到 Text 的中点。
        # 第八轮：右侧两按钮上下纵向堆叠（占用横向空间小），用 sub-Frame 容纳
        # 两个按钮各自 pack(side=tk.TOP)。Example Input 在上、Clear SNP Input 在
        # 下——加载在前、清空在后，匹配阅读顺序。布局：
        #   [ Text ............... | Example Input  ]
        #   [                      | Clear SNP Input]
        snp_button_col = ttk.Frame(input_frame)
        snp_button_col.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(
            snp_button_col, text="Example Input", command=self.load_example_snp_input
        ).pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        ttk.Button(
            snp_button_col, text="Clear SNP Input", command=self.clear_snp_input
        ).pack(side=tk.TOP, fill=tk.X)
        self.snp_text = tk.Text(input_frame, height=5, wrap=tk.WORD, font=self._mono_font)
        self.snp_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.snp_text.insert("1.0", self._EXAMPLE_SNP_INPUT)

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(actions, text="Export FASTA", command=self.export_fasta).pack(side=tk.LEFT)
        ttk.Button(actions, text="Show Run Plan", command=self.show_plan).pack(side=tk.LEFT, padx=8)
        ttk.Button(actions, text="Run Pipeline", command=self.run_pipeline).pack(side=tk.LEFT)
        # Stop Pipeline 按钮跑流程时才可点。__init__ 留了 self.stop_button
        # 占位，这里赋值。第七轮把标签从 "Stop" 改成 "Stop Pipeline"，跟
        # "Run Pipeline" 对称、含义更明确。
        self.stop_button = ttk.Button(
            actions, text="Stop Pipeline", command=self.cancel_pipeline, state="disabled"
        )
        self.stop_button.pack(side=tk.LEFT, padx=8)
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
        # 新 tab：每条 KASP primer 的 BLAST 比对视图（左侧竖排子 tab）。
        # 创建 outer Frame，run 之前 placeholder；_handle_run_complete 后用真实
        # 数据 _populate_kasp_primer_blast_tab() 重新填。
        self.kasp_blast_outer = ttk.Frame(self.notebook)
        self.notebook.add(self.kasp_blast_outer, text="KASP Primer BLAST")
        self._render_kasp_blast_placeholder()
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
                ("BLAST DB", "*.nal *.nin *.nsq *.nhr *.ndb *.nos *.nog"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            path = Path(selected)
            if path.suffix.lower() in {".nal", ".nin", ".nsq", ".nhr", ".ndb", ".nos", ".nog"}:
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

    def clear_snp_input(self) -> None:
        self.snp_text.delete("1.0", tk.END)

    def load_example_snp_input(self) -> None:
        # 「替换」语义：先清空再填，避免追加到用户半截编辑过的行后面破坏 polymarker
        # 格式。和启动预填用同一个 _EXAMPLE_SNP_INPUT 常量。
        self.snp_text.delete("1.0", tk.END)
        self.snp_text.insert("1.0", self._EXAMPLE_SNP_INPUT)

    def reset_params(self) -> None:
        for name, value in self._param_defaults.items():
            getattr(self, name).set(value)
        self._refresh_mode_fields()
        self.log("已重置所有参数为默认值")

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
        "Cancelled": "#dd8800",  # 橙黄（介于 Running 橙和 Failed 红之间）
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
            elif event_type == "cancelled":
                self._handle_run_cancelled(str(payload))
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
        blast_mode = "local"
        remote_provider = None
        remote_fetch_database = None
        if mode == NCBI_MODE:
            blast_mode = "ncbi_online"
        elif mode == OTHER_ONLINE_MODE:
            blast_mode = "provider_online"
            remote_provider = self.remote_provider_var.get().strip() or "ebi"
            remote_fetch_database = self.remote_fetch_database_var.get().strip() or None
        if blast_mode == "local":
            # local 模式互斥校验 + 必填 —— 任何一个都没填会让 core.pipeline 直接撞
            # "非 fixture 模式必须给 reference_db"，提前在这里给一个能动手的错误。
            if reference_fasta and local_db:
                raise ValueError(
                    "Reference FASTA 和 Local BLAST DB 不能同时填——\n"
                    "二选一：要么给 raw FASTA 让程序自动 makeblastdb 建库，"
                    "要么给已经建好的 BLAST DB prefix。\n"
                    "如果只想用其中一个，把另一个字段清空。"
                )
            if not reference_fasta and not local_db:
                raise ValueError(
                    "Local BLAST 模式必须填 Reference FASTA 或 Local BLAST DB 其中之一。"
                )
        else:
            # online 模式忽略两个本地字段（即便残留旧值）；核心 pipeline 会再校验
            # remote_database。
            reference_fasta = None
            local_db = None
            if not self.remote_database_var.get().strip():
                raise ValueError(
                    f"在线 BLAST 模式（{mode}）必须填 Online database。"
                )
            if blast_mode == "provider_online" and not self.remote_email_var.get().strip():
                raise ValueError(
                    "EBI BLAST 必须填 Contact email（EBI 服务条款要求）。"
                )

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
        # 每次 run 在用户选的 Working dir 下建一个 run_<ts> 子目录跑流程，跨 run
        # 不再互相覆盖中间产物 / 结果。working_dir_var 不动，下次 GUI 看到的
        # 还是用户原始填的根目录。
        base_workdir = Path(self.working_dir_var.get())
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_workdir = base_workdir / f"run_{timestamp}"
        try:
            run_workdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "Run Error",
                f"无法创建本次 run 的工作目录 {run_workdir}：{exc}",
            )
            self._set_status("Failed")
            return
        self.log(f"本次 run 输出目录：{run_workdir}")
        # 协作式取消：clear cancel_event；Stop 按钮启用。
        self.cancel_event.clear()
        if self.stop_button is not None:
            self.stop_button.configure(state="normal")
        self.run_thread = threading.Thread(
            target=self._run_pipeline_worker,
            args=(request, binaries, run_workdir),
            daemon=True,
        )
        self.run_thread.start()

    def cancel_pipeline(self) -> None:
        """Stop 按钮回调：set cancel_event。worker 线程会在下一个 step 边界 /
        在线 polling 周期检测到并 raise PipelineCancelled，回到 GUI 后状态切到
        Cancelled。Stop 按钮不立刻 disable 是因为想让用户看到 "你已经按过了"，
        实际 disable 由 _handle_run_cancelled / _handle_run_complete /
        _handle_run_error 做。"""
        if self.run_thread and self.run_thread.is_alive():
            self.cancel_event.set()
            self.log("已发送取消信号——pipeline 会在当前 step 边界 / 在线 polling 周期停下。")

    def _run_pipeline_worker(
        self,
        request: PipelineRequest,
        binaries: BinaryBundle,
        working_dir: Path,
    ) -> None:
        # 延迟 import：避免模块顶端 import core.pipeline 触发 Layer A 的 standalone
        # 测试期望。这里 worker 已经在 PipelineRunner.run() 上下文里，core 早已加载。
        from core.pipeline import PipelineCancelled
        try:
            result = PipelineRunner(
                request=request,
                binaries=binaries,
                working_dir=working_dir,
                logger=self._queue_log,
                cancel_event=self.cancel_event,
            ).run()
        except PipelineCancelled as exc:
            self.ui_queue.put(("cancelled", str(exc)))
            return
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))
            return
        self.ui_queue.put(("complete", result))

    def _handle_run_complete(self, result) -> None:
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
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
        self._populate_kasp_primer_blast_tab(result)
        self.notebook.select(self.summary_text.master)
        self.log("Pipeline completed")

    def _handle_run_error(self, message: str) -> None:
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        self._set_status("Failed")
        self.log(message)
        full = f"{message}\n\n完整日志见: {self._log_path}"
        messagebox.showerror("Pipeline Failed", full)

    def _handle_run_cancelled(self, message: str) -> None:
        if self.stop_button is not None:
            self.stop_button.configure(state="disabled")
        self._set_status("Cancelled")
        self.log(f"Pipeline cancelled: {message}")

    def _render_kasp_blast_placeholder(self) -> None:
        """KASP Primer BLAST tab 默认 placeholder（pipeline 还没跑 / 没勾 Blast primers
        / 没设计 KASP 时显示）。"""
        for child in self.kasp_blast_outer.winfo_children():
            child.destroy()
        msg = ("Run pipeline with both 'Design KASP' and 'Blast primers' checked\n"
               "to populate this view.\n\n"
               "Each KASP primer will get a sub-tab on the left showing its BLAST\n"
               "alignment against the reference (query / midline / subject).")
        lbl = tk.Label(self.kasp_blast_outer, text=msg, justify=tk.LEFT,
                       padx=20, pady=20, font=("Segoe UI", 11), fg="#555555")
        lbl.pack(fill=tk.BOTH, expand=True)

    def _populate_kasp_primer_blast_tab(self, result) -> None:
        """跑完 pipeline 后用真实数据填 KASP Primer BLAST tab。

        UI：PanedWindow 左右分隔。左侧 Listbox + 竖向 Scrollbar，列出
        ``<marker>_<primer_id>`` 条目；右侧 Text 显示选中条目的比对。
        ttk.Notebook 的 vertical tab 不支持滚动，primer 多了就被截断；
        这里换成 Listbox 是为了拿到天然的滚轮 + 滚动条。
        """
        for child in self.kasp_blast_outer.winfo_children():
            child.destroy()

        kasp_dir = getattr(result, "working_dir", None)
        kasp_dir = (kasp_dir / "KASP_output") if kasp_dir else None
        if not kasp_dir or not kasp_dir.is_dir():
            self._render_kasp_blast_placeholder()
            return

        groups = collect_kasp_blast_groups(kasp_dir)
        # 没生成 primer_blast_out_*.txt（没勾 Blast primers）→ placeholder
        if not groups:
            self._render_kasp_blast_placeholder()
            return

        # 渲染好每条 primer 的文本，按显示顺序存进 ordered list
        items: list[str] = []
        rendered_by_label: dict[str, str] = {}
        for marker, by_primer in groups.items():
            for primer_id, hits in by_primer.items():
                label = f"{marker}_{primer_id}"
                items.append(label)
                rendered_by_label[label] = render_alignment(label, None, hits)

        if not items:
            self._render_kasp_blast_placeholder()
            return

        paned = ttk.PanedWindow(self.kasp_blast_outer, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左侧：Listbox + 竖向 Scrollbar
        left = ttk.Frame(paned)
        list_yscroll = ttk.Scrollbar(left, orient=tk.VERTICAL)
        listbox = tk.Listbox(left, font=("Segoe UI", 11),
                             yscrollcommand=list_yscroll.set,
                             exportselection=False, activestyle="dotbox",
                             width=24)
        list_yscroll.configure(command=listbox.yview)
        list_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for label in items:
            listbox.insert(tk.END, label)
        paned.add(left, weight=1)

        # 右侧：Text + 双向 Scrollbar
        right = ttk.Frame(paned)
        txt_yscroll = ttk.Scrollbar(right, orient=tk.VERTICAL)
        txt_xscroll = ttk.Scrollbar(right, orient=tk.HORIZONTAL)
        txt = tk.Text(right, wrap=tk.NONE, font=self._mono_font,
                      yscrollcommand=txt_yscroll.set,
                      xscrollcommand=txt_xscroll.set)
        txt_yscroll.configure(command=txt.yview)
        txt_xscroll.configure(command=txt.xview)
        txt_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        paned.add(right, weight=4)

        def _on_select(_event=None):
            sel = listbox.curselection()
            if not sel:
                return
            label = listbox.get(sel[0])
            txt.configure(state="normal")
            txt.delete("1.0", tk.END)
            txt.insert("1.0", rendered_by_label.get(label, ""))
            txt.configure(state="disabled")

        listbox.bind("<<ListboxSelect>>", _on_select)
        # 默认选中第一条，让用户进 tab 立刻看到内容
        listbox.select_set(0)
        listbox.activate(0)
        _on_select()


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
