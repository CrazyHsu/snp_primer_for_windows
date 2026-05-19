import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from core import pipeline as core_pipeline
from snp_primer_app.models import BinaryBundle, PipelineRequest
from snp_primer_app.pipeline_runner import PipelineRunner


class PipelineRunnerTest(unittest.TestCase):
    def test_pipeline_runner_produces_kasp_and_caps_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()

            target, homeolog, input_seq, blast_seq = self._build_sequences()
            input_csv = tmp / "input.csv"
            input_csv.write_text(f"TEST,7A,{input_seq}\n", encoding="utf-8")
            reference_fasta = tmp / "reference.fa"
            reference_fasta.write_text(">chr7A\n" + target + "\n", encoding="utf-8")

            self._write_script(
                bin_dir / "makeblastdb",
                """
                #!/bin/bash
                infile=""
                out=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    -in) infile="$2"; shift 2 ;;
                    -out) out="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                touch "${out}.nin" "${out}.nsq" "${out}.nhr" "${out}.nsi"
                """,
            )
            self._write_script(
                bin_dir / "blastn",
                f"""
                #!/bin/bash
                query=""
                out=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    -query) query="$2"; shift 2 ;;
                    -out) out="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                if [[ "$(basename "$query")" == "for_blast.fa" ]]; then
                  cat > "$out" <<'EOF'
TEST_7A_R\tchr7A\t99.0\t80\t0\t0\t1\t80\t1\t80\t1e-30\t100\t{blast_seq}\t{target}\t2000
EOF
                else
                  : > "$out"
                fi
                """,
            )
            self._write_script(
                bin_dir / "blastdbcmd",
                f"""
                #!/bin/bash
                out=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    -out) out="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                cat > "$out" <<'EOF'
>chr7A
{target}
>chr7B
{homeolog}
EOF
                """,
            )
            self._write_script(
                bin_dir / "muscle",
                """
                #!/bin/bash
                infile=""
                outfile=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    -in|-align) infile="$2"; shift 2 ;;
                    -out|-output) outfile="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                cp "$infile" "$outfile"
                """,
            )
            self._write_script(
                bin_dir / "primer3_core",
                """
                #!/bin/bash
                outfile=""
                inputfile=""
                for arg in "$@"; do
                  case "$arg" in
                    -output=*) outfile="${arg#-output=}" ;;
                    -p3_settings_file=*) ;;
                    *) inputfile="$arg" ;;
                  esac
                done
                : > "$outfile"
                while IFS= read -r line; do
                  if [[ "$line" == SEQUENCE_ID=* ]]; then
                    id="${line#SEQUENCE_ID=}"
                    cat >> "$outfile" <<EOF
SEQUENCE_ID=$id
PRIMER_PAIR_0_PENALTY=1.0
PRIMER_PAIR_0_COMPL_ANY=0.0
PRIMER_PAIR_0_COMPL_END=0.0
PRIMER_PAIR_0_PRODUCT_SIZE=120
PRIMER_LEFT_0_SEQUENCE=CCCCCCCCCCCCCCCCCCCC
PRIMER_LEFT_0=11,20
PRIMER_LEFT_0_TM=60.0
PRIMER_LEFT_0_GC_PERCENT=50.0
PRIMER_LEFT_0_SELF_ANY_TH=0.0
PRIMER_LEFT_0_SELF_END_TH=0.0
PRIMER_LEFT_0_HAIRPIN_TH=0.0
PRIMER_LEFT_0_END_STABILITY=0.0
PRIMER_RIGHT_0_SEQUENCE=GGGGGGGGGGGGGGGGGGGG
PRIMER_RIGHT_0=61,20
PRIMER_RIGHT_0_TM=60.0
PRIMER_RIGHT_0_GC_PERCENT=50.0
PRIMER_RIGHT_0_SELF_ANY_TH=0.0
PRIMER_RIGHT_0_SELF_END_TH=0.0
PRIMER_RIGHT_0_HAIRPIN_TH=0.0
PRIMER_RIGHT_0_END_STABILITY=0.0
EOF
                  fi
                done < "$inputfile"
                """,
            )

            request = PipelineRequest(
                input_csv=input_csv,
                reference_fasta=reference_fasta,
                ploidy=3,
                max_enzyme_price=200,
                design_caps=True,
                design_kasp=True,
                blast_primers=False,
                max_tm=63,
                max_primer_size=25,
                pick_anyway=False,
            )
            binaries = BinaryBundle(
                blastn=bin_dir / "blastn",
                blastdbcmd=bin_dir / "blastdbcmd",
                makeblastdb=bin_dir / "makeblastdb",
                primer3_core=bin_dir / "primer3_core",
                muscle=bin_dir / "muscle",
            )

            result = PipelineRunner(request, binaries, tmp / "work").run()

            self.assertTrue(result.potential_kasp and result.potential_kasp.exists())
            self.assertTrue(result.potential_caps and result.potential_caps.exists())
            kasp_text = result.potential_kasp.read_text(encoding="utf-8")
            caps_text = result.potential_caps.read_text(encoding="utf-8")
            self.assertIn("-Common", kasp_text)
            self.assertIn("EcoRV,15", caps_text)
            self.assertTrue(result.all_alignment_raw.exists())

    def test_reference_fasta_with_non_ascii_path_is_staged_for_makeblastdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            source_dir = tmp / "参考目录"
            source_dir.mkdir()
            reference_fasta = source_dir / "reference.fa"
            reference_fasta.write_text(">chr7A\nACGT\n", encoding="utf-8")
            args_file = tmp / "makeblastdb_in.txt"

            self._write_script(
                bin_dir / "makeblastdb",
                f"""
                #!/bin/bash
                infile=""
                out=""
                while [ "$#" -gt 0 ]; do
                  case "$1" in
                    -in) infile="$2"; shift 2 ;;
                    -out) out="$2"; shift 2 ;;
                    *) shift ;;
                  esac
                done
                printf '%s\\n' "$infile" > "{args_file}"
                touch "${{out}}.nin" "${{out}}.nsq" "${{out}}.nhr" "${{out}}.nsi"
                """,
            )

            workdir = tmp / "work"
            logs: list[str] = []
            db_prefix = core_pipeline._ensure_blastdb_from_fasta(
                reference_fasta,
                workdir,
                bin_dir,
                logs.append,
            )

            makeblastdb_in = args_file.read_text(encoding="utf-8").strip()
            self.assertEqual(db_prefix, str(workdir / "auto_blastdb" / "reference"))
            self.assertNotEqual(makeblastdb_in, str(reference_fasta.resolve()))
            self.assertNotIn("参考目录", makeblastdb_in)
            self.assertIn("_fasta_stage", makeblastdb_in)
            self.assertTrue(Path(makeblastdb_in).exists())

    def test_reference_fasta_reuses_adjacent_parse_seqids_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            source_dir = tmp / "参考目录"
            source_dir.mkdir()
            reference_fasta = source_dir / "iwgsc_refseqv1.0_chr7A.fsa"
            reference_fasta.write_text(">chr7A\nACGT\n", encoding="utf-8")
            for suffix in (".nhr", ".nin", ".nsq", ".nsi", ".nsd", ".nog"):
                (source_dir / f"Chr7A{suffix}").write_text(suffix, encoding="utf-8")

            self._write_script(
                bin_dir / "makeblastdb",
                """
                #!/bin/bash
                echo makeblastdb should not run >&2
                exit 7
                """,
            )

            workdir = tmp / "work"
            logs: list[str] = []
            db_prefix = core_pipeline._ensure_blastdb_from_fasta(
                reference_fasta,
                workdir,
                bin_dir,
                logs.append,
            )

            self.assertEqual(
                db_prefix,
                str(workdir / "auto_blastdb" / "iwgsc_refseqv1.0_chr7A"),
            )
            self.assertTrue(Path(db_prefix + ".nhr").exists())
            self.assertTrue(Path(db_prefix + ".nsi").exists())
            self.assertTrue(any("已有 -parse_seqids BLAST 库" in msg for msg in logs))

    def _write_script(self, path: Path, body: str) -> None:
        path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _build_sequences(self) -> tuple[str, str, str, str]:
        target = list("A" * 80)
        for index in range(20, 30):
            target[index] = "C"
        target[38:44] = list("GATATC")
        homeolog = target.copy()
        for index in range(20, 30):
            homeolog[index] = "T"
        homeolog[41] = "G"
        target_seq = "".join(target)
        homeolog_seq = "".join(homeolog)
        input_seq = target_seq[:41] + "[A/G]" + target_seq[42:]
        blast_seq = target_seq[:41] + "R" + target_seq[42:]
        return target_seq, homeolog_seq, input_seq, blast_seq


if __name__ == "__main__":
    unittest.main()
