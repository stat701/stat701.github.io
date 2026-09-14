from __future__ import annotations

import importlib.util
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

    def test_security_metadata_is_rejected(self) -> None:
        with self.assertRaisesRegex(private_slides.ValidationError, "Encrypted"):
            private_slides._extract_page_count("Pages: 2\nEncrypted: yes\n")

        def fake_js_run(command: list[str], **_kwargs: object) -> str:
            if command[:2] == ["qpdf", "--check"]:
                return ""
            if command[:1] == ["pdfinfo"] and "-js" not in command:
                return "Pages: 2\nEncrypted: no\n"
            if command[:2] == ["pdfinfo", "-js"]:
                return "OpenAction JavaScript\n"
            if command[:2] == ["pdfdetach", "-list"]:
                return "0 embedded files\n"
            if command[:1] == ["pdftoppm"]:
                return ""
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "fall-2026-01.pdf"
            pdf_path.write_bytes(sample_pdf())
            with mock.patch.object(private_slides, "_run", side_effect=fake_js_run):
                with self.assertRaisesRegex(private_slides.ValidationError, "JavaScript"):
                    private_slides.validate_pdf_with_tools(pdf_path)

        def fake_attachment_run(command: list[str], **_kwargs: object) -> str:
            if command[:2] == ["qpdf", "--check"]:
                return ""
            if command[:2] == ["pdfinfo", "-js"]:
                return ""
            if command[:2] == ["pdfdetach", "-list"]:
                return "1 embedded files\n1: payload.bin\n"
            if command[:1] == ["pdfinfo"]:
                return "Pages: 2\nEncrypted: no\n"
            if command[:1] == ["pdftoppm"]:
                return ""
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "fall-2026-01.pdf"
            pdf_path.write_bytes(sample_pdf())
            with mock.patch.object(private_slides, "_run", side_effect=fake_attachment_run):
                with self.assertRaisesRegex(private_slides.ValidationError, "embedded files"):
                    private_slides.validate_pdf_with_tools(pdf_path)

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
