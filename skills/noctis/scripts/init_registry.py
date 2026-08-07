#!/usr/bin/env python3
"""Validate and deterministically render a project Noctis registry."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from artifact_contract import ArtifactContractError, normalize_ports


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOP_LEVEL_KEYS = (
    "version",
    "default_workflow",
    "executors",
    "supports",
    "capabilities",
    "workflow_templates",
)


class RegistryError(ValueError):
    """Raised when normalized registry input violates the contract."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or compare Noctis/registry.yaml from normalized JSON."
    )
    parser.add_argument("--root", type=Path, required=True, help="Project root.")
    parser.add_argument(
        "--input", required=True, help="Normalized JSON file, or '-' for standard input."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--replace", action="store_true", help="Replace a different existing registry."
    )
    group.add_argument(
        "--dry-run", action="store_true", help="Write the candidate to standard output only."
    )
    return parser.parse_args()


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{context} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise RegistryError(f"{context} keys must be strings")
    return value


def _exact_keys(
    value: dict[str, Any], required: set[str], context: str
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    if missing:
        raise RegistryError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise RegistryError(f"{context} has unknown fields: {', '.join(unknown)}")


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise RegistryError(f"{context} must be a lowercase hyphenated identifier")
    return value


def _contract(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RegistryError(f"{context} must be a positive integer")
    return value


def _string_list(
    value: Any, context: str, *, required: bool = False
) -> list[str]:
    if not isinstance(value, list):
        raise RegistryError(f"{context} must be a list")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RegistryError(f"{context} items must be non-empty strings")
        normalized.append(item.strip())
    if required and not normalized:
        raise RegistryError(f"{context} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise RegistryError(f"{context} contains duplicates")
    return normalized


def _ports(value: Any, context: str) -> dict[str, Any]:
    try:
        return normalize_ports(value, context)
    except ArtifactContractError as error:
        raise RegistryError(str(error)) from error


def _source(value: Any, context: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise RegistryError(f"{context} must be '<task>.<output>'")
    parts = value.split(".")
    if len(parts) != 2:
        raise RegistryError(f"{context} must be '<task>.<output>'")
    return (
        _identifier(parts[0], f"{context} task"),
        _identifier(parts[1], f"{context} output"),
    )


def _sources(value: Any, context: str, cardinality: str) -> list[tuple[str, str]]:
    if cardinality == "one":
        return [_source(value, context)]
    if not isinstance(value, list) or not value:
        raise RegistryError(f"{context} must be a non-empty list of Task outputs")
    result = [
        _source(source, f"{context}[{index}]")
        for index, source in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise RegistryError(f"{context} contains duplicate Task outputs")
    return result


def _validate_dag(items: dict[str, list[str]], context: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise RegistryError(f"{context} contains a dependency cycle at '{item_id}'")
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in items[item_id]:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in items:
        visit(item_id)


def validate_registry(value: Any) -> dict[str, Any]:
    registry = _mapping(value, "registry")
    _exact_keys(registry, set(TOP_LEVEL_KEYS), "registry")
    if isinstance(registry["version"], bool) or registry["version"] != 3:
        raise RegistryError("registry.version must be 3")

    default_workflow = _identifier(
        registry["default_workflow"], "default_workflow"
    )
    executors = _mapping(registry["executors"], "executors")
    supports = _mapping(registry["supports"], "supports")
    capabilities = _mapping(registry["capabilities"], "capabilities")
    workflows = _mapping(registry["workflow_templates"], "workflow_templates")
    if not executors or not capabilities or not workflows:
        raise RegistryError(
            "executors, capabilities, and workflow_templates must not be empty"
        )

    for executor_id, raw in executors.items():
        _identifier(executor_id, "executor id")
        spec = _mapping(raw, f"executors.{executor_id}")
        _exact_keys(spec, {"provider", "source"}, f"executors.{executor_id}")
        _identifier(spec["provider"], f"executors.{executor_id}.provider")
        if spec["source"] not in ("manifest", "manual"):
            raise RegistryError(
                f"executors.{executor_id}.source must be 'manifest' or 'manual'"
            )

    for support_id, raw in supports.items():
        _identifier(support_id, "support id")
        spec = _mapping(raw, f"supports.{support_id}")
        _exact_keys(
            spec, {"contract", "provider", "source"}, f"supports.{support_id}"
        )
        _contract(spec["contract"], f"supports.{support_id}.contract")
        _identifier(spec["provider"], f"supports.{support_id}.provider")
        if spec["source"] not in ("manifest", "manual"):
            raise RegistryError(
                f"supports.{support_id}.source must be 'manifest' or 'manual'"
            )

    for capability_id, raw in capabilities.items():
        _identifier(capability_id, "capability id")
        spec = _mapping(raw, f"capabilities.{capability_id}")
        _exact_keys(
            spec,
            {
                "contract",
                "executor",
                "supports",
                "inputs",
                "outputs",
                "side_effects",
            },
            f"capabilities.{capability_id}",
        )
        _contract(spec["contract"], f"capabilities.{capability_id}.contract")
        executor = _identifier(
            spec["executor"], f"capabilities.{capability_id}.executor"
        )
        if executor not in executors:
            raise RegistryError(
                f"capabilities.{capability_id}.executor references unknown "
                f"executor '{executor}'"
            )
        bindings = _mapping(
            spec["supports"], f"capabilities.{capability_id}.supports"
        )
        for support_id, activation in bindings.items():
            _identifier(support_id, f"capabilities.{capability_id} support id")
            if support_id not in supports:
                raise RegistryError(
                    f"capabilities.{capability_id}.supports references unknown "
                    f"support '{support_id}'"
                )
            if activation not in ("before", "on-request"):
                raise RegistryError(
                    f"capabilities.{capability_id}.supports.{support_id} has "
                    "invalid activation"
                )
        _ports(spec["inputs"], f"capabilities.{capability_id}.inputs")
        _ports(spec["outputs"], f"capabilities.{capability_id}.outputs")
        side_effects = _string_list(
            spec["side_effects"],
            f"capabilities.{capability_id}.side_effects",
        )
        for side_effect in side_effects:
            _identifier(
                side_effect,
                f"capabilities.{capability_id}.side_effects item",
            )

    for workflow_id, raw in workflows.items():
        _identifier(workflow_id, "workflow template id")
        spec = _mapping(raw, f"workflow_templates.{workflow_id}")
        _exact_keys(
            spec,
            {"description", "tasks"},
            f"workflow_templates.{workflow_id}",
        )
        if not isinstance(spec["description"], str) or not spec["description"].strip():
            raise RegistryError(
                f"workflow_templates.{workflow_id}.description must not be empty"
            )
        tasks = _mapping(spec["tasks"], f"workflow_templates.{workflow_id}.tasks")
        if not tasks:
            raise RegistryError(
                f"workflow_templates.{workflow_id}.tasks must not be empty"
            )
        dependencies: dict[str, list[str]] = {}
        task_capabilities: dict[str, str] = {}
        task_inputs: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for task_id, raw_task in tasks.items():
            _identifier(task_id, f"workflow_templates.{workflow_id} task id")
            task = _mapping(
                raw_task, f"workflow_templates.{workflow_id}.tasks.{task_id}"
            )
            _exact_keys(
                task,
                {"capability", "depends_on", "inputs"},
                f"workflow_templates.{workflow_id}.tasks.{task_id}",
            )
            capability = _identifier(
                task["capability"],
                f"workflow_templates.{workflow_id}.tasks.{task_id}.capability",
            )
            if capability in ("fix-review", "fix-verification"):
                raise RegistryError(
                    f"{capability} is a recovery capability and cannot appear "
                    "in a workflow template"
                )
            if capability not in capabilities:
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id} references "
                    f"unknown capability '{capability}'"
                )
            depends_on = task["depends_on"]
            if not isinstance(depends_on, list):
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.depends_on "
                    "must be a list"
                )
            normalized = [
                _identifier(
                    dependency,
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.depends_on item",
                )
                for dependency in depends_on
            ]
            if len(normalized) != len(set(normalized)):
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.depends_on "
                    "contains duplicates"
                )
            dependencies[task_id] = normalized
            task_capabilities[task_id] = capability
            inputs = _mapping(
                task["inputs"],
                f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs",
            )
            capability_inputs = _mapping(
                capabilities[capability]["inputs"],
                f"capabilities.{capability}.inputs",
            )
            unknown_inputs = sorted(set(inputs) - set(capability_inputs))
            if unknown_inputs:
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs "
                    "references unknown capability inputs: "
                    + ", ".join(unknown_inputs)
                )
            missing_inputs = sorted(
                input_id
                for input_id, port in capability_inputs.items()
                if port["required"] and input_id not in inputs
            )
            if missing_inputs:
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs "
                    "is missing required inputs: " + ", ".join(missing_inputs)
                )
            task_inputs[task_id] = {}
            for input_id, source in inputs.items():
                cardinality = capability_inputs[input_id].get("cardinality", "one")
                task_inputs[task_id][input_id] = _sources(
                    source,
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs.{input_id}",
                    cardinality,
                )
        for task_id, depends_on in dependencies.items():
            unknown = sorted(set(depends_on) - set(tasks))
            if unknown:
                raise RegistryError(
                    f"workflow_templates.{workflow_id}.tasks.{task_id}.depends_on "
                    "references unknown tasks: " + ", ".join(unknown)
                )
        _validate_dag(dependencies, f"workflow_templates.{workflow_id}.tasks")
        for task_id, inputs in task_inputs.items():
            capability = task_capabilities[task_id]
            target_ports = capabilities[capability]["inputs"]
            for input_id, sources in inputs.items():
                for source_task, source_output in sources:
                    source = f"{source_task}.{source_output}"
                    if source_task not in tasks:
                        raise RegistryError(
                            f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs."
                            f"{input_id} references unknown task '{source_task}'"
                        )
                    if source_task not in dependencies[task_id]:
                        raise RegistryError(
                            f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs."
                            f"{input_id} must reference a direct dependency"
                        )
                    source_capability = task_capabilities[source_task]
                    source_ports = capabilities[source_capability]["outputs"]
                    if source_output not in source_ports:
                        raise RegistryError(
                            f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs."
                            f"{input_id} references unknown output '{source}'"
                        )
                    target = target_ports[input_id]
                    producer = source_ports[source_output]
                    if target["type"] != producer["type"]:
                        raise RegistryError(
                            f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs."
                            f"{input_id} has incompatible artifact types"
                        )
                    if not set(target["formats"]) & set(producer["formats"]):
                        raise RegistryError(
                            f"workflow_templates.{workflow_id}.tasks.{task_id}.inputs."
                            f"{input_id} requires an explicit adapter task"
                        )

    if default_workflow not in workflows:
        raise RegistryError(
            f"default_workflow references unknown workflow template "
            f"'{default_workflow}'"
        )
    return registry


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_registry(registry: dict[str, Any]) -> str:
    registry = validate_registry(registry)
    lines = [
        f"version: {registry['version']}",
        f"default_workflow: {_quoted(registry['default_workflow'])}",
        "executors:",
    ]
    for executor_id in sorted(registry["executors"]):
        spec = registry["executors"][executor_id]
        lines.extend(
            [
                f"  {executor_id}:",
                f"    provider: {_quoted(spec['provider'])}",
                f"    source: {_quoted(spec['source'])}",
            ]
        )

    supports = registry["supports"]
    if not supports:
        lines.append("supports: {}")
    else:
        lines.append("supports:")
        for support_id in sorted(supports):
            spec = supports[support_id]
            lines.extend(
                [
                    f"  {support_id}:",
                    f"    contract: {spec['contract']}",
                    f"    provider: {_quoted(spec['provider'])}",
                    f"    source: {_quoted(spec['source'])}",
                ]
            )

    lines.append("capabilities:")
    for capability_id in sorted(registry["capabilities"]):
        spec = registry["capabilities"][capability_id]
        lines.extend(
            [
                f"  {capability_id}:",
                f"    contract: {spec['contract']}",
                f"    executor: {_quoted(spec['executor'])}",
            ]
        )
        bindings = spec["supports"]
        if not bindings:
            lines.append("    supports: {}")
        else:
            lines.append("    supports:")
            for support_id in sorted(bindings):
                lines.append(
                    f"      {support_id}: {_quoted(bindings[support_id])}"
                )
        for ports_key in ("inputs", "outputs"):
            ports = spec[ports_key]
            if not ports:
                lines.append(f"    {ports_key}: {{}}")
                continue
            lines.append(f"    {ports_key}:")
            for port_id in sorted(ports):
                port = ports[port_id]
                lines.extend(
                    [
                        f"      {port_id}:",
                        f"        type: {_quoted(port['type'])}",
                        "        formats:",
                        *(
                            f"          - {_quoted(artifact_format)}"
                            for artifact_format in port["formats"]
                        ),
                        "        required: "
                        + ("true" if port["required"] else "false"),
                    ]
                )
                if port.get("cardinality") == "many":
                    lines.append('        cardinality: "many"')
        side_effects = spec["side_effects"]
        if not side_effects:
            lines.append("    side_effects: []")
        else:
            lines.append("    side_effects:")
            lines.extend(
                f"      - {_quoted(side_effect)}" for side_effect in side_effects
            )

    lines.append("workflow_templates:")
    for workflow_id in sorted(registry["workflow_templates"]):
        spec = registry["workflow_templates"][workflow_id]
        lines.extend(
            [
                f"  {workflow_id}:",
                f"    description: {_quoted(spec['description'])}",
                "    tasks:",
            ]
        )
        for task_id in sorted(spec["tasks"]):
            task = spec["tasks"][task_id]
            lines.extend(
                [
                    f"      {task_id}:",
                    f"        capability: {_quoted(task['capability'])}",
                ]
            )
            if task["depends_on"]:
                lines.append("        depends_on:")
                lines.extend(
                    f"          - {_quoted(dependency)}"
                    for dependency in task["depends_on"]
                )
            else:
                lines.append("        depends_on: []")
            inputs = task["inputs"]
            if not inputs:
                lines.append("        inputs: {}")
            else:
                lines.append("        inputs:")
                for input_id in sorted(inputs):
                    source = inputs[input_id]
                    if isinstance(source, list):
                        lines.append(f"          {input_id}:")
                        lines.extend(
                            f"            - {_quoted(item)}" for item in source
                        )
                    else:
                        lines.append(f"          {input_id}: {_quoted(source)}")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_input(source: str) -> Any:
    if source == "-":
        return json.load(sys.stdin)
    with Path(source).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def install_registry(
    root: Path, registry: dict[str, Any], *, replace: bool = False
) -> tuple[str, Path, str | None]:
    root = root.resolve()
    if not root.is_dir():
        raise RegistryError(f"project root does not exist: {root}")
    candidate = render_registry(registry)
    target = root / "Noctis" / "registry.yaml"
    if not target.exists():
        _atomic_write(target, candidate)
        return "created", target, None

    current = target.read_text(encoding="utf-8-sig")
    if current == candidate:
        return "unchanged", target, None
    diff = "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=str(target),
            tofile="candidate",
        )
    )
    if not replace:
        return "different", target, diff
    _atomic_write(target, candidate)
    return "replaced", target, diff


def main() -> int:
    args = parse_args()
    try:
        registry = validate_registry(load_input(args.input))
        candidate = render_registry(registry)
        if args.dry_run:
            sys.stdout.write(candidate)
            return 0
        status, target, diff = install_registry(
            args.root, registry, replace=args.replace
        )
    except (OSError, json.JSONDecodeError, RegistryError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"ok": status != "different", "status": status, "path": str(target)},
            ensure_ascii=False,
        )
    )
    if diff:
        sys.stdout.write(diff)
    return 2 if status == "different" else 0


if __name__ == "__main__":
    raise SystemExit(main())
