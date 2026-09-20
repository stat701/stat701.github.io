#!/usr/bin/env python3
"""Post a trusted PR comment explaining slide PDF validation diagnostics."""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


COMMENT_MARKER = "<!-- stat701-pdf-validation -->"
WORKFLOW_PATH = ".github/workflows/validate-submission.yml"
GITHUB_ACTIONS_BOT_ID = 41_898_282
SLIDES_PATH_RE = re.compile(
    r"\Aassets/slides/fall-2026/fall-2026-(?:0[1-9]|1[0-8])\.pdf\Z"
)
REPOSITORY_RE = re.compile(r"\A[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_ZIP_BYTES = 1_000_000
MAX_REPORT_BYTES = 64_000
MAX_WARNINGS = 40
MAX_WARNING_TEXT = 1_000


class ReporterError(Exception):
    """A trusted operational error in PDF validation reporting."""


@dataclass(frozen=True)
class PullRequestBinding:
    number: int
    head_sha: str
    path: str


class StripAuthorizationRedirect(urllib.request.HTTPRedirectHandler):
    """Follow artifact redirects without forwarding GitHub authorization."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._opener = urllib.request.build_opener(StripAuthorizationRedirect)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> Any:
        url = "https://api.github.com" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise ReporterError(f"GitHub API request failed for {path}: {error}") from error

    def download_bytes(self, url: str, *, max_bytes: int) -> bytes:
        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        try:
            with self._opener.open(request, timeout=30) as response:
                data = response.read(max_bytes + 1)
        except OSError as error:
            raise ReporterError(f"Could not download PDF validation artifact: {error}") from error
        if len(data) > max_bytes:
            raise ReporterError("The PDF validation artifact is unexpectedly large.")
        return data


def _require_string(value: object, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ReporterError(f"The workflow run has invalid {field}.")
    return value


def _validate_repository(repository: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository):
        raise ReporterError("The repository name is invalid.")


def _workflow_run(client: GitHubClient, repository: str, run_id: int) -> Mapping[str, Any]:
    run = client.request_json("GET", f"/repos/{repository}/actions/runs/{run_id}")
    if not isinstance(run, Mapping):
        raise ReporterError("GitHub returned an invalid workflow run.")
    run_repository = run.get("repository")
    if not isinstance(run_repository, Mapping) or run_repository.get("full_name") != repository:
        raise ReporterError("The workflow run does not belong to the expected repository.")
    if run.get("event") != "pull_request":
        raise ReporterError("The workflow run was not triggered by a pull request.")
    if run.get("path") != WORKFLOW_PATH:
        raise ReporterError("The workflow run is not the trusted submission validator.")
    if run.get("status") != "completed":
        raise ReporterError("The workflow run is not completed.")
    if run.get("conclusion") not in {"success", "failure"}:
        raise ReporterError("The workflow run did not finish with a reportable conclusion.")
    head_sha = _require_string(run.get("head_sha"), "head SHA", max_length=64)
    if not SHA_RE.fullmatch(head_sha):
        raise ReporterError("The workflow run has an invalid head SHA.")
    if (
        not isinstance(run.get("run_attempt"), int)
        or isinstance(run.get("run_attempt"), bool)
        or run["run_attempt"] < 1
    ):
        raise ReporterError("The workflow run has an invalid attempt number.")
    return run


def _bind_current_pr(
    client: GitHubClient,
    repository: str,
    run: Mapping[str, Any],
) -> PullRequestBinding | None:
    head_repository = run.get("head_repository")
    if not isinstance(head_repository, Mapping):
        raise ReporterError("The workflow run lacks head repository metadata.")
    head_repository_name = _require_string(
        head_repository.get("full_name"), "head repository"
    )
    owner = head_repository.get("owner")
    if not isinstance(owner, Mapping):
        raise ReporterError("The workflow run lacks head repository owner metadata.")
    head_owner = _require_string(owner.get("login"), "head owner")
    head_branch = _require_string(run.get("head_branch"), "head branch", max_length=250)
    head_sha = _require_string(run.get("head_sha"), "head SHA", max_length=64)

    pulls = client.request_json(
        "GET",
        f"/repos/{repository}/pulls",
        query={
            "state": "open",
            "base": "main",
            "head": f"{head_owner}:{head_branch}",
            "per_page": "2",
        },
    )
    if not isinstance(pulls, list):
        raise ReporterError("GitHub returned invalid pull-request data.")
    if not pulls:
        print("The validated pull request is no longer open; skipping PDF comment.")
        return None
    if len(pulls) > 1:
        raise ReporterError("More than one open pull request matched the validated branch.")
    pull = pulls[0]
    if not isinstance(pull, Mapping):
        raise ReporterError("GitHub returned an invalid pull request.")
    number = pull.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ReporterError("The matched pull request has an invalid number.")
    head = pull.get("head")
    base = pull.get("base")
    if not isinstance(head, Mapping) or not isinstance(base, Mapping):
        raise ReporterError("The matched pull request has invalid branch metadata.")
    head_repo = head.get("repo")
    base_repo = base.get("repo")
    if not isinstance(head_repo, Mapping) or not isinstance(base_repo, Mapping):
        raise ReporterError("The matched pull request has invalid repository metadata.")
    if (
        head.get("sha") != head_sha
        or head_repo.get("full_name") != head_repository_name
        or base_repo.get("full_name") != repository
        or base.get("ref") != "main"
    ):
        raise ReporterError("Could not bind the validation run to one current PR head.")

    files = client.request_json(
        "GET",
        f"/repos/{repository}/pulls/{number}/files",
        query={"per_page": "100"},
    )
    if not isinstance(files, list) or len(files) != 1:
        raise ReporterError("The current pull request is no longer a single-file PDF submission.")
    changed_file = files[0]
    if not isinstance(changed_file, Mapping):
        raise ReporterError("GitHub returned invalid pull-request file data.")
    path = changed_file.get("filename")
    status = changed_file.get("status")
    if not isinstance(path, str) or not SLIDES_PATH_RE.fullmatch(path):
        raise ReporterError("The current pull request no longer contains one public slide PDF.")
    if status != "added":
        raise ReporterError("The current PDF change is not an added file.")
    return PullRequestBinding(number=number, head_sha=head_sha, path=path)


def _download_report(
    client: GitHubClient,
    repository: str,
    run_id: int,
    run_attempt: int,
) -> Mapping[str, Any] | None:
    artifacts = client.request_json(
        "GET",
        f"/repos/{repository}/actions/runs/{run_id}/artifacts",
        query={"per_page": "100"},
    )
    if not isinstance(artifacts, Mapping) or not isinstance(artifacts.get("artifacts"), list):
        raise ReporterError("GitHub returned invalid artifact data.")
    artifact_name = f"pdf-validation-report-{run_attempt}"
    matches = [
        artifact
        for artifact in artifacts["artifacts"]
        if isinstance(artifact, Mapping) and artifact.get("name") == artifact_name
    ]
    if not matches:
        print("No PDF validation artifact was produced; skipping PDF comment.")
        return None
    if len(matches) != 1:
        raise ReporterError("More than one PDF validation artifact matched this run attempt.")
    artifact = matches[0]
    if artifact.get("expired") is True:
        raise ReporterError("The PDF validation artifact has expired.")
    archive_url = _require_string(artifact.get("archive_download_url"), "artifact URL", max_length=2_000)
    parsed_url = urllib.parse.urlparse(archive_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "api.github.com"
        or not re.fullmatch(
            rf"/repos/{re.escape(repository)}/actions/artifacts/[1-9][0-9]*/zip",
            parsed_url.path,
        )
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise ReporterError("The PDF validation artifact URL is not a GitHub artifact zip URL.")
    archive = client.download_bytes(archive_url, max_bytes=MAX_ZIP_BYTES)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
            infos = [info for info in zip_file.infolist() if not info.is_dir()]
            if len(infos) != 1 or infos[0].filename != "report.json":
                raise ReporterError("The PDF validation artifact must contain only report.json.")
            if infos[0].file_size > MAX_REPORT_BYTES:
                raise ReporterError("The PDF validation report is unexpectedly large.")
            data = zip_file.read(infos[0], pwd=None)
    except (OSError, zipfile.BadZipFile) as error:
        raise ReporterError("Could not read the PDF validation report artifact.") from error
    if len(data) > MAX_REPORT_BYTES:
        raise ReporterError("The PDF validation report is unexpectedly large.")
    try:
        report = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReporterError("The PDF validation report is not valid JSON.") from error
    if not isinstance(report, Mapping):
        raise ReporterError("The PDF validation report has an invalid schema.")
    return report


def _nullable_string(value: object, field: str, *, max_length: int = 1_000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_length:
        raise ReporterError(f"The PDF validation report has invalid {field}.")
    return value


def _nullable_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReporterError(f"The PDF validation report has invalid {field}.")
    return value


def _validate_report(
    report: Mapping[str, Any],
    *,
    binding: PullRequestBinding,
) -> Mapping[str, Any]:
    expected_keys = {
        "schema_version",
        "head_sha",
        "submission_path",
        "status",
        "qpdf_exit_code",
        "qpdf_warnings",
        "failure",
        "producer",
        "page_count",
        "rendered_count",
    }
    if set(report) != expected_keys:
        raise ReporterError("The PDF validation report has an unexpected schema.")
    if (
        not isinstance(report["schema_version"], int)
        or isinstance(report["schema_version"], bool)
        or report["schema_version"] != 1
    ):
        raise ReporterError("The PDF validation report has an unsupported schema version.")
    if report["head_sha"] != binding.head_sha or report["submission_path"] != binding.path:
        raise ReporterError("The PDF validation report does not match the current PR.")
    if not isinstance(report["status"], str) or report["status"] not in {"passed", "failed"}:
        raise ReporterError("The PDF validation report has an invalid status.")
    qpdf_exit_code = _nullable_int(report["qpdf_exit_code"], "qpdf exit code")
    warnings = report["qpdf_warnings"]
    if not isinstance(warnings, list) or len(warnings) > MAX_WARNINGS:
        raise ReporterError("The PDF validation report has invalid qpdf warnings.")
    for warning in warnings:
        if not isinstance(warning, str) or len(warning) > MAX_WARNING_TEXT:
            raise ReporterError("The PDF validation report has invalid qpdf warnings.")
    failure = _nullable_string(report["failure"], "failure")
    _nullable_string(report["producer"], "producer", max_length=500)
    page_count = _nullable_int(report["page_count"], "page count")
    rendered_count = _nullable_int(report["rendered_count"], "rendered count")
    if report["status"] == "failed" and not failure:
        raise ReporterError("A failed PDF validation report must include a failure.")
    if report["status"] == "passed" and failure is not None:
        raise ReporterError("A passed PDF validation report cannot include a failure.")
    if report["status"] == "passed" and qpdf_exit_code not in {0, 3}:
        raise ReporterError("A passed PDF validation report has an inconsistent qpdf result.")
    if page_count is not None and (page_count < 1 or page_count > 200):
        raise ReporterError("The PDF validation report has an invalid page count.")
    if rendered_count is not None and (rendered_count < 0 or rendered_count > 200):
        raise ReporterError("The PDF validation report has an invalid rendered count.")
    if report["status"] == "passed" and (
        page_count is None or rendered_count is None or page_count != rendered_count
    ):
        raise ReporterError("A passed PDF validation report has inconsistent render counts.")
    return report


def _safe_text(value: str, *, max_length: int = 2_000) -> str:
    trimmed = value[:max_length]
    return html.escape(trimmed, quote=False).replace("@", "&#64;")


def _known_offset_zero_warning(warnings: Sequence[str]) -> bool:
    joined = "\n".join(warnings).casefold()
    return bool(re.search(r"\bobject has offset 0\b", joined))


def _comment_body(
    *,
    repository: str,
    run_id: int,
    binding: PullRequestBinding,
    report: Mapping[str, Any],
    run_conclusion: str,
) -> str:
    warnings = list(report["qpdf_warnings"])
    status = report["status"]
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    lines = [COMMENT_MARKER]
    if status == "passed" and (warnings or report["qpdf_exit_code"] == 3):
        lines.append(
            "The PDF technical check passed, but qpdf reported structural warnings."
        )
        lines.append(
            "No new export is required for this check. Open your PDF and confirm "
            "that all slides look as intended. Instructor review is still required."
        )
    elif status == "passed":
        lines.append("The PDF technical check now passes without qpdf warnings.")
    else:
        lines.append("The PDF technical check found a problem that needs attention.")
        lines.append(
            "Failed check: "
            f"<code>{_safe_text(str(report['failure']), max_length=800)}</code>"
        )
        lines.append(
            "Follow the instruction above if a new export is needed, and replace "
            "the PDF on this same pull-request branch. If the tool could not run "
            "or timed out, ask the instructor to inspect the check before resubmitting."
        )

    if status == "passed" and run_conclusion != "success":
        lines.append(
            "This comment only describes the PDF technical check; another "
            "part of the validation workflow still needs attention."
        )

    if warnings:
        if _known_offset_zero_warning(warnings):
            lines.append(
                "The warning pattern means some entries in the PDF's internal "
                "cross-reference index point to the start of the file instead "
                "of to a stored object. The validator accepts that only when "
                "the remaining security and rendering checks pass."
            )
        else:
            lines.append(
                "The automatic checker did not recognize this warning pattern. "
                "If the slides render correctly, instructor review can decide "
                "whether the file is acceptable."
            )
    producer = report.get("producer")
    if isinstance(producer, str) and producer:
        explanation = (
            "This is consistent with a macOS/Quartz PDF export, but it does not "
            "prove which app created the deck or why the warning was introduced."
            if "quartz" in producer.casefold()
            else "This metadata does not establish which export step caused the issue."
        )
        lines.append(
            "PDF metadata records this producer: "
            f"<code>{_safe_text(producer, max_length=500)}</code>. {explanation}"
        )
    page_count = report.get("page_count")
    rendered_count = report.get("rendered_count")
    if isinstance(page_count, int) and isinstance(rendered_count, int):
        lines.append(
            "Rendered pages checked: "
            f"<code>{rendered_count}</code> of <code>{page_count}</code>."
        )
    if warnings:
        sample = "\n".join(warnings[:8])
        extra = "" if len(warnings) <= 8 else f"\n... {len(warnings) - 8} more warnings"
        lines.append("<details><summary>qpdf diagnostics</summary>")
        lines.append("")
        lines.append(f"<pre><code>{_safe_text(sample + extra)}</code></pre>")
        lines.append("</details>")
    lines.append(f"Validation run: {run_url}")
    lines.append(f"Checked file: <code>{_safe_text(binding.path, max_length=200)}</code>")
    lines.append(f"Checked commit: <code>{_safe_text(binding.head_sha[:12], max_length=12)}</code>")
    return "\n\n".join(lines) + "\n"


def _find_bot_comment(client: GitHubClient, repository: str, pr_number: int) -> int | None:
    for page in range(1, 11):
        comments = client.request_json(
            "GET",
            f"/repos/{repository}/issues/{pr_number}/comments",
            query={"per_page": "100", "page": str(page)},
        )
        if not isinstance(comments, list):
            raise ReporterError("GitHub returned invalid issue comments.")
        for comment in comments:
            if not isinstance(comment, Mapping):
                continue
            body = comment.get("body")
            user = comment.get("user")
            if not isinstance(body, str) or COMMENT_MARKER not in body:
                continue
            if not isinstance(user, Mapping):
                continue
            login = user.get("login")
            user_type = user.get("type")
            user_id = user.get("id")
            comment_id = comment.get("id")
            if (
                isinstance(comment_id, int)
                and not isinstance(comment_id, bool)
                and user_id == GITHUB_ACTIONS_BOT_ID
                and user_type == "Bot"
                and login == "github-actions[bot]"
            ):
                return comment_id
        if len(comments) < 100:
            return None
    raise ReporterError("Too many comments to safely identify the existing PDF report.")


def report_pdf_validation(
    *,
    client: GitHubClient,
    repository: str,
    run_id: int,
) -> int:
    _validate_repository(repository)
    run = _workflow_run(client, repository, run_id)
    report = _download_report(client, repository, run_id, int(run["run_attempt"]))
    if report is None:
        return 0
    binding = _bind_current_pr(client, repository, run)
    if binding is None:
        return 0
    report = _validate_report(report, binding=binding)
    existing_comment = _find_bot_comment(client, repository, binding.number)
    should_comment = (
        report["status"] == "failed"
        or report["qpdf_exit_code"] == 3
        or bool(report["qpdf_warnings"])
        or existing_comment is not None
    )
    if not should_comment:
        print("PDF validation passed cleanly; no diagnostic comment needed.")
        return 0
    body = _comment_body(
        repository=repository,
        run_id=run_id,
        binding=binding,
        report=report,
        run_conclusion=str(run["conclusion"]),
    )
    current_binding = _bind_current_pr(client, repository, run)
    if current_binding != binding:
        raise ReporterError("The pull request changed before the PDF comment could be posted.")
    if existing_comment is None:
        client.request_json(
            "POST",
            f"/repos/{repository}/issues/{binding.number}/comments",
            body={"body": body},
        )
        print(f"Posted PDF validation diagnostic comment on PR #{binding.number}.")
    else:
        client.request_json(
            "PATCH",
            f"/repos/{repository}/issues/comments/{existing_comment}",
            body={"body": body},
        )
        print(f"Updated PDF validation diagnostic comment on PR #{binding.number}.")
    return 0


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_argument_parser().parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required.", file=sys.stderr)
        return 2
    try:
        return report_pdf_validation(
            client=GitHubClient(token),
            repository=arguments.repository,
            run_id=arguments.run_id,
        )
    except ReporterError as error:
        print(f"PDF validation reporter failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
