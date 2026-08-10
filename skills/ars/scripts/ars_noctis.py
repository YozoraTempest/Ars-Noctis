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
RUNTIME_FIELDS = {"agent_mode", "model", "reasoning_effort"}
RUNTIME_SOURCES = {"explicit", "repository", "task", "provider", "run", "agent"}
AGENT_MODES = {"single", "multi"}


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


def only(value: dict[str, Any], fields: set[str], context: str) -> None:
    unknown = sorted(set(value) - fields)
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


def app_profile_path(project: Path) -> Path:
    repository = git_repository(project)
    raw = run_git(repository, ["rev-parse", "--git-common-dir"]).stdout.strip()
    common = Path(raw)
    if not common.is_absolute():
        common = repository / common
    return common.resolve() / "ars-noctis" / "app-profile.json"


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


def validate_runtime_settings(value: Any, context: str) -> dict[str, str]:
    settings = object_value(value, context)
    only(settings, RUNTIME_FIELDS, context)
    normalized = {
        field: text_value(settings[field], f"{context}.{field}")
        for field in sorted(settings)
    }
    if "agent_mode" in normalized and normalized["agent_mode"] not in AGENT_MODES:
        raise AdapterError(f"{context}.agent_mode must be single or multi")
    return normalized


def validate_app_profile(value: Any, context: str = "app profile") -> dict[str, Any]:
    profile = object_value(value, context)
    exact(profile, {"schema", "skills"}, context)
    if profile["schema"] != "ars.app-profile/v1":
        raise AdapterError(f"{context}.schema must be 'ars.app-profile/v1'")
    skills = object_value(profile["skills"], f"{context}.skills")
    normalized = {}
    for raw_skill, raw_settings in skills.items():
        skill = identifier(raw_skill, f"{context}.skills key")
        normalized[skill] = validate_runtime_settings(
            raw_settings, f"{context}.skills.{skill}"
        )
    return {"schema": "ars.app-profile/v1", "skills": normalized}


def validate_app_selection(
    value: Any, schema: str, context: str
) -> dict[str, Any]:
    selection = object_value(value, context)
    exact(selection, {"schema", "default", "providers", "tasks"}, context)
    if selection["schema"] != schema:
        raise AdapterError(f"{context}.schema must be '{schema}'")
    providers = object_value(selection["providers"], f"{context}.providers")
    tasks = object_value(selection["tasks"], f"{context}.tasks")
    return {
        "schema": schema,
        "default": validate_runtime_settings(
            selection["default"], f"{context}.default"
        ),
        "providers": {
            identifier(key, f"{context}.providers key"): validate_runtime_settings(
                settings, f"{context}.providers.{key}"
            )
            for key, settings in providers.items()
        },
        "tasks": {
            identifier(key, f"{context}.tasks key"): validate_runtime_settings(
                settings, f"{context}.tasks.{key}"
            )
            for key, settings in tasks.items()
        },
    }


def empty_app_profile() -> dict[str, Any]:
    return {"schema": "ars.app-profile/v1", "skills": {}}


def empty_app_selection(schema: str) -> dict[str, Any]:
    return {"schema": schema, "default": {}, "providers": {}, "tasks": {}}


def init_app_profile(project: Path, supplied_path: Path | None = None) -> dict[str, Any]:
    path = supplied_path.resolve() if supplied_path is not None else app_profile_path(project)
    if path.exists():
        profile = validate_app_profile(load_json(path))
        status = "existing"
    else:
        profile = empty_app_profile()
        atomic_write_json(path, profile)
        status = "created"
    return {"ok": True, "status": status, "path": str(path), "profile": profile}


def show_app_profile(project: Path, supplied_path: Path | None = None) -> dict[str, Any]:
    path = supplied_path.resolve() if supplied_path is not None else app_profile_path(project)
    if not path.is_file():
        raise AdapterError(f"App profile does not exist: {path}")
    return {
        "ok": True,
        "path": str(path),
        "profile": validate_app_profile(load_json(path)),
    }


