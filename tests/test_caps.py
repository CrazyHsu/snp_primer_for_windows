import unittest

from snp_primer_app.caps import parse_restriction_enzyme_lines, scan_caps_enzymes


class CapsTest(unittest.TestCase):
    def test_scan_caps_detects_direct_caps_enzyme(self) -> None:
        enzymes = parse_restriction_enzyme_lines(["EcoRV,15\tGATATC"])
        wild_seq = "AAAGATATCTTT"
        mut_seq = "AAAGACATCTTT"

        caps_list, dcaps_list = scan_caps_enzymes(enzymes, wild_seq, mut_seq, max_price=100)

        self.assertEqual([enzyme.name for enzyme in caps_list], ["EcoRV,15"])
        self.assertEqual(dcaps_list, [])


if __name__ == "__main__":
    unittest.main()
