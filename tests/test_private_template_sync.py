import unittest

from scripts.sync_private_slide_template import ROOT, SHARED_SCRIPTS


class PrivateTemplateSyncTests(unittest.TestCase):
    def test_public_pdf_fixes_are_distributed_to_private_repositories(self):
        for name in SHARED_SCRIPTS:
            with self.subTest(script=name):
                source = ROOT / "scripts" / name
                bundled = ROOT / "templates/private-slides/scripts" / name
                self.assertTrue(
                    bundled.is_file(),
                    "Run python scripts/sync_private_slide_template.py before committing.",
                )
                self.assertEqual(
                    source.read_bytes(),
                    bundled.read_bytes(),
                    "Run python scripts/sync_private_slide_template.py before committing.",
                )


if __name__ == "__main__":
    unittest.main()
