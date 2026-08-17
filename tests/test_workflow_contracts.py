from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DownstreamReviewWorkflowTests(unittest.TestCase):
    def test_closed_pull_request_is_a_clean_skip(self) -> None:
        workflows = (
            ROOT / ".github/workflows/review-submission.yml",
            ROOT / ".github/workflows/review-slides.yml",
        )
        for workflow in workflows:
            with self.subTest(workflow=workflow.name):
                source = workflow.read_text(encoding="utf-8")
                self.assertIn('if length == 0 then "none"', source)
                self.assertIn('echo "review_eligible=false"', source)
                self.assertIn('if [[ "$pull_request" == "ambiguous" ]]', source)

    def test_title_review_runs_only_for_an_eligible_open_pull_request(self) -> None:
        source = (ROOT / ".github/workflows/review-submission.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if: steps.pull_request.outputs.review_eligible == 'true'", source
        )


if __name__ == "__main__":
    unittest.main()
