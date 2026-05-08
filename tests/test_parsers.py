import unittest

from snp_primer_app.parsers import parse_polymarker_lines, render_blast_fasta


class ParsersTest(unittest.TestCase):
    def test_parse_polymarker_lines_normalizes_name_and_iupac(self) -> None:
        records = parse_polymarker_lines(
            [
                "IWB_50236,7A,AAACCC[A/G]TTT",
                "",
            ]
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.name, "IWB-50236")
        self.assertEqual(record.snp_index, 6)
        self.assertEqual(record.iupac_code, "R")
        self.assertEqual(record.blast_query_id, "IWB-50236_7A_R")
        self.assertEqual(record.blast_sequence, "AAACCCRTTT")

    def test_render_blast_fasta(self) -> None:
        records = parse_polymarker_lines(["Marker1,7B,TT[A/C]GG"])
        self.assertEqual(render_blast_fasta(records), ">Marker1_7B_M\nTTMGG\n")


if __name__ == "__main__":
    unittest.main()
