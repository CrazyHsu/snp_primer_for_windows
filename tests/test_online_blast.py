import json
import unittest

from snp_primer_app.online_blast import normalize_query_id, parse_ncbi_json_results


class OnlineBlastTest(unittest.TestCase):
    def test_normalize_query_id_prefers_header_token(self) -> None:
        self.assertEqual(normalize_query_id(">IWB50236_7A_R some title"), "IWB50236_7A_R")

    def test_parse_ncbi_json_results_keeps_original_query_title(self) -> None:
        payload = {
            "BlastOutput2": [
                {
                    "report": {
                        "results": {
                            "search": {
                                "query_id": "Query_1947736",
                                "query_title": "IWB50236_7A_R",
                                "hits": [
                                    {
                                        "description": [
                                            {
                                                "accession": "NW_123",
                                                "title": "Triticum aestivum chromosome 7A genomic scaffold",
                                            }
                                        ],
                                        "len": 5000,
                                        "hsps": [
                                            {
                                                "align_len": 101,
                                                "query_from": 1,
                                                "query_to": 101,
                                                "hit_from": 500,
                                                "hit_to": 600,
                                                "qseq": "A" * 101,
                                                "hseq": "A" * 101,
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    }
                }
            ]
        }

        alignments = parse_ncbi_json_results(json.dumps(payload))
        self.assertEqual(len(alignments), 1)
        self.assertEqual(alignments[0].query_id, "IWB50236_7A_R")
        self.assertEqual(alignments[0].subject_chromosome, "7A")


if __name__ == "__main__":
    unittest.main()
