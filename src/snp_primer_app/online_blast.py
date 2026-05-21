from __future__ import annotations

import json
import re
import socket
import threading
import time
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# PipelineCancelled 定义在 core/pipeline.py（更底层）；在线 BLAST 的 polling
# 循环要 raise 它来通知 GUI 用户按了 Stop。core 不 import online_blast 在
# 模块顶端（只在函数内），所以这个反向 import 没循环风险。
from core.pipeline import PipelineCancelled

from .external_tools import LogFn, log_message
from .models import BlastAlignment, FlankingTarget
from .sequence_utils import reverse_complement


NCBI_BLAST_URL = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EBI_BLAST_URL = "https://www.ebi.ac.uk/Tools/services/rest/ncbiblast"
EBI_DBFETCH_URL = "https://www.ebi.ac.uk/Tools/dbfetch/dbfetch"

# v11 第四轮：NCBI / EBI 在线 BLAST 偶尔会因为对端 reset / load balancer
# 切换 / 临时拥塞抛 "Remote end closed connection without response" 一类的
# 瞬时网络错。捕获这一族异常做指数退避重试，避免整条 pipeline 因为一次
# 抖动就挂掉。
_RETRYABLE_NET: tuple[type[BaseException], ...] = (
    URLError,
    RemoteDisconnected,
    IncompleteRead,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
    socket.timeout,
    socket.error,
)
_HTTP_RETRY_DELAYS = (3, 6, 12, 24, 48)  # 5 次重试，累计等 ≈93s


class OnlineBlastError(RuntimeError):
    """Raised when a remote BLAST or sequence-fetching request fails."""


def _cancel_wait(seconds: float, cancel_event: threading.Event | None) -> None:
    """time.sleep 的可中断替身。给了 cancel_event 就走 Event.wait，让 Stop 按钮
    能秒级生效；没给就退化成普通 time.sleep。返回前不抛——上层自己检查
    is_set 决定是否 raise PipelineCancelled。"""
    if cancel_event is not None:
        cancel_event.wait(seconds)
    else:
        time.sleep(seconds)


def _raise_if_cancelled(cancel_event: threading.Event | None, label: str) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise PipelineCancelled(f"用户在 {label} 阶段取消了在线 BLAST")


def _http_request_with_retries(
    do_request: Callable[[], str],
    *,
    description: str,
    logger: LogFn | None,
) -> str:
    """先按 _HTTP_RETRY_DELAYS 节奏 retry，最后一次失败抛 OnlineBlastError。"""
    for attempt, delay in enumerate(_HTTP_RETRY_DELAYS, start=1):
        try:
            return do_request()
        except _RETRYABLE_NET as exc:
            log_message(
                logger,
                f"{description}: 网络抖动 ({type(exc).__name__}: {exc})，"
                f"{delay}s 后第 {attempt}/{len(_HTTP_RETRY_DELAYS)} 次重试",
            )
            time.sleep(delay)
    try:
        return do_request()
    except _RETRYABLE_NET as exc:
        raise OnlineBlastError(
            f"{description} 重试 {len(_HTTP_RETRY_DELAYS)} 次后仍失败：{exc}"
        ) from exc


def normalize_query_id(value: str | None) -> str:
    if not value:
        return "query"
    line = value.strip().splitlines()[0].strip()
    if not line:
        return "query"
    if line.startswith(">"):
        line = line[1:].strip()
    return line.split()[0]


def _http_get(
    url: str,
    params: dict[str, object] | None = None,
    *,
    logger: LogFn | None = None,
    description: str | None = None,
) -> str:
    target = f"{url}?{urlencode(params)}" if params else url
    desc = description or f"GET {url}"

    def _do() -> str:
        with urlopen(target) as response:  # noqa: S310
            return response.read().decode("utf-8")

    return _http_request_with_retries(_do, description=desc, logger=logger)


def _http_post(
    url: str,
    params: dict[str, object],
    *,
    logger: LogFn | None = None,
    description: str | None = None,
) -> str:
    data = urlencode(params).encode("utf-8")
    request = Request(url, data=data)
    desc = description or f"POST {url}"

    def _do() -> str:
        with urlopen(request) as response:  # noqa: S310
            return response.read().decode("utf-8")

    return _http_request_with_retries(_do, description=desc, logger=logger)


