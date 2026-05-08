#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNP 引物设计流程总调度。

对应上游 ``run_getkasp.py`` 的串联逻辑，但全部用 Python 3 + 函数调用，没有
``call(shell=True)`` 调子脚本。

入口： :func:`run`
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path

from . import parse_polymarker_input
from . import getflanking
from . import getCAPS
from . import getkasp3


HERE = Path(__file__).resolve().parent
ASSETS_DIR = HERE / "assets"


# Windows 上每次 subprocess.call(shell=True) 都会弹一个 cmd.exe 黑窗，再加 .exe
# 自身（blastn/makeblastdb/primer3_core/muscle）也是 CUI 程序，从 Tk GUI 启动会
# 闪一下控制台。CREATE_NO_WINDOW 是 Windows 专有 flag，让子进程不创建可见 console。
# 非 Windows 平台 getattr 落到 0；_no_window_kwargs() 直接返回空 dict，subprocess
# 调用形态完全不变。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _no_window_kwargs():
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def _patched_call(*args, **kwargs):
    """``subprocess.call`` 的 wrapper：Windows 上自动加 CREATE_NO_WINDOW。

    getCAPS.py / getkasp3.py 是上游 commit 的 byte-for-byte 移植，不能改源码。
    它们顶部 ``from subprocess import call`` 把名字绑死了；这里在 import 之后把
    它们模块属性的 ``call`` 重新指向本 wrapper，所有后续 ``call(...)`` 调用都会
    走这条路径。
    """
    if sys.platform == "win32" and "creationflags" not in kwargs:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return subprocess.call(*args, **kwargs)


# 在 pipeline 模块 import 时一次性 patch；后续 import 顺序变了也无所谓，因为
# 只有 pipeline.run() 会触发 getCAPS.caps_main / getkasp3.kasp_main，而进入
# pipeline 之前这里已经执行过了。
getCAPS.call = _patched_call
getkasp3.call = _patched_call


