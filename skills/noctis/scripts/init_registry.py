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


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TOP_LEVEL_KEYS = (
    "version",
    "default_preset",
    "executors",
    "supports",
    "stages",
    "presets",
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


def validate_registry(value: Any) -> dict[str, Any]:
    registry = _mapping(value, "registry")
    _exact_keys(registry, set(TOP_LEVEL_KEYS), "registry")
    if isinstance(registry["version"], bool) or registry["version"] != 1:
        raise RegistryError("registry.version must be 1")

    default_preset = _identifier(registry["default_preset"], "default_preset")
    executors = _mapping(registry["executors"], "executors")
    supports = _mapping(registry["supports"], "supports")
    stages = _mapping(registry["stages"], "stages")
    presets = _mapping(registry["presets"], "presets")
    if not executors or not stages or not presets:
        raise RegistryError("executors, stages, and presets must not be empty")

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

    for stage_id, raw in stages.items():
        _identifier(stage_id, "stage id")
        spec = _mapping(raw, f"stages.{stage_id}")
        _exact_keys(
            spec, {"contract", "executor", "supports"}, f"stages.{stage_id}"
        )
        _contract(spec["contract"], f"stages.{stage_id}.contract")
        executor = _identifier(spec["executor"], f"stages.{stage_id}.executor")
        if executor not in executors:
            raise RegistryError(
                f"stages.{stage_id}.executor references unknown executor '{executor}'"
            )
        bindings = _mapping(spec["supports"], f"stages.{stage_id}.supports")
        for support_id, activation in bindings.items():
            _identifier(support_id, f"stages.{stage_id} support id")
            if support_id not in supports:
                raise RegistryError(
                    f"stages.{stage_id}.supports references unknown support '{support_id}'"
                )
            if activation not in ("before", "on-request"):
                raise RegistryError(
                    f"stages.{stage_id}.supports.{support_id} has invalid activation"
                )

    for preset_id, raw in presets.items():
        _identifier(preset_id, "preset id")
        spec = _mapping(raw, f"presets.{preset_id}")
        _exact_keys(spec, {"description", "workflow"}, f"presets.{preset_id}")
        if not isinstance(spec["description"], str) or not spec["description"].strip():
            raise RegistryError(f"presets.{preset_id}.description must not be empty")
        workflow = spec["workflow"]
        if not isinstance(workflow, list) or not workflow:
            raise RegistryError(f"presets.{preset_id}.workflow must not be empty")
        normalized = [
            _identifier(item, f"presets.{preset_id}.workflow item")
            for item in workflow
        ]
        if len(normalized) != len(set(normalized)):
            raise RegistryError(f"presets.{preset_id}.workflow contains duplicates")
        if "fix" in normalized:
            raise RegistryError("fix is a recovery stage and cannot appear in a preset")
        unknown = [stage for stage in normalized if stage not in stages]
        if unknown:
            raise RegistryError(
                f"presets.{preset_id}.workflow references unknown stages: "
                + ", ".join(unknown)
            )

    if default_preset not in presets:
        raise RegistryError(
            f"default_preset references unknown preset '{default_preset}'"
        )
    return registry


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_registry(registry: dict[str, Any]) -> str:
    registry = validate_registry(registry)
    lines = [
        f"version: {registry['version']}",
        f"default_preset: {_quoted(registry['default_preset'])}",
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

    lines.append("stages:")
    for stage_id in sorted(registry["stages"]):
        spec = registry["stages"][stage_id]
        lines.extend(
            [
                f"  {stage_id}:",
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

    lines.append("presets:")
    for preset_id in sorted(registry["presets"]):
        spec = registry["presets"][preset_id]
        lines.extend(
            [
                f"  {preset_id}:",
                f"    description: {_quoted(spec['description'])}",
                "    workflow:",
            ]
        )
        lines.extend(f"      - {_quoted(stage)}" for stage in spec["workflow"])
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
