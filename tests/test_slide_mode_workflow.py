from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/choose-slide-mode.yml"
PUBLIC_CHOICE = "- [x] I choose **public** slide delivery: my PDF will be published on the"
PRIVATE_CHOICE = "- [x] I choose **private** slide delivery: my PDF will be reviewed in a"
PUBLIC_UNCHECKED = "- [ ] I choose **public** slide delivery: my PDF will be published on the"
PRIVATE_UNCHECKED = "- [ ] I choose **private** slide delivery: my PDF will be reviewed in a"


def extract_process_choice_script() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    run_index = next(index for index, line in enumerate(lines) if line == "        run: |")
    first_command = next(
        line for line in lines[run_index + 1 :] if line.strip()
    )
    indent = len(first_command) - len(first_command.lstrip(" "))
    script_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip(" ")) < indent:
            break
        script_lines.append(line[indent:] if len(line) >= indent else "")
    return "\n".join(script_lines) + "\n"


class SlideModeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.log = self.work / "stub.log"
        (self.work / "scripts").mkdir()
        (self.work / "_data").mkdir()
        template = self.work / "templates/private-slides"
        template.mkdir(parents=True)
        (template / "README.md").write_text("private slides\n", encoding="utf-8")
        self.script = self.work / "process-choice.sh"
        self.script.write_text(extract_process_choice_script(), encoding="utf-8")
        self.script.chmod(0o755)
        self._write_stubs()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_stubs(self) -> None:
        gh = self.bin / "gh"
        gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                log = Path(os.environ["STUB_LOG"])

                def record(line):
                    with log.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\\n")

                record("gh " + " ".join(args))
                if args[:2] == ["auth", "setup-git"]:
                    sys.exit(0)
                if args and args[0] == "api":
                    url = next((arg for arg in args if arg.startswith("/repos/")), "")
                    if "/pulls/" in url and url.endswith("/files"):
                        for filename in os.environ.get("FILES", "_talks/fall-2026-01.md").splitlines():
                            if filename:
                                print(filename)
                        sys.exit(0)
                    if "/pulls/" in url:
                        print(os.environ["PR_JSON"])
                        sys.exit(0)
                    if "/git/ref/heads/main" in url:
                        sys.exit(0 if os.environ.get("MAIN_REF_EXISTS", "1") == "1" else 1)
                    sys.exit(0)
                if args[:2] == ["pr", "comment"]:
                    body = args[args.index("--body") + 1]
                    record("comment-body " + body)
                    sys.exit(0)
                if args[:2] == ["pr", "create"]:
                    counter = Path(os.environ["STUB_LOG"]).with_suffix(".create-count")
                    count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                    count += 1
                    counter.write_text(str(count), encoding="utf-8")
                    print(f"https://github.com/stat701/stat701.github.io/pull/{899 + count}")
                    sys.exit(0)
                if args[:2] == ["pr", "merge"]:
                    counter = Path(os.environ["STUB_LOG"]).with_suffix(".merge-count")
                    count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                    count += 1
                    counter.write_text(str(count), encoding="utf-8")
                    sys.exit(1 if count <= int(os.environ.get("MERGE_FAILURES", "0")) else 0)
                if args[:2] == ["pr", "close"]:
                    sys.exit(0)
                if args[:2] == ["repo", "view"]:
                    if "--json" in args:
                        print(os.environ.get("PRIVATE_REPO_VISIBILITY", "PRIVATE"))
                        sys.exit(0)
                    sys.exit(0 if os.environ.get("REPO_EXISTS", "1") == "1" else 1)
                if args[:2] == ["repo", "create"]:
                    sys.exit(0)
                if args[:2] == ["repo", "clone"]:
                    destination = Path(args[3])
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / "README.md").write_text("private slides\\n", encoding="utf-8")
                    sys.exit(0)
                raise SystemExit("unexpected gh call: " + " ".join(args))
                """
            ),
            encoding="utf-8",
        )
        gh.chmod(0o755)

        git = self.bin / "git"
        git.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                log = Path(os.environ["STUB_LOG"])
                with log.open("a", encoding="utf-8") as handle:
                    handle.write("git " + " ".join(args) + "\\n")
                if args[:2] == ["switch", "-C"] and args[-1] == "origin/main":
                    path = Path("_data/slide_modes.yml")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if os.environ.get("CURRENT_MODE") == "private":
                        path.write_text("fall-2026-01: private\\n", encoding="utf-8")
                    else:
                        path.write_text(
                            "# Maintainer-managed delivery modes. Omitted records are public by default.\\n",
                            encoding="utf-8",
                        )
                if "diff" in args and "--cached" in args and "--quiet" in args:
                    target = "PRIVATE_TEMPLATE_DIFF" if any("/repo" in arg for arg in args) else "MANIFEST_DIFF"
                    sys.exit(1 if os.environ.get(target, "0") == "1" else 0)
                sys.exit(0)
                """
            ),
            encoding="utf-8",
        )
        git.chmod(0o755)

        python = self.bin / "python"
        python.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                log = Path(os.environ["STUB_LOG"])
                with log.open("a", encoding="utf-8") as handle:
                    handle.write("python " + " ".join(args) + "\\n")
                if args[:1] == ["scripts/submission_registry.py"]:
                    print('{"status":"owner_match"}')
                    sys.exit(0)
                if args[:1] == ["-"]:
                    print(os.environ.get("CURRENT_MODE", "public"))
                    sys.exit(0)
                if args[:1] == ["scripts/set_slide_mode.py"]:
                    record_id = args[args.index("--record-id") + 1]
                    mode = args[args.index("--mode") + 1]
                    path = Path("_data/slide_modes.yml")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"{record_id}: {mode}\\n", encoding="utf-8")
                    sys.exit(0)
                raise SystemExit("unexpected python call: " + " ".join(args))
                """
            ),
            encoding="utf-8",
        )
        python.chmod(0o755)

    def run_workflow(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        if shutil.which("jq") is None:
            self.skipTest("jq is required to exercise the workflow bash")
        env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            "GH_TOKEN": "",
            "FALLBACK_GITHUB_TOKEN": "fallback-token",
            "ADMIN_TOKEN_AVAILABLE": "true",
            "EVENT_NAME": "issue_comment",
            "REPOSITORY": "stat701/stat701.github.io",
            "COMMENT_PR_NUMBER": "5",
            "CLOSED_PR_NUMBER": "",
            "DISPATCH_PR_NUMBER": "",
            "COMMENT_BODY": "/slides public",
            "COMMENT_AUTHOR_ID": "222",
            "COMMENT_AUTHOR_TYPE": "User",
            "CLOSED_MERGED": "",
            "CLOSED_MERGER_ID": "",
            "CLOSED_MERGER_TYPE": "",
            "DISPATCH_ACTOR_ID": "",
            "GITHUB_RUN_ID": "99",
            "PR_JSON": json_pull_request(),
            "FILES": "_talks/fall-2026-01.md",
            "MANIFEST_DIFF": "1",
            "PRIVATE_TEMPLATE_DIFF": "0",
            "CURRENT_MODE": "public",
            "MAIN_REF_EXISTS": "1",
            "MERGE_FAILURES": "0",
        }
        env.update(overrides)
        manifest = self.work / "_data/slide_modes.yml"
        if env.get("CURRENT_MODE") == "private":
            manifest.write_text(
                "fall-2026-01: private\n",
                encoding="utf-8",
            )
        else:
            manifest.write_text(
                "# Maintainer-managed delivery modes. Omitted records are public by default.\n",
                encoding="utf-8",
            )
        return subprocess.run(
            ["bash", str(self.script)],
            cwd=self.work,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def log_text(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def test_commenter_must_be_pr_author_or_instructor(self) -> None:
        result = self.run_workflow(COMMENT_AUTHOR_ID="333", COMMENT_BODY="/slides private")

        self.assertNotEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("only the registered student or instructor", log)
        self.assertNotIn("scripts/submission_registry.py", log)
        self.assertNotIn("private-slides-fall-2026-01", log)

    def test_private_mode_requires_admin_token_before_using_fallback(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides private",
            ADMIN_TOKEN_AVAILABLE="false",
        )

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("ORG_REPO_ADMIN_TOKEN", result.stdout)
        log = self.log_text()
        self.assertNotIn("repo view stat701/private-slides-fall-2026-01", log)
        self.assertNotIn("scripts/set_slide_mode.py", log)

    def test_public_from_private_requires_admin_token_before_mutation(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides public",
            CURRENT_MODE="private",
            ADMIN_TOKEN_AVAILABLE="false",
        )

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("Changing slide delivery mode requires", result.stdout)
        log = self.log_text()
        self.assertNotIn("scripts/set_slide_mode.py", log)
        self.assertNotIn("pr create", log)

    def test_merged_private_title_configures_private_delivery_without_approval(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="pull_request_target",
            COMMENT_PR_NUMBER="",
            CLOSED_PR_NUMBER="5",
            CLOSED_MERGED="true",
            CLOSED_MERGER_ID="12053767",
            CLOSED_MERGER_TYPE="User",
            PR_JSON=json_pull_request(
                body=f"{PUBLIC_UNCHECKED}\n{PRIVATE_CHOICE}",
                state="closed",
                merged=True,
            ),
            CURRENT_MODE="public",
            MANIFEST_DIFF="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("repo view stat701/private-slides-fall-2026-01", log)
        self.assertIn("python scripts/set_slide_mode.py --record-id fall-2026-01 --mode private", log)
        self.assertNotIn("pull_request_review", log)
        self.assertIn("Private slides enabled", log)

    def test_merged_ambiguous_checklist_fails(self) -> None:
        bodies = (
            f"{PUBLIC_CHOICE}\n{PRIVATE_CHOICE}",
            f"{PUBLIC_UNCHECKED}\n{PRIVATE_UNCHECKED}",
        )
        for body in bodies:
            with self.subTest(body=body):
                result = self.run_workflow(
                    EVENT_NAME="pull_request_target",
                    COMMENT_PR_NUMBER="",
                    CLOSED_PR_NUMBER="5",
                    CLOSED_MERGED="true",
                    CLOSED_MERGER_ID="12053767",
                    CLOSED_MERGER_TYPE="User",
                    PR_JSON=json_pull_request(body=body, state="closed", merged=True),
                )

                self.assertNotEqual(result.returncode, 0, result.stderr)
                log = self.log_text()
                self.assertIn("Please check exactly one slide-delivery option", log)
                self.assertNotIn("private-slides-fall-2026-01", log)

    def test_non_title_merge_cleanly_skips_slide_mode_configuration(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="pull_request_target",
            COMMENT_PR_NUMBER="",
            CLOSED_PR_NUMBER="5",
            CLOSED_MERGED="true",
            CLOSED_MERGER_ID="12053767",
            CLOSED_MERGER_TYPE="User",
            PR_JSON=json_pull_request(
                body=f"{PUBLIC_UNCHECKED}\n{PRIVATE_CHOICE}",
                state="closed",
                merged=True,
            ),
            FILES="_slides/fall-2026-01.pdf",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "Merged pull request is not for a title-and-abstract submission; skipping slide-mode configuration.",
            result.stdout,
        )
        self.assertNotIn("scripts/submission_registry.py", self.log_text())

    def test_closed_unmerged_pull_request_target_skips_before_fetching_pr(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="pull_request_target",
            COMMENT_PR_NUMBER="",
            CLOSED_PR_NUMBER="5",
            CLOSED_MERGED="false",
            CLOSED_MERGER_ID="",
            CLOSED_MERGER_TYPE="",
            PR_JSON=json_pull_request(
                body=f"{PUBLIC_UNCHECKED}\n{PRIVATE_CHOICE}",
                state="closed",
                merged=False,
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pull request was not merged by the instructor", result.stdout)
        self.assertNotIn("/repos/stat701/stat701.github.io/pulls/5", self.log_text())

    def test_workflow_dispatch_can_recover_merged_private_title(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="workflow_dispatch",
            COMMENT_PR_NUMBER="",
            DISPATCH_PR_NUMBER="5",
            DISPATCH_ACTOR_ID="12053767",
            PR_JSON=json_pull_request(
                body=f"{PUBLIC_UNCHECKED}\n{PRIVATE_CHOICE}",
                state="closed",
                merged=True,
            ),
            CURRENT_MODE="public",
            MANIFEST_DIFF="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("gh api /repos/stat701/stat701.github.io/pulls/5", log)
        self.assertIn("python scripts/set_slide_mode.py --record-id fall-2026-01 --mode private", log)
        self.assertIn("Private slides enabled", log)

    def test_workflow_dispatch_rejects_unauthorized_actor(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="workflow_dispatch",
            COMMENT_PR_NUMBER="",
            DISPATCH_PR_NUMBER="5",
            DISPATCH_ACTOR_ID="222",
        )

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("Only the instructor may retry slide-mode configuration", result.stdout)
        self.assertNotIn("/repos/stat701/stat701.github.io/pulls/5", self.log_text())

    def test_workflow_dispatch_unmerged_pr_skips(self) -> None:
        result = self.run_workflow(
            EVENT_NAME="workflow_dispatch",
            COMMENT_PR_NUMBER="",
            DISPATCH_PR_NUMBER="5",
            DISPATCH_ACTOR_ID="12053767",
            PR_JSON=json_pull_request(
                body=f"{PUBLIC_UNCHECKED}\n{PRIVATE_CHOICE}",
                state="open",
                merged=False,
            ),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pull request is not merged; skipping slide-mode configuration.", result.stdout)
        self.assertNotIn("scripts/submission_registry.py", self.log_text())

    def test_invalid_pr_number_fails_before_fetching_pr(self) -> None:
        result = self.run_workflow(COMMENT_PR_NUMBER="not-a-number")

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("Invalid pull request number", result.stdout)
        self.assertNotIn("/repos/stat701/stat701.github.io/pulls/not-a-number", self.log_text())

    def test_public_mode_uses_default_without_manifest_write(self) -> None:
        result = self.run_workflow(COMMENT_BODY="/slides public", CURRENT_MODE="public")

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertNotIn("scripts/set_slide_mode.py", log)
        self.assertNotIn("pr create", log)
        self.assertIn("Public slides enabled", log)

    def test_public_mode_updates_manifest_after_private(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides public",
            CURRENT_MODE="private",
            MANIFEST_DIFF="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("python scripts/set_slide_mode.py --record-id fall-2026-01 --mode public", log)
        self.assertIn("git commit -m Set fall-2026-01 slide delivery mode to public", log)
        self.assertIn("pr create --repo stat701/stat701.github.io --base main --head bot/slide-mode-fall-2026-01-99-1 --title Set fall-2026-01 slides to public", log)
        self.assertIn("Public slides enabled", log)

    def test_manifest_merge_conflict_retries_from_fresh_main(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides public",
            CURRENT_MODE="private",
            MANIFEST_DIFF="1",
            MERGE_FAILURES="1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("--head bot/slide-mode-fall-2026-01-99-1", log)
        self.assertIn("--head bot/slide-mode-fall-2026-01-99-2", log)
        self.assertIn("pr close https://github.com/stat701/stat701.github.io/pull/900", log)
        self.assertIn("pr merge https://github.com/stat701/stat701.github.io/pull/901", log)
        self.assertIn("Public slides enabled", log)

    def test_manifest_merge_failure_errors_after_three_attempts(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides public",
            CURRENT_MODE="private",
            MANIFEST_DIFF="1",
            MERGE_FAILURES="3",
        )

        self.assertNotEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("--head bot/slide-mode-fall-2026-01-99-1", log)
        self.assertIn("--head bot/slide-mode-fall-2026-01-99-2", log)
        self.assertIn("--head bot/slide-mode-fall-2026-01-99-3", log)
        self.assertEqual(log.count("pr close https://github.com/stat701/stat701.github.io/pull/"), 3)
        self.assertIn("Failed to merge slide delivery mode for fall-2026-01 after 3 attempts", result.stdout)
        self.assertNotIn("Public slides enabled", log)

    def test_private_repo_must_be_private(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides private",
            PRIVATE_REPO_VISIBILITY="PUBLIC",
        )

        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("exists but is not private", result.stdout)
        log = self.log_text()
        self.assertIn("repo view stat701/private-slides-fall-2026-01 --json visibility --jq .visibility", log)
        self.assertNotIn("collaborators/student", log)

    def test_repeated_private_choice_skips_empty_commits(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides private",
            CURRENT_MODE="private",
            MANIFEST_DIFF="0",
            PRIVATE_TEMPLATE_DIFF="0",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("repo clone stat701/private-slides-fall-2026-01", log)
        self.assertNotIn("scripts/set_slide_mode.py", log)
        self.assertNotIn(" commit ", log)
        self.assertIn("Private slides enabled", log)

    def test_empty_private_repo_is_initialized_on_main(self) -> None:
        result = self.run_workflow(
            COMMENT_BODY="/slides private",
            CURRENT_MODE="private",
            MAIN_REF_EXISTS="0",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log_text()
        self.assertIn("git -C", log)
        self.assertIn(" init -b main", log)
        self.assertIn(" remote add origin https://github.com/stat701/private-slides-fall-2026-01.git", log)
        self.assertNotIn("repo clone stat701/private-slides-fall-2026-01", log)
        self.assertLess(
            log.index("git -C"),
            log.index("collaborators/student"),
            log,
        )


def json_pull_request(body: str = "", state: str = "open", merged: bool = False) -> str:
    return json.dumps(
        {
            "state": state,
            "merged": merged,
            "merged_by": {"id": 12053767, "login": "instructor", "type": "User"}
            if merged
            else None,
            "body": body,
            "user": {"id": 222, "login": "student", "type": "User"},
            "head": {"repo": {"full_name": "student/stat701.github.io"}},
        }
    )


if __name__ == "__main__":
    unittest.main()
