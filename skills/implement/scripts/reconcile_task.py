#!/usr/bin/env python3
"""Reconcile one implementation Task against reachable Git evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


class ReconcileError(ValueError):
    pass


def git(repo: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise ReconcileError(message or f"git {' '.join(arguments)} failed")
    return result.stdout.strip()


def task_commits(repo: Path, task_id: str) -> list[str]:
    output = git(
        repo,
        "log",
        "--format=%H%x09%(trailers:key=Noctis-Task,valueonly,separator=%x1f)",
        "HEAD",
    )
    matches = []
    for line in output.splitlines():
        commit, _, trailers = line.partition("\t")
        values = [value.strip() for value in trailers.split("\x1f")]
        if task_id in values:
            matches.append(commit)
    return matches


def is_reachable(repo: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def commit_has_task(repo: Path, commit: str, task_id: str) -> bool:
    message = git(repo, "show", "-s", "--format=%B", commit, check=False)
    return any(
        line.partition(":")[2].strip() == task_id
        for line in message.splitlines()
        if line.lower().startswith("noctis-task:")
    )


def reconcile(repo: Path, task_id: str, recorded_commit: str | None) -> dict:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ReconcileError(f"repository does not exist: {repo}")
    git(repo, "rev-parse", "--show-toplevel")
    dirty = bool(git(repo, "status", "--porcelain=v1", "--untracked-files=all"))
    commits = task_commits(repo, task_id)

    status: str
    commit: str | None = None
    reason: str
    if recorded_commit is not None:
        commit = recorded_commit.strip()
        if not commit or not is_reachable(repo, commit):
            status = "blocked-evidence-conflict"
            reason = "recorded commit is not reachable from HEAD"
        elif not commit_has_task(repo, commit, task_id):
            status = "blocked-evidence-conflict"
            reason = "recorded commit does not carry the expected Noctis-Task trailer"
        elif commits and commit not in commits:
            status = "blocked-evidence-conflict"
            reason = "reachable Task trailer points to a different commit"
        else:
            status = "consistent"
            reason = "recorded commit is reachable and carries the expected trailer"
    elif len(commits) > 1:
        status = "blocked-evidence-conflict"
        reason = "multiple reachable commits carry the same Noctis-Task trailer"
    elif len(commits) == 1:
        status = "repair-record-from-commit"
        commit = commits[0]
        reason = "Task commit is reachable but no commit is recorded"
    elif dirty:
        status = "continue-uncommitted"
        reason = "no Task commit exists and the current worktree has changes"
    else:
        status = "rerun-from-checkpoint"
        reason = "no reachable Task commit or local uncommitted work exists"

    return {
        "ok": status != "blocked-evidence-conflict",
        "status": status,
        "repository": str(repo),
        "task": task_id,
        "commit": commit,
        "dirty": dirty,
        "candidates": commits,
        "reason": reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Target Git repository.")
    parser.add_argument("--task-id", required=True, help="Stable Noctis Task ID.")
    parser.add_argument(
        "--recorded-commit",
        help="Commit currently recorded by implementation.md, if any.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = reconcile(args.repo, args.task_id, args.recorded_commit)
    except (OSError, UnicodeError, ReconcileError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
