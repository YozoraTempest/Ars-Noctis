#!/usr/bin/env python3
"""List Noctis task statuses without changing project files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


VALID_STATUSES = ("open", "completed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Noctis task statuses.")
    parser.add_argument("--root", type=Path, help="Project root to scan.")
    parser.add_argument(
        "--status", choices=("all", *VALID_STATUSES), default="all", help="Status filter."
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


def read_status(path: Path) -> str:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing frontmatter")

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, separator, value = stripped.partition(":")
        if separator and key.strip() == "status":
            status = value.strip().strip("\"'")
            if status not in VALID_STATUSES:
                allowed = ", ".join(VALID_STATUSES)
                raise ValueError(f"status must be one of: {allowed}")
            return status
    else:
        raise ValueError("unterminated frontmatter")

    raise ValueError("missing status")


def task_files(noctis_root: Path) -> list[Path]:
    files = {
        *noctis_root.glob("*/tasks/*/tasks.md"),
        *noctis_root.glob("*/tasks/*/*/tasks.md"),
    }
    return sorted(files, key=lambda path: path.as_posix().lower())


def scan(root: Path, status_filter: str) -> tuple[list[dict[str, str | None]], list[str]]:
    tasks: list[dict[str, str | None]] = []
    errors: list[str] = []
    noctis_root = root / "Noctis"

    for path in task_files(noctis_root) if noctis_root.is_dir() else []:
        relative = path.relative_to(root)
        parts = path.relative_to(noctis_root).parts
        try:
            status = read_status(path)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{relative.as_posix()}: {error}")
            continue

        if status_filter == "all" or status == status_filter:
            tasks.append(
                {
                    "status": status,
                    "domain": parts[0],
                    "task": parts[2],
                    "subtask": parts[3] if len(parts) == 5 else None,
                    "path": relative.as_posix(),
                }
            )

    return tasks, errors


def print_table(tasks: list[dict[str, str | None]]) -> None:
    if not tasks:
        print("No Noctis tasks found.")
        return

    headers = ("STATUS", "DOMAIN", "TASK", "SUBTASK", "PATH")
    rows = [tuple(str(task[key] or "-") for key in ("status", "domain", "task", "subtask", "path")) for task in tasks]
    widths = [max(len(header), *(len(row[index]) for row in rows)) for index, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def main() -> int:
    args = parse_args()
    try:
        root = project_root(args.root)
        tasks, errors = scan(root, args.status)
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
