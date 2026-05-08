from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from .alignment import parse_flanking_fasta_file, parse_marker_metadata
from .caps import parse_restriction_enzyme_file, scan_caps_enzymes
from .flanking import collect_flanking_targets, write_marker_batches, write_temp_range_file
from .kasp import build_kasp_primer3_input, prepare_kasp_analysis
from .models import BinaryBundle, PipelineRequest
from .parsers import parse_polymarker_file, write_blast_fasta
from .pipeline_runner import PipelineRunner
from .reference_catalog import load_reference_catalog
from .sequence_utils import IUPAC_ALLELES


def _cmd_export_fasta(args: argparse.Namespace) -> int:
    records = parse_polymarker_file(args.input_csv)
    write_blast_fasta(records, args.output_fasta)
    return 0


def _cmd_build_flanking(args: argparse.Namespace) -> int:
    records = parse_polymarker_file(args.input_csv)
    blast_lines = Path(args.blast_output).read_text(encoding="utf-8").splitlines()
    targets = collect_flanking_targets(records, blast_lines, genome_number=args.ploidy)
    write_temp_range_file(targets, args.output_range)
    if args.marker_dir:
        write_marker_batches(targets, args.marker_dir)
    return 0


def _cmd_check_reference_catalog(args: argparse.Namespace) -> int:
    references = load_reference_catalog(args.source)
    payload = [
        {
            "id": reference.reference_id,
            "display_name": reference.display_name,
            "enabled": reference.enabled,
            "install_subdir": reference.install_subdir,
        }
        for reference in references
    ]
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_prepare_kasp_input(args: argparse.Namespace) -> int:
    metadata, analysis = prepare_kasp_analysis(args.seqfile, args.alignment_fasta)
    payload = build_kasp_primer3_input(
        metadata,
        analysis,
        max_tm=args.max_tm,
        max_size=args.max_size,
        pick_anyway=args.pick_anyway,
    )
    Path(args.output).write_text(payload, encoding="utf-8")
    return 0


def _cmd_scan_caps(args: argparse.Namespace) -> int:
    metadata = parse_marker_metadata(args.seqfile)
    fasta_raw, target, _ = parse_flanking_fasta_file(args.seqfile, metadata.chrom)
    seq_template = fasta_raw[target]
    snp_pos = metadata.pos - 1
    snp_a, snp_b = IUPAC_ALLELES[metadata.allele]
    wild_seq = seq_template[:snp_pos] + snp_a + seq_template[snp_pos + 1 :]
    mut_seq = seq_template[:snp_pos] + snp_b + seq_template[snp_pos + 1 :]
    enzymes = parse_restriction_enzyme_file(args.enzyme_file)
    caps_list, dcaps_list = scan_caps_enzymes(enzymes, wild_seq, mut_seq, args.max_price)
    payload = {
        "caps": [enzyme.name for enzyme in caps_list],
        "dcaps": [enzyme.name for enzyme in dcaps_list],
    }
    print(json.dumps(payload, indent=2))
    return 0