def _parse_rid(submit_text: str) -> tuple[str, int]:
    rid_match = re.search(r"RID\s*=\s*([A-Z0-9-]+)", submit_text)
    rtoe_match = re.search(r"RTOE\s*=\s*(\d+)", submit_text)
    if rid_match is None:
        raise OnlineBlastError(f"Could not parse RID from NCBI response:\n{submit_text}")
    return rid_match.group(1), int(rtoe_match.group(1)) if rtoe_match else 10


def _count_gap_opens(sequence: str) -> int:
    return len(re.findall(r"-+", sequence))


def _count_mismatches(query_sequence: str, subject_sequence: str) -> int:
    mismatches = 0
    for query_base, subject_base in zip(query_sequence, subject_sequence):
        if "-" in (query_base, subject_base):
            continue
        if query_base.upper() != subject_base.upper():
            mismatches += 1
    return mismatches


def infer_chromosome(text: str) -> str | None:
    """**v13 起 deprecated wheat-only 别名**——保留以防外部 import 撞名。
    新代码请走 `core.species.infer_chromosome_for_species(text, species)`，
    把 species 显式传进去。本函数依赖小麦 `[1-7][ABD]` 正则，对非小麦
    全返 None。"""
    from core.species import SPECIES_TABLE, infer_chromosome_for_species
    return infer_chromosome_for_species(text, SPECIES_TABLE["wheat"])


def is_likely_transcript_accession(accession: str) -> bool:
    prefix = accession.split("_", 1)[0].upper()
    return prefix in {"XM", "XR", "NM", "NR"}


def _alignment_from_hsp(
    *,
    query_id: str,
    subject_id: str,
    subject_title: str | None,
    subject_length: int,
    align_len: int,
    query_start: int,
    query_end: int,
    subject_start: int,
    subject_end: int,
    query_sequence: str,
    subject_sequence: str,
) -> BlastAlignment:
    return BlastAlignment(
        query_id=query_id,
        subject_id=subject_id,
        alignment_length=align_len,
        mismatches=_count_mismatches(query_sequence, subject_sequence),
        gap_opens=_count_gap_opens(query_sequence) + _count_gap_opens(subject_sequence),
        query_start=query_start,
        query_end=query_end,
        subject_start=subject_start,
        subject_end=subject_end,
        query_sequence=query_sequence,
        subject_sequence=subject_sequence,
        subject_length=subject_length,
        subject_title=subject_title,
        subject_chromosome=infer_chromosome(f"{subject_id} {subject_title or ''}"),
    )


def parse_ncbi_json_results(text: str) -> list[BlastAlignment]:
    payload = json.loads(text)
    reports = payload.get("BlastOutput2", [])
    if isinstance(reports, dict):
        reports = [reports]

    alignments: list[BlastAlignment] = []
    for report in reports:
        search = report.get("report", {}).get("results", {}).get("search", {})
        query_id = normalize_query_id(search.get("query_title") or search.get("query_id"))
        for hit in search.get("hits", []):
            descriptions = hit.get("description", []) or []
            description = descriptions[0] if descriptions else {}
            subject_id = (
                description.get("accession")
                or description.get("id")
                or hit.get("accession")
                or hit.get("description")
                or "subject"
            )
            subject_title = description.get("title") or hit.get("description")
            subject_length = int(hit.get("len") or 0)
            for hsp in hit.get("hsps", []):
                alignments.append(
                    _alignment_from_hsp(
                        query_id=query_id,
                        subject_id=subject_id,
                        subject_title=subject_title,
                        subject_length=subject_length,
                        align_len=int(hsp.get("align_len") or 0),
                        query_start=int(hsp.get("query_from") or 0),
                        query_end=int(hsp.get("query_to") or 0),
                        subject_start=int(hsp.get("hit_from") or 0),
                        subject_end=int(hsp.get("hit_to") or 0),
                        query_sequence=hsp.get("qseq") or "",
                        subject_sequence=hsp.get("hseq") or "",
                    )
                )
    return alignments


