#!/usr/bin/env python3
"""Validate one STA 701S student submission between two Git commits.

The validator intentionally uses only the Python standard library.  It is
designed to be both a command-line check for GitHub Actions and an importable
module for later review steps.

Student pull requests may change exactly one of the following:

* ``_talks/fall-2026-XX.md`` for a title-and-abstract submission; or
* ``assets/slides/fall-2026/fall-2026-XX.pdf`` for a slides submission.

Pull requests with no changes under either submission directory are ignored so
that maintainers can use the same check on ordinary site changes.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


VALID_RECORD_IDS = tuple(f"fall-2026-{number:02d}" for number in range(1, 17))
VALID_RECORD_ID_SET = frozenset(VALID_RECORD_IDS)

EXPECTED_FRONT_MATTER_FIELDS = (
    "record_id",
    "speaker",
    "date",
    "order",
    "year_in_program",
    "semester",
    "title",
)

TALK_PATH_RE = re.compile(
    r"\A_talks/(?P<record_id>fall-2026-(?:0[1-9]|1[0-6]))\.md\Z"
)
SLIDES_PATH_RE = re.compile(
    r"\Aassets/slides/fall-2026/"
    r"(?P<record_id>fall-2026-(?:0[1-9]|1[0-6]))\.pdf\Z"
)
FRONT_MATTER_LINE_RE = re.compile(r"\A([A-Za-z][A-Za-z0-9_-]*): (.*)\Z")
HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WORD_RE = re.compile(r"[^\W\d_]+(?:[-'\u2019][^\W\d_]+)*", re.UNICODE)

MIN_TITLE_CHARACTERS = 8
MAX_TITLE_CHARACTERS = 200
MIN_ABSTRACT_CHARACTERS = 80
MIN_ABSTRACT_WORDS = 12
MAX_ABSTRACT_CHARACTERS = 5_000
MAX_METADATA_BYTES = 32 * 1024
MIN_PDF_BYTES = 1_024
# Match GitHub's 25 MiB browser-upload limit so the documented browser-only
# submission workflow cannot produce a deck that GitHub refuses to upload.
# This also remains comfortably below OpenAI's 50,000,000-byte file limit.
MAX_PDF_BYTES = 25 * 1024 * 1024


class ValidationError(Exception):
    """A student-facing validation failure."""


class GitCommandError(Exception):
    """An operational failure while reading the Git repository."""


@dataclasses.dataclass(frozen=True)
class TalkDocument:
    """Parsed data from one strict talk Markdown document.

    ``abstract`` excludes an unchanged instructional HTML comment, if one is
    present.  Keeping this parser public lets a later AI reviewer consume the
    same normalized title and abstract that deterministic validation used.
    """

    front_matter_lines: tuple[str, ...]
    fields: Mapping[str, str]
    title: str
    raw_body: str
    abstract: str
    html_comments: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    submission_type: str
    path: str | None
    record_id: str | None
    message: str


def _decode_quoted_title(raw_value: str) -> str:
    """Decode the required JSON-style double-quoted YAML title scalar."""

    if not (raw_value.startswith('"') and raw_value.endswith('"')):
        raise ValidationError(
            'The title must remain inside double quotation marks, for example '
            'title: "A clear and informative title".'
        )

    try:
        title = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValidationError(
            "The quoted title is malformed. Escape any double quotation mark "
            "inside the title with a backslash."
        ) from error

    if not isinstance(title, str):
        raise ValidationError("The title must be text inside double quotation marks.")
    if (
        CONTROL_CHARACTER_RE.search(title)
        or "\n" in title
        or "\r" in title
        or "\t" in title
    ):
        raise ValidationError("The title must be a single line without control characters.")
    try:
        title.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValidationError("The title contains an invalid Unicode character.") from error
    return title


def _split_body_comments(body: str) -> tuple[str, tuple[str, ...]]:
    comments = tuple(HTML_COMMENT_RE.findall(body))
    without_comments = HTML_COMMENT_RE.sub("\n", body)
    if "<!--" in without_comments or "-->" in without_comments:
        raise ValidationError("The abstract contains an incomplete HTML comment.")
    return without_comments.strip(), comments


def parse_talk_document(text: str) -> TalkDocument:
    """Parse a talk document using the repository's intentionally small schema.

    This function validates document structure but does not require a completed
    title or abstract, which allows it to parse the base repository's empty
    student stubs.  Use :func:`validate_talk_document` for a completed
    submission.
    """

    if text.startswith("\ufeff"):
        raise ValidationError("Remove the byte-order mark at the start of the file.")
    if CONTROL_CHARACTER_RE.search(text):
        raise ValidationError("The talk file contains an unsupported control character.")

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValidationError("The talk file must begin with an unchanged '---' line.")

    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise ValidationError("The talk file is missing its closing '---' line.") from error

    front_matter_lines = tuple(lines[1:closing_index])
    parsed_fields: dict[str, str] = {}
    field_order: list[str] = []

    for line in front_matter_lines:
        match = FRONT_MATTER_LINE_RE.fullmatch(line)
        if not match:
            raise ValidationError(
                "Every front-matter line must retain the simple 'field: value' "
                "format; lists, comments, and multiline values are not allowed."
            )
        key, raw_value = match.groups()
        if key in parsed_fields:
            raise ValidationError(f"The front matter contains duplicate field '{key}'.")
        parsed_fields[key] = raw_value
        field_order.append(key)

    if tuple(field_order) != EXPECTED_FRONT_MATTER_FIELDS:
        expected = ", ".join(EXPECTED_FRONT_MATTER_FIELDS)
        raise ValidationError(
            "The front-matter fields or their order changed. The required order is: "
            f"{expected}."
        )

    title = _decode_quoted_title(parsed_fields["title"])
    raw_body = "\n".join(lines[closing_index + 1 :])
    abstract, comments = _split_body_comments(raw_body)

    return TalkDocument(
        front_matter_lines=front_matter_lines,
        fields=parsed_fields,
        title=title,
        raw_body=raw_body,
        abstract=abstract,
        html_comments=comments,
    )


def _normalized_placeholder_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _looks_like_placeholder(value: str) -> bool:
    normalized = _normalized_placeholder_text(value)
    exact_placeholders = {
        "abstract",
        "abstract here",
        "coming soon",
        "forthcoming",
        "n a",
        "none",
        "placeholder",
        "tba",
        "tbd",
        "title",
        "title here",
        "to be announced",
        "to be determined",
        "todo",
    }
    placeholder_phrases = (
        "abstract forthcoming",
        "abstract goes here",
        "insert abstract",
        "insert title",
        "lorem ipsum",
        "title forthcoming",
        "your abstract here",
        "your title here",
    )
    return normalized in exact_placeholders or any(
        phrase in normalized for phrase in placeholder_phrases
    )


def _validate_plain_prose(value: str, label: str) -> None:
    """Reject active/site-structural Markdown while allowing ordinary prose."""

    if "\t" in value:
        raise ValidationError(f"The {label} may not contain tab characters.")
    if "{{" in value or "{%" in value or "}}" in value or "%}" in value:
        raise ValidationError(f"The {label} may not contain Jekyll/Liquid markup.")
    if re.search(r"<(?:/?[A-Za-z]|!|\?)[^<>]*>", value):
        raise ValidationError(f"The {label} may not contain HTML markup.")
    if "`" in value:
        raise ValidationError(f"The {label} may not contain inline or fenced code.")
    if re.search(r"!?\[[^\]]*\]\s*\([^)]*\)", value):
        raise ValidationError(f"The {label} may not contain Markdown links or images.")
    if re.search(r"!?\[[^\]]*\]\s*\[[^\]]*\]", value) or re.search(
        r"(?m)^\s{0,3}\[[^\]]+\]:", value
    ):
        raise ValidationError(f"The {label} may not contain Markdown reference links.")
    if re.search(r"\b(?:https?|ftp)://", value, flags=re.IGNORECASE):
        raise ValidationError(f"The {label} may not contain external URLs.")
    if re.search(r"\b(?:javascript|data|vbscript):", value, flags=re.IGNORECASE):
        raise ValidationError(f"The {label} may not contain active URI schemes.")
    if "{:" in value or "{::" in value:
        raise ValidationError(f"The {label} may not contain Kramdown extensions.")

    structural_line = re.compile(
        r"(?m)^(?:\s{0,3}#{1,6}\s|\s{0,3}>\s|\s{0,3}(?:[-+*]|\d+[.)])\s|"
        r"\s{0,3}(?:```|~~~)|[ \t]{0,3}(?:[-*_][ \t]*){3,}$| {4}\S)"
    )
    if structural_line.search(value):
        raise ValidationError(
            f"Write the {label} as ordinary prose, without headings, lists, "
            "block quotes, or code blocks."
        )


def validate_talk_document(
    *,
    base_text: str,
    head_text: str,
    expected_record_id: str,
    allow_completed_base: bool = False,
) -> TalkDocument:
    """Validate a completed title-and-abstract submission.

    Every front-matter line other than ``title`` must be byte-for-byte
    unchanged after line-ending normalization.  The body may replace the base
    instruction comment with ordinary prose, or may leave that exact comment
    in place alongside the prose.
    """

    base = parse_talk_document(base_text)
    head = parse_talk_document(head_text)

    if expected_record_id not in VALID_RECORD_ID_SET:
        raise ValidationError(f"Unknown record ID '{expected_record_id}'.")
    if base.fields["record_id"] != expected_record_id:
        raise ValidationError(
            "The base talk file's record_id does not match its filename; ask a "
            "maintainer to repair the stub."
        )
    if head.fields["record_id"] != expected_record_id:
        raise ValidationError("The record_id must match the talk filename.")

    if not allow_completed_base and (base.title or base.abstract):
        raise ValidationError(
            "The title and abstract are already published and locked against "
            "further student edits. Contact the instructor if a correction is "
            "needed."
        )

    title_index = EXPECTED_FRONT_MATTER_FIELDS.index("title")
    for index, (base_line, head_line) in enumerate(
        zip(base.front_matter_lines, head.front_matter_lines, strict=True)
    ):
        if index != title_index and base_line != head_line:
            field = EXPECTED_FRONT_MATTER_FIELDS[index]
            raise ValidationError(
                f"Protected front-matter field '{field}' changed. Restore it "
                "exactly to the value on the base branch."
            )

    title = head.title.strip()
    if title != head.title:
        raise ValidationError("Remove leading or trailing whitespace from the title.")
    if not (MIN_TITLE_CHARACTERS <= len(title) <= MAX_TITLE_CHARACTERS):
        raise ValidationError(
            f"The title must contain {MIN_TITLE_CHARACTERS}–"
            f"{MAX_TITLE_CHARACTERS} characters."
        )
    if sum(character.isalpha() for character in title) < 5:
        raise ValidationError("The title must contain meaningful words.")
    if _looks_like_placeholder(title):
        raise ValidationError("Replace the placeholder with the actual talk title.")
    _validate_plain_prose(title, "title")

    if head.html_comments not in ((), base.html_comments):
        raise ValidationError(
            "Do not add or edit HTML comments. Replace the instructional comment "
            "with the abstract, or leave that comment unchanged."
        )

    abstract = head.abstract
    if _looks_like_placeholder(abstract):
        raise ValidationError("Replace the placeholder with the actual talk abstract.")
    if len(abstract) < MIN_ABSTRACT_CHARACTERS:
        raise ValidationError(
            f"The abstract must contain at least {MIN_ABSTRACT_CHARACTERS} characters."
        )
    if len(abstract) > MAX_ABSTRACT_CHARACTERS:
        raise ValidationError(
            f"The abstract must contain no more than {MAX_ABSTRACT_CHARACTERS} "
            "characters."
        )
    if len(WORD_RE.findall(abstract)) < MIN_ABSTRACT_WORDS:
        raise ValidationError(
            f"The abstract must contain at least {MIN_ABSTRACT_WORDS} words."
        )
    _validate_plain_prose(abstract, "abstract")

    return head


def validate_pdf_bytes(data: bytes) -> None:
    """Perform dependency-free PDF envelope checks.

    GitHub Actions should additionally use a real PDF parser and renderer.  The
    checks here catch renamed non-PDF files, Git LFS pointers, truncated files,
    and unreasonable upload sizes before those tools run.
    """

    size = len(data)
    if size < MIN_PDF_BYTES:
        raise ValidationError(
            f"The PDF is only {size} bytes; a presentation PDF must be at least "
            f"{MIN_PDF_BYTES} bytes."
        )
    if size > MAX_PDF_BYTES:
        raise ValidationError(
            f"The PDF is {size} bytes; the maximum accepted size is "
            f"{MAX_PDF_BYTES // (1024 * 1024)} MiB."
        )
    if not re.match(rb"\A%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n|[ %])", data[:16]):
        raise ValidationError(
            "The slide file does not begin with a supported PDF signature. "
            "Export the presentation as a standard PDF rather than renaming a file."
        )
    if b"%%EOF" not in data[-2_048:]:
        raise ValidationError(
            "The slide file has no PDF end marker near the end and may be truncated."
        )


def _run_git(repo: Path, arguments: Sequence[str], *, text: bool = False):
    command = ["git", "-C", str(repo), *arguments]
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            stderr = error.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            detail = (stderr or "unknown Git error").strip()
        else:
            detail = str(error)
        raise GitCommandError(f"Git command failed: {detail}") from error


def _resolve_commit(repo: Path, revision: str, label: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
        raise GitCommandError(f"The {label} revision must be a hexadecimal commit SHA.")
    resolved = _run_git(
        repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"], text=True
    ).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", resolved):
        raise GitCommandError(f"Git returned an invalid {label} commit SHA.")
    return resolved


def _changed_files(repo: Path, base: str, head: str) -> tuple[ChangedFile, ...]:
    merge_base = _run_git(repo, ["merge-base", base, head], text=True).strip()
    raw = _run_git(
        repo,
        ["diff", "--name-status", "-z", "--no-renames", merge_base, head, "--"],
    )
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise GitCommandError("Git returned malformed changed-file data.")

    changes: list[ChangedFile] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValidationError("Submission paths must be valid UTF-8 text.") from error
        changes.append(ChangedFile(status=status, path=path))
    return tuple(changes)


def _is_submission_path(path: str) -> bool:
    return path.startswith("_talks/") or path.startswith("assets/slides/")


def _blob_info(repo: Path, revision: str, path: str) -> tuple[str, int]:
    raw_tree = _run_git(repo, ["ls-tree", "-z", revision, "--", path])
    entries = [entry for entry in raw_tree.split(b"\0") if entry]
    if len(entries) != 1:
        raise ValidationError(f"Could not find a single regular file at '{path}'.")
    metadata, separator, returned_path = entries[0].partition(b"\t")
    if not separator or returned_path.decode("utf-8", errors="replace") != path:
        raise GitCommandError("Git returned malformed tree data.")
    parts = metadata.split()
    if len(parts) != 3:
        raise GitCommandError("Git returned malformed blob metadata.")
    mode, object_type, _object_id = (part.decode("ascii") for part in parts)
    if mode != "100644" or object_type != "blob":
        raise ValidationError(
            f"'{path}' must be a normal, non-executable file rather than a "
            "symlink, submodule, or executable."
        )
    size_text = _run_git(repo, ["cat-file", "-s", f"{revision}:{path}"], text=True)
    try:
        size = int(size_text.strip())
    except ValueError as error:
        raise GitCommandError("Git returned an invalid blob size.") from error
    return mode, size


def _read_blob(repo: Path, revision: str, path: str, *, max_bytes: int) -> bytes:
    _mode, size = _blob_info(repo, revision, path)
    if size > max_bytes:
        raise ValidationError(
            f"'{path}' is {size} bytes, exceeding its {max_bytes}-byte limit."
        )
    data = _run_git(repo, ["cat-file", "blob", f"{revision}:{path}"])
    if len(data) != size:
        raise GitCommandError("Git returned blob data with an unexpected size.")
    return data


def _decode_metadata(data: bytes, path: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(f"'{path}' must be UTF-8 text.") from error


def validate_submission(
    repo: Path | str,
    base: str,
    head: str,
    *,
    allow_published_updates: bool = False,
) -> ValidationResult:
    """Validate the submission diff and return normalized submission metadata."""

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        raise GitCommandError(f"Repository directory does not exist: {repo_path}")
    base_commit = _resolve_commit(repo_path, base, "base")
    head_commit = _resolve_commit(repo_path, head, "head")
    changes = _changed_files(repo_path, base_commit, head_commit)
    submission_changes = [
        change for change in changes if _is_submission_path(change.path)
    ]

    if not submission_changes:
        return ValidationResult(
            submission_type="none",
            path=None,
            record_id=None,
            message="No student submission paths changed; nothing to validate.",
        )

    if len(changes) != 1:
        changed_paths = ", ".join(change.path for change in changes)
        raise ValidationError(
            "A student pull request must change exactly one talk metadata file "
            f"or exactly one PDF. Changed paths: {changed_paths}"
        )

    change = changes[0]
    talk_match = TALK_PATH_RE.fullmatch(change.path)
    slides_match = SLIDES_PATH_RE.fullmatch(change.path)
    if talk_match is None and slides_match is None:
        raise ValidationError(
            "The submission path is not valid. Use exactly "
            "'_talks/fall-2026-XX.md' or "
            "'assets/slides/fall-2026/fall-2026-XX.pdf' with an assigned ID "
            "from 01 through 16."
        )

    if talk_match is not None:
        if change.status != "M":
            raise ValidationError(
                "A title-and-abstract submission must modify its existing talk "
                "file; it may not add, delete, or replace that file."
            )
        record_id = talk_match.group("record_id")
        base_bytes = _read_blob(
            repo_path, base_commit, change.path, max_bytes=MAX_METADATA_BYTES
        )
        head_bytes = _read_blob(
            repo_path, head_commit, change.path, max_bytes=MAX_METADATA_BYTES
        )
        validate_talk_document(
            base_text=_decode_metadata(base_bytes, change.path),
            head_text=_decode_metadata(head_bytes, change.path),
            expected_record_id=record_id,
            allow_completed_base=allow_published_updates,
        )
        return ValidationResult(
            submission_type="metadata",
            path=change.path,
            record_id=record_id,
            message=f"Valid title-and-abstract submission for {record_id}.",
        )

    if change.status not in {"A", "M"}:
        raise ValidationError(
            "A slides submission must add or update its assigned PDF; it may not "
            "delete or rename a file."
        )
    if change.status == "M" and not allow_published_updates:
        raise ValidationError(
            "The published PDF is locked against further student edits. Contact "
            "the instructor if a replacement is needed."
        )
    assert slides_match is not None
    record_id = slides_match.group("record_id")
    talk_path = f"_talks/{record_id}.md"
    talk_bytes = _read_blob(
        repo_path, base_commit, talk_path, max_bytes=MAX_METADATA_BYTES
    )
    talk_text = _decode_metadata(talk_bytes, talk_path)
    try:
        validate_talk_document(
            base_text=talk_text,
            head_text=talk_text,
            expected_record_id=record_id,
            allow_completed_base=True,
        )
    except ValidationError as error:
        raise ValidationError(
            "Submit and merge the matching title and abstract before submitting "
            f"slides for {record_id}."
        ) from error

    pdf_bytes = _read_blob(
        repo_path, head_commit, change.path, max_bytes=MAX_PDF_BYTES + 1
    )
    validate_pdf_bytes(pdf_bytes)
    return ValidationResult(
        submission_type="slides",
        path=change.path,
        record_id=record_id,
        message=f"Valid PDF envelope for {record_id}; parser/render checks may follow.",
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate one STA 701S student submission between Git commits."
    )
    parser.add_argument("--base", required=True, help="Base commit SHA")
    parser.add_argument("--head", required=True, help="Head commit SHA")
    parser.add_argument(
        "--repo", default=".", help="Path to the Git repository (default: current directory)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the successful result as JSON"
    )
    parser.add_argument(
        "--github-output",
        metavar="PATH",
        help=(
            "Append submission_type, submission_path, and record_id to a "
            "GitHub Actions output file"
        ),
    )
    parser.add_argument(
        "--allow-published-updates",
        action="store_true",
        help=(
            "Allow a trusted same-repository maintainer pull request to correct "
            "already-published metadata or replace an already-published PDF"
        ),
    )
    return parser


def _write_github_outputs(output_path: str, result: ValidationResult) -> None:
    """Append safe, single-line values for use by later workflow steps."""

    values = {
        "submission_type": result.submission_type,
        "submission_path": result.path or "",
        "record_id": result.record_id or "",
    }
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise GitCommandError(f"Refusing to write multiline GitHub output '{key}'.")
    try:
        with Path(output_path).open("a", encoding="utf-8") as output_file:
            for key, value in values.items():
                output_file.write(f"{key}={value}\n")
    except OSError as error:
        raise GitCommandError(
            f"Could not write the GitHub Actions output file: {error}"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_argument_parser().parse_args(argv)
    try:
        result = validate_submission(
            arguments.repo,
            arguments.base,
            arguments.head,
            allow_published_updates=arguments.allow_published_updates,
        )
    except ValidationError as error:
        print(f"Submission validation failed: {error}", file=sys.stderr)
        return 1
    except GitCommandError as error:
        print(f"Submission validator could not inspect the repository: {error}", file=sys.stderr)
        return 2

    if arguments.github_output:
        try:
            _write_github_outputs(arguments.github_output, result)
        except GitCommandError as error:
            print(
                f"Submission validator could not publish workflow outputs: {error}",
                file=sys.stderr,
            )
            return 2

    if arguments.json:
        print(json.dumps(dataclasses.asdict(result), sort_keys=True))
    else:
        print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
