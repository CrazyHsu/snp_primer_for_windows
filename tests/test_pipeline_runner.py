import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

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
                while [ "$#" -gt 0 ]; do
                  if [ "$1" = "-in" ]; then
                    infile="$2"
                    shift 2
                  else
                    shift
                  fi
                done
                touch "${infile}.nin" "${infile}.nsq" "${infile}.nhr"
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
                cat <<'EOF'
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