def set_app_profile(
    project: Path,
    skill: str,
    *,
    supplied_path: Path | None = None,
    agent_mode: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    clear_agent_mode: bool = False,
    clear_model: bool = False,
    clear_reasoning_effort: bool = False,
) -> dict[str, Any]:
    path = supplied_path.resolve() if supplied_path is not None else app_profile_path(project)
    profile = validate_app_profile(load_json(path)) if path.is_file() else empty_app_profile()
    skill_id = identifier(skill, "skill")
    settings = dict(profile["skills"].get(skill_id, {}))
    if agent_mode is not None:
        settings["agent_mode"] = text_value(agent_mode, "agent_mode")
    if model is not None:
        settings["model"] = text_value(model, "model")
    if reasoning_effort is not None:
        settings["reasoning_effort"] = text_value(reasoning_effort, "reasoning_effort")
    if clear_agent_mode:
        settings.pop("agent_mode", None)
    if clear_model:
        settings.pop("model", None)
    if clear_reasoning_effort:
        settings.pop("reasoning_effort", None)
    if not any(
        (
            agent_mode is not None,
            model is not None,
            reasoning_effort is not None,
            clear_agent_mode,
            clear_model,
            clear_reasoning_effort,
        )
    ):
        raise AdapterError("App profile update requires a value or clear option")
    if settings:
        profile["skills"][skill_id] = settings
    else:
        profile["skills"].pop(skill_id, None)
    profile = validate_app_profile(profile)
    atomic_write_json(path, profile)
    return {"ok": True, "status": "updated", "path": str(path), "profile": profile}


