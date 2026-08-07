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
    return list(reversed(matches))


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


def _recorded_commits(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    normalized = [commit.strip() for commit in values]
    if not normalized or any(not commit for commit in normalized):
        raise ReconcileError("recorded commits must be non-empty commit ids")
    if len(normalized) != len(set(normalized)):
        raise ReconcileError("recorded commits contain duplicates")
    return normalized


def reconcile(
    repo: Path, task_id: str, recorded_commit: str | list[str] | None
) -> dict:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ReconcileError(f"repository does not exist: {repo}")
    git(repo, "rev-parse", "--show-toplevel")
    dirty = bool(git(repo, "status", "--porcelain=v1", "--untracked-files=all"))
    commits = task_commits(repo, task_id)
    recorded = _recorded_commits(recorded_commit)

    status: str
    commit: str | None = commits[-1] if commits else None
    reason: str
    if recorded:
        unreachable = [value for value in recorded if not is_reachable(repo, value)]
        wrong_task = [
            value
            for value in recorded
            if value not in unreachable and not commit_has_task(repo, value, task_id)
        ]
        if unreachable:
            status = "blocked-evidence-conflict"
            reason = "recorded commits are not reachable from HEAD"
        elif wrong_task:
            status = "blocked-evidence-conflict"
            reason = "recorded commits do not carry the expected Noctis-Task trailer"
        elif recorded != commits:
            status = "blocked-evidence-conflict"
            reason = "recorded commits differ from the ordered reachable Task commits"
        else:
            status = "consistent"
            reason = "all ordered Task commits are reachable and carry the expected trailer"
    elif commits:
        status = "repair-record-from-commit"
        reason = "one or more Task commits are reachable but none are recorded"
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
        "commits": commits,
        "recordedCommits": recorded,
        "dirty": dirty,
        "candidates": commits,
        "reason": reason,
    }


def record_repair(result: dict, record_revision: int) -> dict:
    if result.get("status") != "repair-record-from-commit" or not result.get("commits"):
        raise ReconcileError(
            "record repair requires a repair-record-from-commit reconciliation result"
        )
    if isinstance(record_revision, bool) or record_revision < 1:
        raise ReconcileError("record revision must be a positive integer")
    task_id = result["task"]
    commits = result["commits"]
    commit_lines = "\n".join(f"  - {commit}" for commit in commits)
    content = (
        f"### {task_id}\n\n"
        "- Result: recovered from reachable Git evidence\n"
        f"- Repository: {result['repository']}\n"
        f"- Commits:\n{commit_lines}\n"
        "- Recovery: record repaired after verifying the Noctis-Task trailer"
    )
    return {
        "version": 1,
        "status": "record-repair-ready",
        "evidence": {"task": task_id, "commit": commits[-1], "commits": commits},
        "command": {
            "tool": "scripts/implementation.py",
            "arguments": [
                "append",
                "--section",
                "completed",
                "--item",
                task_id,
                "--expected-revision",
                str(record_revision),
                "--input",
                "-",
            ],
            "stdin": {"content": content},
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("inspect", "plan-record-repair"), default="inspect"
    )
    parser.add_argument("--repo", type=Path, required=True, help="Target Git repository.")
    parser.add_argument("--task-id", required=True, help="Stable Noctis Task ID.")
    parser.add_argument(
        "--recorded-commit",
        action="append",
        help="Ordered commit recorded by implementation.md; repeat for multiple commits.",
    )
    parser.add_argument(
        "--record-revision",
        type=int,
        help="Current implementation.md revision for plan-record-repair.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = reconcile(args.repo, args.task_id, args.recorded_commit)
        if args.action == "plan-record-repair":
            if args.record_revision is None:
                raise ReconcileError(
                    "--record-revision is required for plan-record-repair"
                )
            result = record_repair(result, args.record_revision)
    except (OSError, UnicodeError, ReconcileError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
