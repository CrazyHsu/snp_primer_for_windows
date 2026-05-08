import unittest

from snp_primer_app.alignment import analyze_alignment, parse_fasta_text, parse_marker_metadata


class AlignmentTest(unittest.TestCase):
    def test_parse_marker_metadata_uses_trailing_segments(self) -> None:
        metadata = parse_marker_metadata("/tmp/anything_flanking_temp_marker_TEST_7A_R_41.fa")

        self.assertEqual(metadata.snpname, "TEST")
        self.assertEqual(metadata.chrom, "7A")
        self.assertEqual(metadata.allele, "R")
        self.assertEqual(metadata.pos, 41)

    def test_analyze_alignment_finds_positions_differing_from_all_homeologs(self) -> None:
        target = "A" * 25 + "C" + "A" * 24 + "G" + "A" * 25
        homeolog = "A" * 25 + "T" + "A" * 24 + "T" + "A" * 25
        fasta = parse_fasta_text(f">chr7A-0\n{target}\n>chr7B-1\n{homeolog}\n")

        analysis = analyze_alignment(fasta, "chr7A-0", ["chr7B-1"], snp_site=40)

        self.assertIn(25, analysis.variation)
        self.assertIn(50, analysis.variation)
        self.assertEqual(analysis.target_id, "chr7A-0")


if __name__ == "__main__":
    unittest.main()
