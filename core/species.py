"""物种配置中心。所有跟物种相关的硬编码（taxid / 染色体正则 / subgenome 过滤 /
ploidy 缺省）都集中在这里。

设计目标：
- Wheat 配置必须让 v12 → v13 路径**字节等价**（CLAUDE.md §5 Layer A/B 4/4 PASS
  不能掉链）。
- 非小麦物种配置只保证能跑通且语义合理，**不保证逐字节匹配 wheatomics 输出**
  （非小麦没有外部基准）。
- 切到新物种只需要在 SPECIES_TABLE 里加一条；不改算法。

详见 v13 CLAUDE.md §6.22。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeciesConfig:
    key: str
    display_name: str  # GUI / log 显示
    taxid: int  # NCBI taxonomy ID
    entrez_query: str  # 例如 "txid4565[ORGN]"
    # infer_chromosome 用的正则模式列表（按顺序尝试，返回第一个 match 的 group(1)）
    infer_chrom_patterns: tuple[str, ...]
    # 接受的染色体短码集合，作为后续验证用（如 wheat {"1A","1B",...,"7D"}）
    valid_chrom_codes: frozenset[str]
    # 是否做 wheat-style ABD subgenome 过滤
    # （True 时 getflanking.flanking 会过滤 schrom[1] in subgenome；False 时全收）
    use_abd_filter: bool
    # ploidy GUI 选项；非 wheat 都只有 (1,)
    ploidy_choices: tuple[int, ...]
    default_ploidy: int


# 小麦 7×3 亚基因组：1A, 1B, 1D, 2A, ..., 7D + Un
_WHEAT_CODES = frozenset(
    f"{n}{sub}" for n in "1234567" for sub in "ABD"
) | {"Un"}

# 大麦 7 条单条染色体 + chrUn
_BARLEY_CODES = frozenset(f"{n}H" for n in "1234567") | {"Un"}

# 水稻 12 条单条
_RICE_CODES = frozenset(str(n) for n in range(1, 13)) | {"Un"}

# 玉米 10 条
_MAIZE_CODES = frozenset(str(n) for n in range(1, 11)) | {"Un"}

# 高粱 10 条
_SORGHUM_CODES = frozenset(str(n) for n in range(1, 11)) | {"Un"}

# 拟南芥 5 条
_ARABIDOPSIS_CODES = frozenset(str(n) for n in range(1, 6)) | {"Un"}


SPECIES_TABLE: dict[str, SpeciesConfig] = {
    "wheat": SpeciesConfig(
        key="wheat",
        display_name="Triticum aestivum (wheat)",
        taxid=4565,
        entrez_query="txid4565[ORGN] AND biomol_genomic[PROP]",
        # v12 infer_chromosome 行为字节等价：先尝试 \b[1-7][ABD]\b，再 chromosome|chr 模式
        infer_chrom_patterns=(
            r"\b([1-7][ABD])\b",
            r"(?:chromosome|chr)\s*([1-7][ABD])\b",
        ),
        valid_chrom_codes=_WHEAT_CODES,
        use_abd_filter=True,
        ploidy_choices=(1, 2, 3),
        default_ploidy=3,
    ),
    "barley": SpeciesConfig(
        key="barley",
        display_name="Hordeum vulgare (barley)",
        taxid=4513,
        entrez_query="txid4513[ORGN] AND biomol_genomic[PROP]",
        infer_chrom_patterns=(
            r"\b([1-7]H)\b",
            r"(?:chromosome|chr)\s*([1-7]H)\b",
        ),
        valid_chrom_codes=_BARLEY_CODES,
        use_abd_filter=False,
        ploidy_choices=(1,),
        default_ploidy=1,
    ),
    "rice": SpeciesConfig(
        key="rice",
        display_name="Oryza sativa (rice)",
        taxid=4530,
        entrez_query="txid4530[ORGN] AND biomol_genomic[PROP]",
        # 12 条染色体；优先 chromosome|chr 前缀以避免乱抓 subject_title 里的纯数字
        infer_chrom_patterns=(
            r"(?:chromosome|chr)\s*(1[0-2]|[1-9])\b",
        ),
        valid_chrom_codes=_RICE_CODES,
        use_abd_filter=False,
        ploidy_choices=(1,),
        default_ploidy=1,
    ),
    "maize": SpeciesConfig(
        key="maize",
        display_name="Zea mays (maize)",
        taxid=4577,
        entrez_query="txid4577[ORGN] AND biomol_genomic[PROP]",
        infer_chrom_patterns=(
            r"(?:chromosome|chr)\s*(10|[1-9])\b",
        ),
        valid_chrom_codes=_MAIZE_CODES,
        use_abd_filter=False,
        ploidy_choices=(1,),
        default_ploidy=1,
    ),
    "sorghum": SpeciesConfig(
        key="sorghum",
        display_name="Sorghum bicolor (sorghum)",
        taxid=4558,
        entrez_query="txid4558[ORGN] AND biomol_genomic[PROP]",
        infer_chrom_patterns=(
            r"(?:chromosome|chr)\s*(10|[1-9])\b",
        ),
        valid_chrom_codes=_SORGHUM_CODES,
        use_abd_filter=False,
        ploidy_choices=(1,),
        default_ploidy=1,
    ),
    "arabidopsis": SpeciesConfig(
        key="arabidopsis",
        display_name="Arabidopsis thaliana",
        taxid=3702,
        entrez_query="txid3702[ORGN] AND biomol_genomic[PROP]",
        infer_chrom_patterns=(
            r"(?:chromosome|chr)\s*([1-5])\b",
        ),
        valid_chrom_codes=_ARABIDOPSIS_CODES,
        use_abd_filter=False,
        ploidy_choices=(1,),
        default_ploidy=1,
    ),
}


def get_species(key: str | None) -> SpeciesConfig:
    """根据 key 取 SpeciesConfig；None 或未知 key 落回 wheat（v12 行为兜底）。"""
    if not key:
        return SPECIES_TABLE["wheat"]
    return SPECIES_TABLE.get(key, SPECIES_TABLE["wheat"])


def infer_chromosome_for_species(text: str, species: SpeciesConfig) -> str | None:
    """species-aware 版本的 infer_chromosome。按 species.infer_chrom_patterns 顺序
    尝试匹配；返回首个 match 的 group(1)（大写）。无匹配返回 None。"""
    for pattern in species.infer_chrom_patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None
