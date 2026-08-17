#!/usr/bin/env python3
"""Trusted, append-only GitHub account registry for STA 701S submissions.

The registry is stored as machine-authored comments on one locked GitHub issue.
Student-authored pull-request content is never a source of account ownership.
The stable numeric GitHub user ID is authoritative; logins are retained only as
human-readable audit information and may change without transferring ownership.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any


GITHUB_API_ROOT = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

FIXED_REPOSITORY = "stat701/stat701.github.io"
REGISTRY_ISSUE_NUMBER = 7
REGISTRY_ISSUE_TITLE = "STA 701S student account registry (machine managed)"

GITHUB_ACTIONS_BOT_ID = 41_898_282
GITHUB_ACTIONS_BOT_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_BOT_TYPE = "Bot"

AUTHORIZED_MAINTAINER_ID = 12_053_767
AUTHORIZED_MAINTAINER_LOGIN = "volfovsky"  # Audit/display value, not authority.
AUTHORIZED_MAINTAINER_TYPE = "User"

REGISTRY_NAMESPACE = "stat701-student-account-registry"
REGISTRY_MARKER_PREFIX = f"<!-- {REGISTRY_NAMESPACE}:v1:"
REGISTRY_MARKER_SUFFIX = " -->"

VALID_RECORD_IDS = tuple(f"fall-2026-{number:02d}" for number in range(1, 17))
VALID_RECORD_ID_SET = frozenset(VALID_RECORD_IDS)
EVENT_KEYS = frozenset(
    {
        "event",
        "record_id",
        "github_user_id",
        "github_login",
        "source_pr",
        "source_head_sha",
        "authorized_by_user_id",
        "authorized_by_login",
        "workflow_run_id",
    }
)

LOGIN_RE = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class RegistryError(Exception):
    """Base class for safe, user-facing registry failures."""


class RegistryTrustError(RegistryError):
    """The fixed issue or a purported machine event failed trust checks."""


class RegistryConflictError(RegistryError):
    """A requested or stored binding violates one-to-one ownership."""


class OwnershipError(RegistryError):
    """A pull-request author is not permitted to submit for the record."""


class RegistrationError(RegistryError):
    """A proposed registration is invalid or unauthorized."""


@dataclasses.dataclass(frozen=True)
class RegisteredOwner:
    """One immutable account-to-schedule binding and its audit provenance."""

    record_id: str
    github_user_id: int
    github_login: str
    source_pr: int
    source_head_sha: str
    authorized_by_user_id: int
    authorized_by_login: str
    workflow_run_id: int

    def event_payload(self) -> dict[str, object]:
        """Return the exact JSON object represented by this bind event."""

        return {
            "event": "bind",
            "record_id": self.record_id,
            "github_user_id": self.github_user_id,
            "github_login": self.github_login,
            "source_pr": self.source_pr,
            "source_head_sha": self.source_head_sha,
            "authorized_by_user_id": self.authorized_by_user_id,
            "authorized_by_login": self.authorized_by_login,
            "workflow_run_id": self.workflow_run_id,
        }


@dataclasses.dataclass(frozen=True)
class StudentRegistry:
    """Validated registry state reconstructed from trusted append-only events."""

    owners: tuple[RegisteredOwner, ...]


@dataclasses.dataclass(frozen=True)
class OwnershipDecision:
    """The authorization result for a validated submission envelope."""

    status: str
    owner: RegisteredOwner | None
    message: str

    @property
    def registration_required(self) -> bool:
        return self.status == "registration_required"

    @property
    def maintainer_override(self) -> bool:
        return self.status == "maintainer_override"


@dataclasses.dataclass(frozen=True)
class RegistrationResult:
    """The resulting binding and whether a new registry event was appended."""

    owner: RegisteredOwner
    created: bool


def _require_positive_int(value: object, field: str) -> int:
    if type(value) is not int or not (1 <= value <= 2**63 - 1):
        raise RegistryTrustError(f"Registry field '{field}' must be a positive integer.")
    return value


def _require_login(value: object, field: str) -> str:
    if not isinstance(value, str) or not LOGIN_RE.fullmatch(value):
        raise RegistryTrustError(f"Registry field '{field}' is not a valid GitHub login.")
    return value


def _require_record_id(value: object) -> str:
    if not isinstance(value, str) or value not in VALID_RECORD_ID_SET:
        raise RegistryTrustError("Registry event contains an unknown record ID.")
    return value


def _require_sha(value: object) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise RegistryTrustError("Registry field 'source_head_sha' is not a commit SHA.")
    return value


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def format_registry_marker(owner: RegisteredOwner) -> str:
    """Serialize one bind event as an exact, hidden, single-line marker."""

    payload = owner.event_payload()
    # Validate programmatically constructed events through the same strict path.
    validated = _owner_from_payload(payload)
    canonical = _canonical_json(validated.event_payload())
    return f"{REGISTRY_MARKER_PREFIX}{canonical}{REGISTRY_MARKER_SUFFIX}"


def _owner_from_payload(payload: object) -> RegisteredOwner:
    if not isinstance(payload, Mapping) or frozenset(payload.keys()) != EVENT_KEYS:
        raise RegistryTrustError("Registry bind event has unexpected or missing fields.")
    if payload.get("event") != "bind":
        raise RegistryTrustError("Registry event type must be 'bind'.")

    owner = RegisteredOwner(
        record_id=_require_record_id(payload.get("record_id")),
        github_user_id=_require_positive_int(
            payload.get("github_user_id"), "github_user_id"
        ),
        github_login=_require_login(payload.get("github_login"), "github_login"),
        source_pr=_require_positive_int(payload.get("source_pr"), "source_pr"),
        source_head_sha=_require_sha(payload.get("source_head_sha")),
        authorized_by_user_id=_require_positive_int(
            payload.get("authorized_by_user_id"), "authorized_by_user_id"
        ),
        authorized_by_login=_require_login(
            payload.get("authorized_by_login"), "authorized_by_login"
        ),
        workflow_run_id=_require_positive_int(
            payload.get("workflow_run_id"), "workflow_run_id"
        ),
    )
    if owner.authorized_by_user_id != AUTHORIZED_MAINTAINER_ID:
        raise RegistryTrustError("Registry event was not authorized by an allowed user ID.")
    if owner.github_user_id == AUTHORIZED_MAINTAINER_ID:
        raise RegistryTrustError("The authorized maintainer account cannot own a student record.")
    return owner


def parse_registry_marker(body: object) -> RegisteredOwner:
    """Parse one exact marker, rejecting non-canonical or multiline encodings."""

    if not isinstance(body, str):
        raise RegistryTrustError("Trusted registry comment body is not text.")
    if "\r" in body or "\n" in body:
        raise RegistryTrustError("Trusted registry markers must contain exactly one line.")
    if not body.startswith(REGISTRY_MARKER_PREFIX) or not body.endswith(
        REGISTRY_MARKER_SUFFIX
    ):
        raise RegistryTrustError("Trusted registry comment has a malformed marker.")

    encoded = body[len(REGISTRY_MARKER_PREFIX) : -len(REGISTRY_MARKER_SUFFIX)]
    try:
        payload = json.loads(encoded)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RegistryTrustError("Trusted registry comment contains invalid JSON.") from exc
    owner = _owner_from_payload(payload)
    if encoded != _canonical_json(owner.event_payload()):
        raise RegistryTrustError("Trusted registry event JSON is not canonical.")
    if body != format_registry_marker_without_validation(owner):
        raise RegistryTrustError("Trusted registry marker is not canonical.")
    return owner


def format_registry_marker_without_validation(owner: RegisteredOwner) -> str:
    """Internal non-recursive formatter for an already validated owner."""

    return (
        f"{REGISTRY_MARKER_PREFIX}{_canonical_json(owner.event_payload())}"
        f"{REGISTRY_MARKER_SUFFIX}"
    )


def _is_trusted_bot(user: object) -> bool:
    return bool(
        isinstance(user, Mapping)
        and user.get("id") == GITHUB_ACTIONS_BOT_ID
        and user.get("login") == GITHUB_ACTIONS_BOT_LOGIN
        and user.get("type") == GITHUB_ACTIONS_BOT_TYPE
    )


def _validate_repository(repository: str) -> None:
    if repository != FIXED_REPOSITORY:
        raise RegistryTrustError(
            f"The account registry is fixed to {FIXED_REPOSITORY}."
        )


def _github_request(
    *,
    token: str,
    method: str,
    endpoint: str,
    payload: Mapping[str, object] | None = None,
) -> object:
    if not isinstance(token, str) or not token.strip():
        raise RegistryTrustError("A GitHub token is required to read the registry.")
    if not endpoint.startswith("/") or "\r" in endpoint or "\n" in endpoint:
        raise RegistryTrustError("Internal GitHub API endpoint is invalid.")

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
    request = urllib.request.Request(
        f"{GITHUB_API_ROOT}{endpoint}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "stat701-submission-registry",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise RegistryTrustError(
            f"GitHub API request failed with HTTP {exc.code}."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RegistryTrustError("GitHub API request failed.") from exc
    if len(raw) > 2_000_000:
        raise RegistryTrustError("GitHub API response exceeded the safety limit.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryTrustError("GitHub API returned invalid JSON.") from exc


def _validate_registry_issue(issue: object, repository: str) -> None:
    if not isinstance(issue, Mapping):
        raise RegistryTrustError("Registry issue response is not an object.")
    expected_repository_url = f"{GITHUB_API_ROOT}/repos/{repository}"
    expected_issue_url = f"{expected_repository_url}/issues/{REGISTRY_ISSUE_NUMBER}"
    if issue.get("number") != REGISTRY_ISSUE_NUMBER:
        raise RegistryTrustError("Registry issue number does not match the fixed issue.")
    if issue.get("repository_url") != expected_repository_url:
        raise RegistryTrustError("Registry issue belongs to the wrong repository.")
    if issue.get("url") != expected_issue_url:
        raise RegistryTrustError("Registry issue API URL is not the fixed issue URL.")
    if issue.get("title") != REGISTRY_ISSUE_TITLE:
        raise RegistryTrustError("Registry issue title does not match the locked title.")
    if issue.get("state") != "open":
        raise RegistryTrustError("Registry issue must remain open.")
    if issue.get("locked") is not True:
        raise RegistryTrustError("Registry issue must remain locked.")
    if issue.get("pull_request") is not None:
        raise RegistryTrustError("Registry storage must be an issue, not a pull request.")


def _validated_registry(owners: Sequence[RegisteredOwner]) -> StudentRegistry:
    by_record: dict[str, RegisteredOwner] = {}
    record_by_user: dict[int, str] = {}
    for owner in owners:
        existing = by_record.get(owner.record_id)
        if existing is not None and existing.github_user_id != owner.github_user_id:
            raise RegistryConflictError(
                f"Registry has conflicting owners for {owner.record_id}."
            )
        other_record = record_by_user.get(owner.github_user_id)
        if other_record is not None and other_record != owner.record_id:
            raise RegistryConflictError(
                "One GitHub account is bound to more than one schedule record."
            )
        if existing is None:
            by_record[owner.record_id] = owner
            record_by_user[owner.github_user_id] = owner.record_id
    return StudentRegistry(tuple(by_record[record] for record in sorted(by_record)))


def load_registry(*, token: str, repository: str) -> StudentRegistry:
    """Load and verify the fixed issue and all trusted append-only events."""

    _validate_repository(repository)
    issue_endpoint = f"/repos/{repository}/issues/{REGISTRY_ISSUE_NUMBER}"
    issue = _github_request(
        token=token, method="GET", endpoint=issue_endpoint
    )
    _validate_registry_issue(issue, repository)

    owners: list[RegisteredOwner] = []
    for page in range(1, 11):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        comments = _github_request(
            token=token,
            method="GET",
            endpoint=f"{issue_endpoint}/comments?{query}",
        )
        if not isinstance(comments, list):
            raise RegistryTrustError("Registry issue comments response is not a list.")
        for comment in comments:
            if not isinstance(comment, Mapping):
                raise RegistryTrustError("Registry issue contains an invalid comment object.")
            body = comment.get("body")
            if _is_trusted_bot(comment.get("user")):
                if isinstance(body, str) and REGISTRY_NAMESPACE in body:
                    owners.append(parse_registry_marker(body))
            # Marker lookalikes from non-bot users are deliberately ignored.
        if len(comments) < 100:
            return _validated_registry(owners)
    raise RegistryTrustError("Registry has too many comments to validate safely.")


def resolve_owner(
    registry: StudentRegistry, record_id: str
) -> RegisteredOwner | None:
    """Return the owner of a known record, if it has been registered."""

    if record_id not in VALID_RECORD_ID_SET:
        raise OwnershipError(f"Unknown record ID '{record_id}'.")
    return next(
        (owner for owner in registry.owners if owner.record_id == record_id), None
    )


def is_authorized_maintainer(*, user_id: int, login: str, user_type: str) -> bool:
    """Check explicit maintainer authority; numeric ID and type are authoritative."""

    # Login is intentionally audit-only so a GitHub rename cannot revoke or
    # transfer authority. Requiring a plausible login avoids malformed input.
    return bool(
        type(user_id) is int
        and user_id == AUTHORIZED_MAINTAINER_ID
        and user_type == AUTHORIZED_MAINTAINER_TYPE
        and isinstance(login, str)
        and LOGIN_RE.fullmatch(login)
    )


def is_authorized_registrar(*, user_id: int, login: str, user_type: str) -> bool:
    """Backward-compatible policy name for manual student registration."""

    return is_authorized_maintainer(
        user_id=user_id,
        login=login,
        user_type=user_type,
    )


def check_owner(
    registry: StudentRegistry,
    *,
    record_id: str,
    submission_type: str,
    author_user_id: int,
    author_login: str,
    author_type: str,
    same_repository: bool,
) -> OwnershipDecision:
    """Authorize one metadata or slide submission against stable user IDs."""

    if submission_type not in {"metadata", "slides"}:
        raise OwnershipError("Submission type must be 'metadata' or 'slides'.")
    if type(author_user_id) is not int or author_user_id <= 0:
        raise OwnershipError("Pull-request author has an invalid GitHub user ID.")
    if not isinstance(author_login, str) or not LOGIN_RE.fullmatch(author_login):
        raise OwnershipError("Pull-request author has an invalid GitHub login.")
    if author_type != "User":
        raise OwnershipError("Only an individual GitHub user may submit seminar work.")
    if type(same_repository) is not bool:
        raise OwnershipError("Repository-origin decision must be a boolean.")

    owner = resolve_owner(registry, record_id)
    if owner is None:
        if submission_type == "metadata":
            return OwnershipDecision(
                status="registration_required",
                owner=None,
                message=(
                    f"{record_id} is not registered yet; instructor registration is "
                    "required before AI review."
                ),
            )
        raise OwnershipError(
            f"{record_id} has no registered student account; slides cannot be submitted."
        )

    if author_user_id == owner.github_user_id:
        return OwnershipDecision(
            status="owner_match",
            owner=owner,
            message=f"Pull-request author owns {record_id}.",
        )

    if same_repository and is_authorized_maintainer(
        user_id=author_user_id, login=author_login, user_type=author_type
    ):
        return OwnershipDecision(
            status="maintainer_override",
            owner=owner,
            message=f"Explicit maintainer override for {record_id}.",
        )

    raise OwnershipError(
        f"Pull-request author does not own {record_id}; expected GitHub user ID "
        f"{owner.github_user_id}."
    )


def register_owner(
    *,
    token: str,
    repository: str,
    record_id: str,
    github_user_id: int,
    github_login: str,
    github_user_type: str,
    source_pr: int,
    source_head_sha: str,
    authorized_by_user_id: int,
    authorized_by_login: str,
    authorized_by_type: str,
    workflow_run_id: int,
) -> RegistrationResult:
    """Append one trusted bind event, or return an existing idempotent binding."""

    _validate_repository(repository)
    if not is_authorized_maintainer(
        user_id=authorized_by_user_id,
        login=authorized_by_login,
        user_type=authorized_by_type,
    ):
        raise RegistrationError("Workflow actor is not an authorized registrar.")
    if github_user_type != "User":
        raise RegistrationError("Only an individual GitHub user can own a record.")
    if github_user_id == AUTHORIZED_MAINTAINER_ID:
        raise RegistrationError("The authorized maintainer cannot be a student owner.")

    try:
        proposed = _owner_from_payload(
            {
                "event": "bind",
                "record_id": record_id,
                "github_user_id": github_user_id,
                "github_login": github_login,
                "source_pr": source_pr,
                "source_head_sha": source_head_sha,
                "authorized_by_user_id": authorized_by_user_id,
                "authorized_by_login": authorized_by_login,
                "workflow_run_id": workflow_run_id,
            }
        )
    except RegistryTrustError as exc:
        raise RegistrationError(str(exc)) from exc

    registry = load_registry(token=token, repository=repository)
    existing = resolve_owner(registry, record_id)
    if existing is not None:
        if existing.github_user_id == github_user_id:
            return RegistrationResult(owner=existing, created=False)
        raise RegistryConflictError(f"{record_id} is already bound to another account.")
    duplicate = next(
        (
            owner
            for owner in registry.owners
            if owner.github_user_id == github_user_id
        ),
        None,
    )
    if duplicate is not None:
        raise RegistryConflictError(
            f"This GitHub user ID already owns {duplicate.record_id}."
        )

    body = format_registry_marker(proposed)
    posted = _github_request(
        token=token,
        method="POST",
        endpoint=f"/repos/{repository}/issues/{REGISTRY_ISSUE_NUMBER}/comments",
        payload={"body": body},
    )
    if not isinstance(posted, Mapping) or not _is_trusted_bot(posted.get("user")):
        raise RegistryTrustError(
            "GitHub did not attribute the registry event to the trusted Actions bot."
        )
    if posted.get("body") != body:
        raise RegistryTrustError("GitHub returned a different registry comment body.")
    parsed = parse_registry_marker(posted.get("body"))
    if parsed != proposed:
        raise RegistryTrustError("Posted registry event failed round-trip validation.")
    return RegistrationResult(owner=proposed, created=True)


def _token_from_environment(name: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", name):
        raise RegistryError("Token environment variable name is invalid.")
    token = os.environ.get(name, "")
    if not token.strip():
        raise RegistryError(f"Required token environment variable {name} is not set.")
    return token


def _add_common_parser_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    parser.add_argument("--record-id", required=True)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-pr", help="check a PR author against the registry")
    _add_common_parser_arguments(check)
    check.add_argument("--submission-type", choices=("metadata", "slides"), required=True)
    check.add_argument("--author-id", type=int, required=True)
    check.add_argument("--author-login", required=True)
    check.add_argument("--author-type", required=True)
    check.add_argument("--head-repository", required=True)

    register = commands.add_parser("register", help="append a trusted account binding")
    _add_common_parser_arguments(register)
    register.add_argument("--github-user-id", type=int, required=True)
    register.add_argument("--github-login", required=True)
    register.add_argument("--github-user-type", required=True)
    register.add_argument("--source-pr", type=int, required=True)
    register.add_argument("--source-head-sha", required=True)
    register.add_argument("--authorized-by-user-id", type=int, required=True)
    register.add_argument("--authorized-by-login", required=True)
    register.add_argument("--authorized-by-type", required=True)
    register.add_argument("--workflow-run-id", type=int, required=True)
    return parser


def _decision_json(decision: OwnershipDecision) -> dict[str, object]:
    return {
        "status": decision.status,
        "record_id": decision.owner.record_id if decision.owner else None,
        "registered_owner_id": (
            decision.owner.github_user_id if decision.owner else None
        ),
        "registered_owner_login": (
            decision.owner.github_login if decision.owner else None
        ),
        "message": decision.message,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        token = _token_from_environment(args.token_env)
        if args.command == "check-pr":
            registry = load_registry(token=token, repository=args.repository)
            decision = check_owner(
                registry,
                record_id=args.record_id,
                submission_type=args.submission_type,
                author_user_id=args.author_id,
                author_login=args.author_login,
                author_type=args.author_type,
                same_repository=args.head_repository == args.repository,
            )
            print(_canonical_json(_decision_json(decision)))
            return 0

        result = register_owner(
            token=token,
            repository=args.repository,
            record_id=args.record_id,
            github_user_id=args.github_user_id,
            github_login=args.github_login,
            github_user_type=args.github_user_type,
            source_pr=args.source_pr,
            source_head_sha=args.source_head_sha,
            authorized_by_user_id=args.authorized_by_user_id,
            authorized_by_login=args.authorized_by_login,
            authorized_by_type=args.authorized_by_type,
            workflow_run_id=args.workflow_run_id,
        )
        print(
            _canonical_json(
                {
                    "status": "created" if result.created else "already_registered",
                    "record_id": result.owner.record_id,
                    "github_user_id": result.owner.github_user_id,
                    "github_login": result.owner.github_login,
                }
            )
        )
        return 0
    except RegistryError as exc:
        print(f"Submission registry error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
