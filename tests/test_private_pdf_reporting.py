from __future__ import annotations

import copy
import io
import json
import unittest
import zipfile
from typing import Any, Mapping

from scripts import report_pdf_validation as reporter


REPOSITORY = "stat701/private-slides-fall-2026-01"
PDF_PATH = "fall-2026-01.pdf"
RUN_ID = 12345
HEAD_SHA = "a" * 40


def validation_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "head_sha": HEAD_SHA,
        "submission_path": PDF_PATH,
        "status": "passed",
        "qpdf_exit_code": 3,
        "qpdf_warnings": ["WARNING: slides.pdf (object 12 0): object has offset 0"],
        "failure": None,
        "producer": "sample PDF exporter",
        "page_count": 2,
        "rendered_count": 2,
    }
    report.update(overrides)
    return report


def bot_comment() -> dict[str, Any]:
    return {
        "id": 7,
        "body": reporter.COMMENT_MARKER + "\nPrevious diagnostics",
        "user": {
            "id": 41898282,
            "login": "github-actions[bot]",
            "type": "Bot",
        },
    }


class FakePrivateGitHubClient:
    """GitHub fixture whose repository metadata and PR head can change mid-run."""

    def __init__(self, *, repository: str = REPOSITORY) -> None:
        self.repository = repository
        self.metadata = {
            "full_name": repository,
            "private": True,
            "default_branch": "main",
        }
        self.metadata_before_post: Mapping[str, Any] | None = None
        self.metadata_reads = 0
        self.pull_reads = 0
        self.head_before_post: str | None = None
        self.run: dict[str, Any] = {
            "event": "pull_request",
            "path": ".github/workflows/validate-private-slides.yml",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 2,
            "head_sha": HEAD_SHA,
            "head_branch": "upload-slides",
            "repository": {"full_name": repository},
            "head_repository": {
                "full_name": repository,
                "owner": {"login": "stat701"},
            },
        }
        self.pull: dict[str, Any] = {
            "number": 1,
            "head": {"sha": HEAD_SHA, "repo": {"full_name": repository}},
            "base": {"ref": "main", "repo": {"full_name": repository}},
        }
        self.files = [{"filename": PDF_PATH, "status": "added"}]
        self.report = validation_report()
        self.artifact_name = "pdf-validation-report-2"
        self.archive_member = "report.json"
        self.comments: list[Mapping[str, Any]] = []
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
        root = f"/repos/{self.repository}"
        if path == root and method == "GET":
            self.metadata_reads += 1
            if self.metadata_reads > 1 and self.metadata_before_post is not None:
                return copy.deepcopy(self.metadata_before_post)
            return copy.deepcopy(self.metadata)
        if path == f"{root}/actions/runs/{RUN_ID}" and method == "GET":
            return copy.deepcopy(self.run)
        if path == f"{root}/pulls" and method == "GET":
            self.pull_reads += 1
            pull = copy.deepcopy(self.pull)
            if self.pull_reads > 1 and self.head_before_post is not None:
                pull["head"]["sha"] = self.head_before_post
            return [pull]
        if path == f"{root}/pulls/1/files" and method == "GET":
            return copy.deepcopy(self.files)
        if path == f"{root}/actions/runs/{RUN_ID}/artifacts" and method == "GET":
            return {
                "artifacts": [
                    {
                        "name": self.artifact_name,
                        "expired": False,
                        "archive_download_url": (
                            f"https://api.github.com{root}/actions/artifacts/123/zip"
                        ),
                    }
                ]
            }
        if path == f"{root}/issues/1/comments":
            if method == "GET":
                return copy.deepcopy(self.comments)
            if method == "POST":
                self.comments.append({"id": 99, "body": body["body"]})
                return {}
        if path == f"{root}/issues/comments/7" and method == "PATCH":
            self.comments[0] = dict(self.comments[0]) | {"body": body["body"]}
            return {}
        raise AssertionError((method, path, query, body))

    def download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        self.requests.append(("GET", url, None))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(self.archive_member, json.dumps(self.report))
        return buffer.getvalue()

    def writes(self) -> list[tuple[str, str, Mapping[str, object] | None]]:
        return [request for request in self.requests if request[0] in {"POST", "PATCH"}]


