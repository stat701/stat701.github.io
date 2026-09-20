from __future__ import annotations

import io
import json
import unittest
import zipfile
from typing import Any, Mapping

from scripts.report_pdf_validation import (
    COMMENT_MARKER,
    ReporterError,
    _comment_body,
    _validate_report,
    report_pdf_validation,
)


REPOSITORY = "stat701/stat701.github.io"
RUN_ID = 12345
HEAD_SHA = "a" * 40
PDF_PATH = "assets/slides/fall-2026/fall-2026-05.pdf"


def zip_report(report: Mapping[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("report.json", json.dumps(report))
    return buffer.getvalue()


def run_payload(*, head_sha: str = HEAD_SHA) -> dict[str, Any]:
    return {
        "event": "pull_request",
        "path": ".github/workflows/validate-submission.yml",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 2,
        "head_sha": head_sha,
        "head_branch": "slides",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {
            "full_name": "student/slides",
            "owner": {"login": "student"},
        },
    }


def pr_payload(*, head_sha: str = HEAD_SHA) -> dict[str, Any]:
    return {
        "number": 43,
        "head": {
            "sha": head_sha,
            "repo": {"full_name": "student/slides"},
        },
        "base": {
            "ref": "main",
            "repo": {"full_name": REPOSITORY},
        },
    }


def clean_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "head_sha": HEAD_SHA,
        "submission_path": PDF_PATH,
        "status": "passed",
        "qpdf_exit_code": 0,
        "qpdf_warnings": [],
        "failure": None,
        "producer": "macOS Quartz PDFContext",
        "page_count": 28,
        "rendered_count": 28,
    }
    report.update(overrides)
    return report


class FakeGitHubClient:
    def __init__(
        self,
        *,
        run: Mapping[str, Any] | None = None,
        pull: Mapping[str, Any] | None = None,
        report: Mapping[str, Any] | None = None,
        comments: list[Mapping[str, Any]] | None = None,
    ) -> None:
        self.run = dict(run or run_payload())
        self.pull = dict(pull or pr_payload())
        self.report = dict(report or clean_report())
        self.comments = list(comments or [])
        self.requests: list[tuple[str, str, Mapping[str, object] | None]] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> Any:
        self.requests.append((method, path, body))
        if path == f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}":
            return self.run
        if path == f"/repos/{REPOSITORY}/pulls":
            return [self.pull]
        if path == f"/repos/{REPOSITORY}/pulls/43/files":
            return [{"filename": PDF_PATH, "status": "added"}]
        if path == f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts":
            return {
                "artifacts": [
                    {
                        "name": "pdf-validation-report-2",
                        "expired": False,
                        "archive_download_url": (
                            f"https://api.github.com/repos/{REPOSITORY}/actions/"
                            "artifacts/123/zip"
                        ),
                    }
                ]
            }
        if path == f"/repos/{REPOSITORY}/issues/43/comments":
            if method == "GET":
                return self.comments
            if method == "POST":
                self.comments.append(
                    {
                        "id": 99,
                        "body": body["body"] if body else "",
                        "user": {
                            "id": 41898282,
                            "login": "github-actions[bot]",
                            "type": "Bot",
                        },
                    }
                )
                return {}
        if path == f"/repos/{REPOSITORY}/issues/comments/7" and method == "PATCH":
            self.comments[0] = {
                "id": 7,
                "body": body["body"] if body else "",
                "user": {
                    "id": 41898282,
                    "login": "github-actions[bot]",
                    "type": "Bot",
                },
            }
            return {}
        raise AssertionError((method, path, query, body))

    def download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        self.requests.append(("GET", url, None))
        return zip_report(self.report)


class ReportPdfValidationTests(unittest.TestCase):
    def test_posts_known_warning_comment_from_current_run_artifact(self) -> None:
        client = FakeGitHubClient(
            report=clean_report(
                qpdf_exit_code=3,
                qpdf_warnings=[
                    "WARNING: slides.pdf (object 12 0): object has offset 0",
                ],
            )
        )

        status = report_pdf_validation(
            client=client, repository=REPOSITORY, run_id=RUN_ID
        )

        self.assertEqual(status, 0)
        posts = [request for request in client.requests if request[0] == "POST"]
        self.assertEqual(len(posts), 1)
        body = str(posts[0][2]["body"])
        self.assertIn(COMMENT_MARKER, body)
        self.assertIn("start of the file", body)
        self.assertIn("No new export is required", body)
        self.assertIn("does not prove", body)

    def test_rejects_stale_report_sha(self) -> None:
        binding = type("Binding", (), {"head_sha": HEAD_SHA, "path": PDF_PATH})()
        with self.assertRaisesRegex(ReporterError, "does not match"):
            _validate_report(
                clean_report(head_sha="b" * 40),
                binding=binding,
            )

    def test_rejects_bool_as_integer(self) -> None:
        binding = type("Binding", (), {"head_sha": HEAD_SHA, "path": PDF_PATH})()
        with self.assertRaisesRegex(ReporterError, "qpdf exit code"):
            _validate_report(
                clean_report(qpdf_exit_code=True),
                binding=binding,
            )

    def test_ignores_student_marker_and_posts_bot_comment(self) -> None:
        client = FakeGitHubClient(
            report=clean_report(
                qpdf_exit_code=3,
                qpdf_warnings=["unknown warning"],
            ),
            comments=[
                {
                    "id": 7,
                    "body": COMMENT_MARKER,
                    "user": {"login": "student", "type": "User"},
                }
            ],
        )

        report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)

        posts = [request for request in client.requests if request[0] == "POST"]
        patches = [request for request in client.requests if request[0] == "PATCH"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(patches, [])

    def test_updates_existing_bot_comment_with_resolved_clean_pass(self) -> None:
        client = FakeGitHubClient(
            comments=[
                {
                    "id": 7,
                    "body": COMMENT_MARKER + "\nold warning",
                    "user": {
                        "id": 41898282,
                        "login": "github-actions[bot]",
                        "type": "Bot",
                    },
                }
            ]
        )

        report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)

        patches = [request for request in client.requests if request[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertIn("passes without qpdf warnings", str(patches[0][2]["body"]))

    def test_comment_escapes_warning_metadata_and_mentions(self) -> None:
        body = _comment_body(
            repository=REPOSITORY,
            run_id=RUN_ID,
            binding=type("Binding", (), {"number": 43, "head_sha": HEAD_SHA, "path": PDF_PATH})(),
            report=clean_report(
                qpdf_exit_code=3,
                qpdf_warnings=["WARNING <script>@student</script>"],
                producer="bad <producer> @all",
            ),
            run_conclusion="success",
        )

        self.assertNotIn("<script>", body)
        self.assertNotIn("@student", body)
        self.assertIn("&lt;script&gt;&#64;student&lt;/script&gt;", body)
        self.assertIn("bad &lt;producer&gt; &#64;all", body)


if __name__ == "__main__":
    unittest.main()
