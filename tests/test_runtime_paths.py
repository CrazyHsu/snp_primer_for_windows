import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from snp_primer_app.runtime_paths import default_reference_fasta, ensure_runtime_dirs


class RuntimePathsTest(unittest.TestCase):
    def test_runtime_dirs_follow_env_root_and_find_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"SNP_PRIMER_HOME": tmpdir}
            with patch.dict(os.environ, env, clear=False):
                runtime_dirs = ensure_runtime_dirs()
                self.assertTrue(runtime_dirs["bin"].exists())
                self.assertTrue(runtime_dirs["workspace"].exists())
                self.assertTrue(runtime_dirs["references"].exists())

                reference = Path(tmpdir) / "references" / "demo" / "genome.fa"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text(">chr1\nACGT\n", encoding="utf-8")

                self.assertEqual(default_reference_fasta(), str(reference.resolve()))


if __name__ == "__main__":
    unittest.main()
