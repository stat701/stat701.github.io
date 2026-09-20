from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import validate_slide_pdf


def completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)


class ValidateSlidePdfTests(unittest.TestCase):
    def test_qpdf_warnings_continue_through_render_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            def fake_run(arguments, *, timeout):
                if arguments[0] == "qpdf":
                    return completed(
                        stderr=(
                            "WARNING: slides.pdf (object 12 0): object has offset 0\n"
                            "operation succeeded with warnings\n"
                        ),
                        returncode=3,
                    )
                if arguments[0] == "pdfinfo" and "-js" not in arguments:
                    return completed(
                        stdout=(
                            "Producer:        macOS Quartz PDFContext\n"
                            "Encrypted:       no\n"
                            "Pages:           2\n"
                        )
                    )
                if arguments[0] == "pdfinfo" and "-js" in arguments:
                    return completed()
                if arguments[0] == "pdfdetach":
                    return completed(stdout="0 embedded files\n")
                if arguments[0] == "pdftoppm":
                    prefix = Path(arguments[-1])
                    prefix.with_name("page-1.png").write_bytes(b"page")
                    prefix.with_name("page-2.png").write_bytes(b"page")
                    return completed()
                raise AssertionError(arguments)

            with mock.patch.object(validate_slide_pdf, "_run_tool", side_effect=fake_run):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 0)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn('"status": "passed"', report_text)
            self.assertIn('"qpdf_exit_code": 3', report_text)
            self.assertIn("object has offset 0", report_text)

    def test_qpdf_error_writes_failed_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            with mock.patch.object(
                validate_slide_pdf,
                "_run_tool",
                return_value=completed(stderr="broken xref\n", returncode=2),
            ):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 1)
            report_text = report.read_text(encoding="utf-8")
            self.assertIn('"status": "failed"', report_text)
            self.assertIn('"qpdf_exit_code": 2', report_text)
            self.assertIn("qpdf found a PDF structure error", report_text)

    def test_clean_qpdf_stdout_does_not_create_warning_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            def fake_run(arguments, *, timeout):
                if arguments[0] == "qpdf":
                    return completed(
                        stdout=(
                            "checking slides.pdf\n"
                            "PDF Version: 1.7\n"
                            "File is not encrypted\n"
                        )
                    )
                if arguments[0] == "pdfinfo" and "-js" not in arguments:
                    return completed(stdout="Encrypted: no\nPages: 1\n")
                if arguments[0] == "pdfinfo" and "-js" in arguments:
                    return completed()
                if arguments[0] == "pdfdetach":
                    return completed(stdout="0 embedded files\n")
                if arguments[0] == "pdftoppm":
                    prefix = Path(arguments[-1])
                    prefix.with_name("page-1.png").write_bytes(b"page")
                    return completed()
                raise AssertionError(arguments)

            with mock.patch.object(validate_slide_pdf, "_run_tool", side_effect=fake_run):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 0)
            self.assertIn('"qpdf_warnings": []', report.read_text(encoding="utf-8"))

    def test_warning_report_is_trimmed_to_byte_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = Path(temporary_directory) / "report.json"
            validate_slide_pdf._write_report(
                report,
                {
                    "schema_version": 1,
                    "head_sha": "a" * 40,
                    "submission_path": "assets/slides/fall-2026/fall-2026-05.pdf",
                    "status": "passed",
                    "qpdf_exit_code": 3,
                    "qpdf_warnings": ["WARNING: " + "\u202e" * 1_000] * 100,
                    "failure": None,
                    "producer": "producer",
                    "page_count": 1,
                    "rendered_count": 1,
                },
            )

            self.assertLessEqual(report.stat().st_size, validate_slide_pdf.MAX_REPORT_BYTES)

    def test_any_encrypted_yes_line_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            def fake_run(arguments, *, timeout):
                if arguments[0] == "qpdf":
                    return completed()
                if arguments[0] == "pdfinfo" and "-js" not in arguments:
                    return completed(stdout="Encrypted: no\nPages: 1\nEncrypted: yes\n")
                raise AssertionError(arguments)

            with mock.patch.object(validate_slide_pdf, "_run_tool", side_effect=fake_run):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 1)
            self.assertIn("Encrypted PDFs are not accepted", report.read_text(encoding="utf-8"))

    def test_duplicate_page_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            def fake_run(arguments, *, timeout):
                if arguments[0] == "qpdf":
                    return completed()
                if arguments[0] == "pdfinfo" and "-js" not in arguments:
                    return completed(stdout="Encrypted: no\nPages: 1\nPages: 2\n")
                if arguments[0] == "pdfinfo" and "-js" in arguments:
                    return completed()
                if arguments[0] == "pdfdetach":
                    return completed(stdout="0 embedded files\n")
                raise AssertionError(arguments)

            with mock.patch.object(validate_slide_pdf, "_run_tool", side_effect=fake_run):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 1)
            self.assertIn("Could not determine", report.read_text(encoding="utf-8"))

    def test_non_error_qpdf_exit_is_reported_as_incomplete_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "slides.pdf"
            pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
            report = root / "report.json"

            with mock.patch.object(
                validate_slide_pdf,
                "_run_tool",
                return_value=completed(stderr="killed\n", returncode=137),
            ):
                status = validate_slide_pdf.validate_slide_pdf(
                    pdf,
                    report_path=report,
                    head_sha="a" * 40,
                    submission_path="assets/slides/fall-2026/fall-2026-05.pdf",
                )

            self.assertEqual(status, 1)
            self.assertIn(
                "qpdf exited with status 137",
                report.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