def _resolve_binary(binary_root: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    candidate = binary_root / f"{name}{suffix}"
    if candidate.exists():
        return candidate
    located = shutil.which(name)
    return Path(located) if located else candidate


def _cmd_run_pipeline(args: argparse.Namespace) -> int:
    binary_root = Path(args.binary_root)
    request = PipelineRequest(
        input_csv=Path(args.input_csv),
        reference_fasta=Path(args.reference_fasta) if args.reference_fasta else None,
        ploidy=args.ploidy,
        max_enzyme_price=args.max_price,
        design_caps=args.design_caps,
        design_kasp=args.design_kasp,
        blast_primers=args.blast_primers,
        max_tm=args.max_tm,
        max_primer_size=args.max_size,
        pick_anyway=args.pick_anyway,
        blast_mode=args.blast_mode,
        local_blast_db=Path(args.local_blast_db) if args.local_blast_db else None,
        remote_provider=args.remote_provider,
        remote_database=args.remote_database,
        remote_fetch_database=args.remote_fetch_database,
        remote_email=args.remote_email,
    )
    binaries = BinaryBundle(
        blastn=_resolve_binary(binary_root, "blastn"),
        blastdbcmd=_resolve_binary(binary_root, "blastdbcmd"),
        makeblastdb=_resolve_binary(binary_root, "makeblastdb"),
        primer3_core=_resolve_binary(binary_root, "primer3_core"),
        muscle=_resolve_binary(binary_root, "muscle"),
    )
    result = PipelineRunner(
        request=request,
        binaries=binaries,
        working_dir=args.working_dir,
        logger=print,
    ).run()
    payload = {
        "working_dir": str(result.working_dir),
        "potential_kasp": str(result.potential_kasp) if result.potential_kasp else None,
        "potential_caps": str(result.potential_caps) if result.potential_caps else None,
        "kasp_reports": [str(path) for path in result.kasp_reports],
        "caps_reports": [str(path) for path in result.caps_reports],
    }
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snp-primer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_fasta = subparsers.add_parser("export-fasta")
    export_fasta.add_argument("input_csv")
    export_fasta.add_argument("output_fasta")
    export_fasta.set_defaults(func=_cmd_export_fasta)

    build_flanking = subparsers.add_parser("build-flanking")
    build_flanking.add_argument("input_csv")
    build_flanking.add_argument("blast_output")
    build_flanking.add_argument("output_range")
    build_flanking.add_argument("--ploidy", type=int, required=True)
    build_flanking.add_argument("--marker-dir")
    build_flanking.set_defaults(func=_cmd_build_flanking)

    check_catalog = subparsers.add_parser("check-reference-catalog")
    check_catalog.add_argument("source")
    check_catalog.set_defaults(func=_cmd_check_reference_catalog)

    prepare_kasp = subparsers.add_parser("prepare-kasp-input")
    prepare_kasp.add_argument("seqfile")
    prepare_kasp.add_argument("alignment_fasta")
    prepare_kasp.add_argument("output")
    prepare_kasp.add_argument("--max-tm", type=int, required=True)
    prepare_kasp.add_argument("--max-size", type=int, required=True)
    prepare_kasp.add_argument("--pick-anyway", action="store_true")
    prepare_kasp.set_defaults(func=_cmd_prepare_kasp_input)

    scan_caps = subparsers.add_parser("scan-caps")
    scan_caps.add_argument("seqfile")
    scan_caps.add_argument("enzyme_file")
    scan_caps.add_argument("--max-price", type=int, required=True)
    scan_caps.set_defaults(func=_cmd_scan_caps)

    run_pipeline = subparsers.add_parser("run-pipeline")
    run_pipeline.add_argument("input_csv")
    run_pipeline.add_argument("working_dir")
    run_pipeline.add_argument("--reference-fasta")
    run_pipeline.add_argument("--blast-mode", choices=["local", "ncbi_online", "provider_online"], default="local")
    run_pipeline.add_argument("--local-blast-db")
    run_pipeline.add_argument("--remote-provider")
    run_pipeline.add_argument("--remote-database")
    run_pipeline.add_argument("--remote-fetch-database")
    run_pipeline.add_argument("--remote-email")
    run_pipeline.add_argument("--binary-root", default=str(Path.cwd() / "bin"))
    run_pipeline.add_argument("--ploidy", type=int, default=3)
    run_pipeline.add_argument("--max-price", type=int, default=200)
    run_pipeline.add_argument("--max-tm", type=int, default=63)
    run_pipeline.add_argument("--max-size", type=int, default=25)
    run_pipeline.add_argument("--design-caps", action="store_true")
    run_pipeline.add_argument("--design-kasp", action="store_true")
    run_pipeline.add_argument("--blast-primers", action="store_true")
    run_pipeline.add_argument("--pick-anyway", action="store_true")
    run_pipeline.set_defaults(func=_cmd_run_pipeline)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
