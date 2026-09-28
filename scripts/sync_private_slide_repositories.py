#!/usr/bin/env python3
"""Roll out trusted infrastructure without fetching private slide contents.

Dry-run is the default. Authentication is supplied to gh through GH_TOKEN or
its existing credential helper; this program never reads credential files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/private-slides"
REPOSITORY_PATTERN = re.compile(r"stat701/private-slides-fall-2026-(?:0[1-9]|1[0-8])\Z")
# Intentionally never discover template files dynamically: a PDF or unrelated
# file accidentally added to the template must not be published anywhere.
MANAGED_PATHS = (
    "README.md",
    ".github/pull_request_template.md",
    ".github/workflows/validate-private-slides.yml",
    ".github/workflows/report-private-pdf-validation.yml",
    "scripts/validate_private_slides.py",
    "scripts/validate_slide_pdf.py",
    "scripts/report_pdf_validation.py",
)


class SyncError(RuntimeError):
    """A repository cannot safely be synchronized."""


class GitHub:
    def request(self, method: str, endpoint: str, payload: dict | None = None) -> Any:
        command = ["gh", "api", "--method", method, endpoint]
        if payload is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            # Do not echo arbitrary remote bodies, stderr, or credentials.
            raise SyncError(f"GitHub API {method} {endpoint} failed (exit {result.returncode}).")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SyncError(f"GitHub API returned invalid JSON for {endpoint}.") from error


def validate_repository_name(repository: str) -> None:
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise SyncError(f"Not an allowed STA 701S private slide repository: {repository!r}.")


def validate_repository(api: GitHub, repository: str) -> None:
    validate_repository_name(repository)
    metadata = api.request("GET", f"repos/{repository}")
    if (
        metadata.get("full_name") != repository
        or metadata.get("private") is not True
        or metadata.get("owner", {}).get("login") != "stat701"
        or metadata.get("default_branch") != "main"
        or metadata.get("archived") is True
    ):
        raise SyncError(f"{repository} must be private, active, owned by stat701, and default to main.")


def list_repositories(api: GitHub) -> list[str]:
    repositories = []
    page = 1
    while True:
        entries = api.request("GET", f"orgs/stat701/repos?type=all&per_page=100&page={page}")
        if not isinstance(entries, list):
            raise SyncError("GitHub did not return an organization repository list.")
        for entry in entries:
            name = entry.get("full_name", "")
            if REPOSITORY_PATTERN.fullmatch(name):
                # Include public matches so validation fails visibly rather than
                # silently overlooking a private repository made public.
                repositories.append(name)
        if len(entries) < 100:
            return sorted(set(repositories))
        page += 1


def load_template(directory: Path = TEMPLATE) -> dict[str, bytes]:
    files = {}
    for name in MANAGED_PATHS:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise SyncError(f"Required trusted template file is missing or a symlink: {name}.")
        files[name] = path.read_bytes()
        try:
            files[name].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SyncError(f"Template infrastructure must be UTF-8 text: {name}.") from error
    return files


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def main_sha(api: GitHub, repository: str) -> str:
    ref = api.request("GET", f"repos/{repository}/git/ref/heads/main")
    if ref.get("ref") != "refs/heads/main" or ref.get("object", {}).get("type") != "commit":
        raise SyncError(f"{repository} has no valid main commit reference.")
    return ref["object"]["sha"]


def synchronize(
    api: GitHub,
    repository: str,
    files: dict[str, bytes],
    *,
    apply: bool = False,
    attempts: int = 3,
) -> dict[str, Any]:
    if set(files) != set(MANAGED_PATHS):
        raise SyncError("Only the complete, explicitly allowlisted infrastructure may be synchronized.")
    prefix = f"repos/{repository}"
    expected = {name: blob_sha(content) for name, content in files.items()}
    for _ in range(attempts):
        validate_repository(api, repository)
        parent = main_sha(api, repository)
        commit = api.request("GET", f"{prefix}/git/commits/{parent}")
        base_tree = commit["tree"]["sha"]
        tree = api.request("GET", f"{prefix}/git/trees/{base_tree}?recursive=1")
        if tree.get("truncated") is not False:
            raise SyncError(f"{repository} returned an incomplete Git tree; refusing to update.")
        entries = {entry["path"]: entry for entry in tree["tree"]}
        changed = [
            name for name in MANAGED_PATHS
            if entries.get(name, {}).get("sha") != expected[name]
            or entries.get(name, {}).get("mode") != "100644"
            or entries.get(name, {}).get("type") != "blob"
        ]
        if not changed:
            return {"repository": repository, "status": "up_to_date", "changed": []}
        if not apply:
            return {"repository": repository, "status": "would_update", "changed": changed}
        updates = []
        for name in changed:
            blob = api.request("POST", f"{prefix}/git/blobs", {
                "content": files[name].decode("utf-8"), "encoding": "utf-8",
            })
            if blob.get("sha") != expected[name]:
                raise SyncError(f"GitHub returned an unexpected infrastructure blob hash for {name}.")
            updates.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        # base_tree retains every existing student file. There are no PDF blob
        # downloads, recursive clones, deletions, or changes to student branches.
        new_tree = api.request("POST", f"{prefix}/git/trees", {
            "base_tree": base_tree, "tree": updates,
        })
        new_commit = api.request("POST", f"{prefix}/git/commits", {
            "message": "Update private slide submission infrastructure",
            "tree": new_tree["sha"], "parents": [parent],
        })
        validate_repository(api, repository)
        if main_sha(api, repository) != parent:
            continue
        try:
            api.request("PATCH", f"{prefix}/git/refs/heads/main", {
                "sha": new_commit["sha"], "force": False,
            })
        except SyncError:
            if main_sha(api, repository) != parent:
                continue
            raise
        return {"repository": repository, "status": "updated", "changed": changed, "commit": new_commit["sha"]}
    raise SyncError(f"{repository} main kept changing; no force push was attempted. Retry the rollout.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="One allowed private slide repository; otherwise discover all.")
    parser.add_argument("--apply", action="store_true", help="Write infrastructure updates; defaults to dry-run.")
    args = parser.parse_args()
    try:
        if args.repository:
            validate_repository_name(args.repository)
        files = load_template()
        api = GitHub()
        repositories = [args.repository] if args.repository else list_repositories(api)
        if not repositories:
            print("No matching private slide repositories found.")
        # Validate all selected targets before the first write to avoid a
        # partially applied rollout when a target has unexpected visibility.
        for repository in repositories:
            validate_repository(api, repository)
        for repository in repositories:
            print(json.dumps(synchronize(api, repository, files, apply=args.apply), sort_keys=True))
    except (SyncError, OSError) as error:
        print(f"Private slide infrastructure sync failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
