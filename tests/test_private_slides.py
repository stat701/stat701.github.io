from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "templates"
    / "private-slides"
    / "scripts"
    / "validate_private_slides.py"
)
SPEC = importlib.util.spec_from_file_location("validate_private_slides", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
private_slides = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = private_slides
SPEC.loader.exec_module(private_slides)


class TemporaryGitRepository:
    def __init__(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Validator Test")
        self.git("config", "user.email", "validator@example.invalid")

    def close(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def write_text(self, relative_path: str, content: str) -> None:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def symlink(self, relative_path: str, target: str) -> None:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")


def sample_pdf(page_count: int = 2) -> bytes:
    page_refs: list[bytes] = []
    page_objects: list[bytes] = []
    content_objects: list[bytes] = []
    font_object_id = 3 + 2 * page_count
    for index in range(page_count):
        page_object_id = 3 + index * 2
        content_object_id = 4 + index * 2
        page_refs.append(f"{page_object_id} 0 R".encode())
        page_objects.append(
            (
                f"{page_object_id} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
                f"/Contents {content_object_id} 0 R "
                f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> >>\n"
                "endobj\n"
            ).encode()
        )
        stream = f"BT /F1 18 Tf 50 100 Td (Page {index + 1}) Tj ET\n".encode()
        content_objects.append(
            (
                f"{content_object_id} 0 obj\n"
                f"<< /Length {len(stream)} >>\n"
                "stream\n"
            ).encode()
            + stream
            + b"endstream\nendobj\n"
        )

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids ["
        + b" ".join(page_refs)
        + f"] /Count {page_count} >>\nendobj\n".encode(),
    ]
    for page_object, content_object in zip(page_objects, content_objects, strict=True):
        objects.extend([page_object, content_object])
    objects.append(
        (
            f"{font_object_id} 0 obj\n"
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
            "endobj\n"
        ).encode()
    )

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for pdf_object in objects:
        offsets.append(len(output))
        output.extend(pdf_object)

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def simulated_pdf_tools(scenario: str = "success"):
    def run(command, *, timeout):
        stdout, stderr, returncode = "", "", 0
        if command[0] == "qpdf":
            stderr = "WARNING: slide.pdf (object 12 0): object has offset 0\noperation succeeded with warnings\n"
            returncode = 3
        elif command[0] == "pdfinfo" and "-js" not in command:
            encrypted = "yes" if scenario == "encrypted" else "no"
            pages = {"empty": 0, "too_many_pages": 201}.get(scenario, 2)
            stdout = f"Producer: PowerPoint\nEncrypted: {encrypted}\nPages: {pages}\n"
        elif command[0] == "pdfinfo" and "-js" in command:
            stdout = "PRIVATE_SLIDE_SENTINEL" if scenario == "javascript" else ""
        elif command[0] == "pdfdetach":
            stdout = "1 embedded files\n1: PRIVATE_SLIDE_SENTINEL" if scenario == "attachments" else "0 embedded files\n"
        elif command[0] == "pdftoppm":
            if scenario == "render_failure":
                returncode = 1
            else:
                prefix = Path(command[-1])
                prefix.with_name("page-1.png").write_bytes(b"PRIVATE_SLIDE_SENTINEL")
                if scenario != "missing_page":
                    prefix.with_name("page-2.png").write_bytes(b"PRIVATE_SLIDE_SENTINEL")
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    return run


class PrivateSlideValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = TemporaryGitRepository()
        self.repository.write_text("README.md", "Private slide upload repository.\n")
        self.base = self.repository.commit("Initial private slide repository")

    def tearDown(self) -> None:
        self.repository.close()

    def validate_without_tools(self, base: str | None = None) -> object:
        return private_slides.validate_private_slides(
            self.repository.path,
            base or self.base,
            self.repository.git("rev-parse", "HEAD"),
            "fall-2026-01",
            check_pdf_tools=False,
        )

    def test_exact_root_record_pdf_is_accepted(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        head = self.repository.commit("Submit private slides")

        result = private_slides.validate_private_slides(
            self.repository.path,
            self.base,
            head,
            "fall-2026-01",
            check_pdf_tools=False,
        )

        self.assertEqual(result.path, "fall-2026-01.pdf")
        self.assertEqual(result.record_id, "fall-2026-01")

    def test_wrong_filename_is_rejected_even_if_pdf_is_valid(self) -> None:
        self.repository.write_bytes("slides.pdf", sample_pdf())
        self.repository.commit("Submit wrong filename")

        with self.assertRaisesRegex(private_slides.ValidationError, "fall-2026-01.pdf"):
            self.validate_without_tools()

    def test_extra_changed_or_deleted_file_is_rejected(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        self.repository.write_text("notes.txt", "extra change\n")
        self.repository.commit("Submit slides with notes")

        with self.assertRaisesRegex(private_slides.ValidationError, "exactly one"):
            self.validate_without_tools()

        repository = TemporaryGitRepository()
        try:
            repository.write_text("old.txt", "remove me\n")
            base = repository.commit("Add file that will be deleted")
            (repository.path / "old.txt").unlink()
            repository.write_bytes("fall-2026-01.pdf", sample_pdf())
            head = repository.commit("Submit slides and delete a file")
            with self.assertRaisesRegex(private_slides.ValidationError, "exactly one"):
                private_slides.validate_private_slides(
                    repository.path,
                    base,
                    head,
                    "fall-2026-01",
                    check_pdf_tools=False,
                )
        finally:
            repository.close()

    def test_deleted_pdf_and_symlink_pdf_are_rejected(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        pdf_base = self.repository.commit("Add existing PDF")
        (self.repository.path / "fall-2026-01.pdf").unlink()
        self.repository.commit("Delete PDF")

        with self.assertRaisesRegex(private_slides.ValidationError, "add or modify"):
            self.validate_without_tools(base=pdf_base)

        repository = TemporaryGitRepository()
        try:
            repository.write_text("README.md", "Private slide upload repository.\n")
            base = repository.commit("Initial private slide repository")
            repository.symlink("fall-2026-01.pdf", "/tmp/elsewhere.pdf")
            head = repository.commit("Submit symlink PDF")
            with self.assertRaisesRegex(private_slides.ValidationError, "normal file"):
                private_slides.validate_private_slides(
                    repository.path,
                    base,
                    head,
                    "fall-2026-01",
                    check_pdf_tools=False,
                )
        finally:
            repository.close()

    def test_non_pdf_envelope_is_rejected(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", b"not a pdf" + (b"x" * 46))
        self.repository.commit("Submit renamed non PDF")

        with self.assertRaisesRegex(private_slides.ValidationError, "PDF signature"):
            self.validate_without_tools()

    def test_head_blob_is_validated_even_when_worktree_differs(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        head = self.repository.commit("Submit private slides")
        self.repository.write_bytes("fall-2026-01.pdf", b"not a pdf" + (b"x" * 1_100))

        result = private_slides.validate_private_slides(
            self.repository.path,
            self.base,
            head,
            "fall-2026-01",
            check_pdf_tools=False,
        )

        self.assertEqual(result.path, "fall-2026-01.pdf")

    def test_structure_failure_produces_a_fresh_bounded_report(self) -> None:
        self.repository.write_bytes("slides.pdf", sample_pdf())
        head = self.repository.commit("Submit wrong filename")
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.json"
            report_path.write_text('{"status": "passed"}', encoding="utf-8")
            with self.assertRaisesRegex(private_slides.ValidationError, "fall-2026-01.pdf"):
                private_slides.validate_private_slides(
                    self.repository.path, self.base, head, "fall-2026-01",
                    report_path=report_path,
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["head_sha"], head)
            self.assertEqual(report["submission_path"], "fall-2026-01.pdf")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["qpdf_warnings"], [])
            for field in ("qpdf_exit_code", "producer", "page_count", "rendered_count"):
                self.assertIsNone(report[field])
            self.assertLessEqual(report_path.stat().st_size, 60_000)

    def test_oversized_and_invalid_envelope_pdfs_stop_before_tools(self) -> None:
        for content, maximum, expected in (
            (sample_pdf(), 10, "maximum accepted size"),
            (b"private slide text is not PDF", private_slides.MAX_PDF_BYTES, "PDF signature"),
            (b"%PDF-1.7\nprivate slide text", private_slides.MAX_PDF_BYTES, "end marker"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                self.repository.write_bytes("fall-2026-01.pdf", content)
                head = self.repository.commit("Submit malformed private slides")
                report_path = Path(temporary) / "report.json"
                with mock.patch.object(private_slides, "MAX_PDF_BYTES", maximum), mock.patch.object(
                    private_slides.pdf_validation, "_run_tool"
                ) as run_tool:
                    with self.assertRaisesRegex(private_slides.ValidationError, expected):
                        private_slides.validate_private_slides(
                            self.repository.path, self.base, head, "fall-2026-01",
                            report_path=report_path,
                        )
                run_tool.assert_not_called()
                report_text = report_path.read_text(encoding="utf-8")
                report = json.loads(report_text)
                self.assertEqual(report["status"], "failed")
                self.assertIn(expected, report["failure"])
                self.assertNotIn("private slide text", report_text)

    def test_warning_pdf_runs_all_checks_and_preserves_private_report_identity(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        head = self.repository.commit("Submit private slides with a structural warning")
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.json"
            with mock.patch.object(
                private_slides.pdf_validation, "_run_tool",
                side_effect=simulated_pdf_tools(),
            ) as run_tool:
                result = private_slides.validate_private_slides(
                    self.repository.path, self.base, head, "fall-2026-01",
                    report_path=report_path,
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(result.page_count, 2)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["head_sha"], head)
            self.assertEqual(report["submission_path"], "fall-2026-01.pdf")
            self.assertEqual(report["qpdf_exit_code"], 3)
            self.assertIn("object has offset 0", report["qpdf_warnings"][0])
            self.assertEqual(report["rendered_count"], 2)
            self.assertEqual(
                [call.args[0][0] for call in run_tool.call_args_list],
                ["qpdf", "pdfinfo", "pdfinfo", "pdfdetach", "pdftoppm"],
            )
            self.assertEqual(list(Path(temporary).iterdir()), [report_path])

    def test_qpdf_fatal_error_stops_checks_and_retains_diagnostic_report(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf())
        head = self.repository.commit("Submit private slides")
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.json"
            with mock.patch.object(
                private_slides.pdf_validation, "_run_tool",
                return_value=subprocess.CompletedProcess("qpdf", 2, "", "broken xref"),
            ) as run_tool:
                with self.assertRaisesRegex(private_slides.ValidationError, "PDF structure error"):
                    private_slides.validate_private_slides(
                        self.repository.path, self.base, head, "fall-2026-01",
                        report_path=report_path,
                    )
            run_tool.assert_called_once()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["qpdf_exit_code"], 2)
            self.assertIn("broken xref", report["failure"])

    def test_qpdf_warning_never_bypasses_security_page_count_or_render_failures(self) -> None:
        cases = (
            ("encrypted", "Encrypted PDFs"),
            ("javascript", "JavaScript"),
            ("attachments", "embedded files"),
            ("empty", "between 1 and 200"),
            ("too_many_pages", "between 1 and 200"),
            ("render_failure", "could not be rendered"),
            ("missing_page", "produced 1"),
        )
        for scenario, expected in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                pdf_path = Path(temporary) / "fall-2026-01.pdf"
                pdf_path.write_bytes(sample_pdf())
                report_path = Path(temporary) / "report.json"
                captured = io.StringIO()
                with mock.patch.object(
                    private_slides.pdf_validation, "_run_tool",
                    side_effect=simulated_pdf_tools(scenario),
                ), contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    with self.assertRaisesRegex(private_slides.ValidationError, expected):
                        private_slides.validate_pdf_with_tools(
                            pdf_path, report_path=report_path,
                            head_sha="a" * 40, submission_path=pdf_path.name,
                        )
                report_text = report_path.read_text(encoding="utf-8")
                report = json.loads(report_text)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["qpdf_exit_code"], 3)
                self.assertIn(expected, report["failure"])
                self.assertNotIn("PRIVATE_SLIDE_SENTINEL", report_text + captured.getvalue())

    def test_tool_timeouts_fail_and_write_diagnostics_after_a_warning(self) -> None:
        for timed_out in ("qpdf", "pdftoppm"):
            with self.subTest(tool=timed_out), tempfile.TemporaryDirectory() as temporary:
                pdf_path = Path(temporary) / "fall-2026-01.pdf"
                pdf_path.write_bytes(sample_pdf())
                report_path = Path(temporary) / "report.json"
                fake_tools = simulated_pdf_tools()

                def fake_subprocess_run(command, **kwargs):
                    if command[0] == timed_out:
                        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
                    return fake_tools(command, timeout=kwargs["timeout"])

                with mock.patch.object(
                    private_slides.pdf_validation.subprocess, "run",
                    side_effect=fake_subprocess_run,
                ):
                    with self.assertRaisesRegex(private_slides.ValidationError, "timed out"):
                        private_slides.validate_pdf_with_tools(pdf_path, report_path=report_path)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "failed")
                self.assertIn(timed_out, report["failure"])
                self.assertEqual(report["qpdf_exit_code"], None if timed_out == "qpdf" else 3)

    @unittest.skipUnless(
        all(shutil.which(tool) for tool in ("qpdf", "pdfinfo", "pdfdetach", "pdftoppm")),
        "qpdf and Poppler are required for PDF integration validation",
    )
    def test_installed_cli_accepts_real_offset_zero_warning_and_uses_trusted_engine(self) -> None:
        warning_pdf = (
            sample_pdf(page_count=2)
            .replace(b"xref\n0 8\n", b"xref\n0 9\n")
            .replace(b"trailer\n", b"0000000000 00000 n \ntrailer\n")
            .replace(b"/Size 8 ", b"/Size 9 ")
        )
        self.repository.write_bytes("fall-2026-01.pdf", warning_pdf)
        head = self.repository.commit("Submit PDF with an unused zero-offset object")
        # An untracked module in the untrusted working directory cannot replace
        # the shared engine beside the installed, trusted validator.
        self.repository.write_text(
            "validate_slide_pdf.py", "raise RuntimeError('UNTRUSTED_ENGINE_EXECUTED')\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            trusted_scripts = Path(temporary) / "trusted" / "scripts"
            trusted_scripts.mkdir(parents=True)
            for name in ("validate_private_slides.py", "validate_slide_pdf.py"):
                shutil.copyfile(SCRIPT_PATH.with_name(name), trusted_scripts / name)
            report_path = Path(temporary) / "report.json"
            result = subprocess.run(
                [
                    sys.executable, str(trusted_scripts / "validate_private_slides.py"),
                    "--repo", str(self.repository.path), "--base", self.base,
                    "--head", head, "--record-id", "fall-2026-01",
                    "--report", str(report_path),
                ],
                cwd=self.repository.path, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("UNTRUSTED_ENGINE_EXECUTED", result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["head_sha"], head)
            self.assertEqual(report["submission_path"], "fall-2026-01.pdf")
            self.assertEqual(report["qpdf_exit_code"], 3)
            self.assertIn("object has offset 0", "\n".join(report["qpdf_warnings"]))
            self.assertEqual(report["page_count"], 2)
            self.assertEqual(report["rendered_count"], 2)

    @unittest.skipUnless(
        all(shutil.which(tool) for tool in ("qpdf", "pdfinfo", "pdfdetach", "pdftoppm")),
        "qpdf and Poppler are required for PDF integration validation",
    )
    def test_real_pdf_is_checked_and_rendered_when_tools_are_available(self) -> None:
        self.repository.write_bytes("fall-2026-01.pdf", sample_pdf(page_count=2))
        head = self.repository.commit("Submit renderable private slides")

        result = private_slides.validate_private_slides(
            self.repository.path,
            self.base,
            head,
            "fall-2026-01",
        )

        self.assertEqual(result.page_count, 2)


if __name__ == "__main__":
    unittest.main()
