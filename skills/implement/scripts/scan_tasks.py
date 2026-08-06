#!/usr/bin/env python3
"""List Noctis task statuses without changing project files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


VALID_STATUSES = ("active", "completed", "blocked")
VALID_STAGES = ("implement", "review", "fix", "verify")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Noctis task statuses.")
    parser.add_argument("--root", type=Path, help="Project root to scan.")
    parser.add_argument(
        "--status", choices=("all", *VALID_STATUSES), default="all", help="Status filter."
    )
    parser.add_argument(
        "--stage", choices=("all", *VALID_STAGES), default="all", help="Stage filter."
    )
    parser.add_argument(
        "--format", choices=("table", "json"), default="table", help="Output format."
    )
    return parser.parse_args()


def project_root(explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        root = explicit_root.resolve()
        if not root.is_dir():
            raise ValueError(f"Project root does not exist: {root}")
        return root

    current = Path.cwd().resolve()
    candidates = [path for path in (current, *current.parents) if (path / "Noctis").is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Cannot find Noctis. Pass --root explicitly.")
    raise ValueError(f"Multiple Noctis roots found: {', '.join(map(str, candidates))}")


def read_metadata(path: Path) -> dict[str, str | list[str] | None]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter")

    metadata: dict[str, str | list[str]] = {}
    list_key: str | None = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith("- ") and list_key is not None:
            value = stripped[2:].strip().strip("\"'")
            current = metadata[list_key]
            if isinstance(current, list):
                current.append(value)
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip().strip("\"'")
        if value:
            metadata[key] = value
            list_key = None
        else:
            metadata[key] = []
            list_key = key
    else:
        raise ValueError("unterminated frontmatter")

    status = metadata.get("status")
    if status not in VALID_STATUSES:
        allowed = ", ".join(VALID_STATUSES)
        raise ValueError(f"status must be one of: {allowed}")

    stage = metadata.get("stage")
    if status == "completed":
        if stage is not None:
            raise ValueError("completed task must not declare stage")
    elif stage not in VALID_STAGES:
        allowed = ", ".join(VALID_STAGES)
        raise ValueError(f"active or blocked task stage must be one of: {allowed}")

    workflow = metadata.get("workflow")
    if not isinstance(workflow, list) or not workflow:
        raise ValueError("workflow must be a non-empty list")
    if any(not SKILL_NAME.fullmatch(item) for item in workflow):
        raise ValueError("workflow entries must be lowercase skill names")

    return {"status": status, "stage": stage, "workflow": workflow}


def task_files(noctis_root: Path) -> list[Path]:
    files = {
        *noctis_root.glob("*/tasks/*/tasks.md"),
        *noctis_root.glob("*/tasks/*/*/tasks.md"),
    }
    return sorted(files, key=lambda path: path.as_posix().lower())


def scan(
    root: Path, status_filter: str, stage_filter: str
) -> tuple[list[dict[str, str | list[str] | None]], list[str]]:
    tasks: list[dict[str, str | list[str] | None]] = []
    errors: list[str] = []
    noctis_root = root / "Noctis"

    for path in task_files(noctis_root) if noctis_root.is_dir() else []:
        relative = path.relative_to(root)
        parts = path.relative_to(noctis_root).parts
        try:
            metadata = read_metadata(path)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{relative.as_posix()}: {error}")
            continue

        status = str(metadata["status"])
        stage = metadata["stage"]
        matches_status = status_filter == "all" or status == status_filter
        matches_stage = stage_filter == "all" or stage == stage_filter
        if matches_status and matches_stage:
            tasks.append(
                {
                    "status": status,
                    "stage": stage,
                    "workflow": metadata["workflow"],
                    "domain": parts[0],
                    "task": parts[2],
                    "subtask": parts[3] if len(parts) == 5 else None,
                    "path": relative.as_posix(),
                }
            )

    return tasks, errors


def print_table(tasks: list[dict[str, str | list[str] | None]]) -> None:
    if not tasks:
        print("No Noctis tasks found.")
        return

    headers = ("STATUS", "STAGE", "WORKFLOW", "DOMAIN", "TASK", "SUBTASK", "PATH")
    rows = []
    for task in tasks:
        workflow = task["workflow"]
        values = {
            **task,
            "workflow": ",".join(workflow) if isinstance(workflow, list) else "-",
        }
        rows.append(
            tuple(
                str(values[key] or "-")
                for key in ("status", "stage", "workflow", "domain", "task", "subtask", "path")
            )
        )
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def main() -> int:
    args = parse_args()
    try:
        root = project_root(args.root)
        tasks, errors = scan(root, args.status, args.stage)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"projectRoot": str(root), "tasks": tasks, "errors": errors}, ensure_ascii=False, indent=2))
    else:
        print_table(tasks)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