def load_app_inputs(
    project: Path,
    profile_value: Any | None,
    run_config_value: Any | None,
    explicit_config_value: Any | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if profile_value is None:
        path = app_profile_path(project)
        profile_value = load_json(path) if path.is_file() else empty_app_profile()
    if run_config_value is None:
        run_config_value = empty_app_selection("ars.app-run-config/v1")
    if explicit_config_value is None:
        explicit_config_value = empty_app_selection("ars.app-explicit-config/v1")
    return (
        validate_app_profile(profile_value),
        validate_app_selection(
            run_config_value, "ars.app-run-config/v1", "App Run config"
        ),
        validate_app_selection(
            explicit_config_value,
            "ars.app-explicit-config/v1",
            "explicit App config",
        ),
    )


def scoped_settings(selection: dict[str, Any], task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        selection["tasks"].get(task["id"], {}),
        selection["providers"].get(task["provider"], {}),
        selection["default"],
    ]


def resolve_app_runtime(
    task: dict[str, Any],
    profile: dict[str, Any],
    run_config: dict[str, Any],
    explicit_config: dict[str, Any],
) -> dict[str, Any]:
    tiers = [
        ("explicit", scoped_settings(explicit_config, task)),
        ("repository", [profile["skills"].get(task["provider"], {})]),
        ("task", [run_config["tasks"].get(task["id"], {})]),
        ("provider", [run_config["providers"].get(task["provider"], {})]),
        ("run", [run_config["default"]]),
    ]
    resolved = {}
    for field in sorted(RUNTIME_FIELDS):
        fallback = "single" if field == "agent_mode" else "inherit"
        selection = {"value": fallback, "source": "agent"}
        for source, settings_list in tiers:
            matched = next(
                (settings[field] for settings in settings_list if field in settings),
                None,
            )
            if matched is not None:
                selection = {"value": matched, "source": source}
                break
        resolved[field] = selection
    return {
        "schema": "ars.app-runtime/v1",
        "kind": "codex.app/v1",
        "agent_mode": resolved["agent_mode"],
        "model": resolved["model"],
        "reasoning_effort": resolved["reasoning_effort"],
    }


def validate_app_runtime(value: Any, context: str) -> dict[str, Any]:
    runtime = object_value(value, context)
    exact(
        runtime,
        {"schema", "kind", "agent_mode", "model", "reasoning_effort"},
        context,
    )
    if runtime["schema"] != "ars.app-runtime/v1" or runtime["kind"] != "codex.app/v1":
        raise AdapterError(f"{context} is not a supported Codex App runtime")
    normalized = {"schema": runtime["schema"], "kind": runtime["kind"]}
    for field in sorted(RUNTIME_FIELDS):
        selection = object_value(runtime[field], f"{context}.{field}")
        exact(selection, {"value", "source"}, f"{context}.{field}")
        value = text_value(selection["value"], f"{context}.{field}.value")
        source = text_value(selection["source"], f"{context}.{field}.source")
        if source not in RUNTIME_SOURCES:
            raise AdapterError(f"{context}.{field}.source is invalid: {source}")
        if field == "agent_mode" and value not in AGENT_MODES:
            raise AdapterError(f"{context}.agent_mode.value is invalid: {value}")
        inherited = "single" if field == "agent_mode" else "inherit"
        if source == "agent" and value != inherited:
            raise AdapterError(
                f"{context}.{field}.value must be {inherited} when source is agent"
            )
        normalized[field] = {"value": value, "source": source}
    return normalized


def nullable_text_value(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return text_value(value, context)


def validate_app_host(value: Any, context: str = "App host") -> dict[str, Any]:
    host = object_value(value, context)
    exact(host, {"schema", "current_agent", "subagents"}, context)
    if host["schema"] != "ars.app-host/v1":
        raise AdapterError(f"{context}.schema must be 'ars.app-host/v1'")
    current = object_value(host["current_agent"], f"{context}.current_agent")
    exact(
        current,
        {"model", "reasoning_effort", "explicit_skills"},
        f"{context}.current_agent",
    )
    subagents = object_value(host["subagents"], f"{context}.subagents")
    exact(subagents, {"available", "models"}, f"{context}.subagents")
    if not isinstance(subagents["available"], bool):
        raise AdapterError(f"{context}.subagents.available must be a boolean")
    raw_models = subagents["models"]
    if not isinstance(raw_models, list):
        raise AdapterError(f"{context}.subagents.models must be a list")
    models = []
    seen = set()
    for index, raw_model in enumerate(raw_models):
        model_context = f"{context}.subagents.models[{index}]"
        model = object_value(raw_model, model_context)
        exact(model, {"id", "reasoning_efforts"}, model_context)
        model_id = text_value(model["id"], f"{model_context}.id")
        if model_id == "inherit":
            raise AdapterError(f"{model_context}.id cannot be inherit")
        if model_id in seen:
            raise AdapterError(f"{context}.subagents.models repeats '{model_id}'")
        seen.add(model_id)
        efforts = string_list(
            model["reasoning_efforts"], f"{model_context}.reasoning_efforts"
        )
        models.append({"id": model_id, "reasoning_efforts": efforts})
    explicit_skills = [
        identifier(skill, f"{context}.current_agent.explicit_skills[{index}]")
        for index, skill in enumerate(
            string_list(
                current["explicit_skills"],
                f"{context}.current_agent.explicit_skills",
            )
        )
    ]
    return {
        "schema": "ars.app-host/v1",
        "current_agent": {
            "model": nullable_text_value(
                current["model"], f"{context}.current_agent.model"
            ),
            "reasoning_effort": nullable_text_value(
                current["reasoning_effort"],
                f"{context}.current_agent.reasoning_effort",
            ),
            "explicit_skills": explicit_skills,
        },
        "subagents": {
            "available": subagents["available"],
            "models": models,
        },
    }


def executor_for(
    provider: dict[str, Any], runtime: dict[str, Any] | None = None
) -> dict[str, Any]:
    snapshot = {
        "schema": "ars.executor-snapshot/v1",
        "provider": {
            "id": provider["id"],
            "version": provider["version"],
            "capabilities": provider["capabilities"],
        },
    }
    if runtime is not None:
        snapshot = {
            **snapshot,
            "schema": "ars.executor-snapshot/v2",
            "runtime": validate_app_runtime(runtime, "runtime"),
        }
    digest = canonical_digest(snapshot)
    suffix = "" if runtime is None else f":{digest.removeprefix('sha256:')[:12]}"
    return {
        "id": f"ars:{provider['id']}:{provider['version'].replace('.', '-')}{suffix}",
        "kind": "ars",
        "snapshot": snapshot,
        "digest": digest,
    }


def noctis_task(
    task: dict[str, Any], workspaces: dict[str, dict[str, str]], executor_id: str
) -> dict[str, Any]:
    workspace = workspaces[task["workspace"]]
    return {
        "id": task["id"],
        "needs": task["needs"],
        "executor": executor_id,
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


def bind_app_executors(
    tasks: list[dict[str, Any]],
    providers: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    run_config: dict[str, Any],
    explicit_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    executors = {}
    bindings = {}
    for task in tasks:
        runtime = resolve_app_runtime(task, profile, run_config, explicit_config)
        executor = executor_for(providers[task["provider"]], runtime)
        executors[executor["id"]] = executor
        bindings[task["id"]] = executor["id"]
    return [executors[key] for key in sorted(executors)], bindings


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
    value: Any,
    project: Path,
    skill_roots: list[Path],
    profile_value: Any | None = None,
    run_config_value: Any | None = None,
    explicit_config_value: Any | None = None,
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
    profile, run_config, explicit_config = load_app_inputs(
        project, profile_value, run_config_value, explicit_config_value
    )
    executors, bindings = bind_app_executors(
        tasks, providers, profile, run_config, explicit_config
    )
    return {
        "schema": "noctis.plan/v1",
        "title": text_value(plan["title"], "plan.title"),
        "objective": text_value(plan["objective"], "plan.objective"),
        "executors": executors,
        "tasks": [noctis_task(task, workspaces, bindings[task["id"]]) for task in tasks],
    }


def adapt_extension(
    value: Any,
    project: Path,
    skill_roots: list[Path],
    profile_value: Any | None = None,
    run_config_value: Any | None = None,
    explicit_config_value: Any | None = None,
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
    profile, run_config, explicit_config = load_app_inputs(
        project, profile_value, run_config_value, explicit_config_value
    )
    executors, bindings = bind_app_executors(
        tasks, providers, profile, run_config, explicit_config
    )
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
        "executors": executors,
        "tasks": [noctis_task(task, workspaces, bindings[task["id"]]) for task in tasks],
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
    snapshot_schema = snapshot.get("schema")
    if snapshot_schema == "ars.executor-snapshot/v1":
        exact(snapshot, {"schema", "provider"}, "claim.executor.snapshot")
    elif snapshot_schema == "ars.executor-snapshot/v2":
        exact(snapshot, {"schema", "provider", "runtime"}, "claim.executor.snapshot")
        validate_app_runtime(snapshot["runtime"], "claim.executor.snapshot.runtime")
    else:
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


def claim_app_runtime(claim: dict[str, Any]) -> dict[str, Any]:
    snapshot = object_value(claim["executor"]["snapshot"], "claim.executor.snapshot")
    if snapshot["schema"] == "ars.executor-snapshot/v1":
        return validate_app_runtime(
            {
                "schema": "ars.app-runtime/v1",
                "kind": "codex.app/v1",
                "agent_mode": {"value": "single", "source": "agent"},
                "model": {"value": "inherit", "source": "agent"},
                "reasoning_effort": {"value": "inherit", "source": "agent"},
            },
            "legacy Claim runtime",
        )
    return validate_app_runtime(snapshot["runtime"], "claim.executor.snapshot.runtime")


def dispatch_blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def dispatch_claim(
    claim_value: Any, project: Path, host_value: Any
) -> dict[str, Any]:
    claim = object_value(claim_value, "claim")
    task = adapt_claim(claim, project)
    host = validate_app_host(host_value)
    runtime = claim_app_runtime(claim)
    mode = runtime["agent_mode"]["value"]
    model = runtime["model"]["value"]
    effort = runtime["reasoning_effort"]["value"]
    current = host["current_agent"]
    available_models = {
        item["id"]: set(item["reasoning_efforts"])
        for item in host["subagents"]["models"]
    }
    blockers = []
    spawn = None
    if mode == "single":
        if task["provider"]["id"] not in current["explicit_skills"]:
            blockers.append(
                dispatch_blocker(
                    "single-skill-not-explicit",
                    "single dispatch requires the provider Skill to be explicitly selected in the current App task",
                )
            )
        if model != "inherit" and current["model"] != model:
            code = (
                "current-agent-model-unknown"
                if current["model"] is None
                else "single-model-mismatch"
            )
            blockers.append(
                dispatch_blocker(
                    code,
                    "single dispatch requires the requested model to match the current Agent",
                )
            )
        if effort != "inherit" and current["reasoning_effort"] != effort:
            code = (
                "current-agent-reasoning-effort-unknown"
                if current["reasoning_effort"] is None
                else "single-reasoning-effort-mismatch"
            )
            blockers.append(
                dispatch_blocker(
                    code,
                    "single dispatch requires the requested reasoning effort to match the current Agent",
                )
            )
    else:
        if not host["subagents"]["available"]:
            blockers.append(
                dispatch_blocker(
                    "subagents-unavailable",
                    "multi dispatch requires Codex App subagent capability",
                )
            )
        target_model = current["model"] if model == "inherit" else model
        if model != "inherit" and model not in available_models:
            blockers.append(
                dispatch_blocker(
                    "model-unavailable",
                    f"subagent model is unavailable: {model}",
                )
            )
        if effort != "inherit":
            if target_model is None:
                blockers.append(
                    dispatch_blocker(
                        "inherited-model-unknown",
                        "a concrete reasoning effort with an inherited model requires the current model id",
                    )
                )
            elif model == "inherit" and target_model not in available_models:
                blockers.append(
                    dispatch_blocker(
                        "model-unavailable",
                        f"subagent model is unavailable: {target_model}",
                    )
                )
            elif target_model in available_models and effort not in available_models[target_model]:
                blockers.append(
                    dispatch_blocker(
                        "reasoning-effort-unavailable",
                        f"subagent model {target_model} does not support reasoning effort {effort}",
                    )
                )
        if not blockers:
            skill = task["provider"]["id"]
            message = (
                f"Use ${skill} to execute this exact ars.task/v1. "
                "Return only a valid ars.result/v1 JSON object.\n"
                + json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True)
            )
            spawn = {
                "fork_turns": "none",
                "message": message,
            }
            if model != "inherit":
                spawn["model"] = model
            if effort != "inherit":
                spawn["reasoning_effort"] = effort
    skill = task["provider"]["id"]
    return {
        "schema": "ars.app-dispatch/v1",
        "status": "blocked" if blockers else "ready",
        "mode": mode,
        "skill": skill,
        "invocation": f"${skill}",
        "executor": {
            "id": claim["executor"]["id"],
            "digest": claim["executor"]["digest"],
        },
        "runtime": runtime,
        "task": task,
        "spawn": spawn,
        "blockers": blockers,
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
    bindings = {
        task["id"]: executor_for(providers[task["provider"]])["id"]
        for task in tasks
    }
    return {
        "schema": "noctis.plan/v1",
        "title": text_value(plan["title"], "legacy plan.title"),
        "objective": text_value(plan["objective"], "legacy plan.objective"),
        "executors": [executor_for(providers[item]) for item in sorted(selected)],
        "tasks": [noctis_task(task, workspaces, bindings[task["id"]]) for task in tasks],
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
    plan.add_argument("--app-profile", type=Path)
    plan.add_argument("--run-config", type=Path)
    plan.add_argument("--explicit-config", type=Path)

    extension = commands.add_parser("extension-adapt")
    extension.add_argument("--project", type=Path, required=True)
    extension.add_argument("--extension", type=Path, required=True)
    extension.add_argument("--skills-root", type=Path, action="append", required=True)
    extension.add_argument("--app-profile", type=Path)
    extension.add_argument("--run-config", type=Path)
    extension.add_argument("--explicit-config", type=Path)

    profile_init = commands.add_parser("app-profile-init")
    profile_init.add_argument("--project", type=Path, required=True)
    profile_init.add_argument("--profile", type=Path)

    profile_show = commands.add_parser("app-profile-show")
    profile_show.add_argument("--project", type=Path, required=True)
    profile_show.add_argument("--profile", type=Path)

    profile_set = commands.add_parser("app-profile-set")
    profile_set.add_argument("--project", type=Path, required=True)
    profile_set.add_argument("--profile", type=Path)
    profile_set.add_argument("--skill", required=True)
    mode = profile_set.add_mutually_exclusive_group()
    mode.add_argument("--agent-mode", choices=sorted(AGENT_MODES))
    mode.add_argument("--clear-agent-mode", action="store_true")
    model = profile_set.add_mutually_exclusive_group()
    model.add_argument("--model")
    model.add_argument("--clear-model", action="store_true")
    effort = profile_set.add_mutually_exclusive_group()
    effort.add_argument("--reasoning-effort")
    effort.add_argument("--clear-reasoning-effort", action="store_true")

    claim = commands.add_parser("claim-adapt")
    claim.add_argument("--project", type=Path, required=True)
    claim.add_argument("--claim", type=Path, required=True)

    dispatch = commands.add_parser("claim-dispatch")
    dispatch.add_argument("--project", type=Path, required=True)
    dispatch.add_argument("--claim", type=Path, required=True)
    dispatch.add_argument("--host", type=Path, required=True)

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
        elif args.command == "app-profile-init":
            output = init_app_profile(args.project, args.profile)
        elif args.command == "app-profile-show":
            output = show_app_profile(args.project, args.profile)
        elif args.command == "app-profile-set":
            output = set_app_profile(
                args.project,
                args.skill,
                supplied_path=args.profile,
                agent_mode=args.agent_mode,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                clear_agent_mode=args.clear_agent_mode,
                clear_model=args.clear_model,
                clear_reasoning_effort=args.clear_reasoning_effort,
            )
        elif args.command == "plan-adapt":
            output = adapt_plan(
                load_json(args.plan),
                args.project,
                args.skills_root,
                load_json(args.app_profile) if args.app_profile is not None else None,
                load_json(args.run_config) if args.run_config is not None else None,
                load_json(args.explicit_config)
                if args.explicit_config is not None
                else None,
            )
        elif args.command == "extension-adapt":
            output = adapt_extension(
                load_json(args.extension),
                args.project,
                args.skills_root,
                load_json(args.app_profile) if args.app_profile is not None else None,
                load_json(args.run_config) if args.run_config is not None else None,
                load_json(args.explicit_config)
                if args.explicit_config is not None
                else None,
            )
        elif args.command == "claim-adapt":
            output = adapt_claim(load_json(args.claim), args.project)
        elif args.command == "claim-dispatch":
            output = dispatch_claim(
                load_json(args.claim), args.project, load_json(args.host)
            )
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
