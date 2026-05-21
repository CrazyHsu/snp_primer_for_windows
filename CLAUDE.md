# CLAUDE.md — SNP Primer Windows App v11（ChatGPT 系列）

> 这份文件给未来的 Claude 会话用：你（Claude）会在 v11 目录里被启动协助迭代时，
> **先读这份文件**再动手。它只列那些**从代码里读不出来 / 容易踩坑 / 一旦忘记就出错**
> 的事。常规的目录布局、函数签名、依赖版本去 README.md 和代码里查。

> **v11 = v10 干净副本 + 多卷 BLAST 库自动 alias**（2026-05-20 当日补丁）：
> - 用户给一个多卷 makeblastdb 输出的 prefix（如 `cs_all`，旁边只有 `cs_all.00.nhr`
>   等 volume 文件，没有 `cs_all.nal`）时，v10 会撞 "No alias or index file found"
>   报错。v11 新增 `core/pipeline.py:_ensure_blastdb_alias_for_volumes`：检测到
>   prefix 没 .nhr/.nal 但 parent 下有 `<stem>.<NN>.nhr` volume 时，自动在
>   `<workdir>/blastdb_alias/<stem>.nal` 写一个 alias，DBLIST 用 volume 的绝对路径
>   列出所有 shard，然后把 `reference_db` 重指向这个 workdir alias。
> - 不影响在线 BLAST 模式 / fixture 模式 / 本地单卷库——检测到 `<prefix>.nhr` 或
>   `<prefix>.nal` 存在就原样返回，没有多卷模式也原样返回。
> - 不会修改用户数据目录；alias 完全 workdir-local，每次跑会被新建覆盖。
> - 详见 §6.13。
>
> **v11 第二轮补丁：多卷库 parse_seqids 检查盲点**（2026-05-20 同日）：
> - 当用户给的多卷库**自带 .nal**（v11 第一轮的 auto-alias 跳过、原样返回 prefix），
>   且每个 volume 都已经用 -parse_seqids 建过、accession 索引在
>   `<stem>.NN.nog/.nsd/.nsi` 上时，`_check_blastdb_has_parse_seqids` 仍然只看
>   prefix 后缀，误判没建 -parse_seqids，Step 5 之前直接抛错。
> - 修复：`_blastdb_has_parse_seqids` 改成先在 prefix 上 stat，再读 `.nal` 的
>   DBLIST（或 parent-scan `<stem>.NN.nhr`）拿到 volume 列表，每个 volume 各自
>   stat parse_seqids 后缀；要求所有 volume 都有（blastdbcmd 跨 volume OID 空间，
>   any-volume 缺索引就会漏 accession）。
> - 新增 helper `core/pipeline.py:_blastdb_volume_prefixes`。
> - 触发条件：多卷库 + 已有 .nal + parse_seqids 索引只在 volume 上（用户用例：
>   IWGSC v1.0 全基因组 cs_all，4 个 volume）。详见 §6.14。
>
> **v11 第三轮补丁：stale alignment_raw 导致 KASP KeyError**（2026-05-20 同日）：
> - 第二轮 patch 之后 blastdbcmd 不再被卡，但用户用 cs_all 跑出多 hit
>   flanking 时，getkasp3.kasp() 直接撞 `KeyError: 'chr7A:c40192941-40191941-1'`。
>   根因不是多卷库——是 `core/pipeline.run()` 没清 workdir 上一次留下的
>   `alignment_raw_*.fa`，getkasp3 / getCAPS 的 "alignment_raw 存在就跳 muscle"
>   优化拿到上一次 (chr7A 单库 1 hit) 的字典，跟这次 (cs_all 3 hits) 的 target
>   名字 (`-1` 后缀) 对不上。
> - 修复：`run()` 开头 chdir 后调新 helper
>   `core/pipeline.py:_cleanup_stale_run_artifacts(workdir)` 删
>   `alignment_raw_*.fa` 和 `All_alignment_raw.fa`；fixture 模式的
>   `alignment_files` 拷入紧跟在 sweep 之后，不会被破坏。
> - 详见 §6.15。
>
> **v11 第四轮补丁：4 项 GUI / online BLAST 健壮性**（2026-05-20 同日）：
> 1. Browse Local BLAST DB 加 `.nal` filter，多卷库用户直接选 alias prefix。
> 2. Online database `remote_db_combo` bind `<Button-1>` →
>    `event_generate("<Down>")`，点 entry 任何位置都弹下拉；仍 normal state，
>    可手输自定义 db 名。**注意：这版的 bind 有焦点 bug，第五轮已替换为
>    `ttk::combobox::Post` 路径，详见 §6.17。**
> 3. GUI 每次 Run Pipeline 在 working dir 下建 `run_<YYYYmmdd_HHMMSS>` 子目录
>    跑流程，跨 run 不再互相覆盖中间产物 / 结果。`working_dir_var` 不动。
> 4. `src/snp_primer_app/online_blast.py` 的 `_http_get` / `_http_post` 加 5
>    次指数退避 (3/6/12/24/48s, ≈93s) 重试，捕获 `URLError` /
>    `RemoteDisconnected` / `ConnectionResetError` / `IncompleteRead` /
>    `TimeoutError` / socket errors。所有 fetcher / blast helpers 都加了
>    `logger=` keyword-only 参数，retry 时往 GUI Log tab 打 "网络抖动 ... 重试"
>    可读行。详见 §6.16。
>
> **v11 第五轮补丁：Combobox 焦点 bug 修 + Reset/Clear 按钮 + 超时调大**
> （2026-05-20 同日）：
> 1. 第四轮的 `remote_db_combo` bind 用 `event_generate("<Down>")`，但 key
>    事件按当前键盘焦点 deliver，widget-level Button-1 binding 在
>    `ttk::combobox::Press` 转焦点之前就跑了，结果 `<Down>` 误送到上一个被
>    聚焦的 Combobox（mode_combo），mode 下拉错弹。替换成
>    `event.widget.tk.call("ttk::combobox::Post", event.widget)` 直接 post
>    指定 widget popdown，跟焦点无关；带 `tk.TclError` 兜底到 focus_set +
>    after(1) + Down。详见 §6.17。
> 2. Actions 行加 "Reset Params" 按钮：把所有参数行字段恢复到首次启动时的
>    默认值（__init__ 抓快照存 `self._param_defaults`）。不动 SNP Input /
>    Log / Status。**第六轮挪到右上角。**
> 3. Actions 行加 "Clear SNP Input" 按钮：清空 SNP Input 文本框。**第六轮挪到
>    SNP Input 文本框右侧。**
> 4. `run_ncbi_blast` / `run_ebi_blast` 默认 `timeout_seconds` 600 → 1800
>    （30 分钟）。refseq_genomes 类大库在 NCBI 队列里经常 10-20 分钟，原 600
>    秒不够。
>
> **v11 第六轮补丁：按钮重布局 + 在线 BLAST 状态 URL + Stop 按钮**
> （2026-05-20 同日）：
> 1. Reset Params 从 actions 行挪到 outer Frame 顶端 header 上 `pack(side=RIGHT)`，
>    GUI 右上角。**第七轮再挪到 Design Options form 右侧（独占 header 一行不
>    美观）。** Clear SNP Input 从 actions 行挪到 input_frame 内 Text 右侧
>    `pack(side=RIGHT, anchor=N)`。**第七轮去掉 anchor=N，改成垂直居中。**
>    actions 行只留 Export FASTA / Show Run Plan / Run Pipeline / Stop /
>    Clear Log。
> 2. `online_blast.run_ncbi_blast` / `run_ebi_blast` submit 后多 log 一行
>    `View status / results: <NCBI 或 EBI URL>`，方便用户开浏览器盯任务状态。
>    Text widget 不做超链接渲染，纯字符串展示，复制即可。
> 3. Stop 按钮（actions 行 Run Pipeline 旁边，默认 disabled，跑起来后 normal）
>    +  `core/pipeline.py` 新异常 `PipelineCancelled` + 协作式 cancel：
>    `cancel_event: threading.Event` 一路从 GUI → PipelineRunner →
>    `core.pipeline.run` → `online_blast.run_ncbi_blast / run_ebi_blast /
>    fetch_*` 串。pipeline 在每个 Step 入口 `_check_cancel()`；online polling
>    把 `time.sleep(5)` 换成可中断的 `_cancel_wait(5, cancel_event)` +
>    `_raise_if_cancelled` 双拍。GUI 新 status `Cancelled`（橙黄 `#dd8800`）。
>    **第七轮把按钮标签从 "Stop" 改成 "Stop Pipeline"，跟 "Run Pipeline" 对称
>    且意义明确。** 详见 §6.18。
>
> **v11 第七轮补丁：第六轮 UI 三处微调**（2026-05-20 同日）：纯视觉，无功能
> 变化。详见 §6.18 末尾"第七轮微调"段。
> 1. Reset Params 从顶端 header 挪到 Design Options form 右下空白处
>    （`grid(row=0, col=8, rowspan=2, sticky=E)` + `columnconfigure(8, weight=1)`），
>    顶端 header Frame 整个删掉、GUI 上半部分更紧凑。
> 2. Clear SNP Input 按钮 pack 去掉 `anchor=tk.N`，默认 anchor=CENTER 让它跟
>    SNP Input Text 视觉中线对齐。
> 3. actions 行的 "Stop" → "Stop Pipeline"。

