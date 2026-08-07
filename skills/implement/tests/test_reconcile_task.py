from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_task.py"


def load_script():
    spec = importlib.util.spec_from_file_location("reconcile_task", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReconcileTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def git(self, repo: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *arguments],
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()

    def repository(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "--quiet")
        self.git(repo, "config", "user.name", "Noctis Test")
        self.git(repo, "config", "user.email", "noctis@example.invalid")
        (repo / "base.txt").write_text("base\n", encoding="utf-8")
        self.git(repo, "add", "base.txt")
        self.git(repo, "commit", "--quiet", "-m", "chore: base")
        return repo

    def task_commit(self, repo: Path, task_id: str) -> str:
        (repo / "work.txt").write_text(task_id + "\n", encoding="utf-8")
        self.git(repo, "add", "work.txt")
        self.git(
            repo,
            "commit",
            "--quiet",
            "-m",
            "feat: task",
            "-m",
            f"Noctis-Task: {task_id}",
        )
        return self.git(repo, "rev-parse", "HEAD")

    def test_uncommitted_work_continues_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            (repo / "work.txt").write_text("partial\n", encoding="utf-8")
            result = self.module.reconcile(repo, "U01.T01", None)
            self.assertEqual(result["status"], "continue-uncommitted")

    def test_reachable_commit_repairs_or_confirms_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            commit = self.task_commit(repo, "U01.T01")
            repair = self.module.reconcile(repo, "U01.T01", None)
            self.assertEqual(repair["status"], "repair-record-from-commit")
            self.assertEqual(repair["commit"], commit)
            consistent = self.module.reconcile(repo, "U01.T01", commit)
            self.assertEqual(consistent["status"], "consistent")
            plan = self.module.record_repair(repair, 3)
            self.assertEqual(plan["evidence"]["commit"], commit)
            self.assertEqual(
                plan["command"]["arguments"],
                [
                    "append",
                    "--section",
                    "completed",
                    "--item",
                    "U01.T01",
                    "--expected-revision",
                    "3",
                    "--input",
                    "-",
                ],
            )

    def test_missing_remote_evidence_reruns_or_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            rerun = self.module.reconcile(repo, "U01.T01", None)
            self.assertEqual(rerun["status"], "rerun-from-checkpoint")
            blocked = self.module.reconcile(repo, "U01.T01", "deadbeef")
            self.assertEqual(blocked["status"], "blocked-evidence-conflict")

    def test_fetched_commit_is_reconciled_in_a_fresh_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.repository(root)
            commit = self.task_commit(repo, "U01.T01")
            remote = root / "remote.git"
            target = root / "target"
            subprocess.run(
                ["git", "clone", "--quiet", "--bare", str(repo), str(remote)],
                check=True,
            )
            subprocess.run(
                ["git", "clone", "--quiet", str(remote), str(target)], check=True
            )
            result = self.module.reconcile(target, "U01.T01", None)
            self.assertEqual(result["status"], "repair-record-from-commit")
            self.assertEqual(result["commit"], commit)

    def test_multiple_ordered_task_commits_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            first = self.task_commit(repo, "U01.T01")
            (repo / "work.txt").write_text("second\n", encoding="utf-8")
            self.git(repo, "add", "work.txt")
            self.git(
                repo,
                "commit",
                "--quiet",
                "-m",
                "fix: second",
                "-m",
                "Noctis-Task: U01.T01",
            )
            second = self.git(repo, "rev-parse", "HEAD")
            repair = self.module.reconcile(repo, "U01.T01", None)
            self.assertEqual(repair["status"], "repair-record-from-commit")
            self.assertEqual(repair["commits"], [first, second])
            self.assertEqual(repair["commit"], second)
            consistent = self.module.reconcile(
                repo, "U01.T01", [first, second]
            )
            self.assertEqual(consistent["status"], "consistent")
            reversed_record = self.module.reconcile(
                repo, "U01.T01", [second, first]
            )
            self.assertEqual(
                reversed_record["status"], "blocked-evidence-conflict"
            )
            plan = self.module.record_repair(repair, 2)
            self.assertEqual(plan["evidence"]["commits"], [first, second])

    def test_cli_emits_machine_readable_record_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            commit = self.task_commit(repo, "U01.T01")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--action",
                    "plan-record-repair",
                    "--repo",
                    str(repo),
                    "--task-id",
                    "U01.T01",
                    "--record-revision",
                    "2",
                ],
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["evidence"]["commit"], commit)


if __name__ == "__main__":
    unittest.main()