def parse_standard_blast_xml(text: str) -> list[BlastAlignment]:
    root = ET.fromstring(text)
    alignments: list[BlastAlignment] = []
    for iteration in root.findall(".//Iteration"):
        query_id = normalize_query_id(
            iteration.findtext("Iteration_query-def") or iteration.findtext("Iteration_query-ID")
        )
        for hit in iteration.findall("./Iteration_hits/Hit"):
            subject_id = hit.findtext("Hit_accession") or hit.findtext("Hit_id") or "subject"
            subject_title = hit.findtext("Hit_def")
            subject_length = int(hit.findtext("Hit_len") or 0)
            for hsp in hit.findall("./Hit_hsps/Hsp"):
                alignments.append(
                    _alignment_from_hsp(
                        query_id=query_id,
                        subject_id=subject_id,
                        subject_title=subject_title,
                        subject_length=subject_length,
                        align_len=int(hsp.findtext("Hsp_align-len") or 0),
                        query_start=int(hsp.findtext("Hsp_query-from") or 0),
                        query_end=int(hsp.findtext("Hsp_query-to") or 0),
                        subject_start=int(hsp.findtext("Hsp_hit-from") or 0),
                        subject_end=int(hsp.findtext("Hsp_hit-to") or 0),
                        query_sequence=hsp.findtext("Hsp_qseq") or "",
                        subject_sequence=hsp.findtext("Hsp_hseq") or "",
                    )
                )
    return alignments


def render_alignment_table(alignments: list[BlastAlignment]) -> str:
    rows = []
    for alignment in alignments:
        rows.append(
            "\t".join(
                [
                    alignment.query_id,
                    alignment.subject_id,
                    "0.0",
                    str(alignment.alignment_length),
                    str(alignment.mismatches),
                    str(alignment.gap_opens),
                    str(alignment.query_start),
                    str(alignment.query_end),
                    str(alignment.subject_start),
                    str(alignment.subject_end),
                    "0",
                    "0",
                    alignment.query_sequence,
                    alignment.subject_sequence,
                    str(alignment.subject_length),
                ]
            )
        )
    return "\n".join(rows) + ("\n" if rows else "")


def run_ncbi_blast(
    query_fasta: str,
    database: str,
    *,
    logger: LogFn | None = None,
    max_hits: int = 100,
    program: str = "blastn",
    word_size: int = 11,
    email: str | None = None,
    timeout_seconds: int = 1800,
    cancel_event: threading.Event | None = None,
    # v13: 默认改为 None。由 core/pipeline.py 按用户选的 species 从
    # core.species.SpeciesConfig.entrez_query 取值喂进来——物种信息只在
    # core/species.py 单点维护。本函数直接调用不传时 → 不加 ENTREZ_QUERY
    # （NCBI 端查全库）。详见 v13 CLAUDE.md §6.22。
    entrez_query: str | None = None,
    # v14: 在线 NCBI BLAST 的原始 JSON 响应落盘路径。提供时，函数会把 NCBI
    # 返回的 result_text **逐字节**写到该路径，再从该路径重新读回喂给 parser，
    # 让"下载文件 = 下游分析输入"在 IO 层面成立（用户排查时直接 diff 这个文件
    # 跟 NCBI 网页下载的 JSON 即可）。None（默认）走 v13 内存路径，不落盘——
    # Layer A 测试不传该参数，保持 wheat 字节等价。详见 v14 §6.23。
    raw_output_path: Path | None = None,
) -> list[BlastAlignment]:
    submit_params: dict[str, object] = {
        "CMD": "Put",
        "PROGRAM": program,
        "DATABASE": database,
        "QUERY": query_fasta,
        "HITLIST_SIZE": max_hits,
        "WORD_SIZE": word_size,
        "FILTER": "F",
    }
    if email:
        submit_params["EMAIL"] = email
    if entrez_query:
        submit_params["ENTREZ_QUERY"] = entrez_query
        log_message(logger, f"  NCBI ENTREZ_QUERY filter: {entrez_query}")
    submit_text = _http_post(
        NCBI_BLAST_URL,
        submit_params,
        logger=logger,
        description="NCBI BLAST submit",
    )
    rid, rtoe = _parse_rid(submit_text)
    log_message(logger, f"Submitted NCBI BLAST RID={rid}")
    log_message(
        logger,
        f"  View status / results: {NCBI_BLAST_URL}?CMD=Get&RID={rid}",
    )
    _cancel_wait(max(3, rtoe), cancel_event)
    _raise_if_cancelled(cancel_event, "NCBI BLAST 初始等待")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_cancelled(cancel_event, "NCBI BLAST polling")
        status_text = _http_get(
            NCBI_BLAST_URL,
            {"CMD": "Get", "RID": rid, "FORMAT_OBJECT": "SearchInfo"},
            logger=logger,
            description=f"NCBI BLAST status RID={rid}",
        )
        if "Status=READY" in status_text:
            if "ThereAreHits=yes" not in status_text:
                return []
            result_text = _http_get(
                NCBI_BLAST_URL,
                {
                    "CMD": "Get",
                    "RID": rid,
                    "FORMAT_TYPE": "JSON2_S",
                },
                logger=logger,
                description=f"NCBI BLAST result RID={rid}",
            )
            if raw_output_path is not None:
                raw_output_path.parent.mkdir(parents=True, exist_ok=True)
                raw_output_path.write_text(result_text, encoding="utf-8")
                log_message(
                    logger,
                    f"  Saved NCBI BLAST raw JSON: {raw_output_path}",
                )
                result_text = raw_output_path.read_text(encoding="utf-8")
            return parse_ncbi_json_results(result_text)
        if "Status=FAILED" in status_text or "Status=UNKNOWN" in status_text:
            raise OnlineBlastError(f"NCBI BLAST failed for RID {rid}:\n{status_text}")
        _cancel_wait(5, cancel_event)
    raise OnlineBlastError(f"NCBI BLAST timed out after {timeout_seconds} seconds for RID {rid}")


