#!/usr/bin/env python3
"""Validate one submitted slide PDF with parser, security, and render checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


MAX_REPORT_WARNINGS = 40
MAX_WARNING_CHARACTERS = 1_000
MAX_REPORT_BYTES = 60_000
SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SUBMISSION_PATH_RE = re.compile(
    r"\Aassets/slides/fall-2026/fall-2026-(?:0[1-9]|1[0-8])\.pdf\Z"
)


class PdfValidationFailure(Exception):
    """A student-facing PDF validation failure."""


def _run_tool(arguments: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(arguments),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        command = Path(arguments[0]).name if arguments else "tool"
        raise PdfValidationFailure(
            f"{command} timed out after {timeout} seconds."
        ) from error
    except OSError as error:
        command = Path(arguments[0]).name if arguments else "tool"
        raise PdfValidationFailure(f"Could not run {command}: {error}") from error


def _bounded_warning_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.casefold()
        if not (line.startswith("WARNING:") or "succeeded with warnings" in lowered):
            continue
        if len(line) > MAX_WARNING_CHARACTERS:
            line = line[: MAX_WARNING_CHARACTERS - 3] + "..."
        lines.append(line)
        if len(lines) >= MAX_REPORT_WARNINGS:
            break
    return lines


def _safe_log_text(text: str, *, max_length: int = 800) -> str:
    return " ".join(text.replace("::", ": :").split())[:max_length]


def _parse_pdfinfo_value(pdf_information: str, field: str) -> str | None:
    prefix = f"{field}:"
    for line in pdf_information.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _parse_page_count(pdf_information: str) -> int:
    values = [
        line[len("Pages:") :].strip()
        for line in pdf_information.splitlines()
        if line.startswith("Pages:")
    ]
    if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]):
        raise PdfValidationFailure("Could not determine the PDF page count.")
    page_count = int(values[0])
    if page_count < 1 or page_count > 200:
        raise PdfValidationFailure("The PDF must contain between 1 and 200 pages.")
    return page_count


def _write_report(report_path: Path, report: dict[str, object]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = dict(report)
    warnings = list(serializable.get("qpdf_warnings", []))
    serializable["qpdf_warnings"] = warnings
    while True:
        encoded = (
            json.dumps(serializable, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        if len(encoded) <= MAX_REPORT_BYTES or not warnings:
            break
        warnings.pop()
    report_path.write_bytes(encoded)


def validate_slide_pdf(
    pdf_path: Path,
    *,
    report_path: Path,
    head_sha: str,
    submission_path: str,
) -> int:
    report: dict[str, object] = {
        "schema_version": 1,
        "head_sha": head_sha,
        "submission_path": submission_path,
        "status": "failed",
        "qpdf_exit_code": None,
        "qpdf_warnings": [],
        "failure": None,
        "producer": None,
        "page_count": None,
        "rendered_count": None,
    }

    try:
        qpdf = _run_tool(("qpdf", "--check", str(pdf_path)), timeout=45)
        report["qpdf_exit_code"] = qpdf.returncode
        qpdf_output = qpdf.stderr + "\n" + qpdf.stdout
        if qpdf.returncode != 0:
            report["qpdf_warnings"] = _bounded_warning_lines(qpdf_output)
        if qpdf.returncode == 3 and not report["qpdf_warnings"]:
            report["qpdf_warnings"] = [
                "qpdf reported warnings (exit status 3) without a detailed warning message."
            ]
        if qpdf.returncode not in {0, 3}:
            detail = _safe_log_text(qpdf_output)
            if qpdf.returncode == 2:
                message = (
                    "qpdf found a PDF structure error. Export a fresh standard PDF "
                    "and replace the file in this pull request."
                )
            else:
                message = (
                    f"qpdf exited with status {qpdf.returncode}. The validator could "
                    "not complete the PDF structure check."
                )
            if detail:
                message += f" qpdf said: {detail}"
            raise PdfValidationFailure(message)

        pdfinfo = _run_tool(("pdfinfo", str(pdf_path)), timeout=45)
        if pdfinfo.returncode != 0:
            raise PdfValidationFailure("pdfinfo could not read the PDF metadata.")
        pdf_information = pdfinfo.stdout
        producer = _parse_pdfinfo_value(pdf_information, "Producer")
        if producer:
            report["producer"] = producer[:500]

        if re.search(r"(?im)^Encrypted:\s*yes\b", pdf_information):
            raise PdfValidationFailure(
                "Encrypted PDFs are not accepted. Export an unencrypted PDF."
            )

        javascript = _run_tool(("pdfinfo", "-js", str(pdf_path)), timeout=45)
        if javascript.returncode != 0:
            raise PdfValidationFailure("Could not inspect the PDF for JavaScript.")
        if javascript.stdout.strip():
            raise PdfValidationFailure(
                "PDFs containing JavaScript are not accepted. Export a standard "
                "presentation PDF."
            )

        embedded_files = _run_tool(("pdfdetach", "-list", str(pdf_path)), timeout=45)
        if embedded_files.returncode != 0:
            raise PdfValidationFailure("Could not inspect the PDF for embedded files.")
        if embedded_files.stdout.strip() != "0 embedded files":
            raise PdfValidationFailure(
                "PDFs containing embedded files are not accepted. Export slides "
                "without attachments."
            )

        page_count = _parse_page_count(pdf_information)
        report["page_count"] = page_count
        print(f"PDF metadata read successfully. Pages: {page_count}.")

        with tempfile.TemporaryDirectory() as temporary_directory:
            render_prefix = str(Path(temporary_directory) / "page")
            rendered = _run_tool(
                ("pdftoppm", "-png", "-r", "36", str(pdf_path), render_prefix),
                timeout=180,
            )
            if rendered.returncode != 0:
                raise PdfValidationFailure(
                    "The PDF could not be rendered into page images for review."
                )
            rendered_count = sum(
                1
                for path in Path(temporary_directory).glob("page-*.png")
                if path.is_file() and path.stat().st_size > 0
            )
        report["rendered_count"] = rendered_count
        if rendered_count != page_count:
            raise PdfValidationFailure(
                f"Expected {page_count} rendered pages but produced "
                f"{rendered_count}. Human review is required."
            )

        report["status"] = "passed"
        if qpdf.returncode == 3:
            print(
                "::warning::qpdf reported warnings, but the PDF passed security "
                "and render checks."
            )
        print(f"Successfully opened and rendered all {page_count} PDF pages.")
        return 0
    except PdfValidationFailure as error:
        report["failure"] = str(error)[:1_000]
        print(f"::error::{_safe_log_text(str(error))}", file=sys.stderr)
        return 1
    finally:
        _write_report(report_path, report)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--submission-path", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_argument_parser().parse_args(argv)
    if not SHA_RE.fullmatch(arguments.head_sha):
        print("::error::The pull-request head SHA is invalid.", file=sys.stderr)
        return 1
    if not SUBMISSION_PATH_RE.fullmatch(arguments.submission_path):
        print("::error::The slide submission path is invalid.", file=sys.stderr)
        return 1
    return validate_slide_pdf(
        arguments.pdf,
        report_path=arguments.report,
        head_sha=arguments.head_sha,
        submission_path=arguments.submission_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
