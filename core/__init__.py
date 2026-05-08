"""SNP 引物设计核心算法模块。

各文件直接移植自 https://github.com/pinbo/SNP_Primer_Pipeline 的 Python 2
脚本（`bin/parse_polymarker_input.py`、`bin/getflanking.py`、`bin/getCAPS.py`、
`bin/getkasp3.py`），按 Py3 语法做最小化适配，并把模块级 sys.argv 入口
封装成可调用函数。

通常通过 :mod:`core.pipeline` 暴露的 ``run`` 函数使用，参见 pipeline.py。
"""