def fetch_ncbi_sequence(
    target: FlankingTarget,
    *,
    email: str | None = None,
    logger: LogFn | None = None,
) -> str:
    params: dict[str, object] = {
        "db": "nuccore",
        "id": target.subject_id,
        "rettype": "fasta",
        "retmode": "text",
        "seq_start": target.range_start,
        "seq_stop": target.range_end,
        "strand": 2 if target.strand == "minus" else 1,
    }
    if email:
        params["email"] = email
    text = _http_get(
        NCBI_EFETCH_URL,
        params,
        logger=logger,
        description=f"NCBI efetch {target.subject_id}",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise OnlineBlastError(f"NCBI efetch returned unexpected content for {target.subject_id}")
    header = f">{target.subject_id}|{target.subject_chromosome or 'remote'}"
    return header + "\n" + "".join(lines[1:]) + "\n"


def run_ebi_blast(
    query_fasta: str,
    database: str,
    *,
    email: str,
    logger: LogFn | None = None,
    timeout_seconds: int = 1800,
    cancel_event: threading.Event | None = None,
) -> list[BlastAlignment]:
    if not email:
        raise OnlineBlastError("EBI BLAST requires an email address.")
    job_id = _http_post(
        f"{EBI_BLAST_URL}/run",
        {
            "email": email,
            "program": "blastn",
            "stype": "dna",
            "database": database,
            "sequence": query_fasta,
        },
        logger=logger,
        description="EBI BLAST submit",
    ).strip()
    if not job_id:
        raise OnlineBlastError("EBI BLAST did not return a job ID.")
    log_message(logger, f"Submitted EBI BLAST job {job_id}")
    log_message(
        logger,
        f"  View status: {EBI_BLAST_URL}/status/{job_id}",
    )
    log_message(
        logger,
        f"  View result XML: {EBI_BLAST_URL}/result/{job_id}/xml",
    )

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _raise_if_cancelled(cancel_event, "EBI BLAST polling")
        status = _http_get(
            f"{EBI_BLAST_URL}/status/{job_id}",
            logger=logger,
            description=f"EBI BLAST status {job_id}",
        ).strip().upper()
        if status == "FINISHED":
            xml_text = _http_get(
                f"{EBI_BLAST_URL}/result/{job_id}/xml",
                logger=logger,
                description=f"EBI BLAST result {job_id}",
            )
            return parse_standard_blast_xml(xml_text)
        if status in {"ERROR", "FAILURE", "NOT_FOUND"}:
            raise OnlineBlastError(f"EBI BLAST failed for job {job_id}: {status}")
        _cancel_wait(5, cancel_event)
    raise OnlineBlastError(f"EBI BLAST timed out after {timeout_seconds} seconds for job {job_id}")


def fetch_ebi_sequence(
    target: FlankingTarget,
    database: str,
    *,
    logger: LogFn | None = None,
) -> str:
    fasta_text = _http_get(
        f"{EBI_DBFETCH_URL}/{database}/{target.subject_id}/fasta",
        {"style": "raw"},
        logger=logger,
        description=f"EBI dbfetch {target.subject_id}",
    )
    lines = [line.strip() for line in fasta_text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise OnlineBlastError(f"EBI dbfetch returned unexpected content for {target.subject_id}")
    sequence = "".join(lines[1:])
    subseq = sequence[target.range_start - 1 : target.range_end]
    if target.strand == "minus":
        subseq = reverse_complement(subseq)
    header = f">{target.subject_id}|{target.subject_chromosome or 'remote'}"
    return header + "\n" + subseq + "\n"


# ---------------------------------------------------------------------------
# v10 additions: helpers that let core.pipeline.run() drive online BLAST
# through the upstream getflanking → blastdbcmd-style flow.
#
# getflanking.flanking() filters BLAST hits by inspecting the subject id's
# `chr` prefix / last 2 chars to extract a wheat sub-genome code (A/B/D).
# Raw NCBI accessions like "NC_057814.1" don't expose that, so the online
# pipeline rewrites each subject to "chr{XY}_{accession}" before writing
# blast_out.txt. The rewrite is reversed in Step 5 to recover the accession
# for efetch / dbfetch.
# ---------------------------------------------------------------------------


def render_alignment_table_with_chrom_prefix(
    alignments: list[BlastAlignment],
    logger: LogFn | None = None,
    *,
    species=None,
    sample_dropped_limit: int = 5,
) -> str:
    """Like render_alignment_table but prefixes subject_id with ``chr{XY}_``
    using the inferred chromosome short code for the given species. Hits
    without an inferrable chromosome are dropped.

    v13: species is `core.species.SpeciesConfig`; defaults to wheat for
    backward compatibility. chromosome inference is now species-aware
    (`species.infer_chrom_patterns` drives the regex set).

    Logs total/kept/dropped counts and up to ``sample_dropped_limit`` example
    (subject_id, subject_title) pairs from the dropped set, so the user can
    eyeball whether the drops are non-target species (expected when DB is
    broad), target species without chromosome notation (expected for
    cDNA/EST entries), or target species hits whose chromosome the regex
    missed (real bug — file an issue with the sample titles)."""
    from core.species import get_species, infer_chromosome_for_species
    sp = species if species is not None else get_species("wheat")
    rewritten: list[BlastAlignment] = []
    dropped_samples: list[tuple[str, str]] = []
    dropped = 0
    for a in alignments:
        # v13: 不再读 a.subject_chromosome（_alignment_from_hsp 仍在填它但走的是
        # wheat-only infer_chromosome alias，对非小麦无效）。这里按 species 现算。
        chrom = infer_chromosome_for_species(
            f"{a.subject_id} {a.subject_title or ''}", sp
        )
        if not chrom:
            dropped += 1
            if len(dropped_samples) < sample_dropped_limit:
                dropped_samples.append(
                    (a.subject_id, (a.subject_title or "")[:200])
                )
            continue
        rewritten.append(
            BlastAlignment(
                query_id=a.query_id,
                subject_id=f"chr{chrom}_{a.subject_id}",
                alignment_length=a.alignment_length,
                mismatches=a.mismatches,
                gap_opens=a.gap_opens,
                query_start=a.query_start,
                query_end=a.query_end,
                subject_start=a.subject_start,
                subject_end=a.subject_end,
                query_sequence=a.query_sequence,
                subject_sequence=a.subject_sequence,
                subject_length=a.subject_length,
                subject_title=a.subject_title,
                subject_chromosome=chrom,
            )
        )
    kept = len(rewritten)
    total = kept + dropped
    if total:
        # v13: species-aware label，避免日志写死 "wheat chrom 1-7 A/B/D" 误导
        log_message(
            logger,
            f"BLAST hits: total={total}, kept ({sp.display_name} chrom)={kept}, "
            f"dropped (no inferrable chromosome for {sp.key})={dropped}",
        )
    if dropped_samples:
        log_message(
            logger,
            f"  Sample dropped hits (showing first {len(dropped_samples)}):",
        )
        for sid, stitle in dropped_samples:
            log_message(logger, f"    - {sid}  |  {stitle}")
    return render_alignment_table(rewritten)


# v13: 通用 chr 前缀正则——chr 开头 + 1-3 个 [A-Za-z0-9] + 下划线 + accession 余下。
# 涵盖小麦 "chr7A_NC_xxx"、大麦 "chr5H_NC_xxx"、水稻 "chr12_NC_xxx" 等。
# 旧的 wheat-only `r"^chr([1-7][ABD])_(.+)$"` 反解器 v13 起被这条替换。
_CHROM_PREFIXED_RE = re.compile(r"^chr([A-Za-z0-9]{1,3})_(.+)$")


def split_chrom_prefixed_subject(subject: str) -> tuple[str | None, str]:
    """Inverse of the rewrite done by render_alignment_table_with_chrom_prefix.

    Returns ``(chrom_short_or_None, original_accession)``. Subjects not in
    rewritten form are returned unchanged with ``chrom_short_or_None = None``.

    v13: 通用化为 [A-Za-z0-9]{1,3} 短码，跨物种工作。不再 hard-validate
    against species.valid_chrom_codes——宽松反解 + 让 pipeline 跑通，比硬卡
    更友好。
    """
    m = _CHROM_PREFIXED_RE.match(subject)
    if not m:
        return None, subject
    return m.group(1), m.group(2)


def fetch_ncbi_sequence_for_range(
    subject_id: str,
    start: int,
    end: int,
    strand: str,
    *,
    header_id: str | None = None,
    email: str | None = None,
    logger: LogFn | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    _raise_if_cancelled(cancel_event, "NCBI efetch")
    """Fetch a sub-sequence via NCBI efetch. ``header_id`` is what gets
    written after the ``>`` so downstream getCAPS/getkasp3 can substring-match
    against the target chromosome short code (e.g. ``chr7A_NC_057814.1``)."""
    params: dict[str, object] = {
        "db": "nuccore",
        "id": subject_id,
        "rettype": "fasta",
        "retmode": "text",
        "seq_start": start,
        "seq_stop": end,
        "strand": 2 if strand == "minus" else 1,
    }
    if email:
        params["email"] = email
    text = _http_get(
        NCBI_EFETCH_URL,
        params,
        logger=logger,
        description=f"NCBI efetch {subject_id} {start}-{end}",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise OnlineBlastError(
            f"NCBI efetch returned unexpected content for {subject_id}"
        )
    header = ">" + (header_id or subject_id)
    return header + "\n" + "".join(lines[1:]) + "\n"


def fetch_ebi_sequence_for_range(
    subject_id: str,
    start: int,
    end: int,
    strand: str,
    *,
    fetch_database: str = "ena_sequence",
    header_id: str | None = None,
    logger: LogFn | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    _raise_if_cancelled(cancel_event, "EBI dbfetch")
    """Fetch a sub-sequence via EBI dbfetch. dbfetch has no slice param, so
    this pulls the full record and slices client-side."""
    fasta_text = _http_get(
        f"{EBI_DBFETCH_URL}/{fetch_database}/{subject_id}/fasta",
        {"style": "raw"},
        logger=logger,
        description=f"EBI dbfetch {subject_id}",
    )
    lines = [line.strip() for line in fasta_text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(">"):
        raise OnlineBlastError(
            f"EBI dbfetch returned unexpected content for {subject_id}"
        )
    sequence = "".join(lines[1:])
    subseq = sequence[start - 1 : end]
    if strand == "minus":
        subseq = reverse_complement(subseq)
    header = ">" + (header_id or subject_id)
    return header + "\n" + subseq + "\n"
