from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


_TEMPLATE_LOCK = threading.Lock()
_TEMPLATE_DIRECTORY: tempfile.TemporaryDirectory[str] | None = None
_TEMPLATE_REPOSITORY: Path | None = None


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def repository_template() -> Path:
    global _TEMPLATE_DIRECTORY, _TEMPLATE_REPOSITORY
    with _TEMPLATE_LOCK:
        if _TEMPLATE_REPOSITORY is not None:
            return _TEMPLATE_REPOSITORY
        _TEMPLATE_DIRECTORY = tempfile.TemporaryDirectory()
        repository = Path(_TEMPLATE_DIRECTORY.name) / "repository"
        repository.mkdir()
        _run_git(repository, "init", "-b", "main")
        _run_git(repository, "config", "user.email", "tests@example.test")
        _run_git(repository, "config", "user.name", "Repository Tests")
        (repository / "base.txt").write_text("base\n", encoding="utf-8")
        _run_git(repository, "add", "base.txt")
        _run_git(repository, "commit", "-m", "test: initialize repository")
        _TEMPLATE_REPOSITORY = repository
        return repository


class GitRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        shutil.copytree(repository_template(), self.project)

    def tearDown(self) -> None:
        self.temporary.cleanup()
        super().tearDown()

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.project,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / "fixtures" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path
