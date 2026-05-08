import unittest

from snp_primer_app.primer3_parser import parse_primer3_output_text


class Primer3ParserTest(unittest.TestCase):
    def test_parse_single_primer_pair(self) -> None:
        text = """
SEQUENCE_ID=Marker1-left
PRIMER_PAIR_0_PENALTY=1.23
PRIMER_PAIR_0_COMPL_ANY=0.0
PRIMER_PAIR_0_COMPL_END=0.0
PRIMER_PAIR_0_PRODUCT_SIZE=123
PRIMER_LEFT_0_SEQUENCE=ACGTACGTACGTACGTACGT
PRIMER_LEFT_0=10,20
PRIMER_LEFT_0_TM=60.1
PRIMER_LEFT_0_GC_PERCENT=50.0
PRIMER_RIGHT_0_SEQUENCE=TGCATGCATGCATGCATGCA
PRIMER_RIGHT_0=140,20
PRIMER_RIGHT_0_TM=60.2
PRIMER_RIGHT_0_GC_PERCENT=50.0
"""
        primerpairs = parse_primer3_output_text(text, primerpair_to_return=1)
        pair = primerpairs["Marker1-left-0"]

        self.assertEqual(pair.product_size, 123)
        self.assertEqual(pair.left.start, 10)
        self.assertEqual(pair.left.end, 29)
        self.assertEqual(pair.right.start, 140)
        self.assertEqual(pair.right.end, 121)
        self.assertEqual(pair.left.seq, "ACGTACGTACGTACGTACGT")


if __name__ == "__main__":
    unittest.main()
