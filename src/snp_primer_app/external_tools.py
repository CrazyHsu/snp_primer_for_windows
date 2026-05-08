from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Iterable


LogFn = Callable[[str], None]


class CommandExecutionError(RuntimeError):
    """Raised when an external executable returns a non-zero exit code."""


def log_message(logger: LogFn | None, message: str) -> None:
    if logger is not None:
        logger(message)


def ensure_file_exists(path: str | Path, label: str) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        raise FileNotFoundError(f"{label} not found: {candidate}")
    return candidate


def resolve_primer3_config_dir(primer3_core: str | Path) -> Path | None:
    env_value = os.environ.get("PRIMER3_CONFIG_DIR")
    if env_value:
        path = Path(env_value)
        if path.exists():
            return path
    binary_dir = Path(primer3_core).parent
    for candidate in (binary_dir / "primer3_config", binary_dir.parent / "primer3_config"):
        if candidate.exists():
            return candidate
    return None


def _stringify_cmd(command: Iterable[object]) -> str:
    return " ".join(str(part) for part in command)


def run_command(
    command: list[object],
    *,
    cwd: str | Path | None = None,
    logger: LogFn | None = None,
    env: dict[str, str] | None = None,
) -> None:
    cmd = [str(part) for part in command]
    log_message(logger, f"$ {_stringify_cmd(cmd)}")
    with subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    ) as process:
        assert process.stdout is not None
        output_lines: list[str] = []
        for line in process.stdout:
            output_lines.append(line)
            log_message(logger, line.rstrip())
        return_code = process.wait()
    if return_code != 0:
        raise CommandExecutionError(
            f"Command failed with exit code {return_code}: {_stringify_cmd(cmd)}\n"
            + "".join(output_lines)
        )


def run_command_to_file(
    command: list[object],
    output_path: str | Path,
    *,
    cwd: str | Path | None = None,
    logger: LogFn | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    cmd = [str(part) for part in command]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_message(logger, f"$ {_stringify_cmd(cmd)} > {output}")
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    stdout, stderr = process.communicate()
    output.write_text(stdout, encoding="utf-8")
    if stderr:
        for line in stderr.splitlines():
            log_message(logger, line)
    if process.returncode != 0:
        raise CommandExecutionError(
            f"Command failed with exit code {process.returncode}: {_stringify_cmd(cmd)}\n{stderr}"
        )
    return output