class PrivatePdfReportingTests(unittest.TestCase):
    def report(self, client: FakePrivateGitHubClient) -> int:
        return reporter.report_pdf_validation(
            client=client, repository=client.repository, run_id=RUN_ID, private=True
        )

    def assert_rejected_without_writes(self, client: FakePrivateGitHubClient) -> None:
        with self.assertRaises(reporter.ReporterError):
            self.report(client)
        self.assertEqual(client.writes(), [])

    def assert_instructor_only(self, body: str) -> None:
        self.assertIn("instructor", body.casefold())
        self.assertIn("no ai review", body.casefold())

    def test_warned_private_pdf_posts_diagnostics_only_in_private_repository(self) -> None:
        client = FakePrivateGitHubClient()

        self.assertEqual(self.report(client), 0)

        self.assertEqual(len(client.writes()), 1)
        method, path, payload = client.writes()[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, f"/repos/{REPOSITORY}/issues/1/comments")
        body = str(payload["body"])
        self.assertIn("start of the file", body)
        self.assertIn("No new export is required", body)
        self.assertIn("object has offset 0", body)
        self.assert_instructor_only(body)
        self.assertGreaterEqual(client.metadata_reads, 2)

    def test_failed_private_pdf_explains_failure_and_instructor_only_review(self) -> None:
        client = FakePrivateGitHubClient()
        client.run["conclusion"] = "failure"
        client.report = validation_report(
            status="failed",
            failure="PDF could not be rendered. Export a new PDF and try again.",
            rendered_count=0,
        )

        self.assertEqual(self.report(client), 0)

        body = str(client.writes()[0][2]["body"])
        self.assertIn("PDF could not be rendered", body)
        self.assertIn("same pull-request branch", body)
        self.assert_instructor_only(body)

    def test_modified_private_pdf_can_update_a_previous_diagnostic(self) -> None:
        client = FakePrivateGitHubClient()
        client.files[0]["status"] = "modified"
        client.report = validation_report(qpdf_exit_code=0, qpdf_warnings=[])
        client.comments = [bot_comment()]

        self.assertEqual(self.report(client), 0)

        self.assertEqual([write[0] for write in client.writes()], ["PATCH"])
        body = str(client.writes()[0][2]["body"])
        self.assertIn("passes without qpdf warnings", body)
        self.assert_instructor_only(body)

    def test_clean_private_pdf_needs_no_diagnostic_comment(self) -> None:
        client = FakePrivateGitHubClient()
        client.report = validation_report(qpdf_exit_code=0, qpdf_warnings=[])
        self.assertEqual(self.report(client), 0)
        self.assertEqual(client.writes(), [])

    def test_private_mode_rejects_repositories_outside_the_course_allowlist(self) -> None:
        for repository in (
            "other/private-slides-fall-2026-01",
            "stat701/private-slides-fall-2026-00",
            "stat701/private-slides-fall-2026-19",
            "stat701/stat701.github.io",
        ):
            with self.subTest(repository=repository):
                self.assert_rejected_without_writes(FakePrivateGitHubClient(repository=repository))

    def test_repository_metadata_must_confirm_exact_private_main_repository(self) -> None:
        for overrides in (
            {"full_name": "stat701/private-slides-fall-2026-02"},
            {"private": False},
            {"private": "true"},
            {"private": 1},
            {"default_branch": "student-branch"},
        ):
            with self.subTest(overrides=overrides):
                client = FakePrivateGitHubClient()
                client.metadata.update(overrides)
                self.assert_rejected_without_writes(client)

    def test_repository_becoming_public_prevents_both_post_and_update(self) -> None:
        for existing_comment in (False, True):
            with self.subTest(existing_comment=existing_comment):
                client = FakePrivateGitHubClient()
                client.metadata_before_post = client.metadata | {"private": False}
                if existing_comment:
                    client.comments = [bot_comment()]
                self.assert_rejected_without_writes(client)
                self.assertGreaterEqual(client.metadata_reads, 2)

    def test_only_the_matching_root_pdf_can_receive_a_private_report(self) -> None:
        for path in (
            "fall-2026-02.pdf",
            "nested/fall-2026-01.pdf",
            "assets/slides/fall-2026/fall-2026-01.pdf",
            "../fall-2026-01.pdf",
            "fall-2026-01.PDF",
        ):
            with self.subTest(path=path):
                client = FakePrivateGitHubClient()
                client.files[0]["filename"] = path
                client.report["submission_path"] = path
                self.assert_rejected_without_writes(client)

    def test_deleted_renamed_or_multifile_changes_cannot_receive_a_report(self) -> None:
        for files in (
            [{"filename": PDF_PATH, "status": "removed"}],
            [{"filename": PDF_PATH, "status": "renamed"}],
            [
                {"filename": PDF_PATH, "status": "added"},
                {"filename": "README.md", "status": "modified"},
            ],
        ):
            with self.subTest(files=files):
                client = FakePrivateGitHubClient()
                client.files = files
                self.assert_rejected_without_writes(client)

    def test_public_or_student_workflow_cannot_post_private_diagnostics(self) -> None:
        for path in (
            ".github/workflows/validate-submission.yml",
            ".github/workflows/student-controlled.yml",
        ):
            with self.subTest(path=path):
                client = FakePrivateGitHubClient()
                client.run["path"] = path
                self.assert_rejected_without_writes(client)

    def test_another_repository_run_or_pr_cannot_receive_a_report(self) -> None:
        for target in ("run", "pull"):
            with self.subTest(target=target):
                client = FakePrivateGitHubClient()
                if target == "run":
                    client.run["repository"]["full_name"] = "stat701/private-slides-fall-2026-02"
                else:
                    client.pull["base"]["repo"]["full_name"] = "stat701/private-slides-fall-2026-02"
                self.assert_rejected_without_writes(client)

    def test_head_changed_before_posting_cannot_receive_stale_diagnostics(self) -> None:
        client = FakePrivateGitHubClient()
        client.head_before_post = "b" * 40
        self.assert_rejected_without_writes(client)
        self.assertEqual(client.pull_reads, 2)

    def test_invalid_or_misbound_report_schema_cannot_receive_a_comment(self) -> None:
        for overrides in (
            {"unexpected": "field"},
            {"schema_version": True},
            {"qpdf_exit_code": True},
            {"head_sha": "b" * 40},
            {"submission_path": "fall-2026-02.pdf"},
            {"rendered_count": 1},
        ):
            with self.subTest(overrides=overrides):
                client = FakePrivateGitHubClient()
                client.report.update(overrides)
                self.assert_rejected_without_writes(client)

    def test_an_earlier_run_attempt_artifact_does_not_produce_a_comment(self) -> None:
        client = FakePrivateGitHubClient()
        client.artifact_name = "pdf-validation-report-1"
        self.assertEqual(self.report(client), 0)
        self.assertEqual(client.writes(), [])

    def test_forged_archive_member_names_cannot_receive_a_comment(self) -> None:
        for member in ("../report.json", "nested/report.json", "report.json.py"):
            with self.subTest(member=member):
                client = FakePrivateGitHubClient()
                client.archive_member = member
                self.assert_rejected_without_writes(client)

    def test_forged_bot_comments_are_preserved_and_new_diagnostic_is_posted(self) -> None:
        for user in (
            {"id": 123, "login": "sample-student", "type": "User"},
            {"id": 123, "login": "github-actions[bot]", "type": "Bot"},
            {"id": 41898282, "login": "other[bot]", "type": "Bot"},
        ):
            with self.subTest(user=user):
                client = FakePrivateGitHubClient()
                forged = bot_comment() | {"user": user}
                client.comments = [forged]
                self.assertEqual(self.report(client), 0)
                self.assertEqual([write[0] for write in client.writes()], ["POST"])
                self.assertEqual(client.comments[0], forged)


if __name__ == "__main__":
    unittest.main()
