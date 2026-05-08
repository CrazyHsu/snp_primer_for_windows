# CLAUDE.md — SNP Primer Windows App v7（ChatGPT 系列）

> 这份文件给未来的 Claude 会话用：你（Claude）会在 v7 目录里被启动协助迭代时，
> **先读这份文件**再动手。它只列那些**从代码里读不出来 / 容易踩坑 / 一旦忘记就出错**
> 的事。常规的目录布局、函数签名、依赖版本去 README.md 和代码里查。

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
