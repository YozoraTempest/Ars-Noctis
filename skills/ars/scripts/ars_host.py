#!/usr/bin/env python3
"""Run compact Ars lifecycle commands through the public Noctis CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import ars_noctis as adapter
from ars import ArsError


class HostError(ValueError):
    """Raised when the compact Ars host cannot complete an operation."""


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_noctis(noctis: Path, arguments: list[str]) -> dict[str, Any]:
    executable = noctis.resolve()
    if not executable.is_file():
        raise HostError(f"Noctis CLI does not exist: {executable}")
    result = subprocess.run(
        [sys.executable, str(executable), *arguments],
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        try:
            payload = json.loads(detail)
            detail = payload.get("error", detail) if isinstance(payload, dict) else detail
        except json.JSONDecodeError:
            pass
        raise HostError(f"Noctis command failed: {detail}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise HostError("Noctis command returned invalid JSON") from error
    return adapter.object_value(output, "Noctis output")


def claim_cache_path(project: Path, claim_id: str) -> Path:
    normalized = adapter.uuid_value(claim_id, "claim_id")
    return (
        adapter.git_common_directory(project)
        / "ars-noctis"
        / "claims"
        / f"{normalized}.json"
    )


def cache_claim(project: Path, claim: dict[str, Any]) -> Path:
    path = claim_cache_path(project, claim.get("claim_id"))
    if path.exists():
        raise HostError(f"claim cache already exists: {path}")
    adapter.atomic_write_json(path, claim)
    return path


def create_run(
    *,
    project: Path,
    plan_path: Path,
    skills_roots: list[Path],
    noctis: Path,
    app_profile_path: Path | None = None,
    run_config_path: Path | None = None,
    explicit_config_path: Path | None = None,
    grants: list[str] | None = None,
    grant_reason: str | None = None,
) -> dict[str, Any]:
    plan = adapter.adapt_plan(
        adapter.load_json(plan_path),
        project,
        skills_roots,
        adapter.load_json(app_profile_path) if app_profile_path is not None else None,
        adapter.load_json(run_config_path) if run_config_path is not None else None,
        adapter.load_json(explicit_config_path)
        if explicit_config_path is not None
        else None,
    )
    with tempfile.TemporaryDirectory(prefix="ars-host-") as temporary:
        adapted_path = Path(temporary) / "noctis-plan.json"
        adapter.atomic_write_json(adapted_path, plan)
        run_noctis(noctis, ["plan-check", "--plan", str(adapted_path)])
        arguments = [
            "run-create",
            "--project",
            str(project.resolve()),
            "--plan",
            str(adapted_path),
        ]
        for grant in grants or []:
            arguments.extend(["--grant", grant])
        if grant_reason is not None:
            arguments.extend(["--grant-reason", grant_reason])
        created = run_noctis(noctis, arguments)
    return {"schema": "ars.host-create/v1", **created}


def next_task(
    *,
    project: Path,
    run_id: str,
    host_path: Path,
    noctis: Path,
    task_id: str | None = None,
) -> dict[str, Any]:
    arguments = [
        "task-claim",
        "--project",
        str(project.resolve()),
        "--run-id",
        adapter.uuid_value(run_id, "run_id"),
    ]
    if task_id is not None:
        arguments.extend(["--task-id", adapter.identifier(task_id, "task_id")])
    claim = run_noctis(noctis, arguments)
    cache_claim(project, claim)
    return adapter.dispatch_claim(claim, project, adapter.load_json(host_path))


def finish_task(
    *, project: Path, result_path: Path, noctis: Path
) -> dict[str, Any]:
    result = adapter.object_value(adapter.load_json(result_path), "result")
    claim_id = adapter.uuid_value(result.get("claim_id"), "result.claim_id")
    cache_path = claim_cache_path(project, claim_id)
    if not cache_path.is_file():
        raise HostError(f"claim cache does not exist: {cache_path}")
    claim = adapter.object_value(adapter.load_json(cache_path), "claim")
    adapted = adapter.adapt_result(claim, result, project)
    with tempfile.TemporaryDirectory(prefix="ars-host-") as temporary:
        adapted_path = Path(temporary) / "noctis-result.json"
        adapter.atomic_write_json(adapted_path, adapted)
        finished = run_noctis(
            noctis,
            [
                "task-finish",
                "--project",
                str(project.resolve()),
                "--run-id",
                claim["run_id"],
                "--task-id",
                claim["task_id"],
                "--claim-id",
                claim["claim_id"],
                "--expected-revision",
                str(claim["revision"]),
                "--result",
                str(adapted_path),
            ],
        )
    cache_path.unlink()
    return {"schema": "ars.host-finish/v1", **finished}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--project", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument("--skills-root", type=Path, action="append", required=True)
    create.add_argument("--noctis", type=Path, required=True)
    create.add_argument("--app-profile", type=Path)
    create.add_argument("--run-config", type=Path)
    create.add_argument("--explicit-config", type=Path)
    create.add_argument("--grant", action="append", default=[])
    create.add_argument("--grant-reason")

    next_command = commands.add_parser("next")
    next_command.add_argument("--project", type=Path, required=True)
    next_command.add_argument("--run-id", required=True)
    next_command.add_argument("--task-id")
    next_command.add_argument("--host", type=Path, required=True)
    next_command.add_argument("--noctis", type=Path, required=True)

    finish = commands.add_parser("finish")
    finish.add_argument("--project", type=Path, required=True)
    finish.add_argument("--result", type=Path, required=True)
    finish.add_argument("--noctis", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create":
            output = create_run(
                project=args.project,
                plan_path=args.plan,
                skills_roots=args.skills_root,
                noctis=args.noctis,
                app_profile_path=args.app_profile,
                run_config_path=args.run_config,
                explicit_config_path=args.explicit_config,
                grants=args.grant,
                grant_reason=args.grant_reason,
            )
        elif args.command == "next":
            output = next_task(
                project=args.project,
                run_id=args.run_id,
                task_id=args.task_id,
                host_path=args.host,
                noctis=args.noctis,
            )
        else:
            output = finish_task(
                project=args.project,
                result_path=args.result,
                noctis=args.noctis,
            )
        emit(output)
        return 0
    except (HostError, adapter.AdapterError, ArsError, OSError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
