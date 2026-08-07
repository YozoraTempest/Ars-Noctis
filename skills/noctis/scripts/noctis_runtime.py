#!/usr/bin/env python3
"""Git-backed cooperative runtime for durable Ars task graphs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse


RUNS_RELATIVE_PATH = Path(".ars") / "runs"
CACHE_SCHEMA_VERSION = 2
SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ITEM_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
EFFECTS = {
    "command.execute",
    "deployment",
    "destructive",
    "git.commit",
    "git.push",
    "network.write",
    "workspace.write",
}
HIGH_RISK_EFFECTS = {
    "deployment",
    "destructive",
    "git.commit",
    "git.push",
    "network.write",
}
RESULT_STATES = {"blocked", "completed", "failed", "input-required"}
TERMINAL_STATES = {"canceled", "completed"}
TASK_RESULT_EVENTS = {
    "task.blocked": "blocked",
    "task.completed": "completed",
    "task.failed": "failed",
    "task.input-required": "input-required",
}
TASK_EVENTS = set(TASK_RESULT_EVENTS) | {"task.canceled", "task.retried"}
RUN_EVENTS = {"run.granted", "run.revoked"}


class NoctisError(ValueError):
    """Raised for invalid contracts or lifecycle operations."""


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
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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


def object_value(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise NoctisError(f"{context} must be an object with string keys")
    return value


def exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing:
        raise NoctisError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise NoctisError(f"{context} has unknown fields: {', '.join(unknown)}")


def text_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NoctisError(f"{context} must be a non-empty string")
    return value.strip()


def integer_value(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NoctisError(f"{context} must be an integer greater than or equal to {minimum}")
    return value


def identifier(value: Any, pattern: re.Pattern[str], context: str) -> str:
    result = text_value(value, context)
    if not pattern.fullmatch(result):
        raise NoctisError(f"{context} has an invalid identifier: {result}")
    return result


def uuid_value(value: Any, context: str) -> str:
    result = text_value(value, context)
    try:
        parsed = uuid.UUID(result)
    except ValueError as error:
        raise NoctisError(f"{context} must be a UUID") from error
    if str(parsed) != result:
        raise NoctisError(f"{context} must use canonical lowercase UUID form")
    return result


def timestamp_value(value: Any, context: str) -> str:
    result = text_value(value, context)
    try:
        parsed = datetime.fromisoformat(result)
    except ValueError as error:
        raise NoctisError(f"{context} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise NoctisError(f"{context} must include a timezone")
    return result


def string_list(value: Any, context: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise NoctisError(f"{context} must be a list of non-empty strings")
    result = [item.strip() for item in value]
    if nonempty and not result:
        raise NoctisError(f"{context} must not be empty")
    if len(result) != len(set(result)):
        raise NoctisError(f"{context} contains duplicates")
    return result


def relative_path(value: Any, context: str, *, allow_dot: bool = False) -> str:
    result = text_value(value, context)
    if allow_dot and result == ".":
        return result
    if "\\" in result or ":" in result or result.startswith("/"):
        raise NoctisError(f"{context} must be a relative POSIX path")
    parts = result.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise NoctisError(f"{context} must not contain empty, '.' or '..' segments")
    return PurePosixPath(result).as_posix()


def resolve_inside(root: Path, relative: str, context: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise NoctisError(f"{context} escapes its workspace") from error
    return candidate


def validate_manifest(value: Any, source: Path) -> dict[str, Any]:
    manifest = object_value(value, str(source))
    exact(manifest, {"schema", "id", "version", "capabilities"}, str(source))
    if manifest["schema"] != "ars.skill/v1":
        raise NoctisError(f"{source}: schema must be ars.skill/v1")
    provider_id = identifier(manifest["id"], SKILL_ID, f"{source}: id")
    version = text_value(manifest["version"], f"{source}: version")
    if not SEMVER.fullmatch(version):
        raise NoctisError(f"{source}: version must be MAJOR.MINOR.PATCH")
    raw_capabilities = manifest["capabilities"]
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise NoctisError(f"{source}: capabilities must be a non-empty list")
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_capabilities):
        context = f"{source}: capabilities[{index}]"
        capability = object_value(raw, context)
        exact(
            capability,
            {"id", "description", "accepts", "returns", "effects"},
            context,
        )
        capability_id = identifier(capability["id"], ITEM_ID, f"{context}.id")
        if capability_id in seen:
            raise NoctisError(f"{source}: repeated capability {capability_id}")
        seen.add(capability_id)
        if capability["accepts"] != "ars.task/v1" or capability["returns"] != "ars.result/v1":
            raise NoctisError(f"{context} must use ars.task/v1 -> ars.result/v1")
        effects = string_list(capability["effects"], f"{context}.effects")
        unknown = sorted(set(effects) - EFFECTS)
        if unknown:
            raise NoctisError(f"{context}.effects has unknown values: {', '.join(unknown)}")
        capabilities.append(
            {
                "id": capability_id,
                "description": text_value(capability["description"], f"{context}.description"),
                "accepts": "ars.task/v1",
                "returns": "ars.result/v1",
                "effects": sorted(effects),
            }
        )
    return {
        "id": provider_id,
        "version": version,
        "source": str(source.parent.resolve()),
        "capabilities": sorted(capabilities, key=lambda item: item["id"]),
    }


def discover(skill_roots: Iterable[Path]) -> dict[str, Any]:
    manifests: list[Path] = []
    seen_paths: set[Path] = set()
    for supplied in skill_roots:
        root = supplied.resolve()
        if not root.is_dir():
            raise NoctisError(f"skills root does not exist: {root}")
        candidates = [root / "ars.json"] if (root / "ars.json").is_file() else sorted(root.glob("*/ars.json"))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                manifests.append(resolved)
    providers: list[dict[str, Any]] = []
    by_id: dict[str, Path] = {}
    for path in sorted(manifests):
        provider = validate_manifest(load_json(path), path)
        previous = by_id.get(provider["id"])
        if previous is not None:
            raise NoctisError(
                f"provider '{provider['id']}' is ambiguous: {previous.parent} and {path.parent}"
            )
        by_id[provider["id"]] = path
        providers.append(provider)
    return {"schema": "ars.catalog/v1", "providers": sorted(providers, key=lambda item: item["id"])}


def workspace_roots(project: Path, plan: dict[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    project = project.resolve()
    for workspace in plan["workspaces"]:
        root = project if workspace["root"] == "." else resolve_inside(project, workspace["root"], f"workspace {workspace['id']}")
        if not root.is_dir():
            raise NoctisError(f"workspace does not exist: {root}")
        result[workspace["id"]] = root
    return result


def validate_locator(value: Any, context: str, workspaces: set[str]) -> dict[str, Any]:
    locator = object_value(value, context)
    kind = locator.get("kind")
    if kind == "workspace":
        exact(locator, {"kind", "workspace", "path"}, context)
        workspace = identifier(locator["workspace"], ITEM_ID, f"{context}.workspace")
        if workspace not in workspaces:
            raise NoctisError(f"{context} references unknown workspace '{workspace}'")
        return {
            "kind": "workspace",
            "workspace": workspace,
            "path": relative_path(locator["path"], f"{context}.path"),
        }
    if kind == "git":
        exact(locator, {"kind", "workspace", "commit"}, context)
        workspace = identifier(locator["workspace"], ITEM_ID, f"{context}.workspace")
        if workspace not in workspaces:
            raise NoctisError(f"{context} references unknown workspace '{workspace}'")
        commit = text_value(locator["commit"], f"{context}.commit").lower()
        if not COMMIT.fullmatch(commit):
            raise NoctisError(f"{context}.commit must be a full 40-character SHA")
        return {"kind": "git", "workspace": workspace, "commit": commit}
    if kind == "uri":
        exact(locator, {"kind", "uri"}, context)
        uri = text_value(locator["uri"], f"{context}.uri")
        parsed = urlparse(uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise NoctisError(f"{context}.uri must be an absolute HTTP(S) URI")
        return {"kind": "uri", "uri": uri}
    if kind == "inline":
        exact(locator, {"kind", "value"}, context)
        try:
            json.dumps(locator["value"])
        except (TypeError, ValueError) as error:
            raise NoctisError(f"{context}.value must be JSON serializable") from error
        return {"kind": "inline", "value": locator["value"]}
    raise NoctisError(f"{context}.kind must be workspace, git, uri, or inline")


def validate_artifact(value: Any, context: str, workspaces: set[str]) -> dict[str, Any]:
    artifact = object_value(value, context)
    exact(artifact, {"id", "type", "media_type", "locator", "digest"}, context)
    digest = artifact["digest"]
    if digest is not None and (not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
        raise NoctisError(f"{context}.digest must be null or sha256:<64 lowercase hex>")
    return {
        "id": identifier(artifact["id"], ITEM_ID, f"{context}.id"),
        "type": identifier(artifact["type"], ITEM_ID, f"{context}.type"),
        "media_type": text_value(artifact["media_type"], f"{context}.media_type"),
        "locator": validate_locator(artifact["locator"], f"{context}.locator", workspaces),
        "digest": digest,
    }


def validate_plan(value: Any, project: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    plan = object_value(value, "plan")
    exact(plan, {"schema", "title", "objective", "workspaces", "tasks"}, "plan")
    if plan["schema"] != "ars.plan/v1":
        raise NoctisError("plan.schema must be 'ars.plan/v1'")
    raw_workspaces = plan["workspaces"]
    if not isinstance(raw_workspaces, list) or not raw_workspaces:
        raise NoctisError("plan.workspaces must be a non-empty list")
    workspaces: list[dict[str, str]] = []
    workspace_ids: set[str] = set()
    for index, raw in enumerate(raw_workspaces):
        context = f"plan.workspaces[{index}]"
        workspace = object_value(raw, context)
        exact(workspace, {"id", "root"}, context)
        workspace_id = identifier(workspace["id"], ITEM_ID, f"{context}.id")
        if workspace_id in workspace_ids:
            raise NoctisError(f"plan repeats workspace '{workspace_id}'")
        workspace_ids.add(workspace_id)
        workspaces.append(
            {"id": workspace_id, "root": relative_path(workspace["root"], f"{context}.root", allow_dot=True)}
        )

    providers = {provider["id"]: provider for provider in catalog["providers"]}
    raw_tasks = plan["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise NoctisError("plan.tasks must be a non-empty list")
    task_ids: set[str] = set()
    tasks: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_tasks):
        context = f"plan.tasks[{index}]"
        task = object_value(raw, context)
        exact(
            task,
            {"id", "provider", "capability", "workspace", "needs", "instructions", "inputs", "acceptance", "effects"},
            context,
        )
        task_id = identifier(task["id"], ITEM_ID, f"{context}.id")
        if task_id in task_ids:
            raise NoctisError(f"plan repeats task '{task_id}'")
        task_ids.add(task_id)
        provider_id = identifier(task["provider"], SKILL_ID, f"{context}.provider")
        provider = providers.get(provider_id)
        if provider is None:
            raise NoctisError(f"{context} references unavailable provider '{provider_id}'")
        capability_id = identifier(task["capability"], ITEM_ID, f"{context}.capability")
        capability = next(
            (item for item in provider["capabilities"] if item["id"] == capability_id),
            None,
        )
        if capability is None:
            raise NoctisError(f"provider '{provider_id}' does not provide '{capability_id}'")
        workspace_id = identifier(task["workspace"], ITEM_ID, f"{context}.workspace")
        if workspace_id not in workspace_ids:
            raise NoctisError(f"{context} references unknown workspace '{workspace_id}'")
        effects = string_list(task["effects"], f"{context}.effects")
        undeclared = sorted(set(effects) - set(capability["effects"]))
        if undeclared:
            raise NoctisError(
                f"{context}.effects are not declared by {provider_id}: {', '.join(undeclared)}"
            )
        if "workspace.write" in effects and "git.commit" not in effects:
            raise NoctisError(
                f"{context}.effects must include git.commit when workspace.write is requested"
            )
        raw_inputs = task["inputs"]
        if not isinstance(raw_inputs, list):
            raise NoctisError(f"{context}.inputs must be a list")
        inputs = [
            validate_artifact(item, f"{context}.inputs[{item_index}]", workspace_ids)
            for item_index, item in enumerate(raw_inputs)
        ]
        if len({item["id"] for item in inputs}) != len(inputs):
            raise NoctisError(f"{context}.inputs repeats artifact ids")
        tasks.append(
            {
                "id": task_id,
                "provider": provider_id,
                "capability": capability_id,
                "workspace": workspace_id,
                "needs": string_list(task["needs"], f"{context}.needs"),
                "instructions": text_value(task["instructions"], f"{context}.instructions"),
                "inputs": inputs,
                "acceptance": string_list(task["acceptance"], f"{context}.acceptance", nonempty=True),
                "effects": sorted(effects),
            }
        )

    for task in tasks:
        unknown = sorted(set(task["needs"]) - task_ids)
        if unknown:
            raise NoctisError(f"task '{task['id']}' needs unknown tasks: {', '.join(unknown)}")
        if task["id"] in task["needs"]:
            raise NoctisError(f"task '{task['id']}' cannot depend on itself")
    visiting: set[str] = set()
    visited: set[str] = set()
    dependencies = {task["id"]: task["needs"] for task in tasks}

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise NoctisError(f"plan contains a dependency cycle at '{task_id}'")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)

    normalized = {
        "schema": "ars.plan/v1",
        "title": text_value(plan["title"], "plan.title"),
        "objective": text_value(plan["objective"], "plan.objective"),
        "workspaces": workspaces,
        "tasks": tasks,
    }
    roots = workspace_roots(project, normalized)
    for task in tasks:
        for artifact in task["inputs"]:
            validate_artifact_evidence(artifact, roots, f"task {task['id']} input")
    return normalized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def run_git(root: Path, arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise NoctisError("git is required for durable Noctis state") from error
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise NoctisError(detail)
    return result


def git_repository(path: Path) -> Path:
    result = run_git(path.resolve(), ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def git_head(path: Path) -> str:
    result = run_git(path, ["rev-parse", "HEAD"])
    commit = result.stdout.strip().lower()
    if not COMMIT.fullmatch(commit):
        raise NoctisError("Git HEAD must be a full SHA-1 commit")
    return commit


def git_branch(path: Path) -> str | None:
    result = run_git(path, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    return result.stdout.strip() or None


def git_commit_exists(root: Path, commit: str) -> bool:
    return run_git(root, ["cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode == 0


def git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    return run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode == 0


def validate_artifact_evidence(
    artifact: dict[str, Any], roots: dict[str, Path], context: str
) -> None:
    locator = artifact["locator"]
    if locator["kind"] == "workspace":
        path = resolve_inside(roots[locator["workspace"]], locator["path"], context)
        if not path.exists():
            raise NoctisError(f"{context} does not exist: {path}")
        if artifact["digest"] is not None:
            if not path.is_file():
                raise NoctisError(f"{context} can only digest a file")
            if sha256_file(path) != artifact["digest"]:
                raise NoctisError(f"{context} digest does not match {path}")
    elif locator["kind"] == "git":
        if not git_commit_exists(roots[locator["workspace"]], locator["commit"]):
            raise NoctisError(f"{context} commit is not reachable: {locator['commit']}")


def runs_root(project: Path) -> Path:
    return project.resolve() / RUNS_RELATIVE_PATH


def run_directory(project: Path, run_id: str) -> Path:
    return runs_root(project) / uuid_value(run_id, "run_id")


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
            effect TEXT NOT NULL,
            reason TEXT NOT NULL,
            authorized_at TEXT NOT NULL,
            PRIMARY KEY (run_id, effect)
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
            row["effect"]
            for row in connection.execute(
                "SELECT effect FROM authorizations WHERE run_id = ? ORDER BY effect",
                (run_id,),
            )
        ]
    finally:
        connection.close()


def authorize_local(project: Path, run_id: str, effects: list[str], reason: str) -> None:
    connection = cache_connect(project, create=True)
    if connection is None:
        raise NoctisError("unable to create local cache")
    try:
        timestamp = now()
        connection.executemany(
            "INSERT OR REPLACE INTO authorizations(run_id, effect, reason, authorized_at) VALUES(?, ?, ?, ?)",
            [(run_id, effect, reason, timestamp) for effect in effects],
        )
        connection.commit()
    finally:
        connection.close()


def deauthorize_local(project: Path, run_id: str, effects: list[str]) -> None:
    connection = cache_connect(project, create=False)
    if connection is None:
        return
    try:
        connection.executemany(
            "DELETE FROM authorizations WHERE run_id = ? AND effect = ?",
            [(run_id, effect) for effect in effects],
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


def validate_catalog_snapshot(value: Any) -> dict[str, Any]:
    catalog = object_value(value, "run.catalog")
    exact(catalog, {"schema", "providers"}, "run.catalog")
    if catalog["schema"] != "ars.catalog/v1":
        raise NoctisError("run.catalog.schema must be ars.catalog/v1")
    raw_providers = catalog["providers"]
    if not isinstance(raw_providers, list) or not raw_providers:
        raise NoctisError("run.catalog.providers must be a non-empty list")
    providers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_providers):
        context = f"run.catalog.providers[{index}]"
        provider = object_value(raw, context)
        exact(provider, {"id", "version", "capabilities"}, context)
        provider_id = identifier(provider["id"], SKILL_ID, f"{context}.id")
        if provider_id in seen:
            raise NoctisError(f"run.catalog repeats provider '{provider_id}'")
        seen.add(provider_id)
        version = text_value(provider["version"], f"{context}.version")
        if not SEMVER.fullmatch(version):
            raise NoctisError(f"{context}.version must be MAJOR.MINOR.PATCH")
        capabilities: list[dict[str, Any]] = []
        raw_capabilities = provider["capabilities"]
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            raise NoctisError(f"{context}.capabilities must be a non-empty list")
        capability_ids: set[str] = set()
        for capability_index, raw_capability in enumerate(raw_capabilities):
            capability_context = f"{context}.capabilities[{capability_index}]"
            capability = object_value(raw_capability, capability_context)
            exact(
                capability,
                {"id", "description", "accepts", "returns", "effects"},
                capability_context,
            )
            capability_id = identifier(
                capability["id"], ITEM_ID, f"{capability_context}.id"
            )
            if capability_id in capability_ids:
                raise NoctisError(f"{context} repeats capability '{capability_id}'")
            capability_ids.add(capability_id)
            if capability["accepts"] != "ars.task/v1" or capability["returns"] != "ars.result/v1":
                raise NoctisError(f"{capability_context} has unsupported envelopes")
            effects = string_list(capability["effects"], f"{capability_context}.effects")
            unknown = sorted(set(effects) - EFFECTS)
            if unknown:
                raise NoctisError(
                    f"{capability_context}.effects has unknown values: {', '.join(unknown)}"
                )
            capabilities.append(
                {
                    "id": capability_id,
                    "description": text_value(
                        capability["description"], f"{capability_context}.description"
                    ),
                    "accepts": "ars.task/v1",
                    "returns": "ars.result/v1",
                    "effects": sorted(effects),
                }
            )
        providers.append(
            {"id": provider_id, "version": version, "capabilities": capabilities}
        )
    return {"schema": "ars.catalog/v1", "providers": providers}


def validate_run_record(value: Any, expected_run_id: str) -> dict[str, Any]:
    record = object_value(value, "run")
    exact(
        record,
        {
            "schema",
            "id",
            "plan",
            "catalog",
            "initial_grants",
            "grant_reason",
            "created_at",
            "created_from",
            "durable_ref",
        },
        "run",
    )
    if record["schema"] != "ars.run-record/v1":
        raise NoctisError("run.schema must be ars.run-record/v1")
    run_id = uuid_value(record["id"], "run.id")
    if run_id != expected_run_id:
        raise NoctisError("run.id does not match its directory")
    if record["plan"] != "plan.json":
        raise NoctisError("run.plan must be plan.json")
    grants = string_list(record["initial_grants"], "run.initial_grants")
    unknown = sorted(set(grants) - EFFECTS)
    if unknown:
        raise NoctisError(f"run.initial_grants has unknown values: {', '.join(unknown)}")
    reason = record["grant_reason"]
    if grants:
        reason = text_value(reason, "run.grant_reason")
    elif reason is not None:
        reason = text_value(reason, "run.grant_reason")
    created_from = text_value(record["created_from"], "run.created_from").lower()
    if not COMMIT.fullmatch(created_from):
        raise NoctisError("run.created_from must be a full 40-character SHA")
    durable_ref = record["durable_ref"]
    if durable_ref is not None:
        durable_ref = text_value(durable_ref, "run.durable_ref")
        if not durable_ref.startswith("refs/heads/"):
            raise NoctisError("run.durable_ref must be null or refs/heads/<branch>")
    return {
        "schema": "ars.run-record/v1",
        "id": run_id,
        "plan": "plan.json",
        "catalog": validate_catalog_snapshot(record["catalog"]),
        "initial_grants": sorted(grants),
        "grant_reason": reason,
        "created_at": timestamp_value(record["created_at"], "run.created_at"),
        "created_from": created_from,
        "durable_ref": durable_ref,
    }


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
    if event["schema"] != "ars.event/v1":
        raise NoctisError(f"{path}: schema must be ars.event/v1")
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
    task_id: str | None
    if event_type in TASK_EVENTS:
        task_id = identifier(event["task_id"], ITEM_ID, f"{path}: task_id")
    else:
        if event["task_id"] is not None:
            raise NoctisError(f"{path}: run events must have null task_id")
        task_id = None
    data = object_value(event["data"], f"{path}: data")
    if event_type in TASK_RESULT_EVENTS:
        exact(data, {"attempt", "result"}, f"{path}: data")
        data = {
            "attempt": integer_value(data["attempt"], f"{path}: data.attempt", minimum=1),
            "result": relative_path(data["result"], f"{path}: data.result"),
        }
    elif event_type == "task.retried":
        exact(data, {"attempt", "reason", "acknowledged_effects"}, f"{path}: data")
        if not isinstance(data["acknowledged_effects"], bool):
            raise NoctisError(f"{path}: data.acknowledged_effects must be boolean")
        data = {
            "attempt": integer_value(data["attempt"], f"{path}: data.attempt"),
            "reason": text_value(data["reason"], f"{path}: data.reason"),
            "acknowledged_effects": data["acknowledged_effects"],
        }
    elif event_type == "task.canceled":
        exact(
            data,
            {"attempt", "reason", "acknowledged_effects", "cascade_from"},
            f"{path}: data",
        )
        if not isinstance(data["acknowledged_effects"], bool):
            raise NoctisError(f"{path}: data.acknowledged_effects must be boolean")
        cascade_from = data["cascade_from"]
        if cascade_from is not None:
            cascade_from = identifier(
                cascade_from, ITEM_ID, f"{path}: data.cascade_from"
            )
        data = {
            "attempt": integer_value(data["attempt"], f"{path}: data.attempt"),
            "reason": text_value(data["reason"], f"{path}: data.reason"),
            "acknowledged_effects": data["acknowledged_effects"],
            "cascade_from": cascade_from,
        }
    else:
        exact(data, {"effects", "reason"}, f"{path}: data")
        effects = string_list(data["effects"], f"{path}: data.effects", nonempty=True)
        unknown = sorted(set(effects) - EFFECTS)
        if unknown:
            raise NoctisError(f"{path}: unknown effects: {', '.join(unknown)}")
        data = {
            "effects": sorted(effects),
            "reason": text_value(data["reason"], f"{path}: data.reason"),
        }
    return {
        "schema": "ars.event/v1",
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
        "schema": "ars.event/v1",
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


def validate_result(
    value: Any,
    run_id: str,
    task: dict[str, Any],
    roots: dict[str, Path],
    *,
    require_current_head: bool = False,
) -> dict[str, Any]:
    result = object_value(value, "result")
    exact(
        result,
        {"schema", "run_id", "task_id", "claim_id", "attempt", "status", "summary", "artifacts", "evidence", "effects"},
        "result",
    )
    if result["schema"] != "ars.result/v1":
        raise NoctisError("result.schema must be 'ars.result/v1'")
    if result["run_id"] != run_id or result["task_id"] != task["id"]:
        raise NoctisError("result run_id/task_id does not match the claimed task")
    if (
        result["claim_id"] != task["claim_id"]
        or isinstance(result["attempt"], bool)
        or not isinstance(result["attempt"], int)
        or result["attempt"] != task["attempt"]
    ):
        raise NoctisError("result claim_id/attempt is stale")
    status = result["status"]
    if status not in RESULT_STATES:
        raise NoctisError("result.status must be blocked, completed, failed, or input-required")
    workspace_ids = set(roots)
    normalized_lists: dict[str, list[dict[str, Any]]] = {}
    for field in ("artifacts", "evidence"):
        raw_items = result[field]
        if not isinstance(raw_items, list):
            raise NoctisError(f"result.{field} must be a list")
        items = [
            validate_artifact(item, f"result.{field}[{index}]", workspace_ids)
            for index, item in enumerate(raw_items)
        ]
        if len({item["id"] for item in items}) != len(items):
            raise NoctisError(f"result.{field} repeats artifact ids")
        for index, artifact in enumerate(items):
            validate_artifact_evidence(artifact, roots, f"result.{field}[{index}]")
        normalized_lists[field] = items
    if status == "completed" and not normalized_lists["artifacts"] and not normalized_lists["evidence"]:
        raise NoctisError("a completed result requires at least one artifact or evidence item")

    raw_effects = result["effects"]
    if not isinstance(raw_effects, list):
        raise NoctisError("result.effects must be a list")
    effects: list[dict[str, str]] = []
    expected_key = f"{run_id}/{task['id']}"
    commit_receipts: list[tuple[str, str]] = []
    for index, raw in enumerate(raw_effects):
        context = f"result.effects[{index}]"
        effect = object_value(raw, context)
        exact(effect, {"type", "target", "receipt", "idempotency_key"}, context)
        effect_type = text_value(effect["type"], f"{context}.type")
        if effect_type not in task["effects"]:
            raise NoctisError(f"{context}.type was not declared and granted for this task")
        target = text_value(effect["target"], f"{context}.target")
        receipt = text_value(effect["receipt"], f"{context}.receipt")
        if effect["idempotency_key"] != expected_key:
            raise NoctisError(f"{context}.idempotency_key must be {expected_key}")
        if effect_type == "git.commit":
            if target not in roots:
                raise NoctisError(f"{context}.target must name a workspace for git.commit")
            if not COMMIT.fullmatch(receipt) or not git_commit_exists(roots[target], receipt):
                raise NoctisError(f"{context}.receipt is not a reachable full commit SHA")
            head = git_head(roots[target])
            if not git_is_ancestor(roots[target], receipt, head):
                raise NoctisError(f"{context}.receipt is not an ancestor of workspace HEAD")
            if require_current_head and receipt != head:
                raise NoctisError(f"{context}.receipt must equal the current workspace HEAD")
            commit_receipts.append((target, receipt))
        effects.append(
            {"type": effect_type, "target": target, "receipt": receipt, "idempotency_key": expected_key}
        )

    if status == "completed" and "workspace.write" in task["effects"]:
        if not commit_receipts:
            raise NoctisError("a completed workspace.write task requires a git.commit receipt")
        artifact_commits = {
            (item["locator"]["workspace"], item["locator"]["commit"])
            for item in normalized_lists["artifacts"]
            if item["locator"]["kind"] == "git"
        }
        if not any(receipt in artifact_commits for receipt in commit_receipts):
            raise NoctisError(
                "a completed workspace.write task requires a Git Artifact matching its commit receipt"
            )
    return {
        "schema": "ars.result/v1",
        "run_id": run_id,
        "task_id": task["id"],
        "claim_id": task["claim_id"],
        "attempt": task["attempt"],
        "status": status,
        "summary": text_value(result["summary"], "result.summary"),
        "artifacts": normalized_lists["artifacts"],
        "evidence": normalized_lists["evidence"],
        "effects": effects,
    }


def load_run_state(project: Path, run_id: str) -> dict[str, Any]:
    directory = run_directory(project, run_id)
    record = validate_run_record(load_json(directory / "run.json"), run_id)
    if not git_commit_exists(project, record["created_from"]):
        raise NoctisError("run.created_from is not reachable in the current clone")
    plan = validate_plan(load_json(directory / record["plan"]), project, record["catalog"])
    roots = workspace_roots(project, plan)
    tasks = {
        definition["id"]: {
            **definition,
            "status": "pending",
            "attempt": 0,
            "revision": 0,
            "claim_id": None,
            "result": None,
            "started_at": None,
            "finished_at": None,
        }
        for definition in plan["tasks"]
    }
    event_directory = directory / "events"
    events = [
        validate_event(load_json(path), path, run_id)
        for path in sorted(event_directory.glob("*.json"))
    ] if event_directory.is_dir() else []
    task_events: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in tasks}
    run_events: list[dict[str, Any]] = []
    for event in events:
        if event["task_id"] is None:
            run_events.append(event)
        elif event["task_id"] not in tasks:
            raise NoctisError(f"event {event['id']} references unknown task '{event['task_id']}'")
        else:
            task_events[event["task_id"]].append(event)

    grants = set(record["initial_grants"])
    grant_revision = 0
    for event in sorted(run_events, key=lambda item: (item["revision"], item["id"])):
        if event["previous_revision"] != grant_revision:
            raise NoctisError(
                f"run event {event['id']} conflicts at grant revision {event['previous_revision']}"
            )
        grant_revision = event["revision"]
        if event["type"] == "run.granted":
            grants.update(event["data"]["effects"])
        else:
            grants.difference_update(event["data"]["effects"])

    for task_id, related in task_events.items():
        task = tasks[task_id]
        for event in sorted(related, key=lambda item: (item["revision"], item["id"])):
            if event["previous_revision"] != task["revision"]:
                raise NoctisError(
                    f"task event {event['id']} conflicts at revision {event['previous_revision']}"
                )
            event_type = event["type"]
            data = event["data"]
            if event_type in TASK_RESULT_EVENTS:
                if task["status"] != "pending":
                    raise NoctisError(
                        f"task {task_id} cannot apply {event_type} from {task['status']}"
                    )
                if data["attempt"] != task["attempt"] + 1:
                    raise NoctisError(
                        f"task {task_id} result attempt must follow its prior durable attempt"
                    )
                expected_result = f"results/{task_id}/attempt-{data['attempt']}.json"
                if data["result"] != expected_result:
                    raise NoctisError(
                        f"task {task_id} result path must be {expected_result}"
                    )
                result_path = resolve_inside(directory, data["result"], f"task {task_id} result")
                raw_result = load_json(result_path)
                raw_object = object_value(raw_result, f"task {task_id} result")
                claim_task = {
                    **task,
                    "claim_id": raw_object.get("claim_id"),
                    "attempt": data["attempt"],
                }
                result = validate_result(raw_result, run_id, claim_task, roots)
                expected_status = TASK_RESULT_EVENTS[event_type]
                if result["status"] != expected_status:
                    raise NoctisError(
                        f"task {task_id} event and result status do not match"
                    )
                task.update(
                    {
                        "status": expected_status,
                        "attempt": data["attempt"],
                        "revision": event["revision"],
                        "claim_id": result["claim_id"],
                        "result": result,
                        "finished_at": event["created_at"],
                    }
                )
            elif event_type == "task.retried":
                if task["status"] not in {"pending", "blocked", "failed", "input-required"}:
                    raise NoctisError(
                        f"task {task_id} cannot be retried from {task['status']}"
                    )
                if data["attempt"] < task["attempt"] or data["attempt"] > task["attempt"] + 1:
                    raise NoctisError(f"task {task_id} retry has an invalid attempt")
                task.update(
                    {
                        "status": "pending",
                        "attempt": data["attempt"],
                        "revision": event["revision"],
                        "claim_id": None,
                        "result": None,
                        "started_at": None,
                        "finished_at": None,
                    }
                )
            else:
                if task["status"] in TERMINAL_STATES:
                    raise NoctisError(
                        f"task {task_id} cannot be canceled from {task['status']}"
                    )
                if data["attempt"] < task["attempt"] or data["attempt"] > task["attempt"] + 1:
                    raise NoctisError(f"task {task_id} cancellation has an invalid attempt")
                if data["cascade_from"] is not None and data["cascade_from"] not in tasks:
                    raise NoctisError(
                        f"task {task_id} cancellation references unknown source '{data['cascade_from']}'"
                    )
                task.update(
                    {
                        "status": "canceled",
                        "attempt": data["attempt"],
                        "revision": event["revision"],
                        "claim_id": None,
                        "result": None,
                        "finished_at": event["created_at"],
                    }
                )

    for task in tasks.values():
        dependency_states = [tasks[item]["status"] for item in task["needs"]]
        if task["status"] == "completed" and any(
            state != "completed" for state in dependency_states
        ):
            raise NoctisError(
                f"completed task {task['id']} has a dependency that is not completed"
            )
        if task["status"] == "pending" and any(
            state == "canceled" for state in dependency_states
        ):
            raise NoctisError(
                f"pending task {task['id']} must be canceled after a dependency is canceled"
            )

    ordered_tasks = [tasks[item["id"]] for item in plan["tasks"]]
    updated_at = max(
        [record["created_at"], *(event["created_at"] for event in events)]
    )
    return {
        "record": record,
        "plan": plan,
        "tasks": ordered_tasks,
        "events": events,
        "grants": sorted(grants),
        "grant_revision": grant_revision,
        "updated_at": updated_at,
    }


def derive_run_status(tasks: list[dict[str, Any]]) -> str:
    states = [task["status"] for task in tasks]
    if states and all(state == "completed" for state in states):
        return "completed"
    if any(state == "working" for state in states):
        return "working"
    if any(state == "input-required" for state in states):
        return "input-required"
    if any(state == "blocked" for state in states):
        return "blocked"
    if any(state == "failed" for state in states):
        return "failed"
    if states and all(state in TERMINAL_STATES for state in states):
        return "canceled"
    return "submitted"


def ready_task_ids(tasks: list[dict[str, Any]]) -> list[str]:
    completed = {task["id"] for task in tasks if task["status"] == "completed"}
    return [
        task["id"]
        for task in tasks
        if task["status"] == "pending" and set(task["needs"]).issubset(completed)
    ]


def apply_local_claims(project: Path, run_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def repository_relative(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as error:
        raise NoctisError(f"{path} is outside Git repository {repo}") from error


def git_relative(project: Path, path: Path) -> str:
    return repository_relative(git_repository(project), path)


def checkpoint_info(project: Path, run_id: str) -> dict[str, Any]:
    project = project.resolve()
    repo = git_repository(project)
    directory = run_directory(project, run_id)
    pathspec = repository_relative(repo, directory)
    status = run_git(
        repo,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", pathspec],
    ).stdout.splitlines()
    tracked = True
    for required in (directory / "run.json", directory / "plan.json"):
        relative = repository_relative(repo, required)
        if run_git(repo, ["ls-files", "--error-unmatch", "--", relative], check=False).returncode != 0:
            tracked = False
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
        "committed": tracked and not status,
        "pushed": pushed,
        "changes": status,
    }


def require_committed_checkpoint(project: Path, run_id: str) -> dict[str, Any]:
    checkpoint = checkpoint_info(project, run_id)
    if not checkpoint["committed"]:
        raise NoctisError(
            "Noctis run state is not committed; commit the run JSON checkpoint before continuing"
        )
    return checkpoint


def require_clean_workspace(root: Path) -> None:
    repo = git_repository(root)
    pathspec = repository_relative(repo, root)
    result = run_git(
        repo,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", pathspec],
    )
    if result.stdout.strip():
        raise NoctisError(
            f"workspace has uncommitted content and is not a durable execution base: {root}"
        )


def catalog_snapshot(catalog: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    selected = {task["provider"] for task in plan["tasks"]}
    return {
        "schema": "ars.catalog/v1",
        "providers": [
            {
                "id": provider["id"],
                "version": provider["version"],
                "capabilities": provider["capabilities"],
            }
            for provider in catalog["providers"]
            if provider["id"] in selected
        ],
    }


def create_run(
    project: Path,
    plan_path: Path,
    skills_roots: list[Path],
    grants: list[str],
    grant_reason: str | None,
    confirm_high_risk: bool,
) -> dict[str, Any]:
    project = project.resolve()
    repo = git_repository(project)
    head = git_head(repo)
    unknown = sorted(set(grants) - EFFECTS)
    if unknown:
        raise NoctisError(f"unknown grants: {', '.join(unknown)}")
    if grants and not grant_reason:
        raise NoctisError("--grant-reason is required when grants are supplied")
    high_risk = sorted(set(grants) & HIGH_RISK_EFFECTS)
    if high_risk and not confirm_high_risk:
        raise NoctisError(
            "high-risk grants require --confirm-high-risk: " + ", ".join(high_risk)
        )
    catalog = discover(skills_roots)
    plan = validate_plan(load_json(plan_path), project, catalog)
    requested_effects = {effect for task in plan["tasks"] for effect in task["effects"]}
    excess_grants = sorted(set(grants) - requested_effects)
    if excess_grants:
        raise NoctisError(
            "grants exceed effects requested by the plan: " + ", ".join(excess_grants)
        )
    run_id = str(uuid.uuid4())
    directory = run_directory(project, run_id)
    if directory.exists():
        raise NoctisError(f"run directory already exists: {directory}")
    timestamp = now()
    branch = git_branch(repo)
    record = {
        "schema": "ars.run-record/v1",
        "id": run_id,
        "plan": "plan.json",
        "catalog": catalog_snapshot(catalog, plan),
        "initial_grants": sorted(set(grants)),
        "grant_reason": grant_reason,
        "created_at": timestamp,
        "created_from": head,
        "durable_ref": f"refs/heads/{branch}" if branch is not None else None,
    }
    atomic_write_json(directory / "plan.json", plan)
    atomic_write_json(directory / "run.json", record)
    if grants:
        authorize_local(project, run_id, sorted(set(grants)), text_value(grant_reason, "grant_reason"))
    return {
        "ok": True,
        "run_id": run_id,
        "status": "submitted",
        "ready": ready_task_ids(
            [{**task, "status": "pending"} for task in plan["tasks"]]
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
        "ready": ready_task_ids(tasks),
        "working": [task["id"] for task in tasks if task["status"] == "working"],
        "updated_at": state["updated_at"],
        "checkpoint": checkpoint_info(project, run_id),
    }


def show_run(project: Path, run_id: str | None) -> dict[str, Any]:
    project = project.resolve()
    if run_id is None:
        root = runs_root(project)
        directories = sorted(
            (path for path in root.iterdir() if path.is_dir() and (path / "run.json").is_file()),
            key=lambda path: path.name,
        ) if root.is_dir() else []
        runs = [compact_run(project, load_run_state(project, path.name)) for path in directories]
        runs.sort(key=lambda item: item["updated_at"], reverse=True)
        return {"schema": "ars.run-list/v1", "runs": runs}
    state = load_run_state(project, run_id)
    tasks = apply_local_claims(project, run_id, state["tasks"])
    active = active_grants(project, run_id)
    return {
        "schema": "ars.run/v1",
        "id": run_id,
        "title": state["plan"]["title"],
        "objective": state["plan"]["objective"],
        "status": derive_run_status(tasks),
        "grants": state["grants"],
        "active_grants": active,
        "ready": ready_task_ids(tasks),
        "tasks": tasks,
        "checkpoint": checkpoint_info(project, run_id),
        "created_at": state["record"]["created_at"],
        "updated_at": state["updated_at"],
    }


def show_events(project: Path, run_id: str, limit: int) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise NoctisError("event limit must be between 1 and 1000")
    state = load_run_state(project, run_id)
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
        "schema": "ars.event-list/v1",
        "run_id": run_id,
        "events": events[:limit],
    }


def recover(project: Path, run_id: str | None) -> dict[str, Any]:
    project = project.resolve()
    if run_id is None:
        root = runs_root(project)
        directories = sorted(
            (path for path in root.iterdir() if path.is_dir() and (path / "run.json").is_file()),
            key=lambda path: path.name,
        ) if root.is_dir() else []
        states = [load_run_state(project, path.name) for path in directories]
    else:
        states = [load_run_state(project, run_id)]
    rebuild_cache(project)
    runs = [
        {
            "id": state["record"]["id"],
            "status": derive_run_status(state["tasks"]),
            "ready": ready_task_ids(state["tasks"]),
            "checkpoint": checkpoint_info(project, state["record"]["id"]),
        }
        for state in states
    ]
    return {
        "schema": "ars.recovery/v1",
        "runs": runs,
        "local_claims": "cleared",
        "active_grants": [],
    }


def claim_task(project: Path, run_id: str, requested_task: str | None) -> dict[str, Any]:
    project = project.resolve()
    checkpoint = require_committed_checkpoint(project, run_id)
    state = load_run_state(project, run_id)
    visible_tasks = apply_local_claims(project, run_id, state["tasks"])
    ready = ready_task_ids(visible_tasks)
    task_id = requested_task or (ready[0] if ready else None)
    if task_id is None:
        working = [task["id"] for task in visible_tasks if task["status"] == "working"]
        detail = f"; local working tasks require reconciliation: {', '.join(working)}" if working else ""
        raise NoctisError("no task is ready" + detail)
    if task_id not in ready:
        raise NoctisError(f"task is not ready: {task_id}")
    task = next(item for item in state["tasks"] if item["id"] == task_id)
    roots = workspace_roots(project, state["plan"])
    require_clean_workspace(roots[task["workspace"]])
    recorded = set(state["grants"])
    active = set(active_grants(project, run_id))
    missing_recorded = sorted(set(task["effects"]) - recorded)
    if missing_recorded:
        raise NoctisError(f"task '{task_id}' lacks recorded grants: {', '.join(missing_recorded)}")
    missing_active = sorted(set(task["effects"]) - active)
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
            (run_id, task_id, claim_id, attempt, task["revision"], checkpoint["commit"], timestamp),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise NoctisError(f"task already has a local claim: {task_id}") from error
    finally:
        connection.close()

    resolved_inputs = [
        {"source": {"kind": "plan"}, "artifact": artifact}
        for artifact in task["inputs"]
    ]
    by_id = {item["id"]: item for item in state["tasks"]}
    for dependency in task["needs"]:
        result = by_id[dependency]["result"]
        if result is None:
            raise NoctisError(f"completed dependency has no result: {dependency}")
        resolved_inputs.extend(
            {
                "source": {"kind": "task", "run_id": run_id, "task_id": dependency},
                "artifact": artifact,
            }
            for artifact in result["artifacts"]
        )
    provider = next(
        item for item in state["record"]["catalog"]["providers"]
        if item["id"] == task["provider"]
    )
    return {
        "schema": "ars.task/v1",
        "run_id": run_id,
        "task_id": task_id,
        "claim_id": claim_id,
        "attempt": attempt,
        "revision": task["revision"],
        "provider": {"id": provider["id"], "version": provider["version"]},
        "capability": task["capability"],
        "workspace": {"id": task["workspace"], "root": str(roots[task["workspace"]])},
        "checkpoint": {"commit": checkpoint["commit"]},
        "instructions": task["instructions"],
        "inputs": resolved_inputs,
        "acceptance": task["acceptance"],
        "effects": {"required": task["effects"], "granted": task["effects"]},
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
        raise NoctisError("current workspace HEAD does not inherit the claimed checkpoint")
    missing = sorted(
        set(task["effects"])
        - (set(state["grants"]) & set(active_grants(project, run_id)))
    )
    if missing:
        raise NoctisError(f"task '{task_id}' no longer has effective grants: {', '.join(missing)}")
    claimed = {
        **task,
        "claim_id": claim_id,
        "attempt": claim["attempt"],
    }
    roots = workspace_roots(project, state["plan"])
    require_clean_workspace(roots[task["workspace"]])
    result = validate_result(
        load_json(result_path),
        run_id,
        claimed,
        roots,
        require_current_head=True,
    )
    directory = run_directory(project, run_id)
    result_relative = f"results/{task_id}/attempt-{claim['attempt']}.json"
    stored_result = resolve_inside(directory, result_relative, "stored result")
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
    acknowledge_effects: bool,
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
    if claim is not None and not git_is_ancestor(project, claim["checkpoint_commit"], git_head(project)):
        raise NoctisError("current workspace HEAD does not inherit the claimed checkpoint")
    recorded_effects = task["result"]["effects"] if task["result"] else []
    possible_unrecorded_effects = claim is not None and bool(task["effects"])
    if (recorded_effects or possible_unrecorded_effects) and not acknowledge_effects:
        raise NoctisError("retry requires --acknowledge-effects after reconciling prior side effects")
    if claim is not None:
        roots = workspace_roots(project, state["plan"])
        require_clean_workspace(roots[task["workspace"]])
    attempt = claim["attempt"] if claim is not None else task["attempt"]
    event = new_event(
        run_id,
        task_id,
        "task.retried",
        task["revision"],
        {
            "attempt": attempt,
            "reason": text_value(reason, "reason"),
            "acknowledged_effects": acknowledge_effects,
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


def descendants(tasks: list[dict[str, Any]], task_id: str) -> list[str]:
    selected = [task_id]
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task["id"] not in selected and set(task["needs"]) & set(selected):
                selected.append(task["id"])
                changed = True
    return selected


def cancel_task(
    project: Path,
    run_id: str,
    task_id: str,
    expected_revision: int,
    reason: str,
    acknowledge_effects: bool,
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
    recorded_effects = task["result"]["effects"] if task["result"] else []
    possible_unrecorded_effects = claim is not None and bool(task["effects"])
    if claim is not None and not git_is_ancestor(project, claim["checkpoint_commit"], git_head(project)):
        raise NoctisError("current workspace HEAD does not inherit the claimed checkpoint")
    if (recorded_effects or possible_unrecorded_effects) and not acknowledge_effects:
        raise NoctisError(
            "cancel requires --acknowledge-effects because cancellation does not undo side effects"
        )
    if claim is not None:
        roots = workspace_roots(project, state["plan"])
        require_clean_workspace(roots[task["workspace"]])
    selected = descendants(state["tasks"], task_id)
    events: list[Path] = []
    canceled: list[str] = []
    for candidate in state["tasks"]:
        if candidate["id"] not in selected:
            continue
        if candidate["id"] != task_id and candidate["status"] != "pending":
            continue
        candidate_claim = local_claim(project, run_id, candidate["id"])
        attempt = candidate_claim["attempt"] if candidate_claim is not None else candidate["attempt"]
        event = new_event(
            run_id,
            candidate["id"],
            "task.canceled",
            candidate["revision"],
            {
                "attempt": attempt,
                "reason": text_value(reason, "reason") if candidate["id"] == task_id else f"dependency canceled: {task_id}",
                "acknowledged_effects": acknowledge_effects if candidate["id"] == task_id else False,
                "cascade_from": None if candidate["id"] == task_id else task_id,
            },
            event_id=candidate_claim["claim_id"] if candidate_claim is not None else None,
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


def grant_effects(
    project: Path,
    run_id: str,
    effects: list[str],
    reason: str,
    confirm_high_risk: bool,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    unknown = sorted(set(effects) - EFFECTS)
    if unknown:
        raise NoctisError(f"unknown grants: {', '.join(unknown)}")
    high_risk = sorted(set(effects) & HIGH_RISK_EFFECTS)
    if high_risk and not confirm_high_risk:
        raise NoctisError(
            "high-risk grants require --confirm-high-risk: " + ", ".join(high_risk)
        )
    state = load_run_state(project, run_id)
    requested = {effect for task in state["tasks"] for effect in task["effects"]}
    excess = sorted(set(effects) - requested)
    if excess:
        raise NoctisError(
            "grants exceed effects requested by the plan: " + ", ".join(excess)
        )
    normalized_reason = text_value(reason, "reason")
    new_effects = sorted(set(effects) - set(state["grants"]))
    checkpoint_required: list[str] = []
    if new_effects:
        event = new_event(
            run_id,
            None,
            "run.granted",
            state["grant_revision"],
            {"effects": new_effects, "reason": normalized_reason},
        )
        path = append_event(project, event)
        checkpoint_required.append(git_relative(project, path))
    authorize_local(project, run_id, sorted(set(effects)), normalized_reason)
    return {
        "ok": True,
        "run_id": run_id,
        "grants": sorted(set(state["grants"]) | set(effects)),
        "active_grants": active_grants(project, run_id),
        "checkpoint_required": checkpoint_required,
        "checkpoint": checkpoint_info(project, run_id),
    }


def revoke_effects(
    project: Path,
    run_id: str,
    effects: list[str],
    reason: str,
) -> dict[str, Any]:
    project = project.resolve()
    require_committed_checkpoint(project, run_id)
    unknown = sorted(set(effects) - EFFECTS)
    if unknown:
        raise NoctisError(f"unknown effects: {', '.join(unknown)}")
    state = load_run_state(project, run_id)
    event = new_event(
        run_id,
        None,
        "run.revoked",
        state["grant_revision"],
        {"effects": sorted(set(effects)), "reason": text_value(reason, "reason")},
    )
    path = append_event(project, event)
    deauthorize_local(project, run_id, effects)
    return {
        "ok": True,
        "run_id": run_id,
        "grants": sorted(set(state["grants"]) - set(effects)),
        "active_grants": active_grants(project, run_id),
        "checkpoint_required": [git_relative(project, path)],
        "checkpoint": checkpoint_info(project, run_id),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    catalog = commands.add_parser("catalog")
    catalog.add_argument("--skills-root", type=Path, action="append", required=True)

    check = commands.add_parser("plan-check")
    check.add_argument("--project", type=Path, required=True)
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--skills-root", type=Path, action="append", required=True)

    create = commands.add_parser("run-create")
    create.add_argument("--project", type=Path, required=True)
    create.add_argument("--plan", type=Path, required=True)
    create.add_argument("--skills-root", type=Path, action="append", required=True)
    create.add_argument("--grant", action="append", default=[])
    create.add_argument("--grant-reason")
    create.add_argument("--confirm-high-risk", action="store_true")

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
    retry.add_argument("--acknowledge-effects", action="store_true")

    cancel = commands.add_parser("task-cancel")
    cancel.add_argument("--project", type=Path, required=True)
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--task-id", required=True)
    cancel.add_argument("--expected-revision", type=int, required=True)
    cancel.add_argument("--reason", required=True)
    cancel.add_argument("--acknowledge-effects", action="store_true")

    grant = commands.add_parser("grant")
    grant.add_argument("--project", type=Path, required=True)
    grant.add_argument("--run-id", required=True)
    grant.add_argument("--effect", action="append", required=True)
    grant.add_argument("--reason", required=True)
    grant.add_argument("--confirm-high-risk", action="store_true")

    revoke = commands.add_parser("revoke")
    revoke.add_argument("--project", type=Path, required=True)
    revoke.add_argument("--run-id", required=True)
    revoke.add_argument("--effect", action="append", required=True)
    revoke.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "catalog":
            result = discover(args.skills_root)
        elif args.command == "plan-check":
            catalog = discover(args.skills_root)
            plan = validate_plan(load_json(args.plan), args.project, catalog)
            result = {
                "ok": True,
                "schema": plan["schema"],
                "tasks": len(plan["tasks"]),
                "providers": sorted({task["provider"] for task in plan["tasks"]}),
            }
        elif args.command == "run-create":
            result = create_run(
                args.project,
                args.plan,
                args.skills_root,
                args.grant,
                args.grant_reason,
                args.confirm_high_risk,
            )
        elif args.command == "run-show":
            result = show_run(args.project, args.run_id)
        elif args.command == "run-events":
            result = show_events(args.project, args.run_id, args.limit)
        elif args.command == "recover":
            result = recover(args.project, args.run_id)
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
                args.acknowledge_effects,
            )
        elif args.command == "task-cancel":
            result = cancel_task(
                args.project,
                args.run_id,
                args.task_id,
                args.expected_revision,
                args.reason,
                args.acknowledge_effects,
            )
        elif args.command == "grant":
            result = grant_effects(
                args.project,
                args.run_id,
                args.effect,
                args.reason,
                args.confirm_high_risk,
            )
        else:
            result = revoke_effects(
                args.project,
                args.run_id,
                args.effect,
                args.reason,
            )
        emit(result)
        return 0
    except (NoctisError, OSError, sqlite3.Error) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
