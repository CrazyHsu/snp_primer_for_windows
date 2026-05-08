import tempfile
import unittest
from pathlib import Path

from snp_primer_app.flanking import (
    collect_flanking_targets,
    collect_flanking_targets_from_alignments,
    render_temp_range_file,
    write_marker_batches,
)
from snp_primer_app.models import BlastAlignment
from snp_primer_app.parsers import parse_polymarker_lines


class FlankingTest(unittest.TestCase):
    def test_collect_flanking_targets_keeps_same_chromosome_anchor(self) -> None:
        records = parse_polymarker_lines(["IWB50236,7A,AAACCC[A/G]TTT"])
        blast_lines = [
            "\t".join(
                [
                    "IWB50236_7A_R",
                    "chr7A",
                    "99.0",
                    "80",
                    "0",
                    "0",
                    "1",
                    "80",
                    "1000",
                    "1079",
                    "1e-30",
                    "100",
                    "AAACCCRTTT",
                    "AAACCCGTTT",
                    "2000",
                ]
            )
        ]

        targets = collect_flanking_targets(records, blast_lines, genome_number=3, flank_size=20)

        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.output_query_id, "IWB50236_7A_R_21")
        self.assertEqual(target.subject_id, "chr7A")
        self.assertEqual(target.range_start, 986)
        self.assertEqual(target.range_end, 1026)
        self.assertEqual(target.strand, "plus")
        self.assertEqual(
            render_temp_range_file(targets),
            "IWB50236_7A_R_21\tchr7A\t986-1026\tplus\n",
        )

    def test_collect_flanking_targets_accepts_remote_chromosome_hint(self) -> None:
        records = parse_polymarker_lines(["IWB50236,7A,AAACCC[A/G]TTT"])
        alignments = [
            BlastAlignment(
                query_id="IWB50236_7A_R",
                subject_id="XM_12345",
                alignment_length=80,
                mismatches=0,
                gap_opens=0,
                query_start=1,
                query_end=80,
                subject_start=1000,
                subject_end=1079,
                query_sequence="AAACCCRTTT",
                subject_sequence="AAACCCGTTT",
                subject_length=2000,
                subject_title="Triticum aestivum chromosome 7A scaffold",
                subject_chromosome="7A",
            )
        ]

        targets = collect_flanking_targets_from_alignments(records, alignments, genome_number=3, flank_size=20)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].subject_chromosome, "7A")

    def test_write_marker_batches_groups_multiple_hits_for_one_marker(self) -> None:
        records = parse_polymarker_lines(["IWB50236,7A,AAACCC[A/G]TTT"])
        blast_lines = [
            "\t".join(
                [
                    "IWB50236_7A_R",
                    "chr7A",
                    "99.0",
                    "80",
                    "0",
                    "0",
                    "1",
                    "80",
                    "1000",
                    "1079",
                    "1e-30",
                    "100",
                    "AAACCCRTTT",
                    "AAACCCGTTT",
                    "2000",
                ]
            ),
            "\t".join(
                [
                    "IWB50236_7A_R",
                    "chr7B",
                    "99.0",
                    "80",
                    "0",
                    "0",
                    "1",
                    "80",
                    "2000",
                    "2079",
                    "1e-30",
                    "100",
                    "AAACCCRTTT",
                    "AAACCCTTTT",
                    "3000",
                ]
            ),
        ]
        targets = collect_flanking_targets(records, blast_lines, genome_number=3, flank_size=20)

        with tempfile.TemporaryDirectory() as tmpdir:
            written = write_marker_batches(targets, tmpdir)
            self.assertEqual(len(written), 1)
            batch_text = Path(written[0]).read_text(encoding="utf-8")
            self.assertIn("chr7A", batch_text)
            self.assertIn("chr7B", batch_text)


if __name__ == "__main__":
    unittest.main()
