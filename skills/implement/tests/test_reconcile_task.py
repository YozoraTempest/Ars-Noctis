from __future__ import annotations

import importlib.util
import subprocess
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

    def test_missing_remote_evidence_reruns_or_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.repository(Path(directory))
            rerun = self.module.reconcile(repo, "U01.T01", None)
            self.assertEqual(rerun["status"], "rerun-from-checkpoint")
            blocked = self.module.reconcile(repo, "U01.T01", "deadbeef")
            self.assertEqual(blocked["status"], "blocked-evidence-conflict")


if __name__ == "__main__":
    unittest.main()
