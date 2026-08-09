#!/usr/bin/env python3
"""Adapt Ars providers and envelopes to protocol-neutral Noctis contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlparse

from ars import ArsError, EFFECTS, load_manifest


ITEM_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RESULT_STATES = {"blocked", "completed", "failed", "input-required"}


class AdapterError(ValueError):
    """Raised when Ars data cannot be adapted safely."""


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise AdapterError(f"JSON file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise AdapterError(f"invalid JSON in {path}: {error}") from error


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


def object_value(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AdapterError(f"{context} must be an object with string keys")
    return value


def exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing:
        raise AdapterError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise AdapterError(f"{context} has unknown fields: {', '.join(unknown)}")


def text_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"{context} must be a non-empty string")
    return value.strip()


def identifier(value: Any, context: str) -> str:
    result = text_value(value, context)
    if not ITEM_ID.fullmatch(result):
        raise AdapterError(f"{context} has an invalid identifier: {result}")
    return result


def uuid_value(value: Any, context: str) -> str:
    result = text_value(value, context)
    try:
        parsed = uuid.UUID(result)
    except ValueError as error:
        raise AdapterError(f"{context} must be a UUID") from error
    if str(parsed) != result:
        raise AdapterError(f"{context} must use canonical lowercase UUID form")
    return result


def string_list(value: Any, context: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise AdapterError(f"{context} must be a list")
    result = [text_value(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if nonempty and not result:
        raise AdapterError(f"{context} must not be empty")
    if len(result) != len(set(result)):
        raise AdapterError(f"{context} contains duplicates")
    return result


def strict_json(value: Any, context: str) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise AdapterError(f"{context} must be strict JSON") from error
    return value


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        strict_json(value, "value"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def relative_path(value: Any, context: str, *, allow_dot: bool = False) -> str:
    result = text_value(value, context)
    if allow_dot and result == ".":
        return result
    if "\\" in result or ":" in result or result.startswith("/"):
        raise AdapterError(f"{context} must be a relative POSIX path")
    parts = result.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise AdapterError(f"{context} must not contain empty, '.' or '..' segments")
    return PurePosixPath(result).as_posix()


def resolve_inside(root: Path, relative: str, context: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise AdapterError(f"{context} escapes its root") from error
    return candidate


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
        raise AdapterError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def git_repository(path: Path) -> Path:
    return Path(run_git(path.resolve(), ["rev-parse", "--show-toplevel"]).stdout.strip()).resolve()


def git_head(path: Path) -> str:
    return run_git(path.resolve(), ["rev-parse", "HEAD"]).stdout.strip().lower()


def git_commit_exists(path: Path, commit: str) -> bool:
    return run_git(path.resolve(), ["cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode == 0


def git_is_ancestor(path: Path, ancestor: str, descendant: str) -> bool:
    return run_git(path.resolve(), ["merge-base", "--is-ancestor", ancestor, descendant], check=False).returncode == 0


def require_clean_workspace(root: Path) -> None:
    repo = git_repository(root)
    relative = root.resolve().relative_to(repo).as_posix()
    result = run_git(
        repo,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", relative or "."],
    )
    if result.stdout.strip():
        raise AdapterError(f"workspace has uncommitted content: {root}")


def discover(skill_roots: Iterable[Path]) -> dict[str, Any]:
    manifests: list[Path] = []
    seen_paths: set[Path] = set()
    for supplied in skill_roots:
        root = supplied.resolve()
        if not root.is_dir():
            raise AdapterError(f"skills root does not exist: {root}")
        candidates = [root / "ars.json"] if (root / "ars.json").is_file() else sorted(root.glob("*/ars.json"))
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                manifests.append(resolved)
    providers: list[dict[str, Any]] = []
    by_id: dict[str, Path] = {}
    for path in sorted(manifests):
        try:
            manifest = load_manifest(path)
        except ArsError as error:
            raise AdapterError(str(error)) from error
        previous = by_id.get(manifest["id"])
        if previous is not None:
            raise AdapterError(
                f"provider '{manifest['id']}' is ambiguous: {previous.parent} and {path.parent}"
            )
        by_id[manifest["id"]] = path
        providers.append({**manifest, "source": str(path.parent.resolve())})
    return {
        "schema": "ars.catalog/v1",
        "providers": sorted(providers, key=lambda item: item["id"]),
    }


def validate_locator(value: Any, context: str, workspaces: set[str]) -> dict[str, Any]:
    locator = object_value(value, context)
    kind = locator.get("kind")
    if kind == "workspace":
        exact(locator, {"kind", "workspace", "path"}, context)
        workspace = identifier(locator["workspace"], f"{context}.workspace")
        if workspace not in workspaces:
            raise AdapterError(f"{context} references unknown workspace '{workspace}'")
        return {
            "kind": "workspace",
            "workspace": workspace,
            "path": relative_path(locator["path"], f"{context}.path"),
        }
    if kind == "git":
        exact(locator, {"kind", "workspace", "commit"}, context)
        workspace = identifier(locator["workspace"], f"{context}.workspace")
        if workspace not in workspaces:
            raise AdapterError(f"{context} references unknown workspace '{workspace}'")
        commit = text_value(locator["commit"], f"{context}.commit").lower()
        if not COMMIT.fullmatch(commit):
            raise AdapterError(f"{context}.commit must be a full 40-character SHA")
        return {"kind": "git", "workspace": workspace, "commit": commit}
    if kind == "uri":
        exact(locator, {"kind", "uri"}, context)
        uri = text_value(locator["uri"], f"{context}.uri")
        parsed = urlparse(uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AdapterError(f"{context}.uri must be an absolute HTTP(S) URI")
        return {"kind": "uri", "uri": uri}
    if kind == "inline":
        exact(locator, {"kind", "value"}, context)
        return {"kind": "inline", "value": strict_json(locator["value"], f"{context}.value")}
    raise AdapterError(f"{context}.kind must be workspace, git, uri, or inline")


def validate_artifact(value: Any, context: str, workspaces: set[str]) -> dict[str, Any]:
    artifact = object_value(value, context)
    exact(artifact, {"id", "type", "media_type", "locator", "digest"}, context)
    digest = artifact["digest"]
    if digest is not None and (not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
        raise AdapterError(f"{context}.digest must be null or sha256:<64 lowercase hex>")
    return {
        "id": identifier(artifact["id"], f"{context}.id"),
        "type": identifier(artifact["type"], f"{context}.type"),
        "media_type": text_value(artifact["media_type"], f"{context}.media_type"),
        "locator": validate_locator(artifact["locator"], f"{context}.locator", workspaces),
        "digest": digest,
    }


def validate_workspace(value: Any, context: str, project: Path) -> dict[str, str]:
    workspace = object_value(value, context)
    exact(workspace, {"id", "root"}, context)
    workspace_id = identifier(workspace["id"], f"{context}.id")
    root = relative_path(workspace["root"], f"{context}.root", allow_dot=True)
    resolved = project.resolve() if root == "." else resolve_inside(project, root, context)
    if not resolved.is_dir():
        raise AdapterError(f"workspace does not exist: {resolved}")
    return {"id": workspace_id, "root": root}


def validate_task_definition(
    value: Any,
    context: str,
    providers: dict[str, dict[str, Any]],
    workspaces: dict[str, dict[str, str]],
) -> dict[str, Any]:
    task = object_value(value, context)
    exact(
        task,
        {
            "id",
            "provider",
            "capability",
            "workspace",
            "needs",
            "instructions",
            "inputs",
            "acceptance",
            "effects",
        },
        context,
    )
    task_id = identifier(task["id"], f"{context}.id")
    provider_id = text_value(task["provider"], f"{context}.provider")
    provider = providers.get(provider_id)
    if provider is None:
        raise AdapterError(f"{context} references unavailable provider '{provider_id}'")
    capability_id = identifier(task["capability"], f"{context}.capability")
    capability = next(
        (item for item in provider["capabilities"] if item["id"] == capability_id),
        None,
    )
    if capability is None:
        raise AdapterError(f"provider '{provider_id}' does not provide '{capability_id}'")
    workspace_id = identifier(task["workspace"], f"{context}.workspace")
    if workspace_id not in workspaces:
        raise AdapterError(f"{context} references unknown workspace '{workspace_id}'")
    effects = sorted(string_list(task["effects"], f"{context}.effects"))
    unknown_effects = sorted(set(effects) - EFFECTS)
    if unknown_effects:
        raise AdapterError(f"{context}.effects has unknown values: {', '.join(unknown_effects)}")
    undeclared = sorted(set(effects) - set(capability["effects"]))
    if undeclared:
        raise AdapterError(
            f"{context}.effects are not declared by {provider_id}: {', '.join(undeclared)}"
        )
    if "workspace.write" in effects and "git.commit" not in effects:
        raise AdapterError(
            f"{context}.effects must include git.commit when workspace.write is requested"
        )
    raw_inputs = task["inputs"]
    if not isinstance(raw_inputs, list):
        raise AdapterError(f"{context}.inputs must be a list")
    inputs = [
        validate_artifact(item, f"{context}.inputs[{index}]", set(workspaces))
        for index, item in enumerate(raw_inputs)
    ]
    if len({item["id"] for item in inputs}) != len(inputs):
        raise AdapterError(f"{context}.inputs repeats artifact ids")
    return {
        "id": task_id,
        "provider": provider_id,
        "capability": capability_id,
        "workspace": workspace_id,
        "needs": string_list(task["needs"], f"{context}.needs"),
        "instructions": text_value(task["instructions"], f"{context}.instructions"),
        "inputs": inputs,
        "acceptance": string_list(task["acceptance"], f"{context}.acceptance", nonempty=True),
        "effects": effects,
    }


def executor_for(provider: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "schema": "ars.executor-snapshot/v1",
        "provider": {
            "id": provider["id"],
            "version": provider["version"],
            "capabilities": provider["capabilities"],
        },
    }
    return {
        "id": f"ars:{provider['id']}:{provider['version'].replace('.', '-')}",
        "kind": "ars",
        "snapshot": snapshot,
        "digest": canonical_digest(snapshot),
    }


def noctis_task(
    task: dict[str, Any], workspaces: dict[str, dict[str, str]], provider: dict[str, Any]
) -> dict[str, Any]:
    workspace = workspaces[task["workspace"]]
    return {
        "id": task["id"],
        "needs": task["needs"],
        "executor": executor_for(provider)["id"],
        "request": {
            "schema": "ars.binding/v1",
            "provider": task["provider"],
            "capability": task["capability"],
            "workspace": workspace,
            "instructions": task["instructions"],
            "inputs": task["inputs"],
            "acceptance": task["acceptance"],
            "effects": task["effects"],
        },
        "requirements": task["effects"],
    }


def validate_task_graph(tasks: list[dict[str, Any]]) -> None:
    task_ids = {task["id"] for task in tasks}
    if len(task_ids) != len(tasks):
        raise AdapterError("task ids must be unique")
    dependencies = {task["id"]: task["needs"] for task in tasks}
    for task in tasks:
        unknown = sorted(set(task["needs"]) - task_ids)
        if unknown:
            raise AdapterError(f"task '{task['id']}' needs unknown tasks: {', '.join(unknown)}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise AdapterError(f"task graph contains a cycle at '{task_id}'")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in dependencies[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in dependencies:
        visit(task_id)


def adapt_plan(
    value: Any, project: Path, skill_roots: list[Path]
) -> dict[str, Any]:
    plan = object_value(value, "plan")
    exact(plan, {"schema", "title", "objective", "workspaces", "tasks"}, "plan")
    if plan["schema"] != "ars.plan/v1":
        raise AdapterError("plan.schema must be 'ars.plan/v1'")
    raw_workspaces = plan["workspaces"]
    if not isinstance(raw_workspaces, list) or not raw_workspaces:
        raise AdapterError("plan.workspaces must be a non-empty list")
    workspace_list = [
        validate_workspace(item, f"plan.workspaces[{index}]", project)
        for index, item in enumerate(raw_workspaces)
    ]
    workspaces = {item["id"]: item for item in workspace_list}
    if len(workspaces) != len(workspace_list):
        raise AdapterError("plan repeats workspace ids")
    catalog = discover(skill_roots)
    providers = {item["id"]: item for item in catalog["providers"]}
    raw_tasks = plan["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise AdapterError("plan.tasks must be a non-empty list")
    tasks = [
        validate_task_definition(item, f"plan.tasks[{index}]", providers, workspaces)
        for index, item in enumerate(raw_tasks)
    ]
    validate_task_graph(tasks)
    selected = {task["provider"] for task in tasks}
    executors = [executor_for(providers[provider_id]) for provider_id in sorted(selected)]
    return {
        "schema": "noctis.plan/v1",
        "title": text_value(plan["title"], "plan.title"),
        "objective": text_value(plan["objective"], "plan.objective"),
        "executors": executors,
        "tasks": [noctis_task(task, workspaces, providers[task["provider"]]) for task in tasks],
    }


def adapt_extension(
    value: Any, project: Path, skill_roots: list[Path]
) -> dict[str, Any]:
    extension = object_value(value, "extension")
    exact(extension, {"schema", "origin", "workspaces", "tasks"}, "extension")
    if extension["schema"] != "ars.noctis-extension/v1":
        raise AdapterError("extension.schema must be 'ars.noctis-extension/v1'")
    raw_workspaces = extension["workspaces"]
    if not isinstance(raw_workspaces, list) or not raw_workspaces:
        raise AdapterError("extension.workspaces must be a non-empty list")
    workspace_list = [
        validate_workspace(item, f"extension.workspaces[{index}]", project)
        for index, item in enumerate(raw_workspaces)
    ]
    workspaces = {item["id"]: item for item in workspace_list}
    if len(workspaces) != len(workspace_list):
        raise AdapterError("extension repeats workspace ids")
    catalog = discover(skill_roots)
    providers = {item["id"]: item for item in catalog["providers"]}
    raw_tasks = extension["tasks"]
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise AdapterError("extension.tasks must be a non-empty list")
    tasks = [
        validate_task_definition(
            item, f"extension.tasks[{index}]", providers, workspaces
        )
        for index, item in enumerate(raw_tasks)
    ]
    selected = {task["provider"] for task in tasks}
    origin = object_value(extension["origin"], "extension.origin")
    exact(origin, {"kind", "summary", "reference"}, "extension.origin")
    reference = origin["reference"]
    if reference is not None:
        reference = text_value(reference, "extension.origin.reference")
    return {
        "schema": "noctis.extension/v1",
        "origin": {
            "kind": identifier(origin["kind"], "extension.origin.kind"),
            "summary": text_value(origin["summary"], "extension.origin.summary"),
            "reference": reference,
        },
        "executors": [executor_for(providers[item]) for item in sorted(selected)],
        "tasks": [noctis_task(task, workspaces, providers[task["provider"]]) for task in tasks],
    }


def validate_artifact_evidence(
    artifact: dict[str, Any], roots: dict[str, Path], context: str
) -> None:
    locator = artifact["locator"]
    if locator["kind"] == "workspace":
        path = resolve_inside(roots[locator["workspace"]], locator["path"], context)
        if not path.exists():
            raise AdapterError(f"{context} does not exist: {path}")
        if artifact["digest"] is not None:
            if not path.is_file():
                raise AdapterError(f"{context} can only digest a file")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if artifact["digest"] != "sha256:" + digest:
                raise AdapterError(f"{context} digest does not match {path}")
    elif locator["kind"] == "git":
        if not git_commit_exists(roots[locator["workspace"]], locator["commit"]):
            raise AdapterError(f"{context} commit is not reachable: {locator['commit']}")


def _binding_from_claim(value: Any, project: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    claim = object_value(value, "claim")
    exact(
        claim,
        {
            "schema",
            "run_id",
            "task_id",
            "claim_id",
            "attempt",
            "revision",
            "run_revision",
            "executor",
            "request",
            "dependencies",
            "requirements",
            "checkpoint",
            "idempotency_key",
        },
        "claim",
    )
    if claim["schema"] != "noctis.claim/v1":
        raise AdapterError("claim.schema must be 'noctis.claim/v1'")
    executor = object_value(claim["executor"], "claim.executor")
    exact(executor, {"id", "kind", "snapshot", "digest"}, "claim.executor")
    if executor["kind"] != "ars":
        raise AdapterError("claim executor is not an Ars adapter binding")
    if canonical_digest(executor["snapshot"]) != executor["digest"]:
        raise AdapterError("claim executor snapshot digest does not match")
    snapshot = object_value(executor["snapshot"], "claim.executor.snapshot")
    exact(snapshot, {"schema", "provider"}, "claim.executor.snapshot")
    if snapshot["schema"] != "ars.executor-snapshot/v1":
        raise AdapterError("unsupported Ars executor snapshot")
    provider = object_value(snapshot["provider"], "claim.executor.snapshot.provider")
    exact(provider, {"id", "version", "capabilities"}, "claim.executor.snapshot.provider")
    request = object_value(claim["request"], "claim.request")
    exact(
        request,
        {
            "schema",
            "provider",
            "capability",
            "workspace",
            "instructions",
            "inputs",
            "acceptance",
            "effects",
        },
        "claim.request",
    )
    if request["schema"] != "ars.binding/v1":
        raise AdapterError("claim.request.schema must be 'ars.binding/v1'")
    if request["provider"] != provider["id"]:
        raise AdapterError("claim provider does not match its executor snapshot")
    capability = next(
        (item for item in provider["capabilities"] if item["id"] == request["capability"]),
        None,
    )
    if capability is None:
        raise AdapterError("claim capability is absent from its executor snapshot")
    workspace = object_value(request["workspace"], "claim.request.workspace")
    exact(workspace, {"id", "root"}, "claim.request.workspace")
    workspace_id = identifier(workspace["id"], "claim.request.workspace.id")
    root_path = relative_path(workspace["root"], "claim.request.workspace.root", allow_dot=True)
    root = project.resolve() if root_path == "." else resolve_inside(project, root_path, "workspace")
    if not root.is_dir():
        raise AdapterError(f"workspace does not exist: {root}")
    roots = {workspace_id: root}
    effects = sorted(string_list(request["effects"], "claim.request.effects"))
    undeclared = sorted(set(effects) - set(capability["effects"]))
    if undeclared:
        raise AdapterError("claim effects exceed the executor snapshot: " + ", ".join(undeclared))
    requirements = object_value(claim["requirements"], "claim.requirements")
    exact(requirements, {"required", "granted"}, "claim.requirements")
    required = sorted(string_list(requirements["required"], "claim.requirements.required"))
    granted = sorted(string_list(requirements["granted"], "claim.requirements.granted"))
    if required != effects or granted != effects:
        raise AdapterError("claim requirements must match the Ars effect binding")
    checkpoint = object_value(claim["checkpoint"], "claim.checkpoint")
    exact(checkpoint, {"commit"}, "claim.checkpoint")
    commit = text_value(checkpoint["commit"], "claim.checkpoint.commit").lower()
    if not COMMIT.fullmatch(commit) or not git_commit_exists(project, commit):
        raise AdapterError("claim checkpoint must be a reachable full commit SHA")
    return claim, request, roots


def adapt_claim(value: Any, project: Path) -> dict[str, Any]:
    claim, request, roots = _binding_from_claim(value, project)
    require_clean_workspace(next(iter(roots.values())))
    workspace_ids = set(roots)
    raw_inputs = request["inputs"]
    if not isinstance(raw_inputs, list):
        raise AdapterError("claim.request.inputs must be a list")
    resolved_inputs = []
    for index, raw in enumerate(raw_inputs):
        artifact = validate_artifact(raw, f"claim.request.inputs[{index}]", workspace_ids)
        validate_artifact_evidence(artifact, roots, f"claim.request.inputs[{index}]")
        resolved_inputs.append({"source": {"kind": "plan"}, "artifact": artifact})
    dependencies = claim["dependencies"]
    if not isinstance(dependencies, list):
        raise AdapterError("claim.dependencies must be a list")
    for index, raw_dependency in enumerate(dependencies):
        dependency = object_value(raw_dependency, f"claim.dependencies[{index}]")
        exact(dependency, {"task_id", "result"}, f"claim.dependencies[{index}]")
        result = object_value(dependency["result"], f"claim.dependencies[{index}].result")
        if result.get("schema") != "noctis.result/v1":
            raise AdapterError("dependency result must use noctis.result/v1")
        output = object_value(result.get("output"), f"claim.dependencies[{index}].result.output")
        if output.get("schema") != "ars.result/v1":
            raise AdapterError("Ars dependencies must contain an ars.result/v1 output")
        artifacts = output.get("artifacts")
        if not isinstance(artifacts, list):
            raise AdapterError("dependency Ars result artifacts must be a list")
        for artifact_index, raw_artifact in enumerate(artifacts):
            artifact = validate_artifact(
                raw_artifact,
                f"claim.dependencies[{index}].artifacts[{artifact_index}]",
                workspace_ids,
            )
            validate_artifact_evidence(
                artifact,
                roots,
                f"claim.dependencies[{index}].artifacts[{artifact_index}]",
            )
            resolved_inputs.append(
                {
                    "source": {
                        "kind": "task",
                        "run_id": claim["run_id"],
                        "task_id": dependency["task_id"],
                    },
                    "artifact": artifact,
                }
            )
    provider = object_value(claim["executor"]["snapshot"]["provider"], "provider")
    workspace_id, workspace_root = next(iter(roots.items()))
    return {
        "schema": "ars.task/v1",
        "run_id": claim["run_id"],
        "task_id": claim["task_id"],
        "claim_id": claim["claim_id"],
        "attempt": claim["attempt"],
        "revision": claim["revision"],
        "provider": {"id": provider["id"], "version": provider["version"]},
        "capability": request["capability"],
        "workspace": {"id": workspace_id, "root": str(workspace_root)},
        "checkpoint": claim["checkpoint"],
        "instructions": text_value(request["instructions"], "claim.request.instructions"),
        "inputs": resolved_inputs,
        "acceptance": string_list(request["acceptance"], "claim.request.acceptance", nonempty=True),
        "effects": {"required": request["effects"], "granted": request["effects"]},
        "idempotency_key": claim["idempotency_key"],
    }


def validate_ars_result(
    value: Any,
    claim: dict[str, Any],
    request: dict[str, Any],
    roots: dict[str, Path],
) -> dict[str, Any]:
    result = object_value(value, "result")
    exact(
        result,
        {"schema", "run_id", "task_id", "claim_id", "attempt", "status", "summary", "artifacts", "evidence", "effects"},
        "result",
    )
    if result["schema"] != "ars.result/v1":
        raise AdapterError("result.schema must be 'ars.result/v1'")
    for field in ("run_id", "task_id", "claim_id", "attempt"):
        if result[field] != claim[field]:
            raise AdapterError(f"result.{field} does not match the Noctis claim")
    status = result["status"]
    if status not in RESULT_STATES:
        raise AdapterError("invalid Ars result status")
    workspace_ids = set(roots)
    normalized: dict[str, list[dict[str, Any]]] = {}
    for field in ("artifacts", "evidence"):
        raw_items = result[field]
        if not isinstance(raw_items, list):
            raise AdapterError(f"result.{field} must be a list")
        items = [
            validate_artifact(item, f"result.{field}[{index}]", workspace_ids)
            for index, item in enumerate(raw_items)
        ]
        if len({item["id"] for item in items}) != len(items):
            raise AdapterError(f"result.{field} repeats artifact ids")
        for index, artifact in enumerate(items):
            validate_artifact_evidence(artifact, roots, f"result.{field}[{index}]")
        normalized[field] = items
    if status == "completed" and not normalized["artifacts"] and not normalized["evidence"]:
        raise AdapterError("a completed Ars result requires an Artifact or evidence")
    raw_effects = result["effects"]
    if not isinstance(raw_effects, list):
        raise AdapterError("result.effects must be a list")
    expected_key = claim["idempotency_key"]
    effects: list[dict[str, str]] = []
    commit_receipts: list[tuple[str, str]] = []
    for index, raw in enumerate(raw_effects):
        context = f"result.effects[{index}]"
        effect = object_value(raw, context)
        exact(effect, {"type", "target", "receipt", "idempotency_key"}, context)
        effect_type = text_value(effect["type"], f"{context}.type")
        if effect_type not in request["effects"]:
            raise AdapterError(f"{context}.type was not declared by this Ars binding")
        target = text_value(effect["target"], f"{context}.target")
        receipt = text_value(effect["receipt"], f"{context}.receipt")
        if effect["idempotency_key"] != expected_key:
            raise AdapterError(f"{context}.idempotency_key must be {expected_key}")
        if effect_type == "git.commit":
            if target not in roots:
                raise AdapterError(f"{context}.target must name a workspace")
            if not COMMIT.fullmatch(receipt) or not git_commit_exists(roots[target], receipt):
                raise AdapterError(f"{context}.receipt is not a reachable full commit SHA")
            head = git_head(roots[target])
            if receipt != head:
                raise AdapterError(f"{context}.receipt must equal the current workspace HEAD")
            commit_receipts.append((target, receipt))
        effects.append(
            {"type": effect_type, "target": target, "receipt": receipt, "idempotency_key": expected_key}
        )
    if status == "completed" and "workspace.write" in request["effects"]:
        if not commit_receipts:
            raise AdapterError("a completed workspace.write requires a git.commit receipt")
        artifact_commits = {
            (item["locator"]["workspace"], item["locator"]["commit"])
            for item in normalized["artifacts"]
            if item["locator"]["kind"] == "git"
        }
        if not any(receipt in artifact_commits for receipt in commit_receipts):
            raise AdapterError("workspace.write requires a matching Git Artifact")
    return {
        "schema": "ars.result/v1",
        "run_id": claim["run_id"],
        "task_id": claim["task_id"],
        "claim_id": claim["claim_id"],
        "attempt": claim["attempt"],
        "status": status,
        "summary": text_value(result["summary"], "result.summary"),
        "artifacts": normalized["artifacts"],
        "evidence": normalized["evidence"],
        "effects": effects,
    }


def adapt_result(claim_value: Any, result_value: Any, project: Path) -> dict[str, Any]:
    claim, request, roots = _binding_from_claim(claim_value, project)
    require_clean_workspace(next(iter(roots.values())))
    result = validate_ars_result(result_value, claim, request, roots)
    return {
        "schema": "noctis.result/v1",
        "run_id": claim["run_id"],
        "task_id": claim["task_id"],
        "claim_id": claim["claim_id"],
        "attempt": claim["attempt"],
        "status": result["status"],
        "summary": result["summary"],
        "output": result,
    }


def adapt_legacy_plan(
    value: Any, catalog_value: Any, project: Path
) -> dict[str, Any]:
    plan = object_value(value, "legacy plan")
    exact(plan, {"schema", "title", "objective", "workspaces", "tasks"}, "legacy plan")
    if plan["schema"] != "ars.plan/v1":
        raise AdapterError("legacy plan must use ars.plan/v1")
    catalog = object_value(catalog_value, "legacy catalog")
    exact(catalog, {"schema", "providers"}, "legacy catalog")
    if catalog["schema"] != "ars.catalog/v1":
        raise AdapterError("legacy catalog must use ars.catalog/v1")
    providers: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(catalog["providers"]):
        provider = object_value(raw, f"legacy catalog.providers[{index}]")
        exact(provider, {"id", "version", "capabilities"}, f"legacy catalog.providers[{index}]")
        providers[provider["id"]] = provider
    workspace_list = [
        validate_workspace(item, f"legacy plan.workspaces[{index}]", project)
        for index, item in enumerate(plan["workspaces"])
    ]
    workspaces = {item["id"]: item for item in workspace_list}
    tasks = [
        validate_task_definition(item, f"legacy plan.tasks[{index}]", providers, workspaces)
        for index, item in enumerate(plan["tasks"])
    ]
    validate_task_graph(tasks)
    selected = {task["provider"] for task in tasks}
    return {
        "schema": "noctis.plan/v1",
        "title": text_value(plan["title"], "legacy plan.title"),
        "objective": text_value(plan["objective"], "legacy plan.objective"),
        "executors": [executor_for(providers[item]) for item in sorted(selected)],
        "tasks": [noctis_task(task, workspaces, providers[task["provider"]]) for task in tasks],
    }


def _write_migrated_run(
    project: Path, source: Path, target: Path, run_id: str
) -> tuple[int, int]:
    legacy_run = object_value(load_json(source / "run.json"), "legacy run")
    exact(
        legacy_run,
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
        "legacy run",
    )
    if legacy_run["schema"] != "ars.run-record/v1" or uuid_value(
        legacy_run["id"], "legacy run.id"
    ) != run_id:
        raise AdapterError("legacy run identity is invalid")
    plan_reference = relative_path(legacy_run["plan"], "legacy run.plan")
    plan = adapt_legacy_plan(
        load_json(resolve_inside(source, plan_reference, "legacy plan")),
        legacy_run["catalog"],
        project,
    )
    record = {
        "schema": "noctis.run-record/v1",
        "id": run_id,
        "plan": "plan.json",
        "initial_grants": legacy_run["initial_grants"],
        "grant_reason": legacy_run["grant_reason"],
        "created_at": legacy_run["created_at"],
        "created_from": legacy_run["created_from"],
        "durable_ref": legacy_run["durable_ref"],
    }
    atomic_write_json(target / "plan.json", plan)
    atomic_write_json(target / "run.json", record)
    migrated_events = 0
    migrated_results = 0
    event_root = source / "events"
    for event_path in sorted(event_root.glob("*.json")) if event_root.is_dir() else []:
        event = object_value(load_json(event_path), str(event_path))
        if event.get("schema") != "ars.event/v1":
            raise AdapterError(f"unsupported legacy event: {event_path}")
        event_type = event.get("type")
        if event_type not in {
            "run.granted",
            "run.revoked",
            "task.blocked",
            "task.completed",
            "task.failed",
            "task.input-required",
            "task.retried",
            "task.canceled",
        }:
            raise AdapterError(f"unsupported legacy event type: {event_type}")
        data = object_value(event.get("data"), f"{event_path}: data")
        if event_type in {"run.granted", "run.revoked"}:
            data = {"requirements": data["effects"], "reason": data["reason"]}
        elif event_type == "task.retried":
            data = {
                "attempt": data["attempt"],
                "reason": data["reason"],
                "acknowledged_requirements": data["acknowledged_effects"],
            }
        elif event_type == "task.canceled":
            data = {
                "attempt": data["attempt"],
                "reason": data["reason"],
                "acknowledged_requirements": data["acknowledged_effects"],
                "cascade_from": data["cascade_from"],
            }
        else:
            legacy_result_path = resolve_inside(source, data["result"], "legacy result")
            legacy_result = object_value(load_json(legacy_result_path), "legacy result")
            new_result = {
                "schema": "noctis.result/v1",
                "run_id": legacy_result["run_id"],
                "task_id": legacy_result["task_id"],
                "claim_id": legacy_result["claim_id"],
                "attempt": legacy_result["attempt"],
                "status": legacy_result["status"],
                "summary": legacy_result["summary"],
                "output": strict_json(legacy_result, "legacy result"),
            }
            atomic_write_json(resolve_inside(target, data["result"], "target result"), new_result)
            migrated_results += 1
        migrated_event = {
            **event,
            "schema": "noctis.event/v1",
            "data": data,
        }
        atomic_write_json(target / "events" / event_path.name, migrated_event)
        migrated_events += 1
    return migrated_events, migrated_results


def migrate_run(project: Path, run_id: str) -> dict[str, Any]:
    project = project.resolve()
    normalized_run_id = uuid_value(run_id, "run_id")
    source = project / ".ars" / "runs" / normalized_run_id
    target = project / ".noctis" / "runs" / normalized_run_id
    if not source.is_dir():
        raise AdapterError(f"legacy Run does not exist: {source}")
    if target.exists():
        raise AdapterError(f"target Run already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4()}.tmp")
    try:
        migrated_events, migrated_results = _write_migrated_run(
            project, source, temporary, normalized_run_id
        )
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "ok": True,
        "run_id": normalized_run_id,
        "source": str(source),
        "target": str(target),
        "events": migrated_events,
        "results": migrated_results,
        "checkpoint_required": [str(target.relative_to(git_repository(project)))],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    catalog = commands.add_parser("catalog")
    catalog.add_argument("--skills-root", type=Path, action="append", required=True)

    plan = commands.add_parser("plan-adapt")
    plan.add_argument("--project", type=Path, required=True)
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--skills-root", type=Path, action="append", required=True)

    extension = commands.add_parser("extension-adapt")
    extension.add_argument("--project", type=Path, required=True)
    extension.add_argument("--extension", type=Path, required=True)
    extension.add_argument("--skills-root", type=Path, action="append", required=True)

    claim = commands.add_parser("claim-adapt")
    claim.add_argument("--project", type=Path, required=True)
    claim.add_argument("--claim", type=Path, required=True)

    result = commands.add_parser("result-adapt")
    result.add_argument("--project", type=Path, required=True)
    result.add_argument("--claim", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True)

    migrate = commands.add_parser("migrate-run")
    migrate.add_argument("--project", type=Path, required=True)
    migrate.add_argument("--run-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "catalog":
            output = discover(args.skills_root)
        elif args.command == "plan-adapt":
            output = adapt_plan(load_json(args.plan), args.project, args.skills_root)
        elif args.command == "extension-adapt":
            output = adapt_extension(
                load_json(args.extension), args.project, args.skills_root
            )
        elif args.command == "claim-adapt":
            output = adapt_claim(load_json(args.claim), args.project)
        elif args.command == "result-adapt":
            output = adapt_result(
                load_json(args.claim), load_json(args.result), args.project
            )
        else:
            output = migrate_run(args.project, args.run_id)
        emit(output)
        return 0
    except (AdapterError, ArsError, OSError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
