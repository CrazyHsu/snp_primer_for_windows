#!/usr/bin/env python3
r"""
Windows 端 5 秒自检：确认 ``snp_primer_runtime/bin/`` 下 5 个二进制都到位、能跑。

直接在 Windows 终端跑：

    python tests\check_windows_binaries.py

期望输出（每行一个 [OK]）：

    [OK] blastn       -> ...\bin\blastn.exe        (19.4 MB)  blastn: 2.16.0+
    [OK] blastdbcmd   -> ...\bin\blastdbcmd.exe    (14.0 MB)  blastdbcmd: 2.16.0+
    [OK] makeblastdb  -> ...\bin\makeblastdb.exe   (14.9 MB)  makeblastdb: 2.16.0+
    [OK] muscle       -> ...\bin\muscle.exe        (1.2 MB)   MUSCLE v3.8.31
    [OK] primer3_core -> ...\bin\primer3_core.exe  (X.X MB)   primer3 release X.X.X

任何一行变成 ``[MISSING]`` 或 ``[BROKEN]`` 都说明 bootstrap 没跑完，或者目录里
有 0 字节 WSL 残留 symlink 在挡路。第一种的解法是重跑 ``Launch SNP Primer
Desktop.cmd``，第二种的解法是直接删掉那些 0 字节的无扩展名同名文件。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V5_ROOT = HERE.parent
BIN = V5_ROOT / "snp_primer_runtime" / "bin"

# (binname, version_args)。把每个工具能输出版本号的最小调用列出来。
TOOLS = [
    ("blastn",       ["-version"]),
    ("blastdbcmd",   ["-version"]),
    ("makeblastdb",  ["-version"]),
    ("muscle",       ["-version"]),
    ("primer3_core", ["-about"]),
]


def resolve(binname: str) -> Path | None:
    """模拟 ``core.pipeline._which`` 在当前平台的查找逻辑。"""
    is_win = os.name == "nt"
    suffixes = (".exe", "") if is_win else ("", ".exe")
    for suf in suffixes:
        p = BIN / (binname + suf)
        try:
            if p.is_file() and p.stat().st_size > 0:
                return p
        except OSError:
            continue
    return None


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def main() -> int:
    if os.name != "nt":
        print("注意：你不在 Windows 上跑（os.name != 'nt'）。脚本仍会跑：")
        print("  - bin/ 目录扫描和 0 字节坏 symlink 检测一样有效")
        print("  - .exe 因为 Linux 内核不能执行 PE，会报 'Exec format error'")
        print("  - 这是预期；正式用请在 Windows cmd 里跑\n")
    print(f"BIN = {BIN}")
    if not BIN.is_dir():
        print(f"[ERROR] {BIN} 不存在 —— bootstrap 没跑过？")
        return 2

    # 列一下 bin/ 下所有文件，特别标记 0 字节的（WSL 残留 symlink）。
    print(f"\n--- {BIN.name}/ 目录内容 ---")
    junk = []
    for p in sorted(BIN.iterdir()):
        try:
            sz = p.stat().st_size
        except OSError:
            sz = -1
        marker = ""
        if sz == 0 and p.suffix != ".exe":
            marker = "  <-- ⚠ 0 字节（疑似 WSL 残留 symlink），删掉！"
            junk.append(p)
        print(f"  {p.name:32s} {sz:>12} bytes{marker}")
    if junk:
        print(f"\n⚠ 发现 {len(junk)} 个 0 字节文件，建议删除：")
        for p in junk:
            print(f"  del \"{p}\"")

    print(f"\n--- 二进制可用性自检 ---")
    is_win = os.name == "nt"
    rc = 0
    for binname, vargs in TOOLS:
        path = resolve(binname)
        if path is None:
            print(f"[MISSING]    {binname:13s}  (没找到 .exe 或 0 字节文件挡路)")
            rc = 1
            continue
        size = fmt_size(path.stat().st_size)
        is_pe = path.suffix.lower() == ".exe"
        # 在非 Windows 上跑：Linux/macOS 内核不能执行 PE，遇到 .exe 直接跳过执行
        # 检查；只在 Windows 上才把 PE 不能执行视为问题。
        if is_pe and not is_win:
            print(f"[N/A-LINUX]  {binname:13s} -> {path}  ({size})  "
                  f"PE 二进制，仅 Windows 可执行；路径解析正确即视为 OK")
            continue
        try:
            out = subprocess.run([str(path), *vargs],
                                 capture_output=True, text=True, timeout=15)
            ver = (out.stdout or out.stderr).strip().splitlines()
            ver = ver[0] if ver else "<no version output>"
        except OSError as e:
            print(f"[BROKEN]     {binname:13s} -> {path}  ({size})  无法执行：{e}")
            rc = 1
            continue
        except subprocess.TimeoutExpired:
            print(f"[TIMEOUT]    {binname:13s} -> {path}  ({size})  -version 卡住")
            rc = 1
            continue
        print(f"[OK]         {binname:13s} -> {path}  ({size})  {ver}")

    if rc == 0:
        if is_win:
            print("\n*** 5 个二进制全部就绪，可以放心点 Run Pipeline ***")
        else:
            print("\n*** 路径解析正常；.exe 没法在 Linux 上跑是预期。"
                  "请到 Windows 上再跑一次此脚本以最终确认 ***")
    else:
        print("\n*** 有问题，请按上面提示修复后再点 Run Pipeline ***")
    return rc


if __name__ == "__main__":
    sys.exit(main())
