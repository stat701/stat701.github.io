from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.validate_submission import (
    MAX_PDF_BYTES,
    ValidationError,
    main,
    parse_talk_document,
    validate_pdf_bytes,
    validate_submission,
    validate_talk_document,
)


INSTRUCTION_COMMENT = "<!-- Replace this comment with your abstract. -->"


def talk_text(
    *,
    record_id: str = "fall-2026-01",
    speaker: str = '"Ada Student"',
    title: str = '""',
    abstract: str = INSTRUCTION_COMMENT,
) -> str:
    return (
        "---\n"
        f"record_id: {record_id}\n"
        f"speaker: {speaker}\n"
        "date: 2026-08-31\n"
        "order: 1\n"
        "year_in_program: 3\n"
        "semester: fall-2026\n"
        f"title: {title}\n"
        "---\n\n"
        f"{abstract}\n"
    )


VALID_ABSTRACT = (
    "This talk introduces a useful approach to statistical inference and explains "
    "the central assumptions, computational strategy, and practical consequences "
    "through examples that connect the underlying theory to modern data analysis."
)


def fake_pdf() -> bytes:
    return b"%PDF-1.7\n" + (b"0" * 1_100) + b"\n%%EOF\n"


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

    def write_text(self, relative_path: str, content: str) -> None:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")


class TalkDocumentTests(unittest.TestCase):
    def test_parser_exposes_normalized_title_and_abstract(self) -> None:
        document = parse_talk_document(
            talk_text(
                title='"A Statistical Idea Worth Explaining"',
                abstract=INSTRUCTION_COMMENT + "\n\n" + VALID_ABSTRACT,
            )
        )

        self.assertEqual(document.title, "A Statistical Idea Worth Explaining")
        self.assertEqual(document.abstract, VALID_ABSTRACT)
        self.assertEqual(document.fields["record_id"], "fall-2026-01")

    def test_completed_document_preserves_immutable_front_matter(self) -> None:
        head = talk_text(
            title='"A Statistical Idea Worth Explaining"', abstract=VALID_ABSTRACT
        )

        document = validate_talk_document(
            base_text=talk_text(),
            head_text=head,
            expected_record_id="fall-2026-01",
        )

        self.assertEqual(document.abstract, VALID_ABSTRACT)

    def test_completed_base_is_locked_unless_maintainer_update_is_allowed(self) -> None:
        completed = talk_text(
            title='"A Statistical Idea Worth Explaining"', abstract=VALID_ABSTRACT
        )
        corrected = talk_text(
            title='"A Better Statistical Idea Worth Explaining"',
            abstract=VALID_ABSTRACT + " The revised framing is clearer for the audience.",
        )

        with self.assertRaisesRegex(ValidationError, "already published and locked"):
            validate_talk_document(
                base_text=completed,
                head_text=corrected,
                expected_record_id="fall-2026-01",
            )

        document = validate_talk_document(
            base_text=completed,
            head_text=corrected,
            expected_record_id="fall-2026-01",
            allow_completed_base=True,
        )
        self.assertEqual(document.title, "A Better Statistical Idea Worth Explaining")

    def test_immutable_field_change_is_rejected(self) -> None:
        head = talk_text(
            speaker='"A Different Student"',
            title='"A Statistical Idea Worth Explaining"',
            abstract=VALID_ABSTRACT,
        )

        with self.assertRaisesRegex(ValidationError, "speaker.*changed"):
            validate_talk_document(
                base_text=talk_text(),
                head_text=head,
                expected_record_id="fall-2026-01",
            )

    def test_placeholder_and_short_abstract_are_rejected(self) -> None:
        for abstract in ("Abstract forthcoming", "This is too short."):
            with self.subTest(abstract=abstract):
                with self.assertRaises(ValidationError):
                    validate_talk_document(
                        base_text=talk_text(),
                        head_text=talk_text(
                            title='"A Statistical Idea Worth Explaining"',
                            abstract=abstract,
                        ),
                        expected_record_id="fall-2026-01",
                    )

    def test_unsafe_markup_is_rejected(self) -> None:
        unsafe_abstracts = (
            VALID_ABSTRACT + " <script>alert(1)</script>",
            VALID_ABSTRACT + " {{ site.github }}",
            VALID_ABSTRACT + " [external resource](https://example.com)",
            VALID_ABSTRACT + " [external resource][target]\n[target]: javascript:alert(1)",
            VALID_ABSTRACT + "\n{: onclick=alert(1)}",
            VALID_ABSTRACT + "\n- injected list item",
        )
        for abstract in unsafe_abstracts:
            with self.subTest(abstract=abstract):
                with self.assertRaises(ValidationError):
                    validate_talk_document(
                        base_text=talk_text(),
                        head_text=talk_text(
                            title='"A Statistical Idea Worth Explaining"',
                            abstract=abstract,
                        ),
                        expected_record_id="fall-2026-01",
                    )

    def test_title_must_remain_double_quoted(self) -> None:
        with self.assertRaisesRegex(ValidationError, "double quotation marks"):
            parse_talk_document(talk_text(title="Unquoted title"))

        with self.assertRaisesRegex(ValidationError, "single line"):
            parse_talk_document(talk_text(title='"Encoded\\nnewline title"'))

    def test_statistical_comparison_symbols_are_allowed_in_prose(self) -> None:
        abstract = (
            VALID_ABSTRACT
            + " The discussion also distinguishes regimes where n < p from those "
            "where n > p and expressions such as P(X<Y), without treating these "
            "statistical comparisons as markup."
        )

        validate_talk_document(
            base_text=talk_text(),
            head_text=talk_text(
                title='"Inference When n < p"', abstract=abstract
            ),
            expected_record_id="fall-2026-01",
        )


