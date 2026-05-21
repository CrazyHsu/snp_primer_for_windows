#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SNP 引物设计流程总调度。

对应上游 ``run_getkasp.py`` 的串联逻辑，但全部用 Python 3 + 函数调用，没有
``call(shell=True)`` 调子脚本。

入口： :func:`run`
"""

from __future__ import annotations

import hashlib
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
BLASTDB_PARSE_SEQID_SUFFIXES = (".nos", ".nog", ".nsi", ".nsd", ".nhd", ".nhi")


class PipelineCancelled(RuntimeError):
    """用户通过 GUI 的 Stop 按钮取消 pipeline 时抛出。

    定义在 core/pipeline.py 顶部（不在 online_blast.py），是因为 online_blast 在
    src/snp_primer_app/ 下；core/ 是更底层的层，让 online_blast 反向 import
    PipelineCancelled 才不会破坏 Layer A 测试的 standalone-importable 性质
    （CLAUDE.md §5）。
    """
BLASTDB_FILE_SUFFIXES = (
    ".nhr", ".nin", ".nsq", ".nog", ".nsd", ".nsi", ".nos",
    ".ndb", ".not", ".ntf", ".nto", ".nhd", ".nhi", ".nal",
)


# Windows 上每次 subprocess.call(shell=True) 都会弹一个 cmd.exe 黑窗，再加 .exe
# 自身（blastn/makeblastdb/primer3_core/muscle）也是 CUI 程序，从 Tk GUI 启动会
# 闪一下控制台。CREATE_NO_WINDOW 是 Windows 专有 flag，让子进程不创建可见 console。
# 非 Windows 平台 getattr 落到 0；_no_window_kwargs() 直接返回空 dict，subprocess
# 调用形态完全不变。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _no_window_kwargs():
    """构造 subprocess kwargs：Windows 不弹黑框。

    历史背景：以前这里还会传 ``env=os.environ.copy()`` 并把 ``_MEIPASS`` 从
    PATH 里剔掉。但 PyInstaller ``--onefile`` 下显式传 env= 会让 subprocess
    丢掉一些 PyInstaller bootloader 在 Windows native 层做的 DLL 搜索上下文，
    导致 makeblastdb 启动撞 0xC0000005。改成不传 env=，让子进程通过 Windows
    native 机制继承父进程 env，DLL 搜索行为更稳定。

    binaries 已经被 build_windows*.bat 放在 ``<exe_dir>/bin/`` （一个跟 PyInstaller
    ``_internal/`` / ``_MEIPASS`` 完全隔离的兄弟目录），makeblastdb 启动时 Windows
    DLL search 第一步就找到 ``<exe_dir>/bin/`` 里的 nghttp2.dll / ncbi-vdb-md.dll，
    不会再去 PATH 找。VC runtime 走 System32（用户机上的 VC++ Redist），不依赖
    PyInstaller 自带的 MSVCP140。
    """
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = _CREATE_NO_WINDOW
    return kw


def _make_patched_call(bin_dir):
    """生成 ``subprocess.call`` 的 wrapper，做三件事：

    1. Windows 上自动加 ``creationflags=CREATE_NO_WINDOW``，子进程不弹黑框
    2. 把 ``bin_dir`` 前置到 ``PATH``。这是 getkasp3.primer_blast / getCAPS 类似
       函数的关键——它们 build 命令时用的是裸 ``blastn`` (line 263 of getkasp3.py)
       而不是完整 .exe 路径，依赖 shell 能从 PATH 找到。Windows 上
       ``snp_primer_runtime\\bin\\`` 不在系统 PATH，必须显式注入，否则 shell
       找不到 blastn → 产物文件不生成 → ``open(outfile_blast)`` 抛 FileNotFoundError。
    3. PyInstaller frozen 模式下从继承 PATH 里剔掉 ``_internal/`` / ``_MEIPASS``，
       理由同 ``_no_window_kwargs``。

    getCAPS.py / getkasp3.py 是上游 commit 的 byte-for-byte 移植，不能改源码。
    它们顶部 ``from subprocess import call`` 把名字绑死了；这里在 import 之后把
    它们模块属性的 ``call`` 重新指向本 wrapper，所有后续 ``call(...)`` 调用都会
    走这条路径。
    """
    def _patched(*args, **kwargs):
        if sys.platform == "win32" and "creationflags" not in kwargs:
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        # 只有需要给 shell 注入 bin_dir 时才显式传 env；否则让子进程走 native
        # 继承（理由同 _no_window_kwargs 的注释）。
        if bin_dir and "env" not in kwargs:
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            kwargs["env"] = env
        return subprocess.call(*args, **kwargs)
    return _patched


# 在 pipeline 模块 import 时一次性 patch；后续 import 顺序变了也无所谓，因为
# 只有 pipeline.run() 会触发 getCAPS.caps_main / getkasp3.kasp_main，而进入
# pipeline 之前这里已经执行过了。bin_dir 暂时为 None；run() 会用真正的 bin_dir
# 重新 patch 一次（见 _install_call_patch_with_bin_dir）。
_patched_call = _make_patched_call(None)
getCAPS.call = _patched_call
getkasp3.call = _patched_call


def _install_call_patch_with_bin_dir(bin_dir):
    """run() 解析出 bin_dir 后调一次：把 getCAPS / getkasp3 的 call 重绑成带
    PATH 注入的 wrapper。"""
    patched = _make_patched_call(bin_dir)
    getCAPS.call = patched
    getkasp3.call = patched


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


def _blastdb_volume_prefixes(db_prefix):
    """如果 db_prefix 是多卷库，返回每个 volume 的 prefix list；否则返回 []。

    优先级：
    1. ``<db_prefix>.nal`` 存在 → 读 DBLIST，按空格 split。相对路径相对 .nal
       所在目录解析。BLAST 自己也是按空格 split DBLIST（见 §6.7），所以这里
       不用处理 quote。
    2. parent-scan 找 ``<stem>.<NN>.nhr``（NN 是 ≥2 位数字，与
       ``_ensure_blastdb_alias_for_volumes`` 一致）。

    任何 I/O / 解析错误都返回 []，让上层走原 prefix-only 路径并最终给出已有的
    错误信息。
    """
    db_prefix = os.fspath(db_prefix)
    nal_path = db_prefix + ".nal"
    if os.path.isfile(nal_path):
        try:
            nal_dir = Path(nal_path).parent
            with open(nal_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    parts = stripped.split()
                    if not parts or parts[0].upper() != "DBLIST":
                        continue
                    volumes = []
                    for part in parts[1:]:
                        vp = Path(part)
                        if not vp.is_absolute():
                            vp = nal_dir / vp
                        volumes.append(str(vp))
                    if volumes:
                        return volumes
        except OSError:
            pass
    parent = Path(db_prefix).parent
    stem = Path(db_prefix).name
    if parent.is_dir() and stem:
        pattern = re.compile(re.escape(stem) + r"\.(\d{2,})$")
        scanned = sorted({
            str(parent / f.stem) for f in parent.glob(stem + ".*.nhr")
            if pattern.match(f.stem)
        })
        if scanned:
            return scanned
    return []


def _blastdb_has_parse_seqids(db_prefix):
    """库是否用 -parse_seqids 建过。

    单卷库：prefix 上直接出现 ``.nos/.nog/.nsi/.nsd/.nhd/.nhi`` 任一即通过。
    多卷库（``.nal`` alias，或 ``<stem>.NN.nhr`` 这种切片）：**每个 volume**
    都要有自己的 parse_seqids 索引文件。要求 *all* 而不是 *any*——blastdbcmd
    的 OID 空间跨所有 volume，哪怕一个 volume 缺索引，落在那里的 accession
    都反查不出来；``makeblastdb -parse_seqids`` 实际产出也是要么都有要么都没
    有，all 是正确口径。
    """
    db_prefix = os.fspath(db_prefix)
    if any(os.path.isfile(db_prefix + suf) for suf in BLASTDB_PARSE_SEQID_SUFFIXES):
        return True
    volume_prefixes = _blastdb_volume_prefixes(db_prefix)
    if not volume_prefixes:
        return False
    return all(
        any(os.path.isfile(vp + suf) for suf in BLASTDB_PARSE_SEQID_SUFFIXES)
        for vp in volume_prefixes
    )


def _check_blastdb_has_parse_seqids(db_prefix):
    """检查 BLAST DB 是不是用 -parse_seqids 建过；否则抛带修复指引的错误。

    没用 -parse_seqids 建的库只有 ``.nhr/.nin/.nsq``（外加新版 BLAST+ 的
    ``.ndb/.not/.ntf/.nto``）。要让 blastdbcmd 能按 accession 反查，必须有
    accession→OID 的索引文件——老版叫 ``.nsi``/``.nsd``/``.nog``，新版统一在
    ``.nos`` 里。

    多卷库（用户给的是带 .nal alias 的 prefix，或 makeblastdb 自动切片后的
    多卷库）这些索引文件在 ``<stem>.NN.nog/.nsd/.nsi`` 上而不是 prefix 上；
    见 ``_blastdb_has_parse_seqids`` / ``_blastdb_volume_prefixes``。

    db_prefix 可能是绝对路径（比如经过 _blast_safe_db_path() junction 之后的
    路径），也可能是带空格短名。
    """
    if _blastdb_has_parse_seqids(db_prefix):
        return
    db_prefix = os.fspath(db_prefix)
    base_dir = os.path.dirname(db_prefix) or "."
    base_name = os.path.basename(db_prefix)
    raise RuntimeError(
        f"BLAST 库 {db_prefix} 看起来不是用 -parse_seqids 建的（没找到 "
        f".nos/.nog/.nsi/.nsd 任意一种 accession 索引文件）。\n\n"
        f"多卷库（每个 volume 一个 .nhr）的索引在 <stem>.NN.nog/.nsd/.nsi 上而\n"
        f"不是 prefix 上；如果每个 volume 都缺，说明 makeblastdb 没带 -parse_seqids。\n\n"
        f"blastdbcmd 必须靠这些索引按染色体名（如 Chr7A）反查序列；缺了它\n"
        f"流程会卡在 Step 5 之后产出空文件，再到 getkasp3 里抛 KeyError。\n\n"
        f"修复：到 {base_dir} 下，用原始 FASTA 重建一次：\n"
        f"  makeblastdb -in <你的染色体fasta> -dbtype nucl -parse_seqids -out {base_name}\n"
        f"重建完保留同样的前缀（{base_name}），GUI 不用改设置直接重跑。"
    )


def _blastdb_has_core_files(db_prefix):
    db_prefix = os.fspath(db_prefix)
    old_style = all(os.path.isfile(db_prefix + suf) for suf in (".nhr", ".nin", ".nsq"))
    new_style = any(os.path.isfile(db_prefix + suf) for suf in (".ndb", ".nal"))
    return old_style or new_style


def _ensure_blastdb_alias_for_volumes(db_prefix, workdir, log):
    """如果 db_prefix 是多卷库 prefix 但缺 .nal alias，自动在 workdir 下生成一个。

    背景：``makeblastdb`` 在输入 FASTA 超过 ``-max_file_sz`` 时会自动切片成
    ``<prefix>.00.{nhr,nin,nsq,...}`` / ``<prefix>.01.{...}`` 等 volume，正常情况下
    顺手生成 ``<prefix>.nal`` alias。但如果库是手动 / 旧版本工具建的，可能漏了 .nal——
    此时 ``blastn -db <prefix>`` 会撞 "No alias or index file found"。

    触发条件（按顺序）：

    1. ``<prefix>.nhr`` 或 ``<prefix>.nal`` 任一存在 → 单卷库或已有 alias，原样返回
    2. 扫描 parent，找形如 ``<stem>.<NN>.nhr`` 的 volume（NN 是 2+ 位数字）
    3. 有 ≥1 个 volume → 写 ``<workdir>/blastdb_alias/<stem>.nal``，DBLIST 用
       volume 的绝对路径前缀，返回 ``<workdir>/blastdb_alias/<stem>`` 作为新 prefix
    4. 没有 volume → 原样返回，让 blastn 自己报 "No alias or index file" 错误

    DBLIST 里 volume 路径不能含空格（BLAST 内部按空格 split DBLIST，见 §6.7）。
    含空格时抛 RuntimeError 提示用户挪 DB / 自己 mklink junction。中文 / dot /
    其他 unicode 字符 BLAST 处理 OK，不在此处过滤。

    不写用户 DB 目录（可能只读 / NAS / 共享盘）；alias 完全 workdir-local，每次
    跑都会被新建覆盖。
    """
    db_prefix = os.fspath(db_prefix)
    if _blastdb_has_core_files(db_prefix):
        return db_prefix
    parent = Path(db_prefix).parent
    stem = Path(db_prefix).name
    if not parent.is_dir() or not stem:
        return db_prefix
    pattern = re.compile(re.escape(stem) + r"\.(\d{2,})$")
    volume_stems = sorted({
        f.stem for f in parent.glob(stem + ".*.nhr")
        if pattern.match(f.stem)
    })
    if not volume_stems:
        return db_prefix
    # 校验每个 volume 都有完整的 .nhr/.nin/.nsq；不完整的剔掉
    volume_stems = [
        vol for vol in volume_stems
        if _blastdb_has_core_files(str(parent / vol))
    ]
    if not volume_stems:
        return db_prefix
    abs_volumes = [str((parent / vol).resolve()) for vol in volume_stems]
    spacey = [p for p in abs_volumes if " " in p]
    if spacey:
        raise RuntimeError(
            f"多卷 BLAST 库 prefix {db_prefix} 缺 .nal alias；自动生成 alias 时\n"
            f"发现 volume 绝对路径含空格（BLAST DBLIST 内部按空格 split，无法 quote）：\n"
            + "\n".join(f"  {p}" for p in spacey) + "\n\n"
            f"请把整个 {parent} 目录挪到无空格路径下，或手动 mklink /J 一个无空格的 junction 后重试。"
        )
    alias_dir = Path(workdir) / "blastdb_alias"
    alias_dir.mkdir(parents=True, exist_ok=True)
    nal_path = alias_dir / (stem + ".nal")
    nal_text = (
        "#\n"
        "# Alias file auto-generated by snp_primer_app v11\n"
        f"# Source DB lacked a .nal; volumes auto-collected from {parent}\n"
        "#\n"
        f"TITLE {stem}\n"
        f"DBLIST {' '.join(abs_volumes)}\n"
    )
    nal_path.write_text(nal_text, encoding="ascii")
    log(f"已为多卷 BLAST 库生成 alias：{nal_path}（{len(abs_volumes)} 个 volume）")
    return str(alias_dir / stem)


def _cleanup_stale_run_artifacts(workdir):
    """删上一次 run 留在 workdir 的 alignment_raw_*.fa / All_alignment_raw.fa。

    getkasp3.kasp() (line 482-488) 和 getCAPS.caps() (line 646-652) 都有
    "alignment_raw_<snp>.fa 存在 + 非空就跳过 muscle" 的优化。但
    ``get_fasta2`` 是按 *当前* flanking 文件的 hit 顺序给 sequence_name 加
    ``-0/-1/...`` 后缀的，所以上次 run 的 alignment 字典 keys 跟这次 target
    名字会对不上 → ``fasta[target]`` 抛 KeyError，详见 §6.15。

    fixture 模式（``alignment_files=...``）在 ``run()`` 里下一步才把外部 alignment
    文件拷进 workdir，所以这里无脑删不会破坏 fixture。

    只动 alignment_raw_*.fa 和 All_alignment_raw.fa——其它 step 的中间文件
    （temp_range / temp_marker / flanking / renamed / blast_out / primer3
    output）每次都被写覆盖或者没有 skip-if-exists 复用，不会触发同类 bug。
    """
    if not workdir:
        return
    workdir = Path(workdir)
    if not workdir.is_dir():
        return
    for stale in workdir.glob("alignment_raw_*.fa"):
        try:
            stale.unlink()
        except OSError:
            pass
    all_align = workdir / "All_alignment_raw.fa"
    if all_align.is_file():
        try:
            all_align.unlink()
        except OSError:
            pass


def _first_fasta_seqid(fasta_path):
    try:
        with open(fasta_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(">"):
                    return line[1:].strip().split()[0]
    except OSError:
        return None
    return None


def _candidate_db_prefixes_for_fasta(fasta_path):
    fasta_path = Path(fasta_path)
    candidates = []

    def add(candidate):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(fasta_path.with_suffix(""))
    add(fasta_path.parent / (fasta_path.stem + ".blast_db"))

    seqid = _first_fasta_seqid(fasta_path)
    seqid_variants = []
    if seqid:
        seqid_variants.append(seqid)
        seqid_variants.append(seqid[:1].upper() + seqid[1:])
        if seqid.lower().startswith("chr"):
            seqid_variants.append("Chr" + seqid[3:])
            seqid_variants.append("chr" + seqid[3:])
    for name in seqid_variants:
        add(fasta_path.parent / name)

    m = re.search(r"(chr[0-9A-Za-z]+)", fasta_path.stem, re.IGNORECASE)
    if m:
        chrom = m.group(1)
        add(fasta_path.parent / chrom)
        add(fasta_path.parent / (chrom[:1].upper() + chrom[1:]))
        if chrom.lower().startswith("chr"):
            add(fasta_path.parent / ("Chr" + chrom[3:]))

    return candidates


def _find_existing_parse_seqids_db_for_fasta(fasta_path, log):
    for prefix in _candidate_db_prefixes_for_fasta(fasta_path):
        if not _blastdb_has_core_files(prefix):
            continue
        if _blastdb_has_parse_seqids(prefix):
            log(f"发现 Reference FASTA 旁已有 -parse_seqids BLAST 库：{prefix}")
            return Path(prefix)
        log(f"跳过已有 BLAST 库 {prefix}：缺少 -parse_seqids 索引文件。")
    return None


def _mirror_blastdb_to_prefix(source_prefix, dest_prefix, log):
    source_prefix = Path(source_prefix)
    dest_prefix = Path(dest_prefix)
    dest_prefix.parent.mkdir(parents=True, exist_ok=True)
    copied = 0
    linked = 0
    for suffix in BLASTDB_FILE_SUFFIXES:
        src = Path(str(source_prefix) + suffix)
        if not src.is_file():
            continue
        dst = Path(str(dest_prefix) + suffix)
        try:
            if dst.exists():
                dst_stat = dst.stat()
                src_stat = src.stat()
                if (
                    dst_stat.st_size == src_stat.st_size
                    and dst_stat.st_mtime >= src_stat.st_mtime
                ):
                    continue
                dst.unlink()
            os.link(src, dst)
            linked += 1
        except OSError:
            shutil.copy2(src, dst)
            copied += 1
    if not _blastdb_has_core_files(dest_prefix):
        raise RuntimeError(f"镜像已有 BLAST 库失败，目标缺少核心索引文件：{dest_prefix}")
    _check_blastdb_has_parse_seqids(dest_prefix)
    log(f"已把已有 BLAST 库镜像到 {dest_prefix}（hardlink={linked}, copy={copied}）。")
    return str(dest_prefix)


def _is_ascii_no_whitespace_path(p):
    text = os.fspath(p)
    try:
        text.encode("ascii")
    except UnicodeEncodeError:
        return False
    return not any(ch.isspace() for ch in text)


def _safe_stage_suffix(path):
    suffix = Path(path).suffix.lower()
    if suffix and suffix.encode("ascii", errors="ignore").decode("ascii") == suffix:
        if not any(ch.isspace() for ch in suffix) and len(suffix) <= 12:
            return suffix
    return ".fa"


def _stage_fasta_for_makeblastdb(fasta_path, auto_db_dir, log):
    """Return a makeblastdb-safe FASTA path, staging only when needed.

    NCBI Windows binaries can crash before printing stderr when they receive
    paths containing non-ASCII characters or spaces. The BLAST DB prefix is
    already under the workspace; this helper makes the ``-in`` FASTA path just
    as boring while keeping the GUI's Reference FASTA workflow intact.
    """
    if _is_ascii_no_whitespace_path(fasta_path):
        return fasta_path

    stage_dir = Path(auto_db_dir) / "_fasta_stage"
    if not _is_ascii_no_whitespace_path(stage_dir):
        raise RuntimeError(
            "Reference FASTA 路径包含中文或空格，需要先暂存到工作目录再运行 makeblastdb；\n"
            f"但当前暂存目录也不是纯 ASCII 且无空格：{stage_dir}\n"
            "请把 Working dir 改到一个纯英文、无空格路径后重试。"
        )

    stage_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(str(fasta_path).encode("utf-8")).hexdigest()[:12]
    staged = stage_dir / f"reference_{digest}{_safe_stage_suffix(fasta_path)}"

    source_stat = Path(fasta_path).stat()
    if staged.exists():
        try:
            staged_stat = staged.stat()
            if (
                staged_stat.st_size == source_stat.st_size
                and staged_stat.st_mtime >= source_stat.st_mtime
            ):
                log(f"Reference FASTA 已暂存：{staged}")
                return staged
            staged.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"无法更新 Reference FASTA 暂存文件：{staged}\n{exc}"
            ) from exc

    try:
        os.link(fasta_path, staged)
        method = "hardlink"
    except OSError:
        shutil.copy2(fasta_path, staged)
        method = "copy"
    log(
        "Reference FASTA 路径含中文或空格，已"
        f"通过 {method} 暂存到 {staged}，makeblastdb 将使用该暂存路径。"
    )
    return staged


def _ensure_blastdb_from_fasta(fasta_path, workdir, bin_dir, log, *, cache_root=None):
    """给 raw FASTA 自动建 BLAST 库，返回 prefix。

    缓存位置：
    - ``cache_root`` 指定时（GUI 路径）：库放在
      ``<cache_root>/auto_blastdb/<fasta_stem>__<sha256[:8]>/<fasta_stem>``，
      跨 run 共享（v14 §6.23）。GUI 把 ``working_dir_var``（workspace 根）
      传进来，多次 Run Pipeline 不再重建索引。
    - ``cache_root`` 未指定（Layer A 测试 / 直接 API 调用）：fall back 到
      ``<workdir>/auto_blastdb/<fasta_stem>__<sha256[:8]>/<fasta_stem>``，行为
      与单次 run 等价。

    ``<stem>__<sha256[:8]>`` 子目录用绝对路径 sha256 前 8 hex 做后缀，防止两
    个 basename 相同、内容不同的 FASTA 在共享缓存里互相覆盖。

    workdir / cache_root 由 GUI 保证是无空格 ASCII 路径，绕过 §6.7 "BLAST
    路径按空格 split"。

    缓存命中：如果 ``<prefix>.nhr`` 已经存在且 mtime ≥ FASTA 的 mtime，跳过
    rebuild。建库本身要走 ``-parse_seqids``，否则后面 blastdbcmd 还是反查不出
    来，等于没建。
    """
    fasta_path = Path(fasta_path).resolve()
    if not fasta_path.is_file():
        raise RuntimeError(f"reference_fasta 找不到文件：{fasta_path}")
    auto_db_dir_base = (
        Path(cache_root) / "auto_blastdb"
        if cache_root is not None
        else Path(workdir) / "auto_blastdb"
    )
    digest = hashlib.sha256(str(fasta_path).encode("utf-8")).hexdigest()[:8]
    auto_db_dir = auto_db_dir_base / f"{fasta_path.stem}__{digest}"
    auto_db_dir.mkdir(parents=True, exist_ok=True)
    db_prefix = auto_db_dir / fasta_path.stem
    nhr = Path(str(db_prefix) + ".nhr")
    if nhr.is_file() and nhr.stat().st_mtime >= fasta_path.stat().st_mtime:
        log(f"已存在 BLAST 库 {db_prefix}（mtime ≥ FASTA），跳过 makeblastdb。")
        return str(db_prefix)
    existing_db = _find_existing_parse_seqids_db_for_fasta(fasta_path, log)
    if existing_db:
        return _mirror_blastdb_to_prefix(existing_db, db_prefix, log)
    makeblastdb_fasta = _stage_fasta_for_makeblastdb(fasta_path, auto_db_dir, log)
    makeblastdb_bin = _which("makeblastdb", [bin_dir])
    if not makeblastdb_bin:
        raise RuntimeError(
            "找不到 makeblastdb 二进制。请检查 snp_primer_runtime/bin/ 目录\n"
            "（或重跑 windows/Launch SNP Primer Desktop.cmd 走一次 bootstrap，\n"
            "它会下载 makeblastdb.exe 到 bin/）。"
        )
    log(f"Step 0: 用 makeblastdb 自动从 {fasta_path} 建索引到 {db_prefix}")
    cmd = [makeblastdb_bin,
           "-in", str(makeblastdb_fasta),
           "-dbtype", "nucl",
           "-parse_seqids",
           "-out", str(db_prefix)]
    r = _run(cmd, log)
    if r.returncode != 0 or not nhr.is_file():
        out_log = (r.stdout or "").strip() or "(no output captured)"
        access_violation_hint = ""
        if r.returncode in (3221225477, -1073741819):
            access_violation_hint = (
                "\n\n检测到 Windows 访问冲突 0xC0000005。常见触发原因是 "
                "NCBI makeblastdb 在 PyInstaller/Windows 环境下处理中文、空格路径或 "
                "DLL runtime 时直接崩溃。"
            )
        raise RuntimeError(
            f"makeblastdb 失败 (returncode={r.returncode}, fasta={fasta_path})。\n"
            f"makeblastdb 实际 -in：{makeblastdb_fasta}\n"
            f"输出：\n{out_log}\n\n"
            f"常见原因：FASTA 不是 nucl / 文件已损坏 / 路径含特殊字符。"
            f"{access_violation_hint}"
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
        blast_mode="local",
        remote_provider=None,
        remote_database=None,
        remote_fetch_database=None,
        remote_email=None,
        cancel_event=None,
        species_key="wheat",  # v13: 用户选的物种 key，详见 v13 CLAUDE.md §6.22
        # v14 §6.23: workspace 根目录，用来跨 run 共享 auto_blastdb 缓存。
        # GUI 传 `working_dir_var`（不动的 workspace 根），让多次 Run Pipeline
        # 复用同一份 makeblastdb 索引。None 时 fall back 到 <workdir>/auto_blastdb，
        # Layer A 测试 / 直接 API 调用走该路径，行为与单次 run 等价。
        cache_root=None,
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
    blast_mode : str
        ``"local"`` (default) → 跑 blastn + blastdbcmd（v9 行为完全等价）。
        ``"ncbi_online"`` → 通过 ``snp_primer_app.online_blast.run_ncbi_blast``
        提交到 NCBI BLAST API；flanking 用 efetch 取。要求 ``remote_database``。
        ``"provider_online"`` + ``remote_provider="ebi"`` → 通过
        ``run_ebi_blast`` 提交到 EBI；flanking 用 dbfetch 取（需 ``remote_email``）。
        online 模式下 ``reference_db`` / ``reference_fasta`` 会被忽略。
        **ncbi_online 模式会自动在 NCBI 端加 ENTREZ_QUERY=txid4565[ORGN]
        小麦物种过滤**（pipeline 整体为小麦专用，详见 v12 CLAUDE.md §6.21）。
    remote_provider, remote_database, remote_fetch_database, remote_email : str | None
        online 模式参数。``remote_database`` 是 NCBI/EBI 上的库名（``core_nt`` /
        ``refseq_genomes`` / ``em_rel``...）。``remote_fetch_database`` 仅 EBI
        dbfetch 用（默认 ``ena_sequence``）。``remote_email`` NCBI 强烈建议、EBI 必填。
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

    # v13: resolve species 单次后到处用。"wheat" 默认 → pre-v13 byte-equiv。
    from core.species import get_species
    species = get_species(species_key)
    log(f"物种：{species.display_name} (taxid={species.taxid})")

    bin_dir_str = str(Path(bin_dir).resolve()) if bin_dir else None
    # 把 bin_dir 注入到 getCAPS / getkasp3 那条 subprocess.call 链路的 PATH 上，
    # 它们 build 命令时用裸 ``blastn`` 而不是完整 .exe 路径（getkasp3.py:263）。
    _install_call_patch_with_bin_dir(bin_dir_str)

    # 模式校验：online 模式直接忽略 reference_db / reference_fasta（GUI 不应该
    # 同时给，但兜底用），下面 Step 2 / Step 5 走 online 分支不需要本地库。
    _is_online = blast_mode in ("ncbi_online", "provider_online")
    if _is_online:
        if reference_fasta or reference_db:
            log(f"在线 BLAST 模式（{blast_mode}）下忽略给定的 reference_db / reference_fasta")
            reference_fasta = None
            reference_db = None
        if not remote_database:
            raise ValueError(
                f"在线 BLAST 模式 {blast_mode!r} 必须提供 remote_database（NCBI/EBI 库名）。"
            )
        if blast_mode == "provider_online":
            if (remote_provider or "").lower() != "ebi":
                raise ValueError(
                    f"provider_online 目前只支持 remote_provider='ebi'，收到 {remote_provider!r}"
                )
            if not remote_email:
                raise ValueError("EBI BLAST 必须填写 remote_email。")
    elif blast_mode != "local":
        raise ValueError(f"未知 blast_mode: {blast_mode!r}（应为 local / ncbi_online / provider_online）")

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
            reference_fasta, workdir, bin_dir_str, log,
            cache_root=cache_root,
        )
    if reference_db:
        reference_db = str(Path(reference_db).resolve())
        # v11: 多卷库（makeblastdb 自动切片成 .00 / .01 / …）但缺 .nal alias 时，
        # 自动在 workdir/blastdb_alias 下合成一个，把 reference_db 指向那里。
        # 单卷库 / 已有 alias 的库会原样返回，行为不变。详见 §6.13。
        reference_db = _ensure_blastdb_alias_for_volumes(
            reference_db, workdir, log)
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

    # 协作式取消检查（GUI Stop 按钮设 cancel_event；step 边界抽查）。
    def _check_cancel(label: str) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise PipelineCancelled(f"用户在 {label} 阶段终止了 pipeline")

    # 切到工作目录工作（上游所有脚本都用相对路径 / cwd）
    saved_cwd = Path.cwd()
    try:
        os.chdir(workdir)

        # v11 第三轮补丁：清掉上一次 run 留在 workdir 的 alignment_raw_*.fa /
        # All_alignment_raw.fa。getkasp3 / getCAPS 看到 alignment_raw 存在就跳
        # muscle，但 sequence_name 是按 *当前* flanking 的 hit 顺序加 -0/-1/...
        # 后缀的，上次 run 的 hit 数不一样就会 KeyError（详见 §6.15）。fixture
        # 模式的 alignment_files 在下面才拷入，sweep 不会破坏 fixture。
        _cleanup_stale_run_artifacts(workdir)

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
            _check_cancel("Step 1")
            log("Step 1: 解析 polymarker 输入 -> for_blast.fa")
            parse_polymarker_input.parse(polymarker_csv_in_workdir,
                                         "for_blast.fa")

            # Step 2: blastn (or fixture / online)
            _check_cancel("Step 2")
            if blast_fixture:
                log(f"Step 2: 复用 fixture BLAST 输出 {blast_fixture}")
                src_b = blast_fixture
                if not os.path.isabs(src_b):
                    src_b = str(saved_cwd / src_b)
                shutil.copyfile(src_b, "blast_out.txt")
            elif _is_online:
                # v10 online 分支：HTTP 提交到 NCBI / EBI，把 15 列 blastn -outfmt 6
                # 输出写到 blast_out.txt。subject_id 会被前缀为 "chr{XY}_" 以满足
                # 下游 getflanking.flanking 的 ABD 过滤规则；Step 5 反解前缀拿原始
                # accession 调 efetch / dbfetch。
                from snp_primer_app.online_blast import (
                    run_ncbi_blast,
                    run_ebi_blast,
                    render_alignment_table,
                    render_alignment_table_with_chrom_prefix,
                )
                query_fasta = Path("for_blast.fa").read_text(encoding="utf-8")
                log(f"Step 2: 在线 BLAST 模式={blast_mode} db={remote_database}")
                if blast_mode == "ncbi_online":
                    # v14: raw_output_path 让在线 NCBI BLAST 把 JSON 响应逐字节
                    # 写到 ncbi_blast_raw.json，再从该文件回读喂 parser；保证
                    # "下载的文件 = 下游分析输入"在 IO 层面成立，方便用户直接
                    # diff 这个文件跟 NCBI 网页下载的 JSON。详见 v14 §6.23。
                    alignments = run_ncbi_blast(
                        query_fasta,
                        remote_database,
                        logger=log,
                        email=remote_email,
                        cancel_event=cancel_event,
                        # v13: species 驱动 ENTREZ_QUERY（小麦 txid4565[ORGN] / 大麦
                        # txid4513[ORGN] / ...）。详见 v13 CLAUDE.md §6.22。
                        entrez_query=species.entrez_query,
                        raw_output_path=Path("ncbi_blast_raw.json"),
                    )
                else:  # provider_online → EBI（已在校验阶段限定）
                    alignments = run_ebi_blast(
                        query_fasta,
                        remote_database,
                        email=remote_email or "",
                        logger=log,
                        cancel_event=cancel_event,
                    )
                # v14: 在按染色体正则过滤之前，把全部 hit 落盘成 15 列 TSV，方便
                # 用户回溯"为什么这条 hit 被 drop"——格式与 blast_out.txt 一致，可
                # 直接 diff 前后两表。
                all_hits_table = render_alignment_table(alignments)
                Path("ncbi_blast_all_hits.tsv").write_text(
                    all_hits_table, encoding="utf-8"
                )
                log(
                    f"Step 2: 写入 {len(all_hits_table.splitlines())} 行 "
                    f"ncbi_blast_all_hits.tsv（pre-filter audit table）"
                )
                # v13: 把 species 喂给 chr-prefix render，让染色体正则按物种走
                table = render_alignment_table_with_chrom_prefix(
                    alignments, logger=log, species=species
                )
                Path("blast_out.txt").write_text(table, encoding="utf-8")
                log(f"Step 2 完成：写入 {len(table.splitlines())} 行 blast_out.txt")
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
            _check_cancel("Step 3")
            log("Step 3: 解析 BLAST 结果，确定每个 marker 的 flanking 取范围")
            getflanking.flanking(polymarker_csv_in_workdir,
                                 "blast_out.txt",
                                 "temp_range.txt",
                                 int(ploidy),
                                 species=species)  # v13
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
            _check_cancel("Step 4")
            log("Step 4: 按 marker 拆分 temp_range.txt 并取 flanking 序列")
            _split_temp_range("temp_range.txt")

            # Step 5: 用 blastdbcmd（local）或 efetch/dbfetch（online）取 flanking
            _check_cancel("Step 5")
            if _is_online:
                from snp_primer_app.online_blast import (
                    split_chrom_prefixed_subject,
                    fetch_ncbi_sequence_for_range,
                    fetch_ebi_sequence_for_range,
                )
                log("Step 5: 在线模式，按 temp_marker_*.txt 调 efetch / dbfetch 取 flanking")
                for marker_file in sorted(glob("temp_marker_*.txt")):
                    out_fa = "flanking_" + marker_file + ".fa"
                    chunks: list[str] = []
                    with open(marker_file, "r", encoding="utf-8") as fin:
                        for line in fin:
                            line = line.rstrip("\n")
                            if not line:
                                continue
                            subject, rng, strand = line.split("\t")
                            start_s, end_s = rng.split("-")
                            start, end = int(start_s), int(end_s)
                            # subject 形如 "chr7A_NC_057814.1"。拆出 ("7A", "NC_057814.1")。
                            chrom_short, accession = split_chrom_prefixed_subject(subject)
                            if chrom_short is None:
                                # 不该发生：getflanking 已经按 chr 前缀过滤过
                                log(f"WARN: {marker_file} 行 {line!r} 没有 chr 前缀；跳过")
                                continue
                            _check_cancel("Step 5 fetch")
                            try:
                                if blast_mode == "ncbi_online":
                                    chunk = fetch_ncbi_sequence_for_range(
                                        accession, start, end, strand,
                                        header_id=subject,  # 保留 chr 前缀让下游 getCAPS 匹配
                                        email=remote_email,
                                        logger=log,
                                        cancel_event=cancel_event,
                                    )
                                else:
                                    chunk = fetch_ebi_sequence_for_range(
                                        accession, start, end, strand,
                                        fetch_database=(remote_fetch_database or "ena_sequence"),
                                        header_id=subject,
                                        logger=log,
                                        cancel_event=cancel_event,
                                    )
                            except Exception as exc:  # noqa: BLE001
                                raise RuntimeError(
                                    f"在线取 flanking 失败 (mode={blast_mode}, "
                                    f"accession={accession}, range={start}-{end}, "
                                    f"strand={strand})：{exc}"
                                ) from exc
                            chunks.append(chunk)
                    Path(out_fa).write_text("".join(chunks), encoding="utf-8")
                    if Path(out_fa).stat().st_size == 0:
                        raise RuntimeError(
                            f"在线取 flanking 后 {out_fa} 仍为空——"
                            f"可能 NCBI/EBI 没返回任何可用序列。"
                        )
            else:
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
            _check_cancel("Step 6a")
            log("Step 6a: 跑 KASP 引物设计")
            getkasp3.kasp_main()
        if design_caps:
            _check_cancel("Step 6b")
            log("Step 6b: 跑 CAPS / dCAPS 引物设计")
            getCAPS.caps_main()

        # Step 7: 拼接输出
        _check_cancel("Step 7")
        log("Step 7: 拼接 Potential_*.tsv 与 All_alignment_raw.fa")
        if design_caps:
            _cat_files(sorted(glob("CAPS_output/selected_CAPS_primers*")),
                       "Potential_CAPS_primers.tsv")
        if design_kasp:
            _cat_files(sorted(glob("KASP_output/selected_KASP_primers*")),
                       "Potential_KASP_primers.tsv")
            # Post-process：给 KASP 输出表末尾追加 target_chromosome 列。
            # getkasp3.py 是 byte-for-byte 上游移植不能动；这里是后置增强，
            # 不动 index / 前 16 列，所以 compare_outputs.py 严格比较仍 byte-for-byte
            # 通过 wheatomics。flanking_files fixture 模式没有 polymarker_input.csv，
            # 这一步会 silently skip。
            marker_to_chrom = _read_marker_to_chrom("polymarker_input.csv")
            if marker_to_chrom:
                _add_target_chromosome_column("Potential_KASP_primers.tsv",
                                              marker_to_chrom)
                for sf in glob("KASP_output/selected_KASP_primers_*.txt"):
                    _add_target_chromosome_column(sf, marker_to_chrom)
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


def _read_marker_to_chrom(polymarker_csv_path):
    """从 polymarker_input.csv 读 ``marker→chromosome`` 映射。

    输入行格式：``IWB50236,7A,cctcc...[A/G]CTTGG...``
    返回 ``{"IWB50236": "7A", ...}``。
    """
    mapping = {}
    p = Path(polymarker_csv_path)
    if not p.is_file():
        return mapping
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",", 2)
            if len(parts) >= 2 and parts[0]:
                mapping[parts[0]] = parts[1]
    return mapping


def _add_target_chromosome_column(tsv_path, marker_to_chrom):
    """给 KASP 输出文件末尾追加 ``target_chromosome`` 列。

    覆盖：``Potential_KASP_primers.tsv`` 与
    ``KASP_output/selected_KASP_primers_<MARKER>.txt``。

    安全性：
    - 如果 header 行已经包含 ``target_chromosome`` 列（重跑场景）→ 直接 skip，
      不重复追加
    - 数据行：从 ``index`` 列首段（marker name，例如 ``IWB50236-right-0-A`` →
      ``IWB50236``）查 chromosome；查不到留空
    - 非数据行（空行 / "Sites that can differ all" 这种 footer）原样透传
    """
    p = Path(tsv_path)
    if not p.is_file():
        return
    with open(p, "r", encoding="utf-8") as f:
        original = f.readlines()
    # 已经处理过就跳过，幂等
    for line in original:
        if line.startswith("index\t") and "target_chromosome" in line:
            return
    new_lines = []
    for line in original:
        stripped = line.rstrip("\n")
        if not stripped:
            new_lines.append(line)
            continue
        if stripped.startswith("index\t"):
            new_lines.append(stripped + "\ttarget_chromosome\n")
            continue
        fields = stripped.split("\t")
        if len(fields) >= 2 and fields[0] and "-" in fields[0]:
            # 形如 IWB50236-right-0-A
            marker = fields[0].split("-")[0]
            chrom = marker_to_chrom.get(marker, "")
            new_lines.append(stripped + "\t" + chrom + "\n")
        else:
            new_lines.append(line)
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _cat_files(files, dest):
    with open(dest, "w", encoding="utf-8") as out:
        for f in files:
            with open(f, "r", encoding="utf-8") as inp:
                out.write(inp.read())