> **v11 第九轮补丁：Online database 下拉与 NCBI Web BLAST 全量对齐**
> （2026-05-21 同日）：用户报告选 `nt` 实际跑出 `core_nt`，根因是 NCBI
> 2024 起改了 nucleotide BLAST 的 DB 列表——`nt` 不再是独立 value（被
> 服务器静默 fallback 到 core_nt），`refseq_representative_genomes` 被
> 重命名为 `refseq_reference_genomes`，新增 `nt_euk` / `nt_prok` /
> `nt_viruses` / `nt_others` / `refseq_select` / `refseq_gene` 等。
> 用 WebFetch 抓 NCBI BLAST 页 HTML 里 `<option value="...">` 全量同步成
> 21 项。`workflow.py` 的 fallback 字符串 `nt` → `core_nt`，`core/pipeline.py`
> 的 docstring example 同步。详见 §6.20。

> **v11 第八轮补丁：SNP Input 加 Example Input 按钮**（2026-05-21）：纯 GUI
> 便利按钮，无算法 / 子进程 / 编码改动。详见 §6.19。
> 1. `desktop.py` 顶部 `DesktopApp` 加类常量 `_EXAMPLE_SNP_INPUT`，把启动预填和
>    新按钮共用的两行示例字符串集中到一处，避免双份硬编码漂移。
> 2. SNP Input LabelFrame 右侧加 `Example Input` 按钮。两按钮**上下纵向堆叠**
>    （在 input_frame 右侧建 sub-Frame `snp_button_col`，两按钮 `pack(side=tk.TOP,
>    fill=tk.X)`），Example Input 在上、Clear SNP Input 在下。布局：
>    ```
>    [ Text ........... | Example Input   ]
>    [                  | Clear SNP Input ]
>    ```
>    选纵向堆叠是为了少占文本框横向宽度（横向并排时两个按钮一起吃 ~25% 行宽）。
> 3. 新方法 `load_example_snp_input`：直接 `delete + insert`，覆盖语义（用户
>    确认过），不弹确认对话框。

> **v10 = v9 干净副本 + NCBI / EBI online BLAST 模式真接入**（2026-05-20）：
> - `pipeline_runner.py` 不再静默把 `ncbi_online` / `provider_online` 降级为 local。
>   旧 v9 里"目前只接入了 local BLAST 模式…如需远端 BLAST 请用 v4 流程"的提示
>   已删除——v10 自己实接入了。
> - `core/pipeline.py` 接受 `blast_mode` / `remote_provider` / `remote_database`
>   / `remote_fetch_database` / `remote_email` 五个新关键字参数；Step 2 和 Step 5
>   按 `blast_mode` 分支。`local` 行为与 v9 字节等价。
> - `src/snp_primer_app/online_blast.py`（v4 时代已经在树里、v9 没用）被启用并扩展
>   了三个 helper：`render_alignment_table_with_chrom_prefix`、
>   `split_chrom_prefixed_subject`、`fetch_*_sequence_for_range`，让 v9 风格的
>   pipeline（getflanking → temp_marker_*.txt → fetch）能在线下运行。
> - GUI: 选 online 模式时 Reference FASTA / Local BLAST DB 自动忽略，不再硬要求；
>   email 行加了 "(NCBI recommended, EBI required)" 灰色提示。
> - 算法层（getflanking / getCAPS / getkasp3 / parse_polymarker_input）零改动。
> - bootstrap: 2026-05-20 新 Windows 机器上 v9 仍会卡在
>   `python-3.11.9-amd64.exe` installer exit code 5，所以 v10 改为下载官方
>   `python-3.11.9-amd64.zip`，校验 SHA256 后解压到 `python311`，完全绕开
>   Python `.exe` 安装器；详见 §6.10。
> - **online 模式的 subject_id rewrite**：NCBI 返回的 accession（如 `NC_057814.1`）
>   不带染色体短码，getflanking 的 ABD 过滤会全部丢掉。所以 Step 2 online 分支
>   把 subject_id 改写为 `chr{XY}_{accession}`（XY 从 subject_title 推断）；
>   Step 5 反解前缀拿 accession 调 efetch / dbfetch；FASTA header 保留前缀让
>   下游 getCAPS / getkasp3 的 `target_chrom in sequence_name` 子串匹配成立。
>   `infer_chromosome` 用的是 wheat `[1-7][ABD]` 正则——切到其他物种需要重做。

> **v9 = v8 的干净副本 + bootstrap 下载加固**（2026-05-15）：
> - 加固 `windows/bootstrap_and_launch.ps1` 的 `Invoke-Download`：写入
>   `.partial` 临时文件、失败时清理、`-MinBytes` 大小校验；详见 §6.10。
> - `Ensure-LocalPython` installer 跑失败时主动删 installer，防止下次重试又拿到
>   坏文件死循环（1392 ERROR_FILE_CORRUPT）。
> - 其它逻辑/算法层与 v8 完全等同。

> **v8 vs v7 差异**（2026-05-13）：v8 新增 `windows/bin/` 预打包二进制目录，bootstrap
> 跑 `Copy-BundledBinaries` 时优先从这里 copy，避免每次 bootstrap 都重新下载 BLAST+
> tar 等大文件。v8 也加入了 `build_windows.bat` / `build_windows_onefile.bat` 两套
> PyInstaller 打包入口（v7 引入，v8 调整）。

> **v7 = v6 的干净副本**（2026-05-08）：代码与 v6 等价，但已剔除运行时与 WSL 残留：
> - 删 `snp_primer_runtime/{venv,workspace*,logs,tmp,downloads,bootstrap.log}`
> - 删 `tests/.linux_bin/`（Linux ELF 二进制，Windows 跑不了）
> - 删 `tests/fixtures/_tmp/`（旧测试 BLAST 缓存，几个 GB）
> - 删 `snp_primer_runtime/bin/{blastn,blastdbcmd,makeblastdb,muscle,muscle5}` 这些
>   无后缀的 Linux 二进制；`bin/` 现仅保留 `.exe + .dll`
> - 删 `**/__pycache__/`、`*.pyc`、`.pytest_cache/`
> - **保留** `snp_primer_runtime/bin/` 里的 Windows .exe / .dll，避免重新 bootstrap
>
> 在 WSL 端做 Layer A 算法回归之前，记得先重建 `tests/.linux_bin/`（参考 v6 的
> 那份或者从系统装的 BLAST+ / muscle / primer3 link 过去）。

> **v6 vs v5 差异**（2026-05-08 起）：
> - 用户在 GUI 里给 raw FASTA（`.fa/.fasta/.fna/.fsa/.fas`）会**自动调
>   makeblastdb -parse_seqids 建库**到 `<workdir>/auto_blastdb/<stem>`，缓存
>   按 mtime 比对，不重复建。详见 `core/pipeline.py:_ensure_blastdb_from_fasta`。
> - GUI 强制 `Reference FASTA` 与 `Local BLAST DB` **互斥**（`_build_request`
>   抛 ValueError → "Run Error" messagebox）。
> - `Reference FASTA` 的 Browse 默认能看到 `.fsa/.fas` 后缀；`Local BLAST DB`
>   的 Browse filter 收紧为 BLAST 索引文件（不再混入 raw FASTA）。
> - v5 完整保留作对照，不要往 v5 上面回写改动。

---

## 1. 这是什么

