from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.sync_private_slide_repositories import (
    MANAGED_PATHS,
    SyncError,
    blob_sha,
    list_repositories,
    load_template,
    synchronize,
    validate_repository_name,
)


REPOSITORY = "stat701/private-slides-fall-2026-08"
FILES = {name: f"Trusted infrastructure: {name}\n".encode() for name in MANAGED_PATHS}
PDF = {"path": "fall-2026-08.pdf", "mode": "100644", "type": "blob", "sha": "private-pdf-blob"}


class FakeGitHub:
    """A Git object graph that exposes only tree metadata, never PDF contents."""

    def __init__(self, *, current=False, race=None):
        self.metadata = {
            "full_name": REPOSITORY, "private": True,
            "owner": {"login": "stat701"}, "default_branch": "main", "archived": False,
        }
        self.calls = []
        self.ref = "original-main"
        self.commits = {self.ref: {"tree": {"sha": "original-tree"}}}
        entries = {PDF["path"]: deepcopy(PDF)}
        entries["notes.txt"] = {"path": "notes.txt", "mode": "100644", "type": "blob", "sha": "student-notes"}
        if current:
            entries.update({name: {"path": name, "mode": "100644", "type": "blob", "sha": blob_sha(content)}
                            for name, content in FILES.items()})
        self.trees = {"original-tree": {"truncated": False, "tree": list(entries.values())}}
        self.race = race
        self.raced = False
        self.ref_reads = 0
        self.reject_updates = False

    def concurrent_student_commit(self):
        self.raced = True
        parent_tree = self.commits[self.ref]["tree"]["sha"]
        changed = deepcopy(self.trees[parent_tree])
        changed["tree"] = [entry for entry in changed["tree"] if entry["path"] != PDF["path"]]
        changed["tree"].append({**PDF, "sha": "revised-private-pdf-blob"})
        name = f"concurrent-{len(self.commits)}"
        self.trees[name] = changed
        self.commits[name] = {"tree": {"sha": name}}
        self.ref = name

    def request(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, deepcopy(payload)))
        prefix = f"repos/{REPOSITORY}"
        if endpoint == prefix and method == "GET":
            return deepcopy(self.metadata)
        if endpoint == f"{prefix}/git/ref/heads/main" and method == "GET":
            self.ref_reads += 1
            if self.race == "precheck" and self.ref_reads == 2:
                self.concurrent_student_commit()
            return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.ref}}
        if endpoint.startswith(f"{prefix}/git/commits/") and method == "GET":
            return deepcopy(self.commits[endpoint.rsplit("/", 1)[1]])
        if endpoint.startswith(f"{prefix}/git/trees/") and method == "GET":
            name = endpoint.rsplit("/", 1)[1].split("?", 1)[0]
            return deepcopy(self.trees[name])
        if endpoint == f"{prefix}/git/blobs" and method == "POST":
            return {"sha": blob_sha(payload["content"].encode())}
        if endpoint == f"{prefix}/git/trees" and method == "POST":
            name = f"tree-{len(self.trees)}"
            entries = {entry["path"]: deepcopy(entry) for entry in self.trees[payload["base_tree"]]["tree"]}
            entries.update({entry["path"]: deepcopy(entry) for entry in payload["tree"]})
            self.trees[name] = {"truncated": False, "tree": list(entries.values())}
            return {"sha": name}
        if endpoint == f"{prefix}/git/commits" and method == "POST":
            name = f"commit-{len(self.commits)}"
            self.commits[name] = {"tree": {"sha": payload["tree"]}, "parents": payload["parents"]}
            return {"sha": name}
        if endpoint == f"{prefix}/git/refs/heads/main" and method == "PATCH":
            if self.reject_updates:
                raise SyncError("Simulated permission failure")
            if self.race == "always" or (self.race == "patch" and not self.raced):
                self.concurrent_student_commit()
            if payload["force"] is not False or self.commits[payload["sha"]]["parents"] != [self.ref]:
                raise SyncError("Simulated non-fast-forward rejection")
            self.ref = payload["sha"]
            return {"object": {"sha": self.ref}}
        raise AssertionError(f"Unexpected API call: {method} {endpoint}")

    def current_entries(self):
        tree = self.trees[self.commits[self.ref]["tree"]["sha"]]
        return {entry["path"]: entry for entry in tree["tree"]}


