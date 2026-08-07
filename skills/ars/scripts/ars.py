#!/usr/bin/env python3
"""Inspect, create, and validate lightweight Ars capability manifests."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SKILL_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
CONTRACT_ID = re.compile(r"^[a-z][a-z0-9.-]*/v[1-9][0-9]*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
EFFECTS = {
    "command.execute",
    "deployment",
    "destructive",
    "git.commit",
    "git.push",
    "network.write",
    "workspace.write",
}


class ArsError(ValueError):
    """Raised when an Ars package violates its public contract."""


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ArsError(f"{context} must be an object with string keys")
    return value


def _exact(value: dict[str, Any], fields: set[str], context: str) -> None:
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing:
        raise ArsError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise ArsError(f"{context} has unknown fields: {', '.join(unknown)}")


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArsError(f"{context} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, pattern: re.Pattern[str], context: str) -> str:
    result = _text(value, context)
    if not pattern.fullmatch(result):
        raise ArsError(f"{context} has an invalid identifier: {result}")
    return result


def validate_manifest(value: Any) -> dict[str, Any]:
    manifest = _object(value, "manifest")
    _exact(manifest, {"schema", "id", "version", "capabilities"}, "manifest")
    if manifest["schema"] != "ars.skill/v1":
        raise ArsError("manifest.schema must be 'ars.skill/v1'")
    skill_id = _identifier(manifest["id"], SKILL_ID, "manifest.id")
    version = _text(manifest["version"], "manifest.version")
    if not SEMVER.fullmatch(version):
        raise ArsError("manifest.version must be a stable MAJOR.MINOR.PATCH version")

    raw_capabilities = manifest["capabilities"]
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise ArsError("manifest.capabilities must be a non-empty list")
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_capabilities):
        context = f"manifest.capabilities[{index}]"
        capability = _object(item, context)
        _exact(
            capability,
            {"id", "description", "accepts", "returns", "effects"},
            context,
        )
        capability_id = _identifier(capability["id"], CAPABILITY_ID, f"{context}.id")
        if capability_id in seen:
            raise ArsError(f"manifest repeats capability '{capability_id}'")
        seen.add(capability_id)
        accepts = _identifier(capability["accepts"], CONTRACT_ID, f"{context}.accepts")
        returns = _identifier(capability["returns"], CONTRACT_ID, f"{context}.returns")
        if accepts != "ars.task/v1" or returns != "ars.result/v1":
            raise ArsError(
                f"{context} must accept ars.task/v1 and return ars.result/v1"
            )
        raw_effects = capability["effects"]
        if not isinstance(raw_effects, list) or any(
            not isinstance(effect, str) for effect in raw_effects
        ):
            raise ArsError(f"{context}.effects must be a list of strings")
        effects = sorted(set(raw_effects))
        unknown_effects = sorted(set(effects) - EFFECTS)
        if unknown_effects:
            raise ArsError(
                f"{context}.effects contains unknown values: {', '.join(unknown_effects)}"
            )
        if len(effects) != len(raw_effects):
            raise ArsError(f"{context}.effects contains duplicates")
        capabilities.append(
            {
                "id": capability_id,
                "description": _text(capability["description"], f"{context}.description"),
                "accepts": accepts,
                "returns": returns,
                "effects": effects,
            }
        )
    return {
        "schema": "ars.skill/v1",
        "id": skill_id,
        "version": version,
        "capabilities": sorted(capabilities, key=lambda item: item["id"]),
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ArsError(f"invalid JSON in {path}: {error}") from error
    return validate_manifest(value)


def _frontmatter(skill_file: Path) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ArsError("SKILL.md is missing YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ArsError("SKILL.md frontmatter is not terminated") from error
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        if line.startswith((" ", "\t")) or not line.strip():
            continue
        key, separator, raw = line.partition(":")
        if not separator or not key or key != key.strip():
            continue
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        metadata[key] = value
    if not metadata.get("name"):
        raise ArsError("SKILL.md frontmatter must contain a scalar name")
    if "description" not in metadata:
        raise ArsError("SKILL.md frontmatter must contain description")
    return {"name": metadata["name"], "description": metadata["description"]}


def validate_skill(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ArsError(f"Skill directory does not exist: {root}")
    skill_file = root / "SKILL.md"
    manifest_file = root / "ars.json"
    if not skill_file.is_file():
        raise ArsError(f"Skill is missing SKILL.md: {root}")
    if not manifest_file.is_file():
        raise ArsError(f"Skill is missing ars.json: {root}")
    metadata = _frontmatter(skill_file)
    manifest = load_manifest(manifest_file)
    if metadata["name"] != root.name or manifest["id"] != root.name:
        raise ArsError("directory, SKILL.md name, and manifest.id must match")
    return manifest


def inspect_skill(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ArsError(f"Skill directory does not exist: {root}")
    if not (root / "SKILL.md").is_file():
        raise ArsError(f"directory is not an Agent Skill: {root}")
    metadata = _frontmatter(root / "SKILL.md")
    if metadata["name"] != root.name:
        raise ArsError("directory and SKILL.md name must match")
    if not (root / "ars.json").is_file():
        return {"ok": True, "status": "standard", "path": str(root)}
    manifest = validate_skill(root)
    return {
        "ok": True,
        "status": "native",
        "path": str(root),
        "id": manifest["id"],
        "version": manifest["version"],
        "capabilities": [item["id"] for item in manifest["capabilities"]],
    }


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "validate"):
        command = actions.add_parser(action)
        command.add_argument("--skill", type=Path, required=True)
    create = actions.add_parser("create")
    create.add_argument("--skill", type=Path, required=True)
    create.add_argument("--input", type=Path, required=True)
    create.add_argument("--replace", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.action == "inspect":
            result = inspect_skill(args.skill)
        elif args.action == "validate":
            manifest = validate_skill(args.skill)
            result = {
                "ok": True,
                "status": "valid",
                "path": str(args.skill.resolve()),
                "id": manifest["id"],
                "version": manifest["version"],
            }
        else:
            root = args.skill.resolve()
            if not root.is_dir():
                raise ArsError(f"Skill directory does not exist: {root}")
            metadata = _frontmatter(root / "SKILL.md")
            manifest = load_manifest(args.input)
            if metadata["name"] != root.name or manifest["id"] != root.name:
                raise ArsError("directory, SKILL.md name, and manifest.id must match")
            content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            target = root / "ars.json"
            if args.dry_run:
                sys.stdout.write(content)
                return 0
            if target.exists() and target.read_text(encoding="utf-8-sig") != content:
                if not args.replace:
                    raise ArsError(f"{target} exists with different content; use --replace")
                status = "replaced"
            elif target.exists():
                status = "unchanged"
            else:
                status = "created"
            if status != "unchanged":
                _atomic_write(target, content)
            result = {"ok": True, "status": status, "path": str(target)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ArsError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
