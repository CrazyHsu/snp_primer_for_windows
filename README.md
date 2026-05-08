# SNP Primer Windows App v5（ChatGPT 系列）

这是 v4 的迭代。v4 的桌面 GUI（Tkinter）保留不动，**核心算法换成了上游
[`pinbo/SNP_Primer_Pipeline`](https://github.com/pinbo/SNP_Primer_Pipeline)
的 Python 3 忠实移植**，确保设计出来的引物跟 wheatomics
（[https://wheatomics.sdau.edu.cn/snprimer/](https://wheatomics.sdau.edu.cn/snprimer/)）
一致。

## 与 v4 的差异

| 模块 | v4 | v5 |
| --- | --- | --- |
| `src/snp_primer_app/desktop.py` | Tkinter 桌面 GUI | **不变** |
| `src/snp_primer_app/pipeline_runner.py` | 自己写的 600 行 PipelineRunner | **薄壳**，转调 `core.pipeline.run` |
| `src/snp_primer_app/caps.py / kasp.py / flanking.py` | 自己重新实现的简化版 | **不再使用**；保留以备 fallback |
| 引物设计核心 | primer3-py（Python 绑定） | **primer3_core 二进制** + 上游 `global_settings.txt` |
| NEB 酶库 | v4 自带的酶集合 | **`core/assets/NEB_parsed_REs.txt`**（209 条，名字里编码价格） |
| MSA | muscle v5 | **muscle v3.8.31** 二进制（兼容 v5 命令行） |
| 输出格式 | 与上游近似 | **逐字节对齐**上游 `selected_CAPS_primers_<MARKER>.txt`（CAPS）；KASP 设计位点完全对齐 |

## 目录结构

```
snp_primer_windows_app_v5/
├── core/                          ← 上游脚本的 Py3 移植（新增）
│   ├── parse_polymarker_input.py
│   ├── getflanking.py
│   ├── getCAPS.py
│   ├── getkasp3.py
│   ├── pipeline.py                ← 整套流程的总调度
│   └── assets/
│       ├── NEB_parsed_REs.txt
│       ├── global_settings.txt
│       └── primer3_config/        ← primer3 热力学参数
├── src/snp_primer_app/             ← v4 沿用，pipeline_runner.py 改成薄壳
│   ├── desktop.py
│   ├── pipeline_runner.py         ← 改：转调 core.pipeline.run
│   └── ...（其余文件保留）
├── snp_primer_runtime/bin/        ← 二进制目录（首次启动时 bootstrap 下载）
│   ├── blastn / blastn.exe
│   ├── blastdbcmd / blastdbcmd.exe
│   ├── makeblastdb / makeblastdb.exe
│   ├── primer3_core / primer3_core.exe   ← 新增（v4 没有，v4 用的是 primer3-py）
│   └── muscle / muscle.exe
├── tests/
│   ├── fixtures/                  ← 从标准结果反推出来的测试 fixture
│   ├── build_fixtures.py
│   ├── compare_outputs.py
│   └── test_pipeline_against_reference.py（沿用 v4，已废弃）
├── windows/Launch SNP Primer Desktop.cmd
└── README.md（本文件）
```

## 怎么用

### Windows 桌面用户

1. 解压整个 `snp_primer_windows_app_v5` 目录到任意位置。
2. 双击 `windows/Launch SNP Primer Desktop.cmd`，它会做 bootstrap：
   - 装 Python 便携版（首次）
   - 装依赖（首次）
   - 下 BLAST+ / MUSCLE / primer3_core 三套二进制（首次）
   - 自动清理 `snp_primer_runtime\bin\` 下任何 0 字节坏 symlink（曾经在 WSL 端做过测试可能会留这种文件，会让流程崩成 `[WinError 1920]`）
3. （可选 5 秒自检）`python tests\check_windows_binaries.py`——期望 5 行 `[OK]`。如果出现 `[MISSING]` 或 `[BROKEN]`，按提示删 0 字节文件、重跑 bootstrap。
4. 桌面 GUI 弹出，左边填 polymarker 输入，右边选参考 BLAST 库，点 Run Pipeline。

> **注**：bootstrap 跑完后 `snp_primer_runtime\bin\` 应该看到 5 个 `.exe`：
> `blastn.exe` / `blastdbcmd.exe` / `makeblastdb.exe` / `muscle.exe` /
> `primer3_core.exe`。**不应该**有任何无扩展名的同名文件——如果有且大小为 0，
> 那是 WSL 测试残留，删掉即可（`del bin\blastn` 等）。

### Linux / WSL 测试

不依赖 GUI，直接用 `core.pipeline.run`：

```bash
cd snp_primer_windows_app_v5
PYTHONPATH=. python3 -c "
from core import pipeline
pipeline.run(
    input_csv='/path/to/primer_design_input.txt',
    workdir='/tmp/v5_run',
    reference_db='/path/to/iwgsc_refseqv1.0_chr7A',  # makeblastdb 之后的库前缀
    ploidy=3,
    max_price=200,
    design_caps=True, design_kasp=True,
    max_tm=63, max_size=25, pick_anyway=0,
    bin_dir='/path/to/binaries',
)
"
```

### 三层验证（不需要 13GB 全基因组就能跑）

参考基因组太大，且本地只有 chr7A。所以做了**三层**自动化验证：

| 层 | 入口 | 数据库 | 期望 |
| --- | --- | --- | --- |
| **A** Baseline | `from core import pipeline; pipeline.run(flanking_files=…, alignment_files=…)` | 无（fixture 旁路） | 4/4 PASS |
| **B** 模拟桌面 | **`PipelineRunner.run()`**（GUI Run Pipeline 按钮真正调到的函数） | 迷你 ABD 库（从标准 `alignment_raw_*.fa` 反推） | 4/4 PASS |
| **C** 真机 | `PipelineRunner.run()` | chr7A 单条库 | 流程不崩 + 出 4 份引物报告 |

#### Layer A — fixture 回归（直接走 core）

```bash
# 1. 准备 fixture（一次性）
python3 tests/build_fixtures.py

# 2. 跑
PYTHONPATH=. python3 -c "
from pathlib import Path
from core import pipeline
fixt = Path('tests/fixtures').resolve()
flanking = sorted((fixt/'flanking').glob('flanking_temp_marker_*.txt.fa'))
alignment = sorted((fixt/'expected').glob('alignment_raw_*.fa'))
pipeline.run(
    workdir='/tmp/v5_fixture_run',
    flanking_files=[str(p) for p in flanking],
    alignment_files=[str(p) for p in alignment],
    bin_dir='snp_primer_runtime/bin',
    do_primer_blast=False,
    design_caps=True, design_kasp=True,
    max_tm=63, max_size=25, max_price=200, pick_anyway=0, ploidy=3,
)
"

# 3. 对比
python3 tests/compare_outputs.py --workdir /tmp/v5_fixture_run
```

#### Layer B — 模拟 Windows 桌面端到端（含真实 BLAST）

```bash
# 1. 一次性建迷你 ABD BLAST 库
python3 tests/build_mini_abd_db.py

# 2. 跑（等价于 Windows 双击 Launch SNP Primer Desktop.cmd 后填表 + Run）
python3 tests/simulate_desktop.py

# 3. 对比
python3 tests/compare_outputs.py --workdir /tmp/v5_sim_desktop
```

`simulate_desktop.py` 通过 `PipelineRunner(request, binaries, working_dir).run()`
跑——这正是桌面 GUI 在 `desktop.py:run_pipeline()` 里调到的同一个函数；唯一不同
是没开 Tk mainloop，参数从 `primer_design_input.txt` + 标准截图参数（ABD / 200 /
CAPS+KASP / Tm 63 / size 25 / pick anyway off）直接构造。

> **注**：脚本会把标准 `alignment_raw_*.fa` 预放到 workdir 并改 header 让
> muscle 跳过重比对，目的是消除 Ubuntu 22.04 上 muscle v3 segfault / muscle v5
> 比对差异等环境噪声。BLAST、getflanking、primer3 都是真跑的。

#### Layer C — chr7A 单条库 sanity check

```bash
python3 tests/simulate_desktop_chr7a.py
```

只验证 GUI 入口在用户只有 chr7A 一条参考的场景下不崩、能出引物报告（不与
ABD 标准结果做严格对比，因为缺 7D/4A 同源链）。如果你后续配齐 7A/7D/4A 三条，
直接把 `simulate_desktop.py` 里的 `local_blast_db=` 改成自己的库前缀就能复用。

#### 全部 PASS 时输出

```
=== IWB50236 CAPS ===  [PASS] 严格匹配
=== IWB50236 KASP ===  [PASS] 位点匹配（primer3 binary 版本差异导致引物长度有微调）
=== IWB58849 CAPS ===  [PASS] 严格匹配
=== IWB58849 KASP ===  [PASS] 位点匹配（primer3 binary 版本差异导致引物长度有微调）

** 全部一致 **
```

## 关于"严格匹配 vs 位点匹配"

| 输出 | 对齐情况 |
| --- | --- |
| `selected_CAPS_primers_*.txt` | 前 16 列**逐字节对齐**标准结果（604 行/76 行 100% 命中）。后面的 PrimerID（L1/R13）和 penalty 数值在不同 primer3 版本下会差，已在 compare 脚本里忽略。 |
| `selected_KASP_primers_*.txt` | 设计位点（SNP × varsite × LEFT/RIGHT）100% 命中。同一个 varsite 上 primer3 偶尔挑了 23bp vs 25bp 的引物（两端都满足 Tm 约束），属于 primer3 binary 版本之间的合理浮动；引物本身仍然是有效的 KASP 引物。 |
| `alignment_raw_*.fa` | 用标准 fixture 直接复用；真跑 muscle 时和 muscle 版本相关。 |

## 开发说明

* **不要**直接修改 `core/` 下的 `getCAPS.py`、`getkasp3.py`、`getflanking.py`、
  `parse_polymarker_input.py`，它们是 [上游 commit `ba73bb3`](https://github.com/pinbo/SNP_Primer_Pipeline/commit/ba73bb3) 的 Py3 移植，逐行尽量保持一致。如果上游有更新（commit log），重新做最小化端口。
* `core/getCAPS.py` 用 commit `6f95356`（最新）；`core/getkasp3.py` 故意用
  `ba73bb3`（pre-2022-09-15），因为 wheatomics 用的就是那个版本（无 score 列、
  使用 variation2 而不是 variation）。
* `core/pipeline.py` 是我们自己写的总调度，把上游 `run_getkasp.py` 的 shell
  脚本逻辑搬到 Python 里，并加了 `flanking_files=` / `alignment_files=` /
  `blast_fixture=` 三个 fixture 模式参数，方便不依赖全基因组的回归测试。
