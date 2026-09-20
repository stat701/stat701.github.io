from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import report_pdf_validation as reporter
from scripts import validate_slide_pdf as validator
from tests.test_report_pdf_validation import (
    HEAD_SHA,
    PDF_PATH,
    REPOSITORY,
    RUN_ID,
    FakeGitHubClient,
    clean_report,
    pr_payload,
    run_payload,
)


def warning_report():
    return clean_report(qpdf_exit_code=3, qpdf_warnings=["WARNING: object has offset 0"])


def tool_results(*, failure=None, warnings="WARNING: object has offset 0\n"):
    def run(arguments, **kwargs):
        command = arguments[0]
        if command == "qpdf":
            return subprocess.CompletedProcess(arguments, 3, "", warnings)
        if command == "pdfinfo":
            text = (
                "alert('unsafe');" if failure == "javascript" else ""
            ) if "-js" in arguments else "Producer: Quartz\nEncrypted: no\nPages: 2\n"
            return subprocess.CompletedProcess(arguments, 0, text, "")
        if command == "pdfdetach":
            text = "1 embedded files\n" if failure == "attachment" else "0 embedded files\n"
            return subprocess.CompletedProcess(arguments, 0, text, "")
        if command == "pdftoppm":
            if failure == "render":
                return subprocess.CompletedProcess(arguments, 1, "", "render failed")
            prefix = Path(arguments[-1])
            for page in range(1, 2 if failure == "missing_page" else 3):
                prefix.with_name(f"page-{page}.png").write_bytes(b"rendered page")
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(arguments)

    return run


class PdfReportingBoundaryTests(unittest.TestCase):
    def run_validator(self, *, side_effect):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report_path = Path(directory) / "report.json"
            with (
                mock.patch.object(validator.subprocess, "run", side_effect=side_effect),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                status = validator.validate_slide_pdf(
                    pdf,
                    report_path=report_path,
                    head_sha=HEAD_SHA,
                    submission_path=PDF_PATH,
                )
            encoded = report_path.read_bytes()
        report = json.loads(encoded)
        reporter._validate_report(
            report, binding=reporter.PullRequestBinding(43, HEAD_SHA, PDF_PATH)
        )
        return status, report, encoded

    def assert_no_comment_writes(self, client):
        self.assertEqual(
            [method for method, _, _ in client.requests if method in {"POST", "PATCH"}],
            [],
        )

    def test_qpdf_warnings_do_not_bypass_security_or_render_failures(self):
        for failure, expected in (
            ("javascript", "JavaScript"),
            ("attachment", "embedded files"),
            ("render", "could not be rendered"),
            ("missing_page", "Expected 2 rendered pages"),
        ):
            with self.subTest(failure=failure):
                status, report, _ = self.run_validator(side_effect=tool_results(failure=failure))
                self.assertEqual(status, 1)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["qpdf_exit_code"], 3)
                self.assertIn(expected, report["failure"])

    def test_subprocess_timeout_preserves_a_failed_report(self):
        for command in ("qpdf", "pdftoppm"):
            with self.subTest(command=command):
                success = tool_results()

                def run(arguments, **kwargs):
                    if arguments[0] == command:
                        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])
                    return success(arguments, **kwargs)

                status, report, _ = self.run_validator(side_effect=run)
                self.assertEqual(status, 1)
                self.assertEqual(report["status"], "failed")
                self.assertIn(f"{command} timed out", report["failure"])

    def test_large_unicode_warnings_produce_a_report_the_reporter_accepts(self):
        warnings = ("WARNING: " + "\U0001f4c4\u202e" * 1_000 + "\n") * 100
        status, report, encoded = self.run_validator(side_effect=tool_results(warnings=warnings))
        self.assertEqual(status, 0)
        self.assertTrue(report["qpdf_warnings"])
        self.assertLessEqual(len(encoded), reporter.MAX_REPORT_BYTES)

    def test_untrusted_run_identity_cannot_post_or_update(self):
        for override in (
            {"event": "push"},
            {"path": ".github/workflows/student-controlled.yml"},
            {"repository": {"full_name": "student/other-repository"}},
        ):
            with self.subTest(override=override):
                client = FakeGitHubClient(run=run_payload() | override, report=warning_report())
                with self.assertRaises(reporter.ReporterError):
                    reporter.report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)
                self.assert_no_comment_writes(client)

    def test_absent_report_is_a_benign_skip(self):
        class NoArtifactClient(FakeGitHubClient):
            def request_json(self, method, path, **kwargs):
                if path.endswith("/artifacts"):
                    self.requests.append((method, path, None))
                    return {"artifacts": []}
                return super().request_json(method, path, **kwargs)

        client = NoArtifactClient(report=warning_report())
        status = reporter.report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)
        self.assertEqual(status, 0)
        self.assert_no_comment_writes(client)

    def test_head_changed_before_comment_prevents_a_stale_write(self):
        class ChangedHeadClient(FakeGitHubClient):
            bindings = 0

            def request_json(self, method, path, **kwargs):
                if path == f"/repos/{REPOSITORY}/pulls":
                    self.bindings += 1
                    if self.bindings == 2:
                        self.pull = pr_payload(head_sha="b" * 40)
                return super().request_json(method, path, **kwargs)

        client = ChangedHeadClient(report=warning_report())
        with self.assertRaises(reporter.ReporterError):
            reporter.report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)
        self.assertEqual(client.bindings, 2)
        self.assert_no_comment_writes(client)

    def test_archive_member_and_size_boundaries_prevent_comment_writes(self):
        class ArchiveClient(FakeGitHubClient):
            def download_bytes(self, url, *, max_bytes):
                return archive

        for members in (
            {"../report.json": json.dumps(warning_report())},
            {"nested/report.json": json.dumps(warning_report())},
            {"report.json": json.dumps(warning_report()), "extra.txt": "extra"},
            {"report.json": " " * (reporter.MAX_REPORT_BYTES + 1)},
        ):
            with self.subTest(members=list(members)):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
                    for filename, content in members.items():
                        zipped.writestr(filename, content)
                archive = buffer.getvalue()
                client = ArchiveClient(report=warning_report())
                with self.assertRaises(reporter.ReporterError):
                    reporter.report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)
                self.assert_no_comment_writes(client)

    def test_another_bot_cannot_claim_the_diagnostic_comment(self):
        for user in (
            {"id": 1234, "login": "other[bot]", "type": "Bot"},
            {"id": 1234, "login": "github-actions[bot]", "type": "Bot"},
        ):
            with self.subTest(user=user):
                client = FakeGitHubClient(
                    report=warning_report(),
                    comments=[{"id": 7, "body": reporter.COMMENT_MARKER, "user": user}],
                )
                reporter.report_pdf_validation(client=client, repository=REPOSITORY, run_id=RUN_ID)
                writes = [method for method, _, _ in client.requests if method in {"POST", "PATCH"}]
                self.assertEqual(writes, ["POST"])


if __name__ == "__main__":
    unittest.main()