class PdfTests(unittest.TestCase):
    def test_pdf_cap_matches_github_browser_upload_limit(self) -> None:
        self.assertEqual(MAX_PDF_BYTES, 25 * 1024 * 1024)

    def test_pdf_envelope_is_accepted(self) -> None:
        validate_pdf_bytes(fake_pdf())

    def test_non_pdf_and_truncated_pdf_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "PDF signature"):
            validate_pdf_bytes(b"not a pdf" + (b"0" * 1_100))
        with self.assertRaisesRegex(ValidationError, "end marker"):
            validate_pdf_bytes(b"%PDF-1.7\n" + (b"0" * 1_100))


class RepositoryDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = TemporaryGitRepository()
        self.repository.write_text("_talks/fall-2026-01.md", talk_text())
        self.base = self.repository.commit("Add talk stub")

    def tearDown(self) -> None:
        self.repository.close()

    def commit_completed_metadata(self) -> str:
        self.repository.write_text(
            "_talks/fall-2026-01.md",
            talk_text(
                title='"A Statistical Idea Worth Explaining"',
                abstract=VALID_ABSTRACT,
            ),
        )
        return self.repository.commit("Submit title and abstract")

    def test_one_metadata_file_is_accepted(self) -> None:
        self.repository.write_text(
            "_talks/fall-2026-01.md",
            talk_text(
                title='"A Statistical Idea Worth Explaining"',
                abstract=VALID_ABSTRACT,
            ),
        )
        head = self.repository.commit("Submit title and abstract")

        result = validate_submission(self.repository.path, self.base, head)

        self.assertEqual(result.submission_type, "metadata")
        self.assertEqual(result.record_id, "fall-2026-01")

    def test_published_metadata_is_locked_for_students_but_not_maintainers(self) -> None:
        published_base = self.commit_completed_metadata()
        self.repository.write_text(
            "_talks/fall-2026-01.md",
            talk_text(
                title='"A Better Statistical Idea Worth Explaining"',
                abstract=(
                    VALID_ABSTRACT
                    + " This correction makes the intended seminar framing explicit."
                ),
            ),
        )
        head = self.repository.commit("Correct published title and abstract")

        with self.assertRaisesRegex(ValidationError, "published and locked"):
            validate_submission(self.repository.path, published_base, head)

        result = validate_submission(
            self.repository.path,
            published_base,
            head,
            allow_published_updates=True,
        )
        self.assertEqual(result.submission_type, "metadata")

    def test_one_pdf_is_accepted(self) -> None:
        slides_base = self.commit_completed_metadata()
        self.repository.write_bytes(
            "assets/slides/fall-2026/fall-2026-01.pdf", fake_pdf()
        )
        head = self.repository.commit("Submit slides")

        result = validate_submission(self.repository.path, slides_base, head)

        self.assertEqual(result.submission_type, "slides")
        self.assertEqual(result.record_id, "fall-2026-01")

    def test_published_pdf_is_locked_for_students_but_not_maintainers(self) -> None:
        metadata_base = self.commit_completed_metadata()
        slide_path = "assets/slides/fall-2026/fall-2026-01.pdf"
        self.repository.write_bytes(slide_path, fake_pdf())
        published_base = self.repository.commit("Publish slides")
        replacement_pdf = b"%PDF-1.7\n" + (b"1" * 1_100) + b"\n%%EOF\n"
        self.repository.write_bytes(slide_path, replacement_pdf)
        head = self.repository.commit("Replace published slides")

        with self.assertRaisesRegex(ValidationError, "PDF is locked"):
            validate_submission(self.repository.path, published_base, head)

        result = validate_submission(
            self.repository.path,
            published_base,
            head,
            allow_published_updates=True,
        )
        self.assertEqual(result.submission_type, "slides")
        self.assertNotEqual(metadata_base, published_base)

    def test_pdf_before_completed_metadata_is_rejected(self) -> None:
        self.repository.write_bytes(
            "assets/slides/fall-2026/fall-2026-01.pdf", fake_pdf()
        )
        head = self.repository.commit("Submit slides before title and abstract")

        with self.assertRaisesRegex(ValidationError, "title and abstract before"):
            validate_submission(self.repository.path, self.base, head)

    def test_mixed_submission_is_rejected(self) -> None:
        self.repository.write_bytes(
            "assets/slides/fall-2026/fall-2026-01.pdf", fake_pdf()
        )
        self.repository.write_text("unrelated.txt", "not part of the submission\n")
        head = self.repository.commit("Mix unrelated content into submission")

        with self.assertRaisesRegex(ValidationError, "exactly one"):
            validate_submission(self.repository.path, self.base, head)

    def test_unknown_record_id_is_rejected(self) -> None:
        self.repository.write_bytes(
            "assets/slides/fall-2026/fall-2026-19.pdf", fake_pdf()
        )
        head = self.repository.commit("Use an unknown record ID")

        with self.assertRaisesRegex(ValidationError, "not valid"):
            validate_submission(self.repository.path, self.base, head)

    def test_maintainer_can_add_a_new_talk_record(self) -> None:
        self.repository.write_text(
            "_talks/fall-2026-18.md",
            "---\nrecord_id: fall-2026-18\nspeaker: 'A Student'\n"
            "date: 2026-08-24\norder: 2\nyear_in_program: 3\n"
            "semester: fall-2026\ntitle: \"An interesting idea\"\n---\n\n"
            "This is a sufficiently long abstract explaining the statistical idea clearly to readers.\n",
        )
        head = self.repository.commit("Add a scheduled talk record")

        result = validate_submission(
            self.repository.path, self.base, head, allow_new_records=True
        )

        self.assertEqual(result.submission_type, "metadata")
        self.assertEqual(result.record_id, "fall-2026-18")

    def test_non_submission_change_is_ignored(self) -> None:
        self.repository.write_text("maintainer-notes.txt", "ordinary site work\n")
        head = self.repository.commit("Update maintainer notes")

        result = validate_submission(self.repository.path, self.base, head)

        self.assertEqual(result.submission_type, "none")

    def test_cli_writes_github_action_outputs(self) -> None:
        slides_base = self.commit_completed_metadata()
        self.repository.write_bytes(
            "assets/slides/fall-2026/fall-2026-01.pdf", fake_pdf()
        )
        head = self.repository.commit("Submit slides for workflow output test")
        output_path = self.repository.path / "github-output.txt"

        with redirect_stdout(StringIO()):
            return_code = main(
                [
                    "--repo",
                    str(self.repository.path),
                    "--base",
                    slides_base,
                    "--head",
                    head,
                    "--github-output",
                    str(output_path),
                ]
            )

        self.assertEqual(return_code, 0)
        self.assertEqual(
            output_path.read_text(encoding="utf-8"),
            "submission_type=slides\n"
            "submission_path=assets/slides/fall-2026/fall-2026-01.pdf\n"
            "record_id=fall-2026-01\n",
        )

    def test_cli_allows_explicit_maintainer_correction(self) -> None:
        published_base = self.commit_completed_metadata()
        self.repository.write_text(
            "_talks/fall-2026-01.md",
            talk_text(
                title='"A Corrected Statistical Idea Worth Explaining"',
                abstract=VALID_ABSTRACT + " This is an instructor-approved correction.",
            ),
        )
        head = self.repository.commit("Correct published metadata through CLI")

        with redirect_stdout(StringIO()):
            return_code = main(
                [
                    "--repo",
                    str(self.repository.path),
                    "--base",
                    published_base,
                    "--head",
                    head,
                    "--allow-published-updates",
                ]
            )

        self.assertEqual(return_code, 0)

    def test_talk_file_deletion_is_rejected(self) -> None:
        (self.repository.path / "_talks/fall-2026-01.md").unlink()
        head = self.repository.commit("Delete talk stub")

        with self.assertRaisesRegex(ValidationError, "must modify"):
            validate_submission(self.repository.path, self.base, head)

    def test_maintainer_can_remove_a_scheduled_record(self) -> None:
        (self.repository.path / "_talks/fall-2026-01.md").unlink()
        head = self.repository.commit("Remove an unassigned schedule slot")

        result = validate_submission(
            self.repository.path, self.base, head, allow_schedule_changes=True
        )

        self.assertEqual(result.submission_type, "metadata")
        self.assertEqual(result.record_id, "fall-2026-01")


class ScheduleSwapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = TemporaryGitRepository()
        self.paths = ("_talks/fall-2026-13.md", "_talks/fall-2026-16.md")
        self.original = (
            talk_text(record_id="fall-2026-13", speaker='"Li Fan"').replace(
                "2026-08-31", "2026-11-09"
            ),
            talk_text(
                record_id="fall-2026-16",
                speaker='"Hun Kang"',
                title='"A Statistical Idea Worth Explaining"',
                abstract=INSTRUCTION_COMMENT + "\n\n" + VALID_ABSTRACT,
            ).replace("2026-08-31", "2026-11-16").replace("order: 1", "order: 2"),
        )
        self.swapped = (
            self.original[0].replace("2026-11-09", "2026-11-16").replace(
                "order: 1", "order: 2"
            ),
            self.original[1].replace("2026-11-16", "2026-11-09").replace(
                "order: 2", "order: 1"
            ),
        )
        self.write_documents(self.original)
        self.base = self.repository.commit("Add empty and completed scheduled talks")

    def tearDown(self) -> None:
        self.repository.close()

    def write_documents(self, documents: tuple[str, str]) -> None:
        for path, text in zip(self.paths, documents, strict=True):
            self.repository.write_text(path, text)

    def validate(self, head: str):
        return validate_submission(
            self.repository.path, self.base, head, allow_schedule_changes=True
        )

    def test_swap_preserves_empty_and_completed_talks_and_skips_student_review(self) -> None:
        self.write_documents(self.swapped)
        head = self.repository.commit("Swap two existing slots")

        result = self.validate(head)

        self.assertEqual(result.submission_type, "none")
        self.assertIsNone(result.path)
        self.assertIsNone(result.record_id)
        self.assertIn("trusted-maintainer schedule swap", result.message)
        output_path = self.repository.path / "github-output.txt"
        with redirect_stdout(StringIO()):
            return_code = main([
                "--repo", str(self.repository.path), "--base", self.base,
                "--head", head, "--allow-schedule-changes",
                "--github-output", str(output_path),
            ])
        self.assertEqual(return_code, 0)
        self.assertEqual(
            output_path.read_text(), "submission_type=none\nsubmission_path=\nrecord_id=\n"
        )

    def test_swap_requires_explicit_maintainer_permission(self) -> None:
        self.write_documents(self.swapped)
        head = self.repository.commit("Attempt student schedule swap")
        with self.assertRaisesRegex(ValidationError, "exactly one"):
            validate_submission(self.repository.path, self.base, head)

    def test_swap_rejects_changes_to_identity_title_body_comments_and_whitespace(self) -> None:
        edits = (
            ("record_id: fall-2026-16", "record_id: fall-2026-13"),
            ('speaker: "Hun Kang"', 'speaker: "Another Student"'),
            ("year_in_program: 3", "year_in_program: 2"),
            ("semester: fall-2026", "semester: fall-2027"),
            ("A Statistical Idea Worth Explaining", "A Different Talk Title"),
            (VALID_ABSTRACT, VALID_ABSTRACT + " An additional sentence."),
            (INSTRUCTION_COMMENT, "<!-- Changed instructions. -->"),
            ("\n\n", "\n\n\n"),
        )
        for before, after in edits:
            with self.subTest(edit=before):
                self.write_documents((self.swapped[0], self.swapped[1].replace(before, after)))
                head = self.repository.commit("Attempt content edit during swap")
                with self.assertRaises(ValidationError):
                    self.validate(head)
        self.write_documents((self.swapped[0], self.swapped[1].rstrip("\n")))
        head = self.repository.commit("Attempt trailing newline edit during swap")
        with self.assertRaisesRegex(ValidationError, "only date and order"):
            self.validate(head)

    def test_swap_rejects_invalid_dates_and_orders(self) -> None:
        for before, after in (
            ("2026-11-16", "2026-02-30"),
            ("2026-11-16", "20261116"),
            ("2026-11-16", "2026-1-16"),
            ("order: 2", "order: 3"),
            ("order: 2", "order: 02"),
        ):
            with self.subTest(value=after):
                self.write_documents((self.swapped[0].replace(before, after), self.swapped[1]))
                head = self.repository.commit("Attempt invalid scheduled slot")
                with self.assertRaisesRegex(ValidationError, "ISO dates|order must be"):
                    self.validate(head)

    def test_swap_requires_the_same_unique_slots(self) -> None:
        for new_date in ("2026-11-16", "2026-11-23"):
            with self.subTest(date=new_date):
                second = self.swapped[1].replace("2026-11-09", new_date).replace(
                    "order: 1", "order: 2"
                ).replace("\n", "\r\n")
                self.write_documents((self.swapped[0], second))
                head = self.repository.commit("Attempt duplicate or newly invented slot")
                with self.assertRaisesRegex(ValidationError, "permutation of unique"):
                    self.validate(head)

    def test_line_ending_normalization_alone_does_not_count_as_a_swap(self) -> None:
        self.write_documents(tuple(text.replace("\n", "\r\n") for text in self.original))
        head = self.repository.commit("Change line endings without moving slots")
        with self.assertRaisesRegex(ValidationError, "must change an assigned slot"):
            self.validate(head)

    def test_swap_allows_normalized_line_endings(self) -> None:
        self.write_documents(tuple(text.replace("\n", "\r\n") for text in self.swapped))
        head = self.repository.commit("Swap slots with normalized line endings")
        self.assertEqual(self.validate(head).submission_type, "none")

    def test_swap_rejects_unrelated_files(self) -> None:
        self.write_documents(self.swapped)
        self.repository.write_text("index.html", "an unrelated site edit\n")
        head = self.repository.commit("Mix site edit into swap")
        with self.assertRaisesRegex(ValidationError, "only modify existing assigned"):
            self.validate(head)

    def test_swap_rejects_added_talks(self) -> None:
        self.write_documents(self.swapped)
        self.repository.write_text("_talks/fall-2026-17.md", talk_text(record_id="fall-2026-17"))
        head = self.repository.commit("Mix new talk into swap")
        with self.assertRaisesRegex(ValidationError, "only modify existing assigned"):
            self.validate(head)

    def test_swap_rejects_deleted_talks(self) -> None:
        self.write_documents(self.swapped)
        (self.repository.path / self.paths[1]).unlink()
        head = self.repository.commit("Delete a talk instead of swapping it")
        with self.assertRaisesRegex(ValidationError, "only modify existing assigned"):
            self.validate(head)


if __name__ == "__main__":
    unittest.main()
