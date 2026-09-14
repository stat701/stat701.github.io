#!/usr/bin/env python3
"""Validate one private STA 701S slide PDF between two Git commits."""

from __future__ import annotations

import argparse
import dataclasses
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


RECORD_ID_RE = re.compile(r"\Afall-2026-(?:0[1-9]|1[0-8])\Z")
PDF_SIGNATURE_RE = re.compile(rb"\A%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n|[ %])")
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 200


class ValidationError(Exception):
    """A student-facing validation failure."""


class GitCommandError(Exception):
    """An operational failure while reading Git data."""


@dataclasses.dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    path: str
    record_id: str
    page_count: int | None
    message: str


def _run(
    command: Sequence[str],
    *,
    timeout_seconds: int = 45,
    text: bool = False,
) -> bytes | str:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            timeout=timeout_seconds,
        ).stdout
    except subprocess.TimeoutExpired as error:
        raise ValidationError(f"Command timed out: {command[0]}") from error
    except (OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            detail = detail.strip() or f"exit status {error.returncode}"
        else:
            detail = str(error)
        raise ValidationError(f"{command[0]} failed: {detail}") from error


def _run_git(repo: Path, arguments: Sequence[str], *, text: bool = False) -> bytes | str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            detail = detail.strip() or f"exit status {error.returncode}"
        else:
            detail = str(error)
        raise GitCommandError(f"Git command failed: {detail}") from error


def _resolve_commit(repo: Path, revision: str, label: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
        raise GitCommandError(f"The {label} revision must be a hexadecimal commit SHA.")
    resolved = str(
        _run_git(repo, ["rev-parse", "--verify", f"{revision}^{{commit}}"], text=True)
    ).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", resolved):
        raise GitCommandError(f"Git returned an invalid {label} commit SHA.")
    return resolved


def _changed_files(repo: Path, base: str, head: str) -> tuple[ChangedFile, ...]:
    merge_base = str(_run_git(repo, ["merge-base", base, head], text=True)).strip()
    raw = _run_git(
        repo,
        ["diff", "--name-status", "-z", "--no-renames", merge_base, head, "--"],
    )
    assert isinstance(raw, bytes)
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
            raise ValidationError("Changed paths must be valid UTF-8 text.") from error
        changes.append(ChangedFile(status=status, path=path))
    return tuple(changes)


def _blob_size(repo: Path, revision: str, path: str) -> int:
    raw_tree = _run_git(repo, ["ls-tree", "-z", revision, "--", path])
    assert isinstance(raw_tree, bytes)
    entries = [entry for entry in raw_tree.split(b"\0") if entry]
    if len(entries) != 1:
        raise ValidationError(f"Could not find a single file at '{path}'.")
    metadata, separator, returned_path = entries[0].partition(b"\t")
    if not separator or returned_path.decode("utf-8", errors="replace") != path:
        raise GitCommandError("Git returned malformed tree data.")
    parts = metadata.split()
    if len(parts) != 3:
        raise GitCommandError("Git returned malformed blob metadata.")
    mode, object_type, _object_id = (part.decode("ascii") for part in parts)
    if mode != "100644" or object_type != "blob":
        raise ValidationError(
            f"'{path}' must be a normal file, not a symlink, submodule, or executable."
        )

    size_text = str(_run_git(repo, ["cat-file", "-s", f"{revision}:{path}"], text=True))
    try:
        return int(size_text.strip())
    except ValueError as error:
        raise GitCommandError("Git returned an invalid blob size.") from error


def _read_blob(repo: Path, revision: str, path: str) -> bytes:
    size = _blob_size(repo, revision, path)
    if size > MAX_PDF_BYTES:
        raise ValidationError(
            f"'{path}' is {size} bytes; the maximum accepted size is "
            f"{MAX_PDF_BYTES // (1024 * 1024)} MiB."
        )
    data = _run_git(repo, ["cat-file", "blob", f"{revision}:{path}"])
    assert isinstance(data, bytes)
    if len(data) != size:
        raise GitCommandError("Git returned blob data with an unexpected size.")
    return data


def validate_pdf_envelope(data: bytes) -> None:
    if not PDF_SIGNATURE_RE.match(data[:16]):
        raise ValidationError(
            "The slide file does not begin with a supported PDF signature."
        )
    if b"%%EOF" not in data[-2_048:]:
        raise ValidationError("The slide file has no PDF end marker near the end.")


def _extract_page_count(pdfinfo_output: str) -> int:
    encrypted = re.search(r"(?im)^Encrypted:\s*yes\b", pdfinfo_output)
    if encrypted:
        raise ValidationError("Encrypted PDFs are not accepted.")
    match = re.search(r"(?im)^Pages:\s*(\d+)\s*$", pdfinfo_output)
    if match is None:
        raise ValidationError("Could not determine the PDF page count.")
    page_count = int(match.group(1))
    if page_count < 1 or page_count > MAX_PAGES:
        raise ValidationError(f"The PDF must contain between 1 and {MAX_PAGES} pages.")
    return page_count


def validate_pdf_with_tools(pdf_path: Path) -> int:
    _run(["qpdf", "--check", str(pdf_path)], timeout_seconds=45, text=True)
    pdfinfo_output = str(
        _run(["pdfinfo", str(pdf_path)], timeout_seconds=45, text=True)
    )
    page_count = _extract_page_count(pdfinfo_output)

    javascript = str(_run(["pdfinfo", "-js", str(pdf_path)], timeout_seconds=45, text=True))
    if javascript.strip():
        raise ValidationError(
            "PDFs containing JavaScript are not accepted. Export a standard PDF."
        )

    embedded_files = str(
        _run(["pdfdetach", "-list", str(pdf_path)], timeout_seconds=45, text=True)
    )
    if embedded_files.strip() != "0 embedded files":
        raise ValidationError(
            "PDFs containing embedded files are not accepted. Export slides without "
            "attachments."
        )

    with tempfile.TemporaryDirectory(prefix="private-slide-render-") as temporary:
        prefix = Path(temporary) / "page"
        _run(
            [
                "pdftoppm",
                "-f",
                "1",
                "-l",
                str(page_count),
                "-png",
                "-r",
                "24",
                str(pdf_path),
                str(prefix),
            ],
            timeout_seconds=180,
            text=True,
        )
        rendered_count = sum(
            1
            for path in Path(temporary).glob("page-*.png")
            if path.is_file() and path.stat().st_size > 0
        )
    if rendered_count != page_count:
        raise ValidationError(
            f"Expected {page_count} rendered pages but produced {rendered_count}."
        )
    return page_count


def validate_private_slides(
    repo: Path | str,
    base: str,
    head: str,
    record_id: str,
    *,
    check_pdf_tools: bool = True,
) -> ValidationResult:
    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        raise GitCommandError(f"Repository directory does not exist: {repo_path}")
    if RECORD_ID_RE.fullmatch(record_id) is None:
        raise ValidationError(
            "The record id must have the form fall-2026-XX, from 01 through 18."
        )

    base_commit = _resolve_commit(repo_path, base, "base")
    head_commit = _resolve_commit(repo_path, head, "head")
    changes = _changed_files(repo_path, base_commit, head_commit)
    expected_path = f"{record_id}.pdf"
    if len(changes) != 1:
        changed_paths = ", ".join(change.path for change in changes) or "none"
        raise ValidationError(
            "A private slides PR must change exactly one root PDF. "
            f"Changed paths: {changed_paths}"
        )

    change = changes[0]
    if change.path != expected_path:
        raise ValidationError(
            f"A private slides PR for {record_id} must change only '{expected_path}'."
        )
    if change.status not in {"A", "M"}:
        raise ValidationError(
            "A private slides PR must add or modify its PDF; deletes and renames are "
            "not accepted."
        )

    data = _read_blob(repo_path, head_commit, expected_path)
    validate_pdf_envelope(data)

    page_count: int | None = None
    if check_pdf_tools:
        with tempfile.TemporaryDirectory(prefix="private-slide-blob-") as temporary:
            pdf_path = Path(temporary) / expected_path
            pdf_path.write_bytes(data)
            page_count = validate_pdf_with_tools(pdf_path)

    rendered = (
        f" and rendered all {page_count} pages"
        if page_count is not None
        else " at the Git blob level"
    )
    return ValidationResult(
        path=expected_path,
        record_id=record_id,
        page_count=page_count,
        message=f"Validated {expected_path}{rendered}.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--github-output")
    parser.add_argument(
        "--skip-pdf-tools",
        action="store_true",
        help="Only run Git and dependency-free PDF checks; intended for unit tests.",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_private_slides(
            args.repo,
            args.base,
            args.head,
            args.record_id,
            check_pdf_tools=not args.skip_pdf_tools,
        )
    except (GitCommandError, ValidationError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write(f"submission_path={result.path}\n")
            output.write(f"record_id={result.record_id}\n")
            if result.page_count is not None:
                output.write(f"page_count={result.page_count}\n")
    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