class PrivateSlideRepositorySyncTests(unittest.TestCase):
    def test_dry_run_is_default_and_performs_no_writes(self):
        api = FakeGitHub()
        result = synchronize(api, REPOSITORY, FILES)
        self.assertEqual(result["status"], "would_update")
        self.assertEqual(set(result["changed"]), set(MANAGED_PATHS))
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_rollout_preserves_student_blobs_without_reading_them(self):
        api = FakeGitHub()
        result = synchronize(api, REPOSITORY, FILES, apply=True)
        self.assertEqual(result["status"], "updated")
        entries = api.current_entries()
        self.assertEqual(entries[PDF["path"]], PDF)
        self.assertEqual(entries["notes.txt"]["sha"], "student-notes")
        self.assertEqual(set(entries), set(MANAGED_PATHS) | {PDF["path"], "notes.txt"})
        for method, endpoint, payload in api.calls:
            self.assertNotIn("/contents", endpoint)
            self.assertFalse(method == "GET" and "/blobs" in endpoint)
            if method == "POST" and endpoint.endswith("/git/trees"):
                self.assertEqual(payload["base_tree"], "original-tree")
                self.assertEqual({item["path"] for item in payload["tree"]}, set(MANAGED_PATHS))
            if method == "PATCH":
                self.assertIs(payload["force"], False)

    def test_up_to_date_repository_has_no_new_commits(self):
        api = FakeGitHub(current=True)
        self.assertEqual(synchronize(api, REPOSITORY, FILES, apply=True)["status"], "up_to_date")
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_only_changed_infrastructure_is_written(self):
        api = FakeGitHub(current=True)
        files = dict(FILES)
        files["README.md"] = b"Updated student instructions\n"
        result = synchronize(api, REPOSITORY, files, apply=True)
        self.assertEqual(result["changed"], ["README.md"])
        self.assertEqual(len([call for call in api.calls if call[0] == "POST" and call[1].endswith("/blobs")]), 1)

    def test_wrong_repository_names_are_rejected_before_api_access(self):
        for name in ("other/private-slides-fall-2026-08", "stat701/stat701.github.io",
                     "stat701/private-slides-fall-2026-00", "stat701/private-slides-fall-2026-19",
                     REPOSITORY + "/../something", REPOSITORY + "\n"):
            with self.subTest(name=name):
                api = FakeGitHub()
                with self.assertRaises(SyncError):
                    synchronize(api, name, FILES, apply=True)
                self.assertEqual(api.calls, [])
        for number in range(1, 19):
            validate_repository_name(f"stat701/private-slides-fall-2026-{number:02}")

    def test_public_wrong_owner_wrong_default_or_archived_is_rejected(self):
        for field, value in (("private", False), ("private", "true"), ("owner", {"login": "other"}),
                             ("full_name", "other/repo"), ("default_branch", "student-slides"),
                             ("archived", True)):
            with self.subTest(field=field, value=value):
                api = FakeGitHub()
                api.metadata[field] = value
                with self.assertRaises(SyncError):
                    synchronize(api, REPOSITORY, FILES, apply=True)
                self.assertEqual(len(api.calls), 1)

    def test_non_allowlisted_or_partial_template_is_rejected(self):
        for files in ({**FILES, "fall-2026-08.pdf": b"private content"}, {"README.md": b"partial"}):
            api = FakeGitHub()
            with self.assertRaises(SyncError):
                synchronize(api, REPOSITORY, files, apply=True)
            self.assertEqual(api.calls, [])

    def test_truncated_tree_is_rejected_before_writes(self):
        api = FakeGitHub()
        api.trees["original-tree"]["truncated"] = True
        with self.assertRaisesRegex(SyncError, "incomplete Git tree"):
            synchronize(api, REPOSITORY, FILES, apply=True)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_concurrent_student_commit_is_preserved_before_or_during_ref_update(self):
        for race in ("precheck", "patch"):
            with self.subTest(race=race):
                api = FakeGitHub(race=race)
                result = synchronize(api, REPOSITORY, FILES, apply=True)
                self.assertEqual(result["status"], "updated")
                self.assertEqual(api.current_entries()[PDF["path"]]["sha"], "revised-private-pdf-blob")
                self.assertEqual(set(api.current_entries()), set(MANAGED_PATHS) | {PDF["path"], "notes.txt"})

    def test_repeated_races_fail_without_force_push(self):
        api = FakeGitHub(race="always")
        with self.assertRaisesRegex(SyncError, "main kept changing"):
            synchronize(api, REPOSITORY, FILES, apply=True)
        patches = [call for call in api.calls if call[0] == "PATCH"]
        self.assertEqual(len(patches), 3)
        self.assertTrue(all(call[2]["force"] is False for call in patches))
        self.assertEqual(set(api.current_entries()), {PDF["path"], "notes.txt"})

    def test_permission_failure_is_not_treated_as_a_race(self):
        api = FakeGitHub()
        api.reject_updates = True
        with self.assertRaisesRegex(SyncError, "permission failure"):
            synchronize(api, REPOSITORY, FILES, apply=True)
        self.assertEqual(len([call for call in api.calls if call[0] == "PATCH"]), 1)
        self.assertEqual(api.ref, "original-main")

    def test_repository_discovery_is_paginated_and_does_not_hide_public_matches(self):
        class ListingAPI:
            def __init__(self):
                self.calls = []

            def request(self, method, endpoint):
                self.calls.append((method, endpoint))
                if endpoint.endswith("page=1"):
                    return [{"full_name": f"stat701/unrelated-{n}"} for n in range(99)] + [
                        {"full_name": REPOSITORY, "private": True}]
                return [{"full_name": "stat701/private-slides-fall-2026-07", "private": False},
                        {"full_name": "stat701/private-slides-fall-2026-19", "private": True}]
        api = ListingAPI()
        self.assertEqual(list_repositories(api), ["stat701/private-slides-fall-2026-07", REPOSITORY])
        self.assertEqual(len(api.calls), 2)

    def test_template_loading_never_reads_accidental_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in FILES.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            (root / "accidental.pdf").write_bytes(b"private PDF")
            original = Path.read_bytes
            def checked_read(path):
                self.assertNotEqual(path.suffix, ".pdf")
                return original(path)
            with patch.object(Path, "read_bytes", checked_read):
                self.assertEqual(load_template(root), FILES)
            (root / "README.md").unlink()
            (root / "README.md").symlink_to(root / "accidental.pdf")
            with self.assertRaisesRegex(SyncError, "symlink"):
                load_template(root)


if __name__ == "__main__":
    unittest.main()
