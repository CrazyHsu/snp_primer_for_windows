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
2. 首次启动会自动 bootstrap：下载 Python 3.11 便携版、NCBI BLAST+、primer3、
   muscle 到 `snp_primer_runtime/`；如缺 VC++ Redist 也会自动安装。需联网。
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
snp_primer_runtime/        首次启动后由 bootstrap 创建
  bin/                     blastn.exe / blastdbcmd.exe / makeblastdb.exe /
                           primer3_core.exe / muscle.exe + 必要的 .dll
  venv/                    Python 虚拟环境
  workspace/               每次运行的产物
  logs/                    desktop_*.log
references/                参考序列示例配置
tests/                     单元测试 + fixtures（dev 用）
```

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
