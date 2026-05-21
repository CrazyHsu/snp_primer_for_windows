from __future__ import annotations

from pathlib import Path

from .models import BinaryBundle, PipelinePlan, PipelineRequest


def build_pipeline_plan(
    request: PipelineRequest,
    binaries: BinaryBundle,
    working_dir: str | Path,
) -> PipelinePlan:
    workdir = Path(working_dir)
    input_fasta = workdir / "for_blast.fa"
    blast_output = workdir / "blast_out.txt"
    temp_range = workdir / "temp_range.txt"

    steps: list[list[str]] = [[
        "python",
        "-m",
        "snp_primer_app.cli",
        "export-fasta",
        str(request.input_csv),
        str(input_fasta),
    ]]

    if request.blast_mode == "local":
        database = str(request.local_blast_db or request.reference_fasta)
        steps.append(
            [
                str(binaries.blastn),
                "-task",
                "blastn",
                "-db",
                database,
                "-query",
                str(input_fasta),
                "-outfmt",
                "6 std qseq sseq slen",
                "-word_size",
                "11",
                "-num_threads",
                "3",
                "-out",
                str(blast_output),
            ]
        )
    elif request.blast_mode == "ncbi_online":
        steps.append(["NCBI BLAST URL API", request.remote_database or "core_nt", str(blast_output)])
    else:
        steps.append(
            [
                f"Online provider:{request.remote_provider or 'ebi'}",
                request.remote_database or "",
                request.remote_fetch_database or "",
                str(blast_output),
            ]
        )

    steps.append(
        [
            "python",
            "-m",
            "snp_primer_app.cli",
            "build-flanking",
            str(request.input_csv),
            str(blast_output),
            str(temp_range),
            "--ploidy",
            str(request.ploidy),
        ]
    )
    return PipelinePlan(working_dir=workdir, steps=steps)