def _try_short_path_win(p):
    """Windows 上试着把含空格的 path 转成 8.3 短名；不行返回 None。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        gspn = ctypes.windll.kernel32.GetShortPathNameW
        gspn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        gspn.restype = wintypes.DWORD
        d, n = os.path.split(p)
        if " " in d:
            buf = ctypes.create_unicode_buffer(1024)
            rc = gspn(d, buf, 1024)
            if rc == 0 or rc >= 1024:
                return None
            d = buf.value
        cand = os.path.join(d, n)
        if " " not in cand:
            return cand
    except Exception:
        pass
    return None


def _make_junction_win(link, target):
    """Windows 上调 ``mklink /J`` 建 NTFS Junction。返回是否成功。

    Junction 不需要管理员权限，且跨本地卷有效（跟 hardlink 不一样）。
    """
    if os.name != "nt":
        return False
    try:
        # link 必须不存在（否则 mklink 报错）
        if os.path.exists(link) or os.path.islink(link):
            try:
                os.rmdir(link)  # junction 用 rmdir 删
            except OSError:
                try:
                    os.unlink(link)
                except OSError:
                    return False
        # cmd /c 调 mklink
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True,
                           **_no_window_kwargs())
        return r.returncode == 0 and os.path.isdir(link)
    except Exception:
        return False


def _blast_safe_db_path(p, fallback_dir=None):
    """把 BLAST DB 路径处理成 ``-db`` 参数能正确传递的形式。

    **关键事实**：BLAST 的 ``-db`` 设计上支持多 DB（例 ``-db "db1 db2"``），
    所以 blastn 拿到 db 参数后**主动按空格 split**。即便 Python subprocess 用
    list args 把整个含空格 path quote 成单个 cmdline 参数，blastn 内部仍按空格
    split。``-out`` / ``blastdb_aliastool -dblist`` 等同理——BLAST 全家如此。

    所以含空格 path 没法靠 quote 解决；必须让 DB 文件**物理出现在无空格 path** 下。

    策略（按可行性排）：

    1. ``p`` 无空格 → 直接返回
    2. Windows + 8.3 短名可用 → 返回短名（如 ``F:\\X~1\\Chr7A``）
    3. Windows + ``fallback_dir`` 提供（必须无空格）→ 调 ``mklink /J`` 把 DB 所在
       目录 junction 到 fallback_dir 下的无空格名，返回 junction 内的 DB prefix
    4. 全部失败 → 抛 RuntimeError，文本里给用户两条手动路径
    """
    p = os.fspath(p)
    if " " not in p:
        return p
    if os.name != "nt":
        raise RuntimeError(
            f"BLAST DB 路径含空格不能由 -db 正确传递（BLAST 会主动按空格 split）：\n"
            f"  {p}\n"
            f"请把 BLAST 库移到一个无空格的路径下重试。"
        )
    # Try (2) 8.3 短名
    short = _try_short_path_win(p)
    if short:
        return short
    # Try (3) Junction
    if fallback_dir and " " not in str(fallback_dir):
        db_dir, db_name = os.path.split(p)
        junction = os.path.join(str(fallback_dir), "blastdb_jn")
        if _make_junction_win(junction, db_dir):
            return os.path.join(junction, db_name)
    # Fail (4)
    raise RuntimeError(
        f"BLAST DB 路径含空格，且 8.3 短名 / NTFS Junction 两种自动 fallback 都失败：\n"
        f"  原路径：{p}\n"
        f"BLAST 工具家族（blastn/makeblastdb/blastdb_aliastool 等）都对 path 参数\n"
        f"按空格 split，没法靠 quote 绕过。请手动把 BLAST DB 移到无空格路径下，\n"
        f"例如 F:\\BlastDB\\Chr7A，然后在 GUI 里重新指定。"
    )


def _check_blastdb_has_parse_seqids(db_prefix):
    """检查 BLAST DB 是不是用 -parse_seqids 建过。

    没用 -parse_seqids 建的库只有 ``.nhr/.nin/.nsq``（外加新版 BLAST+ 的
    ``.ndb/.not/.ntf/.nto``）。要让 blastdbcmd 能按 accession 反查，必须有
    accession→OID 的索引文件——老版叫 ``.nsi``/``.nsd``/``.nog``，新版统一在
    ``.nos`` 里。这里只要这几个里有任意一个存在就当通过；都没有就抛错。

    db_prefix 可能是绝对路径（比如经过 _blast_safe_db_path() junction 之后的
    路径），也可能是带空格短名。检查时按 prefix + 后缀直接 stat。
    """
    suffixes = (".nos", ".nog", ".nsi", ".nsd", ".nhd", ".nhi")
    db_prefix = os.fspath(db_prefix)
    if any(os.path.isfile(db_prefix + suf) for suf in suffixes):
        return
    # 没找到任何 parse_seqids 产物。报错给用户能动手的提示。
    base_dir = os.path.dirname(db_prefix) or "."
    base_name = os.path.basename(db_prefix)
    raise RuntimeError(
        f"BLAST 库 {db_prefix} 看起来不是用 -parse_seqids 建的（没找到 "
        f".nos/.nog/.nsi/.nsd 任意一种 accession 索引文件）。\n\n"
        f"blastdbcmd 必须靠这些索引按染色体名（如 Chr7A）反查序列；缺了它\n"
        f"流程会卡在 Step 5 之后产出空文件，再到 getkasp3 里抛 KeyError。\n\n"
        f"修复：到 {base_dir} 下，用原始 FASTA 重建一次：\n"
        f"  makeblastdb -in <你的染色体fasta> -dbtype nucl -parse_seqids -out {base_name}\n"
        f"重建完保留同样的前缀（{base_name}），GUI 不用改设置直接重跑。"
    )


def _ensure_blastdb_from_fasta(fasta_path, workdir, bin_dir, log):
    """给 raw FASTA 自动建 BLAST 库，返回 prefix。

    建出的库放在 ``<workdir>/auto_blastdb/<fasta_stem>``。workdir 由 GUI 保证
    是无空格 ASCII 路径，正好绕过 §6.7 那道"BLAST 路径按空格 split"的坎。

    缓存：如果 ``<prefix>.nhr`` 已经存在且 mtime ≥ FASTA 的 mtime，跳过 rebuild。
    建库本身要走 ``-parse_seqids``，否则后面 blastdbcmd 还是反查不出来，等于没建。
    """
    fasta_path = Path(fasta_path).resolve()
    if not fasta_path.is_file():
        raise RuntimeError(f"reference_fasta 找不到文件：{fasta_path}")
    auto_db_dir = Path(workdir) / "auto_blastdb"
    auto_db_dir.mkdir(parents=True, exist_ok=True)
    db_prefix = auto_db_dir / fasta_path.stem
    nhr = Path(str(db_prefix) + ".nhr")
    if nhr.is_file() and nhr.stat().st_mtime >= fasta_path.stat().st_mtime:
        log(f"已存在 BLAST 库 {db_prefix}（mtime ≥ FASTA），跳过 makeblastdb。")
        return str(db_prefix)
    makeblastdb_bin = _which("makeblastdb", [bin_dir])
    if not makeblastdb_bin:
        raise RuntimeError(
            "找不到 makeblastdb 二进制。请检查 snp_primer_runtime/bin/ 目录\n"
            "（或重跑 windows/Launch SNP Primer Desktop.cmd 走一次 bootstrap，\n"
            "它会下载 makeblastdb.exe 到 bin/）。"
        )
    log(f"Step 0: 用 makeblastdb 自动从 {fasta_path} 建索引到 {db_prefix}")
    cmd = [makeblastdb_bin,
           "-in", str(fasta_path),
           "-dbtype", "nucl",
           "-parse_seqids",
           "-out", str(db_prefix)]
    r = _run(cmd, log)
    if r.returncode != 0 or not nhr.is_file():
        out_log = (r.stdout or "").strip() or "(no output captured)"
        raise RuntimeError(
            f"makeblastdb 失败 (returncode={r.returncode}, fasta={fasta_path})。\n"
            f"输出：\n{out_log}\n\n"
            f"常见原因：FASTA 不是 nucl / 文件已损坏 / 路径含特殊字符。"
        )
    return str(db_prefix)


def _which(binname, candidates):
    """在候选目录里找二进制，找不到返回 PATH 中的同名命令。

    Windows 上优先 ``.exe``；并且**跳过 0 字节文件**——这能挡住 WSL 端测试遗留
    在 NTFS 上的 Linux symlink（从 Windows 进程视角，它们是 0 字节"坏链接"，
    `Path.exists()` 仍然返回 True，会被 subprocess 当成 PE 二进制去执行从而
    抛 ``WinError 1920``）。
    """
    is_win = os.name == "nt"
    suffixes = (".exe", "") if is_win else ("", ".exe")
    for d in candidates:
        if d is None:
            continue
        for suf in suffixes:
            p = Path(d) / (binname + suf)
            try:
                if p.is_file() and p.stat().st_size > 0:
                    return str(p)
            except OSError:
                continue
    return shutil.which(binname)


def _run(cmd, log, cwd=None):
    """跑一条命令，把命令本身先 log 出来。"""
    if isinstance(cmd, list):
        log("CMD: " + " ".join(str(x) for x in cmd))
    else:
        log("CMD: " + str(cmd))
    return subprocess.run(cmd, cwd=cwd, check=False,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, **_no_window_kwargs())


def run(*,
        input_csv=None,
        workdir,
        reference_db=None,
        reference_fasta=None,
        ploidy=3,
        max_price=200,
        design_caps=True,
        design_kasp=True,
        max_tm=63,
        max_size=25,
        pick_anyway=0,
        do_primer_blast=True,
        blast_fixture=None,
        flanking_files=None,
        alignment_files=None,
        bin_dir=None,
        log=print):
    """
    跑完整 SNP 引物设计流程。

    Parameters
    ----------
    input_csv : str | Path
        polymarker 风格输入。可以带行号首列。
    workdir : str | Path
        工作目录。流程产物写在这里；上游会在里面创建 ``CAPS_output/``、
        ``KASP_output/`` 等子目录。
    reference_db : str | Path | None
        本地 BLAST 库（``makeblastdb`` 输出的前缀路径）。若用 ``blast_fixture``
        模式则可以为 None，但 step 4 ``blastdbcmd`` 取 flanking 仍需要一个
        BLAST 库（fixture 模式下 pipeline.py 会期待您给一个迷你库，包含同
        源序列条目）。**与 reference_fasta 互斥**。
    reference_fasta : str | Path | None
        raw FASTA 文件（``.fa/.fasta/.fna/.fsa/.fas``）。若给了，会自动调
        ``makeblastdb -dbtype nucl -parse_seqids`` 在
        ``<workdir>/auto_blastdb/<stem>`` 下建出 BLAST 库再继续。第二次跑同一
        个 FASTA 会按 mtime 走缓存，不重建。**与 reference_db 互斥**。
    ploidy : int
        1 / 2 / 3，对应 A / AB / ABD。Chinese Spring 标准是 3。
    max_price, max_tm, max_size, pick_anyway : 同上游
    do_primer_blast : bool
        是否对设计好的引物再做一次 BLAST 来填 ``matched_chromosomes`` 列。
    blast_fixture : str | Path | None
        如果给了路径，就跳过 step 2 ``blastn``，直接拷贝这个文件作
        ``blast_out.txt``。用于 Layer 1 fixture 验证。
    flanking_files : list[str | Path] | None
        如果给了一组 flanking_*.fa 文件，就跳过 step 1-5（包括 BLAST），
        直接把这些文件拷进工作目录。用于不依赖任何 BLAST 库的 fixture
        验证。``input_csv`` 在这个模式下可以为 None。
    alignment_files : list[str | Path] | None
        额外可选：预先放好 ``alignment_raw_<SNP>.fa`` 文件，使
        getCAPS / getkasp3 跳过对 muscle 的调用。便于在没有 muscle 二进制
        的环境里跑 fixture 验证。
    bin_dir : str | Path | None
        primer3_core / muscle / blastn / blastdbcmd / makeblastdb 所在目录。
        留 None 则在 PATH 中找。
    log : callable
        每条进度信息的回调。

    Returns
    -------
    dict
        ``{"workdir": ..., "caps_dir": ..., "kasp_dir": ...,
           "all_alignment_raw": ..., "potential_caps": ..., "potential_kasp": ...}``
    """
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    if input_csv is not None:
        input_csv = str(Path(input_csv).resolve())
    elif flanking_files is None:
        raise ValueError("必须提供 input_csv 或 flanking_files 至少一个")

    bin_dir_str = str(Path(bin_dir).resolve()) if bin_dir else None
    # reference_fasta vs reference_db 二选一；同时给说明上层逻辑乱了。
    if reference_fasta and reference_db:
        raise ValueError(
            "reference_fasta 与 reference_db 不能同时给——只接受一个。"
        )
    # 给 raw FASTA 时先 makeblastdb 自动建库，把 prefix 当 reference_db 用。
    # 这样下游 step 2 / step 5 / _check_blastdb_has_parse_seqids 都不用知道
    # 输入到底是 FASTA 还是 prefix。
    if reference_fasta and not reference_db:
        reference_db = _ensure_blastdb_from_fasta(
            reference_fasta, workdir, bin_dir_str, log)
    if reference_db:
        reference_db = str(Path(reference_db).resolve())
        # BLAST 的 -db 按空格 split（连 -out / blastdb_aliastool 也一样）。
        # 自动尝试：(1) 无空格透传 → (2) Windows 8.3 短名 → (3) workdir 里建 NTFS
        # junction，让 DB 文件出现在无空格路径下。最后失败才抛错给用户。
        reference_db = _blast_safe_db_path(reference_db, fallback_dir=str(workdir))

    # 找二进制
    blastn_bin = _which("blastn", [bin_dir_str])
    blastdbcmd_bin = _which("blastdbcmd", [bin_dir_str])
    primer3_bin = _which("primer3_core", [bin_dir_str])
    # 优先 muscle5（Ubuntu 22.04 上的 muscle v3 静态二进制会 segfault），
    # 找不到再回退到 muscle / muscle3.8.31_*
    muscle_bin = _which("muscle5", [bin_dir_str])
    if not muscle_bin:
        muscle_bin = _which("muscle", [bin_dir_str])
    if not muscle_bin:
        muscle_bin = _which("muscle3.8.31_i86linux64", [bin_dir_str])
    log(f"binaries: blastn={blastn_bin} blastdbcmd={blastdbcmd_bin} "
        f"primer3={primer3_bin} muscle={muscle_bin}")

    # 注入路径到 getCAPS / getkasp3
    assets_dir_str = str(ASSETS_DIR)
    getCAPS.set_assets_dir(assets_dir_str)
    getkasp3.set_assets_dir(assets_dir_str)
    if reference_db:
        getCAPS.set_blast_reference(str(reference_db))
        getkasp3.set_blast_reference(str(reference_db))
    if bin_dir_str:
        getCAPS.configure(blast_flag=1 if do_primer_blast else 0,
                          max_price_=max_price, max_tm=max_tm,
                          max_primer_size=max_size, pick_anyway_=pick_anyway,
                          base_path=bin_dir_str)
        getkasp3.configure(blast_flag=1 if do_primer_blast else 0,
                           max_tm=max_tm, max_primer_size=max_size,
                           pick_anyway_=pick_anyway, base_path=bin_dir_str)
    else:
        getCAPS.configure(blast_flag=1 if do_primer_blast else 0,
                          max_price_=max_price, max_tm=max_tm,
                          max_primer_size=max_size, pick_anyway_=pick_anyway)
        getkasp3.configure(blast_flag=1 if do_primer_blast else 0,
                           max_tm=max_tm, max_primer_size=max_size,
                           pick_anyway_=pick_anyway)

    # 切到工作目录工作（上游所有脚本都用相对路径 / cwd）
    saved_cwd = Path.cwd()
    try:
        os.chdir(workdir)

        # 预先放标准 alignment_raw_*.fa（独立于 flanking_files 模式）
        if alignment_files is not None:
            log("alignment_files 模式：预放标准 alignment_raw 文件，让 muscle 跳过")
            for f in alignment_files:
                src = Path(f)
                if not src.is_absolute():
                    src = saved_cwd / src
                dst = Path(src.name)
                shutil.copyfile(str(src), str(dst))

        if flanking_files is not None:
            # flanking-fixture 模式：跳过 step 1-5，直接拿现成 flanking 文件
            log("flanking_files 模式：跳过 BLAST 与 flanking 提取，直接复制现成文件")
            for f in flanking_files:
                src = Path(f)
                if not src.is_absolute():
                    src = saved_cwd / src
                dst = Path(src.name)
                shutil.copyfile(str(src), str(dst))
        else:
            # 把 input_csv 拷一份到工作目录，去掉行号列后命名为 polymarker_input.csv
            polymarker_csv_in_workdir = "polymarker_input.csv"
            src_csv = input_csv
            if not os.path.isabs(src_csv):
                src_csv = str(saved_cwd / src_csv)
            _normalize_polymarker_input(src_csv, polymarker_csv_in_workdir)

            # Step 1: parse polymarker -> for_blast.fa
            log("Step 1: 解析 polymarker 输入 -> for_blast.fa")
            parse_polymarker_input.parse(polymarker_csv_in_workdir,
                                         "for_blast.fa")

            # Step 2: blastn (or fixture)
            if blast_fixture:
                log(f"Step 2: 复用 fixture BLAST 输出 {blast_fixture}")
                src_b = blast_fixture
                if not os.path.isabs(src_b):
                    src_b = str(saved_cwd / src_b)
                shutil.copyfile(src_b, "blast_out.txt")
            else:
                if not blastn_bin:
                    raise RuntimeError("找不到 blastn，请通过 bin_dir 指向 BLAST+ "
                                       "目录，或先用 fixture 模式（blast_fixture=...）")
                if not reference_db:
                    raise RuntimeError("非 fixture 模式必须给 reference_db")
                log("Step 2: 对参考库做 blastn")
                cmd = [
                    blastn_bin, "-task", "blastn",
                    "-db", str(reference_db),
                    "-query", "for_blast.fa",
                    "-outfmt", "6 std qseq sseq slen",
                    "-word_size", "11",
                    "-num_threads", "3",
                    "-out", "blast_out.txt",
                ]
                r = _run(cmd, log)
                if r.returncode != 0:
                    log(r.stdout)
                    tail = "\n".join((r.stdout or "").splitlines()[-10:]) or "(no output captured)"
                    raise RuntimeError(
                        f"blastn 失败 (returncode={r.returncode}, db={reference_db})。"
                        f"最后 10 行输出：\n{tail}"
                    )

            # Step 3: getflanking
            log("Step 3: 解析 BLAST 结果，确定每个 marker 的 flanking 取范围")
            getflanking.flanking(polymarker_csv_in_workdir,
                                 "blast_out.txt",
                                 "temp_range.txt",
                                 int(ploidy))
            if Path("temp_range.txt").stat().st_size == 0:
                log("temp_range.txt 是空的；所有 SNP 都被过滤掉了。")
                with open("Potential_CAPS_primers.tsv", "w") as f:
                    f.write("All SNPs filtered out (no good BLAST hits).\n")
                with open("Potential_KASP_primers.tsv", "w") as f:
                    f.write("All SNPs filtered out (no good BLAST hits).\n")
                with open("All_alignment_raw.fa", "w") as f:
                    pass
                return {
                    "workdir": str(workdir),
                    "caps_dir": None,
                    "kasp_dir": None,
                }

            # Step 4: 把 temp_range.txt 拆成每个 marker 一个 temp_marker_*.txt
            log("Step 4: 按 marker 拆分 temp_range.txt 并取 flanking 序列")
            _split_temp_range("temp_range.txt")

            # Step 5: 用 blastdbcmd 取每个 marker 的 flanking 序列
            if not blastdbcmd_bin:
                raise RuntimeError("找不到 blastdbcmd，请提供 bin_dir")
            if not reference_db:
                raise RuntimeError("step 5 需要 reference_db 才能 blastdbcmd")
            # 预检查 -parse_seqids：blastdbcmd 必须靠 parse_seqids 建出来的索引
            # （.nos/.nog/.nsi 等）按 accession 取序列。如果用户建库时漏了
            # -parse_seqids，blastdbcmd 会报 "OID not found" 然后产出 0 字节文件，
            # 后面的 getkasp3 / getCAPS 会一路撞到莫名其妙的 KeyError。提前在这里
            # 拦截，给一句能动手的错误。
            _check_blastdb_has_parse_seqids(reference_db)
            for marker_file in sorted(glob("temp_marker_*.txt")):
                out_fa = "flanking_" + marker_file + ".fa"
                cmd = [blastdbcmd_bin,
                       "-entry_batch", marker_file,
                       "-db", str(reference_db),
                       "-out", out_fa]
                r = _run(cmd, log)
                # blastdbcmd 失败时（最常见：DB 没 -parse_seqids、accession 拼写不对）
                # 必须立刻抛错，否则下游会拿空的 flanking 去喂 muscle / primer3，
                # 在 getkasp3.py 里以 KeyError: '' 这种没头没尾的形式爆掉。
                if r.returncode != 0 or Path(out_fa).stat().st_size == 0:
                    out_log = (r.stdout or "").strip() or "(no output captured)"
                    raise RuntimeError(
                        f"blastdbcmd 取 flanking 失败 (returncode={r.returncode}, "
                        f"db={reference_db}, entry_batch={marker_file})。"
                        f"输出：\n{out_log}\n\n"
                        f"最常见原因：BLAST 库建的时候没加 -parse_seqids，"
                        f"blastdbcmd 没法按 accession (Chr7A 这种) 反查序列。"
                        f"修复：用 makeblastdb -in <fasta> -dbtype nucl -parse_seqids "
                        f"-out <prefix> 重建一次该库。"
                    )

        # Step 6: 跑 KASP / CAPS
        if design_kasp:
            log("Step 6a: 跑 KASP 引物设计")
            getkasp3.kasp_main()
        if design_caps:
            log("Step 6b: 跑 CAPS / dCAPS 引物设计")
            getCAPS.caps_main()

        # Step 7: 拼接输出
        log("Step 7: 拼接 Potential_*.tsv 与 All_alignment_raw.fa")
        if design_caps:
            _cat_files(sorted(glob("CAPS_output/selected_CAPS_primers*")),
                       "Potential_CAPS_primers.tsv")
        if design_kasp:
            _cat_files(sorted(glob("KASP_output/selected_KASP_primers*")),
                       "Potential_KASP_primers.tsv")
        # All_alignment_raw.fa：和上游一致，每个文件加文件名头
        align_files = sorted(glob("alignment_raw_*"))
        with open("All_alignment_raw.fa", "w", encoding="utf-8") as out:
            for f in align_files:
                out.write(f + "\n")
                with open(f, "r", encoding="utf-8") as inp:
                    out.write(inp.read())
                out.write("\n\n")

    finally:
        os.chdir(saved_cwd)

    return {
        "workdir": str(workdir),
        "caps_dir": str(workdir / "CAPS_output") if design_caps else None,
        "kasp_dir": str(workdir / "KASP_output") if design_kasp else None,
        "all_alignment_raw": str(workdir / "All_alignment_raw.fa"),
        "potential_caps": str(workdir / "Potential_CAPS_primers.tsv") if design_caps else None,
        "potential_kasp": str(workdir / "Potential_KASP_primers.tsv") if design_kasp else None,
    }


def _normalize_polymarker_input(src, dst):
    """复制输入到工作目录，顺手把首列行号去掉（如果有）。"""
    with open(src, "r", encoding="utf-8") as fin, \
         open(dst, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and "," in parts[1]:
                fout.write(parts[1] + "\n")
            else:
                fout.write(line + "\n")


def _split_temp_range(path):
    """复刻上游 step 4 的 awk：每个 marker 输出到 temp_marker_<query>.txt"""
    by_marker = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            fields = line.split("\t")
            # 字段顺序：query_with_pos, subject, start-end, strand
            query, subject, rng, strand = fields[0], fields[1], fields[2], fields[3]
            by_marker.setdefault(query, []).append(
                "\t".join([subject, rng, strand]))
    for query, lines in by_marker.items():
        with open("temp_marker_" + query + ".txt", "w", encoding="utf-8") as out:
            for ln in lines:
                out.write(ln + "\n")


def _cat_files(files, dest):
    with open(dest, "w", encoding="utf-8") as out:
        for f in files:
            with open(f, "r", encoding="utf-8") as inp:
                out.write(inp.read())