**双击就能跑的 Windows 桌面 SNP 引物设计工具**（Tkinter GUI），目标是产出与
[wheatomics.sdau.edu.cn/snprimer](https://wheatomics.sdau.edu.cn/snprimer/) **逐字节对齐**
的 KASP / CAPS / dCAPS 引物报告。底层算法是
[pinbo/SNP_Primer_Pipeline](https://github.com/pinbo/SNP_Primer_Pipeline) 的 Py3 忠实移植。

输入 `polymarker` 格式（每行 `name,chr,seq[A/G]seq`），输出 4 份
`selected_*_primers_<MARKER>.txt` + `Potential_*.tsv` + `alignment_raw_*.fa`。

---

## 2. 架构与"不要碰"清单

```
core/                          ← 上游算法 Py3 移植，逐字逼近上游
├── parse_polymarker_input.py     ← 上游同名脚本
├── getflanking.py                ← 上游同名脚本
├── getCAPS.py                    ← 上游 commit 6f95356（最新）
├── getkasp3.py                   ← 上游 commit ba73bb3（pre-2022-09-15，故意旧版）
├── pipeline.py                   ← 我们写的总调度，替代上游 run_getkasp.py
└── assets/                       ← 上游 NEB_parsed_REs.txt / global_settings.txt / primer3_config/
src/snp_primer_app/            ← Tkinter GUI shell
├── desktop.py                    ← GUI；Run Pipeline 按钮 → PipelineRunner.run()
├── pipeline_runner.py            ← 薄壳：把 PipelineRequest+BinaryBundle 翻译成 core.pipeline.run 参数
└── models.py                     ← PipelineRequest / BinaryBundle 数据类
snp_primer_runtime/bin/        ← Windows 用户分发：5 个 .exe（首次 bootstrap 下载）
tests/
├── fixtures/                     ← 从标准结果反推的测试 fixture
├── .linux_bin/                   ← WSL 端测试用的 Linux 二进制（不分发给 Windows 用户）
├── build_fixtures.py / build_mini_abd_db.py
├── simulate_desktop.py / simulate_desktop_chr7a.py / simulate_browser.py（v4 那边）
├── check_windows_binaries.py     ← Windows 端 5 秒自检
└── compare_outputs.py            ← 与标准 fixture 对比的判定脚本
windows/Launch SNP Primer Desktop.cmd → bootstrap_and_launch.ps1
```

### 不要随便碰
- **`core/getCAPS.py` / `getkasp3.py` / `getflanking.py` / `parse_polymarker_input.py`**：
  上游 commit 的逐字 Py3 移植。要改请去找上游对应的修订版重新做最小化端口，
  不要在这边做"小改进"。`getkasp3.py` 故意用 `ba73bb3` 那个旧版（无 score 列、
  使用 variation2 而不是 variation），因为 wheatomics 用的就是它，改新版就对不上字节。
- **`core/assets/`**：上游原样拷贝。`global_settings.txt` 改了就跟标准 primer3 输出对不上。
- **`src/snp_primer_app/desktop.py` 的 `_build_request`**：GUI → PipelineRequest 的字段映射
  是 GUI 唯一的契约面，改一个字段名要同步 `pipeline_runner.py` + `models.py`。

### 可以放心改
- `core/pipeline.py`：是我们自己写的总调度，逻辑清晰，改它的参数和加新模式（fixture 旁路、
  `flanking_files=` / `alignment_files=` / `blast_fixture=`）是预期的扩展点。
- `tests/`：随便加。
- `windows/bootstrap_and_launch.ps1`：bootstrap 流程，加新二进制下载、改顺序都行——
  **但见下文「PowerShell 编码坑」**。

---

## 3. 关键约束 / 接口契约

1. **必须用 primer3_core 二进制**（不是 primer3-py）+ 上游 `global_settings.txt`。
   `core/getCAPS.py:get_software_path()` 已按平台拼 `primer3_core` / `.exe` /
   `_darwin64`。bootstrap 必须把 `primer3_core.exe` 下到 `snp_primer_runtime/bin/`
   （来源 [pinbo/SNP_Primer_Pipeline raw bin](https://github.com/pinbo/SNP_Primer_Pipeline/tree/master/bin)）。
2. **必须用上游 NEB_parsed_REs.txt**（209 条，名字编码价格）。不要自己写 dict。
3. **酶迭代顺序按酶名排序**，不要靠 Python dict 插入序——上游 Py2 默认有序，Py3 没
   保证（理论上 3.7+ 有，但显式 sort 才稳妥）。
4. **Windows 桌面入口的真实路径**：双击 `.cmd` → `bootstrap_and_launch.ps1` →
   `python -m snp_primer_app.launch_gui` → `desktop.py:run_pipeline()` →
   `PipelineRunner(request, binaries, working_dir).run()` → `core.pipeline.run()`。
   **没有任何 fixture 旁路**——Windows 用户每次都走真实 BLAST。
5. **二进制查找的`_which()`** 在 `core/pipeline.py`：Windows 优先 `.exe` + 跳过 0 字节
   文件。这是阻挡 WSL 残留 Linux symlink 把 GUI 搞崩成 `[WinError 1920]` 的关键防线，
   不能弱化。

---

## 4. 验证的局限（重要！别误把 WSL pass 当 Windows pass）

**WSL 端三层 4/4 PASS 只能证明算法没退化，不能证明 Windows GUI 能跑通**。差距：

| WSL 端 | Windows 端 |
|---|---|
| Linux ELF（`tests/.linux_bin/blastn` 等） | Windows .exe（依赖 vcruntime140.dll / vcomp140.dll 等 VC++ Redist） |
| `core.pipeline.run()` 直接调用 | `desktop.py` → 多线程 → `ui_queue` → Tk widget |
| `/mnt/e/...` Linux 路径，无中文 | `E:\...` + 用户参考库路径常含中文/空格/`+` |
| WSL 默认 UTF-8 stdio | Windows cmd / Tk 子进程默认 GBK |

**已踩过的因这道鸿沟没发现的坑**：
- `[WinError 1920]`：WSL 的 0 字节 symlink 在 Linux 路径解析里 `Path.exists()` 一致，
  Windows 上变成 PE 加载失败
- `bootstrap.ps1` 编码：UTF-8 中文注释 → Windows PS 5.1 按 GBK 解析 → 函数变量为 null
- `0xC0000135 DLL_NOT_FOUND`：blastn.exe 启动失败。**真因有两层**——
  (a) VC++ Redist 缺 → bootstrap 已加 `Ensure-VCRedist`（注册表查 → 缺则 UAC 自动装）
  (b) 更阴险：NCBI BLAST+ tar 里 bin/ 还有 `nghttp2.dll` / `ncbi-vdb-md.dll`，必须跟
      .exe 同目录。早期 bootstrap 只 copy 了三个 .exe 漏了 .dll → blastn 启动直接 0xC0000135 +
      空 stderr。已修：`Ensure-BlastTools` 改成 `Copy bin/*.exe + bin/*.dll` 全量拷贝
- **诊断 .exe DLL 依赖的正确姿势**：用 Python 在 WSL 端解析 PE Import Table，
  列出实际 IMPORT_DESCRIPTOR 里的 DLL 名字。**不要靠猜**——我之前直接断言
  "VC++ Redist 缺"就让用户白装一次，浪费时间。涉及 .exe 启动失败的，第一步永远是
  PE imports 分析（脚本见对话历史），不是给用户糊弄一个最常见原因

**给迭代用 Claude 的指南**（写给未来的我）：
- 任何涉及子进程、`.exe` 路径、Windows 路径分隔符、Windows 编码、PS/cmd 脚本的改动，
  **WSL pass ≠ 任务完成**。要明确告诉用户："这一改我只验证了算法层面没退化；Windows
  端到端是否跑通需要您实跑 GUI 才算"。不要再给"全部完成"的假阳性结论
- `desktop_<时间戳>.log` 文件是 Windows 端唯一可靠的反馈通道（就是这次找出
  `0xC0000135` 的方式）。每个新改动后让用户跑一次 GUI，把 log 文件贴出来
- WSL 能查的：纯算法逻辑、Python 单元测试、`grep '[^\x00-\x7F]'` 检查 ASCII 完整、
  `core/` 与 v5 / v4 一致性 diff
- WSL 查不了的：`.exe` 是否能加载（DLL 依赖）、Tk GUI 行为、Windows 路径解析、
  cmd / PowerShell 脚本的实际执行

## 5. 三层验证（迭代前后必跑，确保没退化）

| 层 | 入口 | 验证点 | 期望 |
|---|---|---|---|
| **A** | `core.pipeline.run(flanking_files=…, alignment_files=…)` | 算法本身没退化 | `compare_outputs.py` 4/4 PASS |
| **B** | `PipelineRunner(request, binaries, workdir).run()`（GUI 真实路径）+ 迷你 ABD 库 | GUI 入口、真实 BLAST、整链路 | `compare_outputs.py` 4/4 PASS |
| **C** | 同 B，但库换成 `iwgsc_refseqv1.0_chr7A` 或用户全基因组 | 流程在大库下不崩 | 出 4 份 selected + 7A 行对齐 |

WSL 端一次性回归命令：
```bash
# Layer A
PYTHONPATH=. python3 -c "
from pathlib import Path; from core import pipeline
fixt = Path('tests/fixtures').resolve()
pipeline.run(workdir='/tmp/v5_fixture_run',
    flanking_files=[str(p) for p in sorted((fixt/'flanking').glob('flanking_temp_marker_*.txt.fa'))],
    alignment_files=[str(p) for p in sorted((fixt/'expected').glob('alignment_raw_*.fa'))],
    bin_dir='tests/.linux_bin', do_primer_blast=False,
    design_caps=True, design_kasp=True, max_tm=63, max_size=25, max_price=200, pick_anyway=0, ploidy=3)
"
python3 tests/compare_outputs.py --workdir /tmp/v5_fixture_run

# Layer B（先 build_mini_abd_db.py 一次性建库）
python3 tests/build_mini_abd_db.py
PYTHONPATH=src python3 tests/simulate_desktop.py
python3 tests/compare_outputs.py --workdir /tmp/v5_sim_desktop

# Layer C
PYTHONPATH=src python3 tests/simulate_desktop_chr7a.py
```

`compare_outputs.py` 的判定口径（重要——理解这个才不会误判 FAIL）：
- **CAPS 严格匹配**：前 16 列逐字节对齐（604 行 / 76 行 100% 命中）。后续 `PrimerID`
  / `penalty` 列受 primer3 二进制版本影响，已忽略。
- **KASP 位点匹配**：设计位点（snp × varsite × LEFT/RIGHT）100% 命中即通过。
  primer3 偶尔挑 23bp vs 25bp 不同长度引物（同 varsite 上两端都满足 Tm 约束），
  属于 primer3 版本间合理浮动，不算 FAIL。

---

## 6. 反复踩到的坑（写在这里别再踩）

### 6.1 PowerShell 编码
**Windows PowerShell 5.1 默认按系统 ANSI 读 .ps1**（中文系统 = GBK）。文件无 BOM
+ UTF-8 编码 + 含中文 → PS 词法分析直接乱套，函数体里某些变量赋值会变成 null，
然后报莫名的 "Test-Path 参数为空" / "无法绑定 LiteralPath" 之类。

**规则**：`windows/bootstrap_and_launch.ps1` **保持纯 ASCII**。要写中文注释请改成英文。
验证：`grep -P '[^\x00-\x7F]' windows/bootstrap_and_launch.ps1` 必须无输出。

### 6.2 muscle v3 在 Ubuntu 22.04 segfault
旧静态二进制在新 glibc 下崩。`core/pipeline.py:_which()` 已经按 muscle5 → muscle →
muscle3.8.31 优先级查找。WSL 测试环境必须有 `muscle5`（v5.1.linux64，
`tests/.linux_bin/muscle5`）。

### 6.3 alignment_raw header 必须是 `chrXY_Chinese_Spring1.0-N` 格式
当 fixture 模式预放 `alignment_raw_*.fa` 进 workdir 想跳过 muscle 时，header 必须改成
`chrXY_Chinese_Spring1.0-N`（N 是 BLAST hit rank，从 0 起）。否则
`getCAPS.py:get_fasta2()` 不识别，会强制重跑 muscle，产出与 muscle v3 不一致的 MSA → 位点偏移。

`tests/simulate_desktop.py` 的 header 重写循环就是干这事的。

### 6.4 v4（claude_primer_windows_app/snp_primer_app_v4）的 `polymarker_input.csv` 自截 bug
v4 `pipeline.py` 一度把 polymarker 输入写到 `polymarker_input.csv`，跟
`core/pipeline.py:_normalize_polymarker_input` 写出的同名文件冲突，会被截 0。
v4 那边已改成写 `input.csv`。如果 v5 / v4 共享 core 后再发现类似冲突，按相同思路改名。

### 6.5 WSL Linux symlink 污染 Windows 分发目录
在 WSL 里 `ln -s` 进 NTFS 路径，从 Windows 看就是 0 字节坏链接，但
`Path.exists()` 仍返回 True。这就是 `[WinError 1920]` 的根因。

**已经做的防御**：
- `core/pipeline.py:_which()` Windows 优先 `.exe` + 拒绝 0 字节
- `bootstrap_and_launch.ps1:Remove-LinuxJunkBinaries()` 启动时自动清
- WSL 端测试统一用 `tests/.linux_bin/`，**不要再在 `snp_primer_runtime/bin/` 里建 symlink**

### 6.6 GUI 报错怎么排查（错误三处看）

GUI 跑流程失败时，**真错误在这三个地方**——别只看 messagebox：

1. **messagebox 标题"Pipeline Failed"**：现在会带 `returncode=` 和 stderr 最后 10 行
   （`core/pipeline.py:235-241` 的改动）。如果还嫌信息不够看下面两条。
2. **GUI Log Tab**：每条 log 都在这里实时滚出，包括 `_run` 跑的每条 subprocess
   命令以及它的 stdout+stderr。但只在内存里，关 GUI 就丢。
3. **持久化日志文件**：`<SNP_PRIMER_HOME>/logs/desktop_<YYYYmmdd_HHMMSS>.log`，
   GUI 启动时 open，运行期 append + flush，关 GUI 也保留。messagebox 末尾会附路径。

如果用户贴 "blastn 失败" 但没具体 BLAST stderr：
- 让他看 messagebox 的多行内容（v5 改完后默认带 stderr 尾部）
- 或者打开 `snp_primer_runtime\logs\desktop_*.log`，把最近一份贴出来
- 90% 是 DB prefix 写错（如 `Chr7A` 实际文件是 `Chr7A.fasta.nhr`，应填 `Chr7A.fasta`）
  或 DB 没用 `-parse_seqids` 建过

**online 模式排错**：v10 起 GUI 的 NCBI Online BLAST / Other Online Provider
真的会去 HTTP 跑（不再降级为 local）。常见症状：
- log 里只有 "Submitted NCBI BLAST RID=..." 然后超时（默认 600s）→ NCBI 端排队中或
  database 选错（如 `wgs` 对小 query 不返回）。换 `refseq_genomes` / `core_nt` 重试。
- log 里有 "Dropped N hit(s) with no inferrable wheat chromosome" → 命中里 subject
  title 不含 `chromosome [1-7][ABD]` 的字样（如命中了 scaffold / 转录本）。检查
  `blast_out.txt` 看实际返回内容；可能需要换 database 或调整 `online_blast.infer_chromosome`。
- "在线取 flanking 失败" + accession 看上去合法 → efetch 限流。带上 `Contact email`
  让 NCBI 提配额。
- EBI 任务卡 `FAILURE`：邮箱不合法或库名错（EBI 的库名跟 NCBI 不一样，如 `em_rel`
  而非 `nt`）。

### 6.7 BLAST 全家对 path 参数按空格 split

**关键事实**：BLAST 的 `-db` / `-out` / `blastdb_aliastool -dblist` 都是这个套路——
设计上支持多个用空格分隔的值，所以 blastn 拿到 path 参数后**主动按空格 split**。
即便 Python subprocess 用 list args 把含空格路径 quote 成单个 cmdline 参数，BLAST
内部仍 split。中文 Windows 用户的 path 经常含空格（如
`F:\项目\2024.11.27 实验数据\db`），就会报"No alias or index file found for
[F:\项目\2024.11.27]"——截到第一个空格。**`.nal` alias 文件里的 DBLIST 也按空格
split**，所以 alias 路径方案也走不通——必须让 DB 物理出现在无空格路径下。

**`core/pipeline.py:_blast_safe_db_path(p, fallback_dir)` 三级 fallback**：

1. p 无空格 → 直接透传
2. Windows + 8.3 短名可用（系统启用了 NTFS 8.3 命名）→ 返回短名
3. Windows + `fallback_dir` 提供（必须无空格）→ 调 `mklink /J` 把 DB 所在目录
   junction 到 fallback_dir 下的无空格名，返回 junction 内的 DB prefix。Junction
   不需要管理员权限，且跨本地卷有效（不像 hardlink）
4. 全部失败 → RuntimeError 提示用户手动挪 DB

实测 F: 盘禁了 8.3 命名（很多 NTFS 卷默认/被组策略禁），所以第 2 级失败、走到
第 3 级 Junction。

未来再加 BLAST 路径处理逻辑时记得：path 参数永远过 `_blast_safe_db_path`，
不要直接传给 subprocess。

### 6.8 NCBI BLAST tar 里 bin/ 还有 helper DLL（不是只有 .exe）

`bin/blastn.exe` 依赖同目录的 `nghttp2.dll`（HTTP/2）；`blastdbcmd.exe` /
`makeblastdb.exe` 用到 `ncbi-vdb-md.dll`。这俩 .dll 必须跟 .exe 同目录，**不在
VC++ Redist 里**。早期 `Ensure-BlastTools` 只 copy 三个 .exe 漏了 .dll → blastn 启动
时找不到 nghttp2.dll → 0xC0000135（DLL_NOT_FOUND）+ 空 stderr。已修：
copy `bin/*.exe + bin/*.dll` 全量。

### 6.9 全基因组太大（13 GB），本地只有 chr7A
所以才做"迷你 ABD BLAST 库"——从标准 `alignment_raw_*.fa` 提取 7A/7D/4A 同源段、
500N padding、100kb N spacer 拼一条染色体大小的合成 contig。详见
`tests/build_mini_abd_db.py`。**MSA 序列要剥掉 `-` 字符再入库**，否则 BLAST 命中坐标偏移。

### 6.10 Python runtime 下载 / installer 失败（v9 加固，v10 绕开）

**症状**（新电脑首次启动 v8 时观察到）：`bootstrap.log` 显示
```
[SNPPrimer] Installing local Python runtime
PS>TerminatingError():"Python installer failed with exit code 1392"
```
反复重试（双击 launch cmd 多次）都死在同一行。1392 = `ERROR_FILE_CORRUPT`。

**根因**：v8 及更早的 `Invoke-Download` 只检查文件存在与否：
```powershell
if (Test-Path -LiteralPath $OutFile) { return }   # 残破文件也不重下
Invoke-WebRequest -Uri $Url -OutFile $OutFile
```
`Invoke-WebRequest` 失败时**已经在目标路径写出了部分文件**（PowerShell 流式写入，
失败不自动清理）。第一次下载被掐（杀软 HTTPS MITM / 公司代理 reset）→ partial 文件
留在 `snp_primer_runtime\downloads\python-3.11.9-amd64.exe` → 后续每次重启都跳过下载、
把损坏的 installer 喂给 Start-Process → 1392 死循环。

**v9 修复**（`windows/bootstrap_and_launch.ps1`）：
1. `Invoke-Download` 下到 `$OutFile.partial`，全部下完才 `Move-Item` 到目标 → 任何
   中间失败都不会污染下次重试。
2. `try/catch` 包住 `Invoke-WebRequest`，catch 里删 `.partial`。
3. 新参数 `-MinBytes`：下完后检查文件大小，太小（HTTP 没报错但内容被截断）也直接
   清掉重抛。所有调用点都填了合理下限（python installer 20MB / BLAST tar 50MB /
   muscle 1MB / primer3_core 50KB / vc_redist 10MB）。
4. `Ensure-LocalPython` installer 跑失败时（任何 exit code 非 0）主动 `Remove-Item`
   installer 文件，强制下次重新下载。

**v10 修复**（2026-05-20 新机器 v9 installer exit code 5）：
- 不再下载 / 启动 `python-3.11.9-amd64.exe` 安装器。
- 改为下载官方 `python-3.11.9-amd64.zip`，`MinBytes=30000000`，并校验
  SHA256 `4ba90a4ab8990891033d37ff04d2047fdae8948d0d2729a68d3a6a17c585b681`。
- `Invoke-Download` 新增 `-Sha256`，缓存命中时也校验大小和 hash；坏缓存会删掉
  重下，不会复用。
- `Ensure-LocalPython` 解压到 `tmp\python311_extract`，探活
  `import sys, venv, ensurepip, tkinter` 成功后才移动到 `snp_primer_runtime\python311`。
  已存在但坏掉的 `python311` 会自动重建。

**用户线上排查（万一 v10 仍碰到）**：
- 删 `snp_primer_runtime\downloads\python-3.11.9-amd64.zip` 重试。
- 如果网络持续被中断：关本机杀软 HTTPS 拦截 / 换网络，或在系统上手动装
  Python 3.11+——bootstrap 的 `Get-ExistingPython` 会自动检测并跳过下载。
- 如果是 v9 日志里的 `Python installer failed with exit code 5/1392`，直接换 v10。

未来再加新二进制下载时，**必须**走 `Invoke-Download` 且加 `-MinBytes`；
能拿到官方 SHA256 的下载项也必须加 `-Sha256`。不要直接调 `Invoke-WebRequest`。

### 6.11 跨机器分发时 venv 残留 → "No Python at ..." (v9 第二轮修)

zip / 拷贝 bundle 给别的电脑时，如果不小心把 `snp_primer_runtime/venv/` 一起
带过去了，那个 venv 的 base interpreter 路径是构建机的绝对路径，目标机上几乎
肯定不可达。表现是 pip 这步报：

```
No Python at '<构建机的 Python 路径>'
PS>TerminatingError():"Upgrading pip failed with exit code 103"
```

**v9 修复**：`Ensure-Venv` 在 launcher 上跑一次 `python -c "import sys"` 探活；
失败就 `Remove-Item -Recurse` 整个 venv 目录然后用当前 `$PythonExe` 重建。
venv 里只有第三方包，重建后 `Ensure-ProjectInstalled` 重新装一遍，几秒钟的事。

**分发铁律**：往别处发布 bundle 之前必须 prune
`snp_primer_runtime/{venv,python311,workspace*,logs,tmp,downloads,bootstrap.log}`。
v9 顶部说明的"干净副本"已经按这套清单 prune 过；以后凡是要给别人的包都按
这套清单清一遍再 zip——**不要先在自己机器跑一次 bootstrap 再打包**，否则 venv
/ python311 / downloads 又会进包。

### 6.12 MUSCLE v5 / v3 命令行不兼容 → KASP 隐式 FileNotFoundError (v9 第三轮修)

`core/getkasp3.py` 和 `core/getCAPS.py` 里 fork-added 的 `_muscle_align_cmd`
按文件名挑命令行：含 "v5" / "muscle5" 用 v5 语法 `-align/-output`，否则用 v3
`-in/-out/-quiet`。下游 `call(cmd, shell=True)` 不查返回码——v5 muscle 喂 v3
语法会静默退出非 0、不写 output，下一步 `get_fasta("alignment_raw_<snp>.fa")`
就报 `[Errno 2]`。

bootstrap **必须**把下载的 muscle v5.x 二进制存成 `muscle5.exe`，**不能存成
`muscle.exe`**。v9 已修：

- `Ensure-Muscle` 一律存为 `muscle5.exe`；并在启动时探测旧 `muscle.exe`
  自动 rename 到 `muscle5.exe`（一次性、idempotent）。
- `Copy-BundledBinaries` 的 `$Names` 同时识别 `muscle5.exe`（首选）和
  `muscle.exe`（legacy）。
- `Test-BinaryRunnable` smoke-test 优先探 `muscle5.exe`，找不到再退回 `muscle.exe`。
- `windows/bin/` 里捆绑的也是 `muscle5.exe`。

新加二进制时记得：**文件名就是算法 wrapper 的关键信号**。不要随手命名。

排查这类问题的钩子：log 里若看到 KASP 跑到 `[Errno 2] No such file or
directory: 'alignment_raw_*.fa'`，第一反应去 `snp_primer_runtime\bin\` 检查
muscle 是叫 `muscle5.exe` 还是 `muscle.exe`。

### 6.13 多卷 BLAST 库 + 缺 .nal alias（v11 已修）

**症状**：`BLAST Database error: No alias or index file found for nucleotide
database [...\cs_all]`。Step 2 直接退出，returncode=2。

**触发条件**：用户的输入 FASTA 超过 `makeblastdb -max_file_sz`（新版默认 4GB），
makeblastdb 自动把库切成 volume：`cs_all.00.{nhr,nin,nsq,nog,nsd,nsi}` /
`cs_all.01.{...}` / … 正常情况下顺手生成 `cs_all.nal` alias 把所有 volume 串起来。
但库可能是手动建的 / 老版本 makeblastdb / NCBI 直接下载的预建包 / 用
`blastdb_aliastool` 拆 volume 漏建 alias —— 这时 parent 下有 N 个 `.NN.nhr` 但
没有 `<prefix>.nal`。

实测案例（IWGSC v1.0 全基因组，3.4 GB）：
`E:\…\cs_all.blast_db\cs_all.{00,01,02,03}.{nhr,nin,nsq,nog,nsd,nsi}`，4 个 shard，
没有 `cs_all.nal`。用户指 `cs_all` 报上述错，指 `cs_all.03` 倒是能跑但只匹配
volume .03 里的染色体——其他染色体（7A 在 .03 里，其他基本不在）的 marker 全
`temp_range.txt 是空的`。

**v11 修复**：`core/pipeline.py:_ensure_blastdb_alias_for_volumes(db_prefix, workdir, log)`

- 检测：`<prefix>.nhr` 与 `<prefix>.nal` 都不存在 → 扫 parent 找
  `<stem>.<NN>.nhr`（NN 是 ≥2 位数字，兼容 `.00`/`.001` 等命名）
- 校验：每个候选 volume 自己必须有完整 `.nhr/.nin/.nsq`；少一个就丢
- 写：`<workdir>/blastdb_alias/<stem>.nal`，文本格式
  ```
  TITLE <stem>
  DBLIST <abs_path_to_volume_0> <abs_path_to_volume_1> ...
  ```
- 返回新 prefix `<workdir>/blastdb_alias/<stem>`，下游 blastn / blastdbcmd / Step 5
  全用这个

**重要约束**：volume 绝对路径不能含空格（BLAST 内部按空格 split DBLIST，
见 §6.7）。含空格直接抛 RuntimeError 给用户清晰错误，不静默忽略。中文 / dot
没问题，BLAST 处理 OK——v11 实测案例的中文路径就 work。

**不会写用户 DB 目录**：alias 完全 workdir-local，对只读盘 / NAS / 共享目录都
安全。每次 GUI 跑会新建覆盖一次。

**手动 fallback**（万一 v11 扫描没找到）：

```cmd
cd <用户 DB 目录>
blastdb_aliastool -dblist "cs_all.00 cs_all.01 cs_all.02 cs_all.03" ^
                  -dbtype nucl -out cs_all -title cs_all
```

排查钩子：log 里看不到 `已为多卷 BLAST 库生成 alias：...` 这行，说明 v11 的
扫描跳过了——检查 volume 文件名是不是真按 `.00` / `.01` 命名（不是 `.0` / `.1`），
后缀是 `.nhr` 不是 `.phr`（蛋白质库会用 `.phr`，扫描不到很正常）。

### 6.14 多卷 BLAST 库 + parse_seqids 检查盲点（v11 第二轮补丁）

**症状**：Step 2 的 blastn 正常跑完，Step 4 拆完 temp_range，但日志里立刻冒出：

> BLAST 库 …\cs_all 看起来不是用 -parse_seqids 建的（没找到 .nos/.nog/.nsi/.nsd
> 任意一种 accession 索引文件）。

然后 RuntimeError 抛出，pipeline 失败。但实际上 DB 是用 `-parse_seqids` 建过的，
每个 volume（`cs_all.00`～`cs_all.03`）都有完整 `.nog/.nsd/.nsi`。

**触发条件**：多卷库 + **已经有 .nal alias**（所以 §6.13 的 auto-alias 不会触发，
`_ensure_blastdb_alias_for_volumes` 直接 return 原 prefix）+ parse_seqids 索引文件
只挂在每个 volume 上（`cs_all.NN.nog` 而非 `cs_all.nog`）。实测用户用例：
IWGSC v1.0 全基因组 `cs_all.blast_db\cs_all`，4 个 volume 都带索引，`cs_all.nal`
已经存在，但 prefix 自己没有任何 parse_seqids 后缀。

**根因**：`_check_blastdb_has_parse_seqids` 只 stat `<prefix>.<suffix>`，没下钻
到 volume。多卷模式 prefix 上只有 `.nal`，索引在 `<stem>.NN.<suffix>` 上。

**v11 修复**：

- 新增 `core/pipeline.py:_blastdb_volume_prefixes(db_prefix)`：读 `<prefix>.nal`
  的 `DBLIST` 行（相对路径相对 .nal 目录解析），拿不到再 parent-scan
  `<stem>.<NN>.nhr` 找 volume。
- `_blastdb_has_parse_seqids` 重写：先在 prefix 上 stat，没命中就拿 volume 列表，
  **要求所有 volume 都有 parse_seqids 索引**（blastdbcmd 跨 volume OID 空间，
  任意一个 volume 缺索引都会漏 accession；makeblastdb 实操要么全做要么不做，
  all 是正确口径）。
- `_check_blastdb_has_parse_seqids` 委托给新的 `_blastdb_has_parse_seqids`，
  错误信息里追加一段说 "多卷库的索引在 `<stem>.NN.nog/.nsd/.nsi` 上而不是 prefix
  上"，帮用户一眼判断是真没建索引还是配置看错。

**Pyright pre-existing diagnostics**：本次 patch 没引入新告警；`pipeline.py`
里现有的 "Import `snp_primer_app.online_blast` could not be resolved" 是因
为 `src/snp_primer_app/` 没在 Pyright 默认 search path 上，跟 6.14 这个修无关。

排查钩子：log 里 Step 4 之后直接抛此错且 `<prefix>.nal` 存在 / 各 volume 有
`.nog`，那就是这条路径没触发 `_blastdb_volume_prefixes`——检查 .nal 的 DBLIST
是不是被空行/注释隔开，或 volume 名拼写跟 .nhr 文件不一致。

### 6.15 stale alignment_raw 导致 KASP KeyError（v11 第三轮补丁）

**症状**：log 显示 Step 5 的 blastdbcmd 全部跑通，Step 6a 开头紧跟一条单引号
裸 key 报错，类似：

```
Step 6a: 跑 KASP 引物设计
'chr7A:c40192941-40191941-1'
```

pipeline 直接终止；没有 KASP 输出、Potential_KASP_primers.tsv 也不会写。

**根因**：`core/getkasp3.py:482-488` 和 `core/getCAPS.py:646-652` 有一段
skip-if-exists：

```python
RawAlignFile = "alignment_raw_" + snpname + ".fa"
if os.path.exists(RawAlignFile) and os.path.getsize(RawAlignFile) > 0:
    print(f"对齐文件 {RawAlignFile} 已存在，跳过 muscle。")
else:
    call(_muscle_align_cmd(muscle_path, seqfile2, RawAlignFile), shell=True)
```

这段是给 fixture 模式留的（§6.3 解释了为什么 alignment_raw header 要按
`chrXY_..._-N` 命名）。但在非 fixture 模式下，**上一次 run 留下的
alignment_raw_*.fa 也会触发它**——`get_fasta2` 按当前 flanking 文件的 hit 顺序
给 sequence_name 加 `-0/-1/-2` 后缀，所以两次跑 hit 数变了 (例如换 DB / 换
input)，target 名字跟 alignment 字典 keys 就对不上，`fasta[target]` 抛 KeyError。

实测：

```
flanking_temp_marker_IWB50236_*.fa  (cs_all 全基因组，3 hits)
  >chr7D:c40281192-40280192
  >chr7A:c40192941-40191941        ← target 拿到 -1 后缀
  >chr4A:c646785230-646784230

alignment_raw_IWB50236.fa  (mtime 比 flanking 早，上次 chr7A 单库剩的，1 hit)
  >chr7A:c40192941-40191941-0      ← 字典里只有 -0
```

`fasta["chr7A:c40192941-40191941-1"]` → KeyError，单引号裸 key 就是这么来的
（getkasp3 没 try/except，直接 raise 上去）。

**v11 修复**：`core/pipeline.py:_cleanup_stale_run_artifacts(workdir)`
在 `run()` 每次 chdir 之后、fixture 拷入之前调一次，删
`alignment_raw_*.fa` 和 `All_alignment_raw.fa`。

只动这两类文件：
- `alignment_raw_<snp>.fa`：触发 skip-if-exists 的元凶
- `All_alignment_raw.fa`：Step 7 会重写

不动 `flanking_*.fa` / `renamed_*` / `temp_marker_*.txt` / `temp_range.txt` /
`blast_out.txt` / `KASP_output/` / `CAPS_output/`——这些要么每次写覆盖，要么
没有 skip-if-exists 复用路径。

**fixture 模式不受影响**：`run()` 里 `if alignment_files is not None: copy(...)`
紧跟在 sweep 之后，sweep 删的是 stale 文件，fixture 接着拷入要求的真正
alignment 文件。两者不冲突。

**普适性**：这个 bug 跟多卷库无关——任何让 BLAST hit 数 / 顺序变化的操作
（换 DB、换 marker 输入、改 ploidy）都能踩到。补丁是一次性修死的。

排查钩子：log 出现"Step 6a 紧跟一个单引号裸 key 报错"+ workspace 里
`alignment_raw_*.fa` 的 mtime 早于 `flanking_*.fa`——就是这个 bug。看
`_cleanup_stale_run_artifacts` 这一行有没有被调到（grep log 里
"Step 1" 之前应该没有报 alignment_raw 还在的迹象——它是静默删，无 log 行）。

### 6.16 GUI / online BLAST 健壮性 4 项（v11 第四轮补丁）

合并写在一节，因为单条都很小。

**(1) Browse Local BLAST DB 看不见 .nal**：
`src/snp_primer_app/desktop.py:choose_local_blast_db` 的 filedialog filetypes
原来只列 `.nin/.nsq/.nhr/.ndb/.nos/.nog`，漏 `.nal`，多卷库用户没法在 file
dialog 里看到 alias 文件。已在 filetypes 和 suffix-strip 集合都加上 `.nal`，
选中 `<prefix>.nal` 后 `path.with_suffix("")` 自动剥成 prefix（跟其它后缀
一样的处理）。

**(2) Online database Combobox 点击不弹下拉**：
`remote_db_combo` 之前走默认 normal state，只有点击右侧小箭头才弹下拉。
其它几个 readonly Combobox（mode / provider / ploidy / max_*）本来点击就弹。
为了让 normal state 也点击即弹但**仍可手输**自定义 db 名（NCBI 偶尔上新库
还没收录到 values），给它 bind 一个：

```python
self.remote_db_combo.bind(
    "<Button-1>",
    lambda event: event.widget.event_generate("<Down>"),
)
```

`<Down>` 是 Tk Combobox 内部"弹下拉"的事件，幂等——点小箭头本身也会触发
`<Button-1>`，但再 `event_generate("<Down>")` 一次还是开着同一个 popdown，
不会双弹。

**(3) GUI 每次 run 写到 `run_<YYYYmmdd_HHMMSS>` 子目录**：
之前 `desktop.py:run_pipeline` 直接把 `working_dir_var.get()` 当 workdir 交给
PipelineRunner，跨 run 互相覆盖 / 互相留 stale 文件（§6.15 那个 bug 就是这
么来的）。改为：

```python
base_workdir = Path(self.working_dir_var.get())
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
run_workdir = base_workdir / f"run_{timestamp}"
run_workdir.mkdir(parents=True, exist_ok=True)
self.log(f"本次 run 输出目录：{run_workdir}")
# 把 run_workdir 喂给 thread，不动 working_dir_var
```

`working_dir_var` 不动 → 下次 GUI 看到的还是用户原始选的根目录。每次 run
独立子目录，所有相对路径（`temp_*` / `flanking_*` / `alignment_raw_*` /
`KASP_output/` / `CAPS_output/`）都落在里面。`_cleanup_stale_run_artifacts`
(§6.15) 现在每次都跑在新空目录上，no-op，零成本。1 秒内连点 Run 两次会撞
名（覆盖同一目录），但概率低 + 后果可控，本轮不加 PID 后缀。

**(4) NCBI / EBI online BLAST 网络抖动 retry**：
`src/snp_primer_app/online_blast.py` 的 `_http_get` / `_http_post` 之前是
单次调用，对端 reset / load balancer 切换 / 临时拥塞抛
`<urlopen error Remote end closed connection without response>` 直接挂掉
整个 pipeline。新增内部 helper `_http_request_with_retries`：

- 重试节奏：3 / 6 / 12 / 24 / 48 秒 5 次（累计 ≈93s），最后一次还失败抛
  `OnlineBlastError`
- 捕获：`URLError` / `RemoteDisconnected` / `IncompleteRead` /
  `ConnectionResetError` / `ConnectionAbortedError` / `TimeoutError` /
  `socket.timeout` / `socket.error`
- 每次重试调 `log_message(logger, ...)`，GUI Log tab 会出现 "网络抖动 ... 重试"
  可读行，用户能看到不是卡死
- `_http_get` / `_http_post` / `fetch_ncbi_sequence` / `run_ebi_blast` /
  `fetch_ebi_sequence` / `fetch_ncbi_sequence_for_range` /
  `fetch_ebi_sequence_for_range` 都加了 `logger=` keyword-only 参数；
  `core/pipeline.py` 调用 fetch 时传 `logger=log`
- 兼容性：`logger` / `description` 都 keyword-only 新参数，未提供也兼容；
  现有 4xx/5xx 业务错（status=FAILED / UNKNOWN / ERROR / FAILURE）依然原样
  抛 `OnlineBlastError`，不在 retry 之列

排查钩子：log 看到 "网络抖动 ... 重试" 几次然后正常继续——是 retry 在工作；
看到 "重试 N 次后仍失败"——真的网断了，让用户检查代理 / VPN / NCBI 状态页。

### 6.17 Combobox 焦点 bug + Reset/Clear 按钮 + 超时调大（v11 第五轮）

**(1) `remote_db_combo` 错弹了 `mode_combo` 的 popdown**：

第四轮加的 bind：
```python
self.remote_db_combo.bind(
    "<Button-1>",
    lambda event: event.widget.event_generate("<Down>"),
)
```

实测表现：第一次点 Online database → BLAST mode 下拉弹出；第二次点都关；
第三次才正常弹 Online database 自己的。

根因：`event_generate("<Down>")` 的 source widget 是 event.widget（remote_db_combo），
但 **key 事件的 delivery target 按当前键盘焦点走**（Tk 文档原话）。我的
widget-level Button-1 binding 在 class-level `ttk::combobox::Press` 之前触发；
那时焦点还没移到 remote_db_combo，仍停在上一个 Combobox（GUI 启动时通常是
mode_combo）→ `<Down>` 实际 deliver 给 mode_combo → mode 下拉错弹。

修复：用 ttk Combobox 的 Tcl-level 内部 proc `ttk::combobox::Post`：

```python
def _open_remote_db_dropdown(event):
    try:
        event.widget.tk.call("ttk::combobox::Post", event.widget)
    except tk.TclError:
        # 兜底（Tk 早期版本 / 自定义编译）：focus_set + after(1) + <Down>
        event.widget.focus_set()
        event.widget.after(
            1, lambda w=event.widget: w.event_generate("<Down>")
        )
self.remote_db_combo.bind("<Button-1>", _open_remote_db_dropdown)
```

`Post` 是 Tk 8.5+ 标配的公开 Tcl proc，直接 post 给指定 widget 的 popdown，
跟焦点无关；幂等（已 posted 时再 post 不重复弹）；跟 class-level Press
handler 协作良好（click on entry 不会 Unpost）。

**未来再给任何 Combobox 加 click-to-pop 时记得：不要用
`event_generate("<Down>")`，要么用 `ttk::combobox::Post`，要么用 readonly
state（readonly Combobox click on entry 默认就弹）。**

**(2) Reset Params 按钮**：

`actions` 行加按钮：

```python
ttk.Button(actions, text="Reset Params",
           command=self.reset_params).pack(side=tk.LEFT, padx=8)
```

`__init__` 在创建完所有 var 后立刻抓字典快照：

```python
self._param_defaults: dict[str, object] = {
    "mode_var": self.mode_var.get(),
    "reference_path_var": self.reference_path_var.get(),
    "local_blast_db_var": self.local_blast_db_var.get(),
    ...
    "binary_root_var": self.binary_root_var.get(),
}
```

```python
def reset_params(self) -> None:
    for name, value in self._param_defaults.items():
        getattr(self, name).set(value)
    self._refresh_mode_fields()
    self.log("已重置所有参数为默认值")
```

**不动**：snp_text（SNP Input）、log_text、status_var、notebook 选中 tab。
没确认对话框——只重置 GUI 状态、不删文件，误点没什么后果。

**(3) Clear SNP Input 按钮**：跟 Clear Log 平级，挨着摆。

```python
def clear_snp_input(self) -> None:
    self.snp_text.delete("1.0", tk.END)
```

**(4) NCBI / EBI BLAST 默认 timeout 600→1800s**：

`run_ncbi_blast` / `run_ebi_blast` 的默认 `timeout_seconds` 提到 1800（30
分钟）。refseq_genomes 之类大库在 NCBI 公共队列里 10-20 分钟出结果是常事；
第四轮日志（desktop_20260520_221540.log）就是 600s 不够直接抛
`NCBI BLAST timed out after 600 seconds`。

排查钩子：如果以后还撞到 1800 不够（比如 nt 这种更大的库 + 队列爆满），考虑
在 GUI 加一个 timeout 字段而不是再无脑加大默认。

### 6.18 按钮重布局 + Online BLAST 状态 URL + Stop 按钮（v11 第六轮）

**(1) 按钮挪位**：

- Reset Params 从 actions 行挪到 outer Frame 顶端 header 上 `pack(side=RIGHT)`，
  视觉上独占 GUI 右上角。
- Clear SNP Input 从 actions 行挪到 input_frame（SNP Input LabelFrame）内，
  Text widget 改成 `pack(side=LEFT, fill=X, expand=True)`，按钮
  `pack(side=RIGHT, padx=(8,0), anchor=N)`——anchor=N 让按钮贴顶部不被 Text
  拉伸。
- actions 行精简：Export FASTA / Show Run Plan / Run Pipeline / **Stop** /
  Clear Log。

**(2) Online BLAST log 加 status URL**：

`online_blast.run_ncbi_blast` submit 后追加：

```python
log_message(logger, f"  View status / results: {NCBI_BLAST_URL}?CMD=Get&RID={rid}")
```

NCBI 这个 URL 在浏览器里直接打开就是 BLAST 状态页（自动刷新），用户可以脱
GUI 自己盯。`run_ebi_blast` 同样追加 `/status/{job_id}` 和 `/result/{job_id}/xml`。
**Log Tab 是普通 tk.Text，不做超链接 tag bind / cursor 切换 / system open**——
用户复制粘贴到浏览器即可。

**(3) Stop 按钮 + 协作式 cancel**：

worker thread 不能强杀，所以走 cooperative cancel。设计：

- 新异常 `core/pipeline.py:PipelineCancelled(RuntimeError)`。
- `core/pipeline.py:run(...)` 加 keyword-only `cancel_event: threading.Event |
  None = None`，闭包式 `_check_cancel(label)` 在每个 Step 入口（Step
  1/2/3/4/5/Step 5 fetch/6a/6b/7）调一次，set 就 raise PipelineCancelled。
- `online_blast.run_ncbi_blast` / `run_ebi_blast` 同样接 `cancel_event` kw。
  原本 `time.sleep(5)` 换成 `_cancel_wait(5, cancel_event)`（拿到就走
  `Event.wait(5)`）；循环顶部加 `_raise_if_cancelled(cancel_event, label)`。
  这样 GUI 点 Stop 后**≤5 秒**就能把 polling 中断。
- `PipelineRunner.__init__` 加 `cancel_event` kw 透传到 `core.pipeline.run`。
- `desktop.py` 新增 `self.cancel_event = threading.Event()`、`self.stop_button`、
  `cancel_pipeline()` 方法（set event）、`_handle_run_cancelled()` handler。
  worker `_run_pipeline_worker` 捕获 PipelineCancelled 单独走 `("cancelled",
  msg)` ui_queue 通道；普通 Exception 仍走 `("error", ...)`。Status 加新
  状态 "Cancelled"，配色 `#dd8800` 橙黄。

**取消粒度**：

- 本地 BLAST / KASP / CAPS 设计：subprocess 不强杀；当前 step 跑完后到下一个
  `_check_cancel` 就 raise。通常局部 step 几秒钟到几十秒钟。
- 在线 BLAST 等待：`_cancel_wait(5)` + 立即检查，≤5 秒能切。
- 已提交到 NCBI 的任务**不撤回**（也不该撤——别的客户可能想用 RID 复用）；
  client 不再 poll，NCBI 队列里任务自然到期失效（或者用户自己在我们 log 的
  status URL 上手动 cancel）。

**为什么 PipelineCancelled 在 core 而不在 online_blast**：

online_blast 在 `src/snp_primer_app/`，core 在 `core/`。CLAUDE.md §5 的 Layer A
测试 `PYTHONPATH=.` 把 core 直接 import 时，不一定能找到
`src/snp_primer_app/`。让 `online_blast` 反向 `from core.pipeline import
PipelineCancelled` 就 OK（core 不在模块顶端 import online_blast，只在函数体内
延迟 import，避免循环）。**未来加新跨模块异常时记得遵守"低层定义、高层
import"原则。**

排查钩子：
- 按 Stop 但 status 不切 Cancelled？检查 worker 是不是已经走到一个长的
  blocking 子进程（subprocess.run），那要等子进程跑完才会到下一个
  `_check_cancel`。
- online polling 不响应？检查 `_cancel_wait` / `_raise_if_cancelled` 是不是被
  调到——大概率是新加的 helper 函数忘了改它的 `time.sleep` 调用点。

#### 第七轮微调（2026-05-20 同日，UI 视觉精修）

第六轮三项落地后视觉上还有三处不舒服，用户提出精修。**只动 desktop.py**：

1. **Reset Params 位置**：第六轮放 outer 顶端 header（独占一行只有这一个按钮），
   视觉上浪费一行 + 跟内容割裂。第七轮挪到 Design Options form 右下空白
   区——这个 form 第二行 column 4-7 是空的：

   ```python
   form.columnconfigure(8, weight=1)
   ttk.Button(form, text="Reset Params", command=self.reset_params).grid(
       row=0, column=8, rowspan=2, sticky=tk.E, padx=(20, 0)
   )
   ```

   `columnconfigure(8, weight=1)` 让 col 8 吃掉剩余水平 space，把按钮推到 form
   最右边沿；`rowspan=2 + sticky=E` 让按钮纵跨两行，grid 默认 cell-内
   anchor=CENTER 自动垂直居中。顶端 header Frame 整段删掉。

2. **Clear SNP Input 垂直居中**：第六轮用 `pack(..., anchor=tk.N)` 让按钮贴
   input_frame 顶部，结果跟 Text 的第一行齐，下面 4 行 Text 没视觉对齐。
   第七轮去掉 anchor → pack 默认 anchor=CENTER 让按钮在右侧 column 垂直居中
   到 Text 的中点。

3. **"Stop" 按钮改名 "Stop Pipeline"**：跟 "Run Pipeline" 对称（同样
   动词 + Pipeline 结构），一眼看出停的是 pipeline 而不是其他东西；维持英文
   保持 GUI 字符集一致。

未来加 UI 按钮时记得：
- 单按钮独占一整行通常视觉上"奇怪"，应该塞到已有 LabelFrame 的空白处而不是
  另起 header。
- pack 的 anchor 默认 CENTER，只在确实需要顶/底对齐时才写 `anchor=tk.N/S`。
- 按钮标签跟旁边的按钮维持词性对称（如 "Run Pipeline" / "Stop Pipeline"）。

### 6.19 SNP Input 加 Example Input 按钮（v11 第八轮）

**起因**：启动时 SNP Input 文本框预填两条 polymarker 示例
（IWB50236 / IWB58849），第七轮把 `Clear SNP Input` 挪到了文本框右侧并垂直
居中。但用户一旦点 Clear，就**没法再拿回示例**——新用户只剩两条路：手敲或回去
看 README。功能性损失，跟"GUI 就该让新用户秒上手"的初衷冲突。

**修复**（只动 `src/snp_primer_app/desktop.py`）：

1. `DesktopApp` 类里加常量 `_EXAMPLE_SNP_INPUT`（两行 polymarker，原来 inline
   在 `_build_ui` 里），启动预填和按钮 handler 共用同一份字符串，避免漂移。
2. SNP Input LabelFrame 右侧加 `Example Input` 按钮。两按钮**上下纵向堆叠**——
   在 input_frame 右侧建 sub-Frame `snp_button_col`，里面两按钮各自
   `pack(side=tk.TOP, fill=tk.X)`，Example Input 在上、Clear SNP Input 在下：
   ```python
   snp_button_col = ttk.Frame(input_frame)
   snp_button_col.pack(side=tk.RIGHT, padx=(8, 0))
   ttk.Button(snp_button_col, text="Example Input",
              command=self.load_example_snp_input).pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
   ttk.Button(snp_button_col, text="Clear SNP Input",
              command=self.clear_snp_input).pack(side=tk.TOP, fill=tk.X)
   ```
   最终：
   ```
   [ Text ............ | Example Input   ]
   [                   | Clear SNP Input ]
   ```
   选纵向堆叠是为了**少占横向宽度**——横向并排两按钮在 1440px 默认窗口下会
   吃掉文本框 ~25% 行宽（按钮 padx=8 + 文字宽 + 边距），polymarker 一行 100
   多字符的输入会更早换行。纵向堆叠时两按钮共用一列，宽度对齐到较长的
   "Clear SNP Input"（`fill=tk.X`），更整齐。
   Example Input 在上、Clear 在下：加载在前、清空在后，匹配阅读顺序，也避免
   "destructive 操作摆在第一眼位置" 的反 UX 直觉。
3. `load_example_snp_input`：先 delete 全部再 insert `_EXAMPLE_SNP_INPUT`，
   覆盖语义。**不弹确认对话框**——文本框非空时直接覆盖；用户明确选过这个语义
   （append 会破坏 polymarker 行格式；confirm dialog 在示例按钮这种轻量操作上
   嫌重）。
4. 按钮命名「Example Input」是为了跟 LabelFrame 标题「SNP Input」词法一致；
   不取 "Load Example" / "Sample" / "Demo" 等其它说法。

**没改的**：
- `core/` / `pipeline.py` / `models.py` / `pipeline_runner.py` 零改动。
- bootstrap / PyInstaller spec / 二进制 / 测试 零改动。
- 启动预填行为保持不变（首次启动仍有示例可看）。
- Clear SNP Input 按钮位置 / 行为不动；Reset Params 不动；actions 行不动。

**反惯例点提醒**：[[feedback_versioned_iteration]] 默认规则是
"snp_primer_windows_app 系列每改一轮就 vN → v(N+1) 拷贝"。本轮用户**明确
override**为「直接改 v11」——一次性 override，不改变默认惯例。后续轮次若用户
没再 override，仍按 v12 / v13 ... 的拷贝节奏走。

排查钩子：
- 按 Example Input 没反应？检查 `load_example_snp_input` 是不是真的被 bind
  到 `ttk.Button` 的 `command=`（grep `command=self.load_example_snp_input`）。
- 按钮位置错位（横向并排而不是上下堆叠）？看 input_frame 里有没有真正
  建立 `snp_button_col` sub-Frame——两按钮必须 pack 进 sub-Frame，而不是
  直接 pack 进 input_frame。直接 pack 进 input_frame 后 `side=tk.TOP` 会撞
  上 snp_text 的 `side=tk.LEFT`，几何管理器会按 pack 顺序占用边，结果是
  按钮堆在文本框顶部而不是右侧列。

### 6.20 Online database 下拉与 NCBI Web BLAST 全量对齐（v11 第九轮）

**症状**：用户在 GUI 的 Online database 下拉里选 `nt`，跑完后 log /
NCBI 状态页显示实际比对的 DB 是 `core_nt`，不是 `nt`。

**根因**：NCBI 2024 起重构了 nucleotide BLAST 的 standard databases 下拉：

- `nt` **不再是独立 value**——"Nucleotide collection" 那一项实际 value 是
  `nr/nt`（带斜杠）。旧 `nt` 名字传到 NCBI URL API 后**被服务器静默 fallback
  到 `core_nt`**，不报错、不警告。这就是用户看到"选 A 跑 B"的根源。
- `refseq_representative_genomes` 被**重命名**为 `refseq_reference_genomes`。
  v11 旧列表里的旧名字传上去也是 invalid value，同样静默 fallback 到 core_nt。
- 新增的 taxon 分桶：`nt_euk` / `nt_prok` / `nt_viruses` / `nt_others`——
  小麦 SNP 设计应该首选 `nt_euk`（只查真核序列，比 nt/core_nt 小一个数量级，
  排队等待短、命中也更相关）。
- 新增的其它条目：`refseq_select`（curated 高质量子集）、`refseq_gene`
  （人类 RefSeqGene）、`tls`（Targeted Loci）等。

**修复**：用 WebFetch 抓
`https://blast.ncbi.nlm.nih.gov/Blast.cgi?PAGE=Nucleotides&PROGRAM=blastn&BLAST_PROGRAMS=megaBlast&PAGE_TYPE=BlastSearch&SHOW_DEFAULTS=on`
HTML 里的 `<option value="...">`，**按 NCBI 自己的顺序**全量替换
`desktop.py:remote_db_combo` 的 values 列表（21 项）。

NCBI 当前 standard nucleotide databases 完整列表（顺序与 dropdown 一致）：
```
nt_euk, nt_prok, nt_viruses, nt_others, core_nt, refseq_select,
refseq_rna, refseq_reference_genomes, refseq_genomes, nr/nt, wgs,
est, sra, tsa, tls, htgs, pat, pdb, refseq_gene, gss, dbsts
```

附带改动：
- `workflow.py:49` 把 Plan tab fallback 字符串 `request.remote_database or "nt"`
  改成 `or "core_nt"`，反映 NCBI 当前的事实默认。
- `core/pipeline.py:754` docstring 里的 example DB 名 `nt` → `core_nt`，
  避免后来读代码时被旧名字误导。
- **不动** `online_blast.py:run_ncbi_blast`——它早就是 `DATABASE: database`
  原样透传，无 alias。

**`nr/nt` 带斜杠的 value**：Web 表单里它就是这个字符串。`urllib.parse.urlencode`
会自动把 `/` 编码成 `%2F`，NCBI 服务器解析得动；`run_ncbi_blast` 的 `_http_post`
走的就是 urlencode，无需特殊处理。

**Combobox 仍是 normal-state**（不 readonly）：用户可以手输自定义 DB 名。
NCBI 偶尔会上新库还没收录到下拉里（如 future 新的 nt_*** 分桶），保留手输能力
作为应急。

**默认值**：`self.remote_database_var = tk.StringVar(value="refseq_genomes")`
不动——`refseq_genomes` 仍在 NCBI 列表里，且对小麦全基因组场景适用。

排查钩子：
- log 里看到 NCBI 实际跑的 DB 不是你选的？95% 是用户敲了/选了 NCBI 当前
  list 之外的 value（typo / 旧名字 / 自定义不存在的 db），NCBI 静默 fallback
  到 `core_nt`。让用户对照 `View status / results: <URL>` 链接里的 `DATABASE=`
  参数验证。
- NCBI 一两年内大概率还会再调 DB 列表（看 2023→2024 这次变动节奏）。**下次
  发现 GUI 选的 DB 跟 NCBI 实际跑的对不上，第一步永远是用 WebFetch 重抓
  NCBI BLAST 页 HTML 里的 `<option value="...">`**，不要从训练数据 / 记忆里
  推断当前列表——记忆滞后是这次出错的根因。

---

## 7. 常用环境信息

- 标准输入：`/mnt/e/Software/small_tools/priner_design/primer_design_input.txt`
- 标准输出：`/mnt/e/Software/small_tools/priner_design/My_{CAPS,KASP}_539.tar.gz`
  解压后的 `selected_*_primers_<MARKER>.txt`
- WSL 系统 BLAST+：`/home/xufeng/miniconda3/bin/{blastn,blastdbcmd,makeblastdb}`
- 上游源码（参考用）：`/tmp/SNP_Primer_Pipeline/bin/`

---

## 8. 改动后的提交清单（不强制，但建议养成）

**核心铁律**：涉及 .exe / Windows 路径 / 子进程 / 编码的改动，提交清单里必须有
"用户在 Windows 端实跑 GUI 一次"这一条；不能用"WSL pass"代替。



- [ ] `grep -P '[^\x00-\x7F]' windows/bootstrap_and_launch.ps1` 仍无输出
- [ ] Layer A 4/4 PASS
- [ ] Layer B 4/4 PASS
- [ ] 如果改了 `_which()` / 二进制路径解析：本机不能跑 Windows，但跑
      `python3 tests/check_windows_binaries.py`，确认 bin/ 扫描和路径解析逻辑正确
- [ ] 改了 `core/` 下的"上游忠实移植"四件套之一：在 commit / PR 描述里明确指向
      上游对应 commit 哈希
- [ ] 改了 GUI / `pipeline_runner.py` 接口：`desktop.py:_build_request` 同步更新
