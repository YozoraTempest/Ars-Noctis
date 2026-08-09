from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import (
    NoctisError,
    RESULT_STATES,
    TERMINAL_STATES,
    exact,
    identifier,
    integer_value,
    json_value,
    object_value,
    string_list,
    text_value,
    timestamp_value,
    uuid_value,
    validate_extension,
    validate_executor,
    validate_origin,
    validate_plan,
    validate_result,
    validate_task,
)
from .state import (
    RUN_EVENTS,
    TASK_EVENTS,
    TASK_RESULT_EVENTS,
    derive_run_status,
    descendants,
    ready_task_ids,
    reduce_run_event,
    reduce_task_event,
    task_state,
    validate_dependency_states,
)


RUNS_RELATIVE_PATH = Path(".noctis") / "runs"
CACHE_SCHEMA_VERSION = 3


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise NoctisError(f"JSON file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise NoctisError(f"invalid JSON in {path}: {error}") from error


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    payload = json.dumps(
        json_value(value, str(path)), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_once(path: Path, value: Any, context: str) -> None:
    if path.exists():
        if load_json(path) != value:
            raise NoctisError(f"{context} already exists with different content: {path}")
        return
    atomic_write_json(path, value)


def run_git(
    root: Path, arguments: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise NoctisError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def git_repository(path: Path) -> Path:
    result = run_git(path.resolve(), ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def git_head(path: Path) -> str:
    return run_git(path.resolve(), ["rev-parse", "HEAD"]).stdout.strip().lower()


def git_branch(path: Path) -> str | None:
    result = run_git(path.resolve(), ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    return result.stdout.strip() or None


def git_commit_exists(root: Path, commit: str) -> bool:
    return run_git(root, ["cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode == 0


def git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode == 0


def repository_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise NoctisError(f"{path} is outside Git repository {repo}") from error


def runs_root(project: Path) -> Path:
    return project.resolve() / RUNS_RELATIVE_PATH


def run_directory(project: Path, run_id: str) -> Path:
    return runs_root(project) / uuid_value(run_id, "run_id")


def git_relative(project: Path, path: Path) -> str:
    return repository_relative(git_repository(project), path)


def cache_path(project: Path) -> Path:
    result = run_git(project.resolve(), ["rev-parse", "--absolute-git-dir"])
    return Path(result.stdout.strip()).resolve() / "noctis" / "cache.sqlite3"


def cache_connect(project: Path, *, create: bool) -> sqlite3.Connection | None:
    path = cache_path(project)
    if not path.is_file() and not create:
        return None
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS claims (
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            claim_id TEXT NOT NULL UNIQUE,
            attempt INTEGER NOT NULL,
            base_revision INTEGER NOT NULL,
            checkpoint_commit TEXT NOT NULL,
            started_at TEXT NOT NULL,
            PRIMARY KEY (run_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS authorizations (
            run_id TEXT NOT NULL,
            requirement TEXT NOT NULL,
            reason TEXT NOT NULL,
            authorized_at TEXT NOT NULL,
            PRIMARY KEY (run_id, requirement)
        );
        """
    )
    current = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if current is None:
        connection.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
            (str(CACHE_SCHEMA_VERSION),),
        )
        connection.commit()
    elif current["value"] != str(CACHE_SCHEMA_VERSION):
        actual = current["value"]
        connection.close()
        raise NoctisError(
            f"unsupported local cache schema {actual}; run recover to rebuild it"
        )
    return connection


def rebuild_cache(project: Path) -> None:
    path = cache_path(project)
    if path.exists():
        path.unlink()
    connection = cache_connect(project, create=True)
    if connection is not None:
        connection.close()


def active_grants(project: Path, run_id: str) -> list[str]:
    connection = cache_connect(project, create=False)
    if connection is None:
        return []
    try:
        return [
            row["requirement"]
            for row in connection.execute(
                "SELECT requirement FROM authorizations WHERE run_id = ? ORDER BY requirement",
                (run_id,),
            )
        ]
    finally:
        connection.close()


def authorize_local(project: Path, run_id: str, requirements: list[str], reason: str) -> None:
    connection = cache_connect(project, create=True)
    if connection is None:
        raise NoctisError("unable to create local cache")
    try:
        timestamp = now()
        connection.executemany(
            "INSERT OR REPLACE INTO authorizations(run_id, requirement, reason, authorized_at) VALUES(?, ?, ?, ?)",
            [(run_id, requirement, reason, timestamp) for requirement in requirements],
        )
        connection.commit()
    finally:
        connection.close()


def deauthorize_local(project: Path, run_id: str, requirements: list[str]) -> None:
    connection = cache_connect(project, create=False)
    if connection is None:
        return
    try:
        connection.executemany(
            "DELETE FROM authorizations WHERE run_id = ? AND requirement = ?",
            [(run_id, requirement) for requirement in requirements],
        )
        connection.commit()
    finally:
        connection.close()


def local_claim(project: Path, run_id: str, task_id: str) -> dict[str, Any] | None:
    connection = cache_connect(project, create=False)
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT * FROM claims WHERE run_id = ? AND task_id = ?",
            (run_id, task_id),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        connection.close()


def local_claims(project: Path, run_id: str) -> dict[str, dict[str, Any]]:
    connection = cache_connect(project, create=False)
    if connection is None:
        return {}
    try:
        return {
            row["task_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM claims WHERE run_id = ?", (run_id,)
            )
        }
    finally:
        connection.close()


def delete_local_claim(project: Path, run_id: str, task_id: str) -> None:
    connection = cache_connect(project, create=False)
    if connection is None:
        return
    try:
        connection.execute(
            "DELETE FROM claims WHERE run_id = ? AND task_id = ?", (run_id, task_id)
        )
        connection.commit()
    finally:
        connection.close()


def validate_run_record(value: Any, expected_run_id: str) -> dict[str, Any]:
    record = object_value(value, "run")
    exact(
        record,
        {
            "schema",
            "id",
            "plan",
            "initial_grants",
            "grant_reason",
            "created_at",
            "created_from",
            "durable_ref",
        },
        "run",
    )
    if record["schema"] != "noctis.run-record/v1":
        raise NoctisError("run.schema must be 'noctis.run-record/v1'")
    run_id = uuid_value(record["id"], "run.id")
    if run_id != expected_run_id:
        raise NoctisError("run.id does not match its directory")
    if record["plan"] != "plan.json":
        raise NoctisError("run.plan must be plan.json")
    grants = sorted(string_list(record["initial_grants"], "run.initial_grants"))
    reason = record["grant_reason"]
    if grants:
        reason = text_value(reason, "run.grant_reason")
    elif reason is not None:
        reason = text_value(reason, "run.grant_reason")
    created_from = text_value(record["created_from"], "run.created_from").lower()
    if not is_full_commit_sha(created_from):
        raise NoctisError("run.created_from must be a full 40-character SHA")
    durable_ref = record["durable_ref"]
    if durable_ref is not None:
        durable_ref = text_value(durable_ref, "run.durable_ref")
        if not durable_ref.startswith("refs/heads/"):
            raise NoctisError("run.durable_ref must be null or refs/heads/<branch>")
    return {
        "schema": "noctis.run-record/v1",
        "id": run_id,
        "plan": "plan.json",
        "initial_grants": grants,
        "grant_reason": reason,
        "created_at": timestamp_value(record["created_at"], "run.created_at"),
        "created_from": created_from,
        "durable_ref": durable_ref,
    }


def is_full_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


def validate_event(value: Any, path: Path, run_id: str) -> dict[str, Any]:
    event = object_value(value, str(path))
    exact(
        event,
        {
            "schema",
            "id",
            "run_id",
            "task_id",
            "type",
            "previous_revision",
            "revision",
            "created_at",
            "data",
        },
        str(path),
    )
    if event["schema"] != "noctis.event/v1":
        raise NoctisError(f"{path}: schema must be noctis.event/v1")
    event_id = uuid_value(event["id"], f"{path}: id")
    if path.name != f"{event_id}.json":
        raise NoctisError(f"{path}: filename must match event id")
    if uuid_value(event["run_id"], f"{path}: run_id") != run_id:
        raise NoctisError(f"{path}: run_id does not match its run")
    event_type = text_value(event["type"], f"{path}: type")
    if event_type not in TASK_EVENTS | RUN_EVENTS:
        raise NoctisError(f"{path}: unsupported event type {event_type}")
    previous_revision = integer_value(
        event["previous_revision"], f"{path}: previous_revision"
    )
    revision = integer_value(event["revision"], f"{path}: revision", minimum=1)
    if revision != previous_revision + 1:
        raise NoctisError(f"{path}: revision must increment previous_revision by one")
    if event_type in TASK_EVENTS:
        task_id: str | None = identifier(event["task_id"], f"{path}: task_id")
    else:
        if event["task_id"] is not None:
            raise NoctisError(f"{path}: run events must have null task_id")
        task_id = None
    raw_data = object_value(event["data"], f"{path}: data")
    if event_type in TASK_RESULT_EVENTS:
        exact(raw_data, {"attempt", "result"}, f"{path}: data")
        data = {
            "attempt": integer_value(raw_data["attempt"], f"{path}: data.attempt", minimum=1),
            "result": text_value(raw_data["result"], f"{path}: data.result"),
        }
    elif event_type == "task.retried":
        exact(raw_data, {"attempt", "reason", "acknowledged_requirements"}, f"{path}: data")
        if not isinstance(raw_data["acknowledged_requirements"], bool):
            raise NoctisError(f"{path}: acknowledged_requirements must be boolean")
        data = {
            "attempt": integer_value(raw_data["attempt"], f"{path}: data.attempt"),
            "reason": text_value(raw_data["reason"], f"{path}: data.reason"),
            "acknowledged_requirements": raw_data["acknowledged_requirements"],
        }
    elif event_type == "task.canceled":
        exact(
            raw_data,
            {"attempt", "reason", "acknowledged_requirements", "cascade_from"},
            f"{path}: data",
        )
        if not isinstance(raw_data["acknowledged_requirements"], bool):
            raise NoctisError(f"{path}: acknowledged_requirements must be boolean")
        cascade_from = raw_data["cascade_from"]
        if cascade_from is not None:
            cascade_from = identifier(cascade_from, f"{path}: data.cascade_from")
        data = {
            "attempt": integer_value(raw_data["attempt"], f"{path}: data.attempt"),
            "reason": text_value(raw_data["reason"], f"{path}: data.reason"),
            "acknowledged_requirements": raw_data["acknowledged_requirements"],
            "cascade_from": cascade_from,
        }
    elif event_type in {"run.granted", "run.revoked"}:
        exact(raw_data, {"requirements", "reason"}, f"{path}: data")
        data = {
            "requirements": sorted(
                string_list(raw_data["requirements"], f"{path}: data.requirements", nonempty=True)
            ),
            "reason": text_value(raw_data["reason"], f"{path}: data.reason"),
        }
    else:
        exact(raw_data, {"extension"}, f"{path}: data")
        data = {"extension": json_value(raw_data["extension"], f"{path}: data.extension")}
    return {
        "schema": "noctis.event/v1",
        "id": event_id,
        "run_id": run_id,
        "task_id": task_id,
        "type": event_type,
        "previous_revision": previous_revision,
        "revision": revision,
        "created_at": timestamp_value(event["created_at"], f"{path}: created_at"),
        "data": data,
    }


def new_event(
    run_id: str,
    task_id: str | None,
    event_type: str,
    previous_revision: int,
    data: dict[str, Any],
    *,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "noctis.event/v1",
        "id": event_id or str(uuid.uuid4()),
        "run_id": run_id,
        "task_id": task_id,
        "type": event_type,
        "previous_revision": previous_revision,
        "revision": previous_revision + 1,
        "created_at": now(),
        "data": data,
    }


def append_event(project: Path, event: dict[str, Any]) -> Path:
    path = run_directory(project, event["run_id"]) / "events" / f"{event['id']}.json"
    write_once(path, event, "event")
    return path


def _tracked(repo: Path, path: Path) -> bool:
    relative = repository_relative(repo, path)
    return run_git(
        repo, ["ls-files", "--error-unmatch", "--", relative], check=False
    ).returncode == 0


def _first_add_commit(repo: Path, path: Path) -> str | None:
    relative = repository_relative(repo, path)
    commits = run_git(
        repo,
        ["log", "--diff-filter=A", "--format=%H", "--", relative],
        check=False,
    ).stdout.splitlines()
    if not commits:
        return None
    if len(commits) != 1:
        raise NoctisError(f"durable base file was added more than once: {path}")
    return commits[0].lower()


def _git_json(repo: Path, commit: str, path: Path) -> Any:
    relative = repository_relative(repo, path)
    result = run_git(repo, ["show", f"{commit}:{relative}"])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise NoctisError(f"invalid sealed JSON for {relative} at {commit}") from error


def verify_base_seal(project: Path, directory: Path) -> dict[str, Any]:
    repo = git_repository(project)
    run_path = directory / "run.json"
    plan_path = directory / "plan.json"
    run_tracked = _tracked(repo, run_path)
    plan_tracked = _tracked(repo, plan_path)
    if not run_tracked and not plan_tracked:
        return {"sealed": False, "commit": None}
    if run_tracked != plan_tracked:
        raise NoctisError("run.json and plan.json must be committed together")
    run_commit = _first_add_commit(repo, run_path)
    plan_commit = _first_add_commit(repo, plan_path)
    if run_commit is None or plan_commit is None or run_commit != plan_commit:
        raise NoctisError("run.json and plan.json must share one creation checkpoint")
    if not git_is_ancestor(repo, run_commit, git_head(repo)):
        raise NoctisError("the current HEAD does not inherit the Run creation checkpoint")
    if load_json(run_path) != _git_json(repo, run_commit, run_path):
        raise NoctisError("run.json is sealed and must not be modified")
    if load_json(plan_path) != _git_json(repo, plan_commit, plan_path):
        raise NoctisError("plan.json is sealed and must not be modified")
    return {"sealed": True, "commit": run_commit}


def load_run_state(project: Path, run_id: str) -> dict[str, Any]:
    project = project.resolve()
    directory = run_directory(project, run_id)
    record = validate_run_record(load_json(directory / "run.json"), run_id)
    if not git_commit_exists(project, record["created_from"]):
        raise NoctisError("run.created_from is not reachable in the current clone")
    seal = verify_base_seal(project, directory)
    plan = validate_plan(load_json(directory / record["plan"]))
    executors = list(plan["executors"])
    tasks: dict[str, dict[str, Any]] = {
        definition["id"]: task_state(definition, added_revision=0)
        for definition in plan["tasks"]
    }
    order = [definition["id"] for definition in plan["tasks"]]
    event_directory = directory / "events"
    event_paths = sorted(event_directory.glob("*.json")) if event_directory.is_dir() else []
    events = [validate_event(load_json(path), path, run_id) for path in event_paths]
    run_events = [event for event in events if event["task_id"] is None]
    task_events = [event for event in events if event["task_id"] is not None]

    grants = set(record["initial_grants"])
    run_revision = 0
    normalized_run_events: list[dict[str, Any]] = []
    for event in sorted(run_events, key=lambda item: (item["revision"], item["id"])):
        run_revision, grants, executors, tasks, order, event = reduce_run_event(
            event, run_revision, grants, executors, tasks, order
        )
        normalized_run_events.append(event)

    related: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in tasks}
    for event in task_events:
        task_id = event["task_id"]
        if task_id not in tasks:
            raise NoctisError(f"event {event['id']} references unknown task '{task_id}'")
        related[task_id].append(event)

    normalized_task_events: list[dict[str, Any]] = []
    for task_id, task_related in related.items():
        task = tasks[task_id]
        for event in sorted(task_related, key=lambda item: (item["revision"], item["id"])):
            event_type = event["type"]
            data = event["data"]
            result: dict[str, Any] | None = None
            if event_type in TASK_RESULT_EVENTS:
                result_path = directory.joinpath(*Path(data["result"]).parts).resolve()
                try:
                    result_path.relative_to(directory.resolve())
                except ValueError as error:
                    raise NoctisError(f"task {task_id} result escapes its Run") from error
                raw_result = object_value(load_json(result_path), f"task {task_id} result")
                result = validate_result(
                    raw_result,
                    run_id,
                    task_id,
                    event["id"],
                    data["attempt"],
                )
            task = reduce_task_event(task, event, result, set(tasks))
            tasks[task_id] = task
            normalized_task_events.append(event)

    validate_dependency_states(list(tasks.values()))

    ordered_tasks = [tasks[task_id] for task_id in order]
    normalized_events = [*normalized_run_events, *normalized_task_events]
    updated_at = max(
        [record["created_at"], *(event["created_at"] for event in normalized_events)]
    )
    return {
        "record": record,
        "plan": plan,
        "executors": executors,
        "tasks": ordered_tasks,
        "events": normalized_events,
        "grants": sorted(grants),
        "run_revision": run_revision,
        "updated_at": updated_at,
        "seal": seal,
    }


def apply_local_claims(
    project: Path, run_id: str, tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    claims = local_claims(project, run_id)
    current_head = git_head(project)
    result: list[dict[str, Any]] = []
    for task in tasks:
        rendered = dict(task)
        claim = claims.get(task["id"])
        if (
            claim is not None
            and task["status"] == "pending"
            and claim["base_revision"] == task["revision"]
            and git_is_ancestor(project, claim["checkpoint_commit"], current_head)
        ):
            rendered.update(
                {
                    "status": "working",
                    "attempt": claim["attempt"],
                    "claim_id": claim["claim_id"],
                    "started_at": claim["started_at"],
                }
            )
        result.append(rendered)
    return result


def checkpoint_info(project: Path, run_id: str) -> dict[str, Any]:
    project = project.resolve()
    repo = git_repository(project)
    directory = run_directory(project, run_id)
    pathspec = repository_relative(repo, directory)
    changes = run_git(
        repo,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", pathspec],
    ).stdout.splitlines()
    tracked = all(_tracked(repo, directory / name) for name in ("run.json", "plan.json"))
    head = git_head(repo)
    branch = git_branch(repo)
    upstream_result = run_git(
        repo,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        check=False,
    )
    upstream = upstream_result.stdout.strip() or None
    pushed: bool | None = None
    if upstream is not None:
        pushed = git_is_ancestor(repo, head, upstream)
    return {
        "commit": head,
        "branch": branch,
        "upstream": upstream,
        "committed": tracked and not changes,
        "pushed": pushed,
        "changes": changes,
    }


def require_committed_checkpoint(project: Path, run_id: str) -> dict[str, Any]:
    checkpoint = checkpoint_info(project, run_id)
    if not checkpoint["committed"]:
        raise NoctisError(
            "Noctis Run state is not committed; commit the JSON checkpoint before continuing"
        )
    verify_base_seal(project, run_directory(project, run_id))
    return checkpoint


def create_run(
    project: Path,
    plan_path: Path,
    grants: list[str],
    grant_reason: str | None,
) -> dict[str, Any]:
    project = project.resolve()
    repo = git_repository(project)
    head = git_head(repo)
    plan = validate_plan(load_json(plan_path))
    normalized_grants = sorted(set(identifier(item, "grant") for item in grants))
    if normalized_grants and not grant_reason:
        raise NoctisError("--grant-reason is required when grants are supplied")
    requested = {
        requirement for task in plan["tasks"] for requirement in task["requirements"]
    }
    excess = sorted(set(normalized_grants) - requested)
    if excess:
        raise NoctisError(
            "grants exceed requirements requested by the plan: " + ", ".join(excess)
        )
    run_id = str(uuid.uuid4())
    directory = run_directory(project, run_id)
    if directory.exists():
        raise NoctisError(f"run directory already exists: {directory}")
    branch = git_branch(repo)
    record = {
        "schema": "noctis.run-record/v1",
        "id": run_id,
        "plan": "plan.json",
        "initial_grants": normalized_grants,
        "grant_reason": grant_reason,
        "created_at": now(),
        "created_from": head,
        "durable_ref": f"refs/heads/{branch}" if branch is not None else None,
    }
    atomic_write_json(directory / "plan.json", plan)
    atomic_write_json(directory / "run.json", record)
    if normalized_grants:
        authorize_local(
            project,
            run_id,
            normalized_grants,
            text_value(grant_reason, "grant_reason"),
        )
    return {
        "ok": True,
        "run_id": run_id,
        "status": "submitted",
        "ready": ready_task_ids(
            [task_state(task, added_revision=0) for task in plan["tasks"]]
        ),
        "checkpoint": checkpoint_info(project, run_id),
    }


def compact_run(project: Path, state: dict[str, Any]) -> dict[str, Any]:
    run_id = state["record"]["id"]
    tasks = apply_local_claims(project, run_id, state["tasks"])
    return {
        "id": run_id,
        "title": state["plan"]["title"],
        "status": derive_run_status(tasks),
        "run_revision": state["run_revision"],
        "ready": ready_task_ids(tasks),
        "working": [task["id"] for task in tasks if task["status"] == "working"],
        "updated_at": state["updated_at"],
        "checkpoint": checkpoint_info(project, run_id),
    }


def show_run(project: Path, run_id: str | None) -> dict[str, Any]:
    project = project.resolve()
    if run_id is None:
        root = runs_root(project)
        directories = (
            sorted(
                path
                for path in root.iterdir()
                if path.is_dir() and (path / "run.json").is_file()
            )
            if root.is_dir()
            else []
        )
        runs = [compact_run(project, load_run_state(project, path.name)) for path in directories]
        runs.sort(key=lambda item: item["updated_at"], reverse=True)
        return {"schema": "noctis.run-list/v1", "runs": runs}
    state = load_run_state(project, run_id)
    tasks = apply_local_claims(project, run_id, state["tasks"])
    return {
        "schema": "noctis.run/v1",
        "id": run_id,
        "title": state["plan"]["title"],
        "objective": state["plan"]["objective"],
        "status": derive_run_status(tasks),
        "run_revision": state["run_revision"],
        "grants": state["grants"],
        "active_grants": active_grants(project, run_id),
        "executors": state["executors"],
        "ready": ready_task_ids(tasks),
        "tasks": tasks,
        "checkpoint": checkpoint_info(project, run_id),
        "created_at": state["record"]["created_at"],
        "updated_at": state["updated_at"],
    }


def show_events(project: Path, run_id: str, limit: int) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise NoctisError("event limit must be between 1 and 1000")
    state = load_run_state(project.resolve(), run_id)
    created = {
        "id": f"run:{run_id}",
        "task_id": None,
        "type": "run.created",
        "revision": 0,
        "data": {
            "initial_grants": state["record"]["initial_grants"],
            "grant_reason": state["record"]["grant_reason"],
        },
        "created_at": state["record"]["created_at"],
    }
    events = [
        {
            "id": event["id"],
            "task_id": event["task_id"],
            "type": event["type"],
            "revision": event["revision"],
            "data": event["data"],
            "created_at": event["created_at"],
        }
        for event in state["events"]
    ]
    events.append(created)
    events.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return {
        "schema": "noctis.event-list/v1",
        "run_id": run_id,
        "events": events[:limit],
    }


def recover(project: Path, run_id: str | None) -> dict[str, Any]:
    project = project.resolve()
    if run_id is None:
        root = runs_root(project)
        directories = (
            sorted(
                path
                for path in root.iterdir()
                if path.is_dir() and (path / "run.json").is_file()
            )
            if root.is_dir()
            else []
        )
        states = [load_run_state(project, path.name) for path in directories]
    else:
        states = [load_run_state(project, run_id)]
    rebuild_cache(project)
    runs = [
        {
            "id": state["record"]["id"],
            "status": derive_run_status(state["tasks"]),
            "run_revision": state["run_revision"],
            "ready": ready_task_ids(state["tasks"]),
            "checkpoint": checkpoint_info(project, state["record"]["id"]),
        }
        for state in states
    ]
    return {
        "schema": "noctis.recovery/v1",
        "runs": runs,
        "local_claims": "cleared",
        "active_grants": [],
    }


def check_extension_value(project: Path, run_id: str, value: Any) -> dict[str, Any]:
    state = load_run_state(project.resolve(), run_id)
    extension = validate_extension(
        value, state["executors"], state["tasks"]
    )
    canceled = {task["id"] for task in state["tasks"] if task["status"] == "canceled"}
    invalid = sorted(
        {
            dependency
            for task in extension["tasks"]
            for dependency in task["needs"]
            if dependency in canceled
        }
    )
    if invalid:
        raise NoctisError(
            "extension depends on canceled tasks: " + ", ".join(invalid)
        )
    required = {
        requirement
        for task in extension["tasks"]
        for requirement in task["requirements"]
    }
    return {
        "ok": True,
        "schema": extension["schema"],
        "run_id": run_id,
        "run_revision": state["run_revision"],
        "executors_added": [item["id"] for item in extension["executors"]],
        "tasks_added": [item["id"] for item in extension["tasks"]],
        "missing_grants": sorted(required - set(state["grants"])),
        "extension": extension,
    }


def check_extension(project: Path, run_id: str, extension_path: Path) -> dict[str, Any]:
    return check_extension_value(project, run_id, load_json(extension_path))


def extend_run_value(
    project: Path,
    run_id: str,
    value: Any,
    expected_run_revision: int,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    checked = check_extension_value(project, run_id, value)
    if checked["run_revision"] != expected_run_revision:
        raise NoctisError(
            f"Run revision conflict: expected {expected_run_revision}, actual {checked['run_revision']}"
        )
    event = new_event(
        run_id,
        None,
        "run.tasks-added",
        expected_run_revision,
        {"extension": checked["extension"]},
    )
    path = append_event(project, event)
    refreshed = load_run_state(project, run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "run_revision": event["revision"],
        "executors_added": checked["executors_added"],
        "tasks_added": checked["tasks_added"],
        "missing_grants": checked["missing_grants"],
        "status": derive_run_status(refreshed["tasks"]),
        "ready": ready_task_ids(refreshed["tasks"]),
        "checkpoint_required": [git_relative(project, path)],
        "checkpoint": checkpoint_info(project, run_id),
    }


def extend_run(
    project: Path,
    run_id: str,
    extension_path: Path,
    expected_run_revision: int,
) -> dict[str, Any]:
    return extend_run_value(
        project, run_id, load_json(extension_path), expected_run_revision
    )


def add_task(
    project: Path,
    run_id: str,
    task_path: Path,
    executor_path: Path | None,
    origin_kind: str,
    reason: str,
    origin_reference: str | None,
    expected_run_revision: int,
) -> dict[str, Any]:
    task = validate_task(load_json(task_path), "task")
    executors = [] if executor_path is None else [validate_executor(load_json(executor_path), "executor")]
    extension = {
        "schema": "noctis.extension/v1",
        "origin": validate_origin(
            {
                "kind": origin_kind,
                "summary": reason,
                "reference": origin_reference,
            }
        ),
        "executors": executors,
        "tasks": [task],
    }
    return extend_run_value(project, run_id, extension, expected_run_revision)


def claim_task(project: Path, run_id: str, requested_task: str | None) -> dict[str, Any]:
    project = project.resolve()
    checkpoint = require_committed_checkpoint(project, run_id)
    state = load_run_state(project, run_id)
    visible_tasks = apply_local_claims(project, run_id, state["tasks"])
    ready = ready_task_ids(visible_tasks)
    task_id = requested_task or (ready[0] if ready else None)
    if task_id is None:
        working = [task["id"] for task in visible_tasks if task["status"] == "working"]
        detail = (
            f"; local working tasks require reconciliation: {', '.join(working)}"
            if working
            else ""
        )
        raise NoctisError("no task is ready" + detail)
    if task_id not in ready:
        raise NoctisError(f"task is not ready: {task_id}")
    task = next(item for item in state["tasks"] if item["id"] == task_id)
    recorded = set(state["grants"])
    active = set(active_grants(project, run_id))
    missing_recorded = sorted(set(task["requirements"]) - recorded)
    if missing_recorded:
        raise NoctisError(
            f"task '{task_id}' lacks recorded grants: {', '.join(missing_recorded)}"
        )
    missing_active = sorted(set(task["requirements"]) - active)
    if missing_active:
        raise NoctisError(
            f"task '{task_id}' requires current-machine authorization: {', '.join(missing_active)}"
        )
    claim_id = str(uuid.uuid4())
    attempt = task["attempt"] + 1
    timestamp = now()
    connection = cache_connect(project, create=True)
    if connection is None:
        raise NoctisError("unable to create local cache")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO claims(run_id, task_id, claim_id, attempt, base_revision, checkpoint_commit, started_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                task_id,
                claim_id,
                attempt,
                task["revision"],
                checkpoint["commit"],
                timestamp,
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise NoctisError(f"task already has a local claim: {task_id}") from error
    finally:
        connection.close()
    by_id = {item["id"]: item for item in state["tasks"]}
    dependencies = []
    for dependency in task["needs"]:
        result = by_id[dependency]["result"]
        if result is None:
            raise NoctisError(f"completed dependency has no result: {dependency}")
        dependencies.append({"task_id": dependency, "result": result})
    executor = next(
        item for item in state["executors"] if item["id"] == task["executor"]
    )
    return {
        "schema": "noctis.claim/v1",
        "run_id": run_id,
        "task_id": task_id,
        "claim_id": claim_id,
        "attempt": attempt,
        "revision": task["revision"],
        "run_revision": state["run_revision"],
        "executor": executor,
        "request": task["request"],
        "dependencies": dependencies,
        "requirements": {
            "required": task["requirements"],
            "granted": task["requirements"],
        },
        "checkpoint": {"commit": checkpoint["commit"]},
        "idempotency_key": f"{run_id}/{task_id}",
    }


def finish_task(
    project: Path,
    run_id: str,
    task_id: str,
    claim_id: str,
    expected_revision: int,
    result_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    state = load_run_state(project, run_id)
    task = next((item for item in state["tasks"] if item["id"] == task_id), None)
    if task is None:
        raise NoctisError(f"task does not exist: {task_id}")
    claim = local_claim(project, run_id, task_id)
    if claim is None or claim["claim_id"] != claim_id:
        raise NoctisError(f"task is not held by local claim {claim_id}")
    if task["status"] != "pending":
        raise NoctisError(f"task cannot finish from {task['status']}")
    if task["revision"] != expected_revision or claim["base_revision"] != expected_revision:
        raise NoctisError(
            f"revision conflict for {task_id}: expected {expected_revision}, actual {task['revision']}"
        )
    if not git_is_ancestor(project, claim["checkpoint_commit"], git_head(project)):
        raise NoctisError("current HEAD does not inherit the claimed checkpoint")
    effective = set(state["grants"]) & set(active_grants(project, run_id))
    missing = sorted(set(task["requirements"]) - effective)
    if missing:
        raise NoctisError(
            f"task '{task_id}' no longer has effective grants: {', '.join(missing)}"
        )
    result = validate_result(
        load_json(result_path),
        run_id,
        task_id,
        claim_id,
        claim["attempt"],
    )
    directory = run_directory(project, run_id)
    result_relative = f"results/{task_id}/attempt-{claim['attempt']}.json"
    stored_result = directory.joinpath(*Path(result_relative).parts)
    write_once(stored_result, result, "task result")
    event = new_event(
        run_id,
        task_id,
        f"task.{result['status']}",
        task["revision"],
        {"attempt": claim["attempt"], "result": result_relative},
        event_id=claim_id,
    )
    event_path = append_event(project, event)
    delete_local_claim(project, run_id, task_id)
    refreshed = load_run_state(project, run_id)
    return {
        "ok": True,
        "run_id": run_id,
        "task_id": task_id,
        "task_status": result["status"],
        "run_status": derive_run_status(refreshed["tasks"]),
        "revision": event["revision"],
        "ready": ready_task_ids(refreshed["tasks"]),
        "checkpoint_required": [
            git_relative(project, stored_result),
            git_relative(project, event_path),
        ],
        "checkpoint": checkpoint_info(project, run_id),
    }


def retry_task(
    project: Path,
    run_id: str,
    task_id: str,
    expected_revision: int,
    reason: str,
    acknowledge_requirements: bool,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    state = load_run_state(project, run_id)
    task = next((item for item in state["tasks"] if item["id"] == task_id), None)
    if task is None:
        raise NoctisError(f"task does not exist: {task_id}")
    if task["revision"] != expected_revision:
        raise NoctisError(
            f"revision conflict for {task_id}: expected {expected_revision}, actual {task['revision']}"
        )
    claim = local_claim(project, run_id, task_id)
    if task["status"] in TERMINAL_STATES:
        raise NoctisError(f"task cannot be retried from {task['status']}")
    if task["status"] == "pending" and claim is None:
        raise NoctisError("task cannot be retried from pending without a local claim")
    if claim is not None and not git_is_ancestor(
        project, claim["checkpoint_commit"], git_head(project)
    ):
        raise NoctisError("current HEAD does not inherit the claimed checkpoint")
    if claim is not None and task["requirements"] and not acknowledge_requirements:
        raise NoctisError(
            "retry requires --acknowledge-requirements after reconciling prior execution"
        )
    attempt = claim["attempt"] if claim is not None else task["attempt"]
    event = new_event(
        run_id,
        task_id,
        "task.retried",
        task["revision"],
        {
            "attempt": attempt,
            "reason": text_value(reason, "reason"),
            "acknowledged_requirements": acknowledge_requirements,
        },
        event_id=claim["claim_id"] if claim is not None else None,
    )
    event_path = append_event(project, event)
    delete_local_claim(project, run_id, task_id)
    return {
        "ok": True,
        "run_id": run_id,
        "task_id": task_id,
        "status": "pending",
        "revision": event["revision"],
        "checkpoint_required": [git_relative(project, event_path)],
        "checkpoint": checkpoint_info(project, run_id),
    }


def cancel_task(
    project: Path,
    run_id: str,
    task_id: str,
    expected_revision: int,
    reason: str,
    acknowledge_requirements: bool,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    state = load_run_state(project, run_id)
    task = next((item for item in state["tasks"] if item["id"] == task_id), None)
    if task is None:
        raise NoctisError(f"task does not exist: {task_id}")
    if task["revision"] != expected_revision:
        raise NoctisError(
            f"revision conflict for {task_id}: expected {expected_revision}, actual {task['revision']}"
        )
    if task["status"] in TERMINAL_STATES:
        raise NoctisError(f"task cannot be canceled from {task['status']}")
    claim = local_claim(project, run_id, task_id)
    if claim is not None and task["requirements"] and not acknowledge_requirements:
        raise NoctisError(
            "cancel requires --acknowledge-requirements because cancellation does not undo execution"
        )
    selected = descendants(state["tasks"], task_id)
    events: list[Path] = []
    canceled: list[str] = []
    for candidate in state["tasks"]:
        if candidate["id"] not in selected:
            continue
        if candidate["id"] != task_id and candidate["status"] != "pending":
            continue
        candidate_claim = local_claim(project, run_id, candidate["id"])
        attempt = (
            candidate_claim["attempt"]
            if candidate_claim is not None
            else candidate["attempt"]
        )
        event = new_event(
            run_id,
            candidate["id"],
            "task.canceled",
            candidate["revision"],
            {
                "attempt": attempt,
                "reason": (
                    text_value(reason, "reason")
                    if candidate["id"] == task_id
                    else f"dependency canceled: {task_id}"
                ),
                "acknowledged_requirements": (
                    acknowledge_requirements if candidate["id"] == task_id else False
                ),
                "cascade_from": None if candidate["id"] == task_id else task_id,
            },
            event_id=(
                candidate_claim["claim_id"] if candidate_claim is not None else None
            ),
        )
        events.append(append_event(project, event))
        delete_local_claim(project, run_id, candidate["id"])
        canceled.append(candidate["id"])
    return {
        "ok": True,
        "run_id": run_id,
        "task_id": task_id,
        "status": "canceled",
        "revision": expected_revision + 1,
        "canceled": canceled,
        "checkpoint_required": [git_relative(project, path) for path in events],
        "checkpoint": checkpoint_info(project, run_id),
    }


def grant_requirements(
    project: Path, run_id: str, requirements: list[str], reason: str
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    normalized = sorted(set(identifier(item, "requirement") for item in requirements))
    state = load_run_state(project, run_id)
    requested = {
        requirement
        for task in state["tasks"]
        for requirement in task["requirements"]
    }
    excess = sorted(set(normalized) - requested)
    if excess:
        raise NoctisError(
            "grants exceed requirements requested by the Run: " + ", ".join(excess)
        )
    normalized_reason = text_value(reason, "reason")
    new_requirements = sorted(set(normalized) - set(state["grants"]))
    checkpoint_required: list[str] = []
    if new_requirements:
        event = new_event(
            run_id,
            None,
            "run.granted",
            state["run_revision"],
            {"requirements": new_requirements, "reason": normalized_reason},
        )
        path = append_event(project, event)
        checkpoint_required.append(git_relative(project, path))
    authorize_local(project, run_id, normalized, normalized_reason)
    return {
        "ok": True,
        "run_id": run_id,
        "grants": sorted(set(state["grants"]) | set(normalized)),
        "active_grants": active_grants(project, run_id),
        "checkpoint_required": checkpoint_required,
        "checkpoint": checkpoint_info(project, run_id),
    }


def revoke_requirements(
    project: Path, run_id: str, requirements: list[str], reason: str
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    normalized = sorted(set(identifier(item, "requirement") for item in requirements))
    state = load_run_state(project, run_id)
    event = new_event(
        run_id,
        None,
        "run.revoked",
        state["run_revision"],
        {"requirements": normalized, "reason": text_value(reason, "reason")},
    )
    path = append_event(project, event)
    deauthorize_local(project, run_id, normalized)
    return {
        "ok": True,
        "run_id": run_id,
        "grants": sorted(set(state["grants"]) - set(normalized)),
        "active_grants": active_grants(project, run_id),
        "checkpoint_required": [git_relative(project, path)],
        "checkpoint": checkpoint_info(project, run_id),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Protocol-neutral Git-backed durable task graph runtime."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("plan-check")
    check.add_argument("--plan", type=Path, required=True)

    create = commands.add_parser("run-create")
    create.add_argument("--project", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument("--grant", action="append", default=[])
    create.add_argument("--grant-reason")

    show = commands.add_parser("run-show")
    show.add_argument("--project", type=Path, required=True)
    show.add_argument("--run-id")

    events = commands.add_parser("run-events")
    events.add_argument("--project", type=Path, required=True)
    events.add_argument("--run-id", required=True)
    events.add_argument("--limit", type=int, default=100)

    recovery = commands.add_parser("recover")
    recovery.add_argument("--project", type=Path, required=True)
    recovery.add_argument("--run-id")

    extension_check = commands.add_parser("extension-check")
    extension_check.add_argument("--project", type=Path, required=True)
    extension_check.add_argument("--run-id", required=True)
    extension_check.add_argument("--extension", type=Path, required=True)

    extend = commands.add_parser("run-extend")
    extend.add_argument("--project", type=Path, required=True)
    extend.add_argument("--run-id", required=True)
    extend.add_argument("--extension", type=Path, required=True)
    extend.add_argument("--expected-run-revision", type=int, required=True)

    add = commands.add_parser("task-add")
    add.add_argument("--project", type=Path, required=True)
    add.add_argument("--run-id", required=True)
    add.add_argument("--task", type=Path, required=True)
    add.add_argument("--executor", type=Path)
    add.add_argument("--origin-kind", required=True)
    add.add_argument("--reason", required=True)
    add.add_argument("--origin-reference")
    add.add_argument("--expected-run-revision", type=int, required=True)

    claim = commands.add_parser("task-claim")
    claim.add_argument("--project", type=Path, required=True)
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--task-id")

    finish = commands.add_parser("task-finish")
    finish.add_argument("--project", type=Path, required=True)
    finish.add_argument("--run-id", required=True)
    finish.add_argument("--task-id", required=True)
    finish.add_argument("--claim-id", required=True)
    finish.add_argument("--expected-revision", type=int, required=True)
    finish.add_argument("--result", type=Path, required=True)

    retry = commands.add_parser("task-retry")
    retry.add_argument("--project", type=Path, required=True)
    retry.add_argument("--run-id", required=True)
    retry.add_argument("--task-id", required=True)
    retry.add_argument("--expected-revision", type=int, required=True)
    retry.add_argument("--reason", required=True)
    retry.add_argument("--acknowledge-requirements", action="store_true")

    cancel = commands.add_parser("task-cancel")
    cancel.add_argument("--project", type=Path, required=True)
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--task-id", required=True)
    cancel.add_argument("--expected-revision", type=int, required=True)
    cancel.add_argument("--reason", required=True)
    cancel.add_argument("--acknowledge-requirements", action="store_true")

    grant = commands.add_parser("grant")
    grant.add_argument("--project", type=Path, required=True)
    grant.add_argument("--run-id", required=True)
    grant.add_argument("--requirement", action="append", required=True)
    grant.add_argument("--reason", required=True)

    revoke = commands.add_parser("revoke")
    revoke.add_argument("--project", type=Path, required=True)
    revoke.add_argument("--run-id", required=True)
    revoke.add_argument("--requirement", action="append", required=True)
    revoke.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "plan-check":
            plan = validate_plan(load_json(args.plan))
            result = {
                "ok": True,
                "schema": plan["schema"],
                "executors": len(plan["executors"]),
                "tasks": len(plan["tasks"]),
            }
        elif args.command == "run-create":
            result = create_run(args.project, args.plan, args.grant, args.grant_reason)
        elif args.command == "run-show":
            result = show_run(args.project, args.run_id)
        elif args.command == "run-events":
            result = show_events(args.project, args.run_id, args.limit)
        elif args.command == "recover":
            result = recover(args.project, args.run_id)
        elif args.command == "extension-check":
            result = check_extension(args.project, args.run_id, args.extension)
        elif args.command == "run-extend":
            result = extend_run(
                args.project,
                args.run_id,
                args.extension,
                args.expected_run_revision,
            )
        elif args.command == "task-add":
            result = add_task(
                args.project,
                args.run_id,
                args.task,
                args.executor,
                args.origin_kind,
                args.reason,
                args.origin_reference,
                args.expected_run_revision,
            )
        elif args.command == "task-claim":
            result = claim_task(args.project, args.run_id, args.task_id)
        elif args.command == "task-finish":
            result = finish_task(
                args.project,
                args.run_id,
                args.task_id,
                args.claim_id,
                args.expected_revision,
                args.result,
            )
        elif args.command == "task-retry":
            result = retry_task(
                args.project,
                args.run_id,
                args.task_id,
                args.expected_revision,
                args.reason,
                args.acknowledge_requirements,
            )
        elif args.command == "task-cancel":
            result = cancel_task(
                args.project,
                args.run_id,
                args.task_id,
                args.expected_revision,
                args.reason,
                args.acknowledge_requirements,
            )
        elif args.command == "grant":
            result = grant_requirements(
                args.project, args.run_id, args.requirement, args.reason
            )
        else:
            result = revoke_requirements(
                args.project, args.run_id, args.requirement, args.reason
            )
        emit(result)
        return 0
    except (NoctisError, OSError, sqlite3.Error) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
