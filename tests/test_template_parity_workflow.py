from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/validate-submission.yml"
SHARED = ("validate_slide_pdf.py", "report_pdf_validation.py")


def parity_script() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index("      - name: Check proposed private PDF template parity")
    run = lines.index("        run: |", start)
    commands = []
    for line in lines[run + 1 :]:
        if line.strip() and not line.startswith("          "):
            break
        commands.append(line[10:] if line else "")
    return "\n".join(commands) + "\n"


class TemplateParityWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.repo = self.work / "submission"
        self.repo.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Synthetic fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "README.md").write_text("Synthetic fixture\n", encoding="utf-8")
        self.commit("Initial fixture")

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *arguments],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--message", message)
        return self.git("rev-parse", "HEAD")

    def write_pairs(self, content: bytes = b"this is deliberately invalid Python!\n") -> None:
        for name in SHARED:
            for prefix in ("scripts", "templates/private-slides/scripts"):
                path = self.repo / prefix / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

    def check(self, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", parity_script()],
            cwd=self.work,
            env=os.environ | environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_identical_invalid_python_is_compared_without_execution(self) -> None:
        self.write_pairs()
        self.commit("Identical opaque source")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_executable_content_is_never_run(self) -> None:
        marker = self.work / "must-not-exist"
        self.write_pairs(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode())
        self.commit("Code must remain data")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_each_public_script_change_requires_matching_template(self) -> None:
        self.write_pairs()
        self.commit("Install paired scripts")
        for name in SHARED:
            with self.subTest(script=name):
                (self.repo / "scripts" / name).write_bytes(b"updated opaque content\n")
                self.commit("Change only public script")
                result = self.check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sync_private_slide_template.py", result.stderr)
                self.assertIn(name, result.stderr)
                (self.repo / "templates/private-slides/scripts" / name).write_bytes(
                    b"updated opaque content\n"
                )
                self.commit("Synchronize private copy")
                result = self.check()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_template_file_is_rejected(self) -> None:
        self.write_pairs()
        (self.repo / "templates/private-slides/scripts/validate_slide_pdf.py").unlink()
        self.commit("Missing private engine")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)

    def test_identical_symlink_blobs_are_not_accepted_as_scripts(self) -> None:
        self.write_pairs()
        for prefix in ("scripts", "templates/private-slides/scripts"):
            path = self.repo / prefix / "validate_slide_pdf.py"
            path.unlink()
            path.symlink_to("report_pdf_validation.py")
        self.commit("Symlinks are not scripts")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)

    def test_old_student_branch_receives_new_base_files_in_merge_tree(self) -> None:
        self.git("switch", "-c", "student")
        (self.repo / "talk.md").write_text("Synthetic talk metadata\n", encoding="utf-8")
        old_student_head = self.commit("Student submission before template rollout")
        self.git("switch", "main")
        self.write_pairs()
        self.commit("Add current private infrastructure")
        self.git("merge", "--no-edit", "student")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), old_student_head)
        result = self.check(HEAD_SHA=old_student_head)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_reads_committed_blobs_instead_of_worktree_files(self) -> None:
        self.write_pairs()
        self.commit("Matching proposed commit")
        (self.repo / "scripts/validate_slide_pdf.py").write_bytes(b"Uncommitted mismatch\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
