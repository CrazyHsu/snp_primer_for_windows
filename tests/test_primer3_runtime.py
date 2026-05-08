import unittest

from snp_primer_app.primer3_parser import parse_primer3_output_text
from snp_primer_app.primer3_runtime import parse_boulder_records, render_boulder_result


class Primer3RuntimeTest(unittest.TestCase):
    def test_parse_boulder_records_splits_records(self) -> None:
        records = parse_boulder_records(
            "\n".join(
                [
                    "SEQUENCE_ID=marker-left",
                    "SEQUENCE_TEMPLATE=AAACTG",
                    "PRIMER_PRODUCT_SIZE_RANGE=40-70 70-100",
                    "=",
                    "SEQUENCE_ID=marker-right",
                    "SEQUENCE_TEMPLATE=TTTGCA",
                    "=",
                ]
            )
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["SEQUENCE_ID"], "marker-left")
        self.assertEqual(records[1]["SEQUENCE_ID"], "marker-right")

    def test_render_boulder_result_round_trips_core_fields(self) -> None:
        text = render_boulder_result(
            "marker-left",
            {
                "PRIMER_PAIR_0_PENALTY": 1.0,
                "PRIMER_PAIR_0_COMPL_ANY": 0.0,
                "PRIMER_PAIR_0_COMPL_END": 0.0,
                "PRIMER_PAIR_0_PRODUCT_SIZE": 120,
                "PRIMER_LEFT_0_SEQUENCE": "CCCCCCCCCCCCCCCCCCCC",
                "PRIMER_LEFT_0": [11, 20],
                "PRIMER_LEFT_0_TM": 60.0,
                "PRIMER_LEFT_0_GC_PERCENT": 50.0,
                "PRIMER_LEFT_0_SELF_ANY_TH": 0.0,
                "PRIMER_LEFT_0_SELF_END_TH": 0.0,
                "PRIMER_LEFT_0_HAIRPIN_TH": 0.0,
                "PRIMER_LEFT_0_END_STABILITY": 0.0,
                "PRIMER_RIGHT_0_SEQUENCE": "GGGGGGGGGGGGGGGGGGGG",
                "PRIMER_RIGHT_0": [61, 20],
                "PRIMER_RIGHT_0_TM": 60.0,
                "PRIMER_RIGHT_0_GC_PERCENT": 50.0,
                "PRIMER_RIGHT_0_SELF_ANY_TH": 0.0,
                "PRIMER_RIGHT_0_SELF_END_TH": 0.0,
                "PRIMER_RIGHT_0_HAIRPIN_TH": 0.0,
                "PRIMER_RIGHT_0_END_STABILITY": 0.0,
            },
        )
        pairs = parse_primer3_output_text(text, 1)
        pair = pairs["marker-left-0"]
        self.assertEqual(pair.product_size, 120)
        self.assertEqual(pair.left.seq, "CCCCCCCCCCCCCCCCCCCC")
        self.assertEqual(pair.right.seq, "GGGGGGGGGGGGGGGGGGGG")

