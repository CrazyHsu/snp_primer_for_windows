# snp_primer_for_windows

双击就能跑的 Windows 桌面 SNP 引物设计工具（Tkinter GUI）。给一份
`polymarker` 格式的输入和参考序列，输出 KASP / CAPS / dCAPS 引物。

底层算法是
[pinbo/SNP_Primer_Pipeline](https://github.com/pinbo/SNP_Primer_Pipeline)
的 Python 3 忠实移植，结果与 wheatomics
（[https://wheatomics.sdau.edu.cn/snprimer/](https://wheatomics.sdau.edu.cn/snprimer/)）一致。

## 快速开始

1. 把整个仓库解压到本地（任意路径），双击：
   ```
   windows\Launch SNP Primer Desktop.cmd
   ```
2. 首次启动会自动 bootstrap：创建 Python venv，并把仓库自带的 BLAST+、
   primer3、muscle 从 `windows/bin/` 复制到 `snp_primer_runtime/bin/`。如果机器
   没有可用 Python，才会下载 Python 3.11；如缺 VC++ Redist 也会自动安装。
3. GUI 启动后：
   - **Reference FASTA**：填一个 `.fa/.fasta/.fna/.fsa` 文件，程序会自动
     `makeblastdb -parse_seqids` 建索引（缓存在 `<workdir>/auto_blastdb/`）。
   - **Local BLAST DB**：或者直接填一个已经建好的 BLAST 库前缀。两者互斥。
   - **SNP Input**：贴 polymarker 行 `name,chr,seq[A/G]seq`。
   - 点 **Run Pipeline**。

输出在工作目录下：`selected_KASP_primers_<MARKER>.txt`、
`selected_CAPS_primers_<MARKER>.txt`、`Potential_*.tsv`、`alignment_raw_*.fa`。

## 输入示例

```
IWB50236,7A,cctcctcgtttcaaaagaagtaactcatcaaatgattcaaaaatatcgat[A/G]CTTGGCTGGTGTATCGTGCAGACGACAGTTCGTCCGGTATCAACAGCATT
IWB58849,7A,ATGACAATCAGAGCATGGAAGAAGACTTCGAGAAAGGAACCGCGCCCAAG[T/C]GGTTTTGCTACAGCGACTTGGCCATGGCCACCGACAACTTTTCCGACGAT
```

## 目录结构

```
core/                      上游算法 Py3 移植
  pipeline.py              总调度
  parse_polymarker_input.py / getflanking.py / getCAPS.py / getkasp3.py
  assets/                  primer3 配置 + NEB 酶库
src/snp_primer_app/        Tkinter GUI 与 runner
  desktop.py               GUI 入口
  pipeline_runner.py       GUI → core.pipeline 的薄壳
  models.py / parsers.py / runtime_paths.py / ...
windows/
  Launch SNP Primer Desktop.cmd     一键启动
  bootstrap_and_launch.ps1          下载依赖 + 启 GUI
  bin/                              随仓库携带的 Windows BLAST/primer3/muscle 二进制
snp_primer_runtime/        首次启动后由 bootstrap 创建
  bin/                     blastn.exe / blastdbcmd.exe / makeblastdb.exe /
                           primer3_core.exe / muscle.exe + 必要的 .dll
  venv/                    Python 虚拟环境
  workspace/               每次运行的产物
  logs/                    desktop_*.log
references/                参考序列示例配置
tests/                     单元测试 + fixtures（dev 用）
```

## 打包成独立 .exe（可选）

如果要分发给完全没装 Python 的用户，可以用 PyInstaller 打成可执行。先**跑一次
bootstrap** 让 `snp_primer_runtime\venv\` 与 `snp_primer_runtime\bin\*.exe` 就位
（双击 `windows\Launch SNP Primer Desktop.cmd`），然后两条路径任选其一：

| | `build_windows.bat`（onedir） | `build_windows_onefile.bat`（onefile） |
|---|---|---|
| 输出 | `dist\SNPPrimerDesktop\` 文件夹（带 `_internal\` + `bin\`） | `dist\SNPPrimerDesktop.exe` + `dist\bin\` |
| 启动速度 | 几乎瞬开 | 每次 5-15s 解压临时目录 |
| 杀软误报 | 较低 | 较高（PyInstaller `--onefile` bootloader 常被误判） |
| 调试 | 文件结构看得见 | 临时解压在 `%TEMP%\_MEIxxxxxx\`，过会清掉 |
| Workspace 落点 | `dist\SNPPrimerDesktop\snp_primer_runtime\` | **从哪个目录双击就在哪** |
| 分发 | 整个文件夹拷给用户 | `.exe` 与 `bin\` 一起拷给用户 |

两种产物里 BLAST+/primer3/muscle 二进制 + 算法 assets 都已打进去，终端用户机器
上不用装 Python。**强烈推荐 onedir**——启动快、易排错，且 onefile 在某些 Windows
机器上跑 makeblastdb 会撞 `0xC0000005`（已知问题：PyInstaller `--onefile`
bootloader 的 SxS activation context 通过 `CreateProcess` 继承到 NCBI .exe，
触发 VC runtime DLL 版本错配）。这不是 PATH/env 层面能解决的问题。如果你的环境
正好不撞这个，onefile 也能跑，但首选还是 onedir。

> 单 .exe 用户提醒：建议给 .exe 单独放一个文件夹（如 `Desktop\SNPPrimer\`），
> 否则 workspace / logs 会建在 .exe 所在的目录里，污染下载 / 桌面。
>
> onefile 版本不再把 BLAST/primer3/muscle 嵌进 PyInstaller 包里；构建脚本会把
> 它们复制到 `dist\bin\`。这不是纯单文件分发，但能避开 `makeblastdb`
> `0xC0000005` 这类 Windows/PyInstaller 子进程问题。

## 系统需求

- Windows 10 / 11 (x64)
- 网络：首次启动需要下载约 200 MB 依赖；之后离线可用
- 磁盘：bootstrap 完约 300 MB；BLAST 库另算

## 致谢

- 上游算法：[pinbo/SNP_Primer_Pipeline](https://github.com/pinbo/SNP_Primer_Pipeline)
- 验证基准：[wheatomics SNPrimer](https://wheatomics.sdau.edu.cn/snprimer/)
- 依赖二进制：[NCBI BLAST+](https://ftp.ncbi.nlm.nih.gov/blast/)、
  [primer3](https://github.com/primer3-org/primer3)、
  [muscle](https://github.com/rcedgar/muscle)
