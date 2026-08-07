"""Command-line surface for the Noctis execution engine."""

from __future__ import annotations

import argparse
from pathlib import Path


VALID_LEVELS = ("task", "unit", "work")
VALID_STATUSES = ("pending", "active", "completed", "blocked")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Noctis execution lifecycle and structured document toolchain."
    )
    groups = parser.add_subparsers(dest="group", required=True)

    entry = groups.add_parser(
        "entry", help="Discover or prepare a context-free execution entry."
    )
    entry.add_argument("--start", type=Path, default=Path.cwd())
    entry.add_argument("--record", type=Path, help="Specific noctis.md record.")
    entry.add_argument("--id", help="Task or Unit item selected from the record.")
    entry.add_argument(
        "--list", action="store_true", help="Return every candidate without selecting."
    )

    workflow = groups.add_parser(
        "workflow", help="Materialize a confirmed ExecutionPlan as pending records."
    )
    workflow_actions = workflow.add_subparsers(dest="action", required=True)
    materialize = workflow_actions.add_parser("materialize")
    materialize.add_argument("--project-root", type=Path, required=True)
    materialize.add_argument("--input", default="-", help="ExecutionPlan JSON or '-'.")
    materialize.add_argument("--confirmed", action="store_true")
    materialize.add_argument("--dry-run", action="store_true")

    orchestration = groups.add_parser(
        "orchestration", help="Operate Task, Unit, and Work orchestration."
    )
    actions = orchestration.add_subparsers(dest="action", required=True)

    create = actions.add_parser("create")
    create.add_argument("--level", choices=VALID_LEVELS, required=True)
    create.add_argument("--path", type=Path, required=True)
    create.add_argument("--input", default="-", help="Record input JSON or '-'.")
    create.add_argument("--dry-run", action="store_true")

    inspect = actions.add_parser("inspect")
    inspect.add_argument("--path", type=Path, required=True)
    inspect.add_argument("--id")
    inspect.add_argument("--format", choices=("json", "markdown"), default="json")

    for name in ("start", "resume"):
        command = actions.add_parser(name)
        command.add_argument("--path", type=Path, required=True)
        command.add_argument("--id", required=True)
        command.add_argument("--expected-revision", type=int, required=True)

    finish = actions.add_parser("finish")
    finish.add_argument("--path", type=Path, required=True)
    finish.add_argument("--id", required=True)
    finish.add_argument("--to-status", choices=("completed", "blocked"), required=True)
    finish.add_argument("--outcome", required=True)
    finish.add_argument("--artifacts", help="Artifact JSON file, or '-' for stdin.")
    finish.add_argument("--expected-revision", type=int, required=True)

    apply_result = actions.add_parser(
        "apply-result", help="Validate an ExecutorResult and advance its active Task."
    )
    apply_result.add_argument("--path", type=Path, required=True)
    apply_result.add_argument("--id", required=True)
    apply_result.add_argument("--expected-revision", type=int, required=True)
    apply_result.add_argument(
        "--input", default="-", help="ExecutorResult v1 JSON or '-'."
    )

    splice = actions.add_parser("splice")
    splice.add_argument("--path", type=Path, required=True)
    splice.add_argument("--after", required=True)
    splice.add_argument("--expected-revision", type=int, required=True)
    splice.add_argument("--input", default="-", help="Recovery splice JSON or '-'.")

    scan = actions.add_parser("scan")
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--level", choices=("all", *VALID_LEVELS), default="all")
    scan.add_argument("--status", choices=("all", *VALID_STATUSES), default="all")

    extend = groups.add_parser("extend", help="Operate structured Markdown extensions.")
    extend_actions = extend.add_subparsers(dest="action", required=True)
    for name in ("insert", "upsert", "sync", "remove"):
        command = extend_actions.add_parser(name)
        command.add_argument("--document", type=Path, required=True)
        command.add_argument("--slot", required=True)
        command.add_argument("--scope", choices=("once", "each", "item"), required=True)
        command.add_argument("--item")
        command.add_argument("--id", required=True)
        command.add_argument("--expected-revision", type=int, required=True)
        if name != "remove":
            command.add_argument("--content", required=True)

    read = extend_actions.add_parser("read")
    read.add_argument("--document", type=Path, required=True)
    read.add_argument("--id", required=True)
    read.add_argument("--item")
    read.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args()
