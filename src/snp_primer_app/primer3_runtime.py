from __future__ import annotations

from pathlib import Path
from typing import Any

from .external_tools import LogFn, log_message
from .models import PrimerPair
from .primer3_parser import parse_primer3_output_text


_INT_KEYS = {
    "PRIMER_EXPLAIN_FLAG",
    "PRIMER_FIRST_BASE_INDEX",
    "PRIMER_LIBERAL_BASE",
    "PRIMER_MAX_SIZE",
    "PRIMER_NUM_RETURN",
    "PRIMER_PICK_ANYWAY",
    "SEQUENCE_FORCE_LEFT_END",
    "SEQUENCE_FORCE_LEFT_START",
    "SEQUENCE_FORCE_RIGHT_END",
    "SEQUENCE_FORCE_RIGHT_START",
}

_FLOAT_KEYS = {
    "PRIMER_MAX_TM",
    "PRIMER_MIN_TM",
    "PRIMER_OPT_TM",
    "PRIMER_PAIR_MAX_DIFF_TM",
}


class Primer3RuntimeUnavailable(RuntimeError):
    """Raised when neither primer3_core nor primer3-py is available."""


def has_primer3_python() -> bool:
    try:
        import primer3  # noqa: F401
    except ImportError:
        return False
    return True


def parse_boulder_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "=":
            if current:
                records.append(current)
                current = {}
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        current[key] = value
    if current:
        records.append(current)
    return records


def _coerce_range_list(value: str) -> list[list[int]]:
    ranges: list[list[int]] = []
    for token in value.split():
        left, right = token.split("-")
        ranges.append([int(left), int(right)])
    return ranges


def _coerce_interval_list(value: str) -> list[list[int]]:
    intervals: list[list[int]] = []
    for token in value.split(";"):
        token = token.strip()
        if not token:
            continue
        start, length = token.split(",", 1)
        intervals.append([int(start), int(length)])
    return intervals


def _coerce_value(key: str, value: str) -> Any:
    if key in _INT_KEYS:
        return int(value)
    if key in _FLOAT_KEYS:
        return float(value)
    if key == "PRIMER_PRODUCT_SIZE_RANGE":
        return _coerce_range_list(value)
    if key == "SEQUENCE_TARGET":
        intervals = _coerce_interval_list(value)
        return intervals if len(intervals) > 1 else intervals[0]
    return value


def _render_result_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return ",".join(_render_result_value(item) for item in value)
    return str(value)


def render_boulder_result(sequence_id: str, result: dict[str, Any]) -> str:
    lines = [f"SEQUENCE_ID={sequence_id}"]
    for key in sorted(result):
        if key == "SEQUENCE_ID":
            continue
        value = result[key]
        if value in (None, ""):
            continue
        lines.append(f"{key}={_render_result_value(value)}")
    return "\n".join(lines)


def _run_python_record(record: dict[str, str]) -> dict[str, Any]:
    try:
        import primer3
    except ImportError as exc:  # pragma: no cover - exercised via availability checks
        raise Primer3RuntimeUnavailable(
            "primer3-py is not installed and primer3_core.exe is not available."
        ) from exc

    bindings = primer3.bindings
    design_fn = getattr(bindings, "design_primers", None) or getattr(bindings, "designPrimers", None)
    if design_fn is None:  # pragma: no cover - defensive
        raise Primer3RuntimeUnavailable("primer3-py does not expose a primer design function.")

    sequence_args: dict[str, Any] = {}
    global_args: dict[str, Any] = {}
    for key, value in record.items():
        target = sequence_args if key.startswith("SEQUENCE_") else global_args
        target[key] = _coerce_value(key, value)
    return design_fn(sequence_args, global_args)


def run_primer3_with_python(
    input_path: str | Path,
    output_path: str | Path,
    primerpair_to_return: int,
    *,
    logger: LogFn | None = None,
) -> dict[str, PrimerPair]:
    input_text = Path(input_path).read_text(encoding="utf-8")
    chunks: list[str] = []
    for record in parse_boulder_records(input_text):
        sequence_id = record.get("SEQUENCE_ID", "unknown")
        log_message(logger, f"Using primer3-py for {sequence_id}")
        result = _run_python_record(record)
        chunks.append(render_boulder_result(sequence_id, result))
    output_text = "\n".join(chunks) + ("\n" if chunks else "")
    Path(output_path).write_text(output_text, encoding="utf-8")
    return parse_primer3_output_text(output_text, primerpair_to_return)
