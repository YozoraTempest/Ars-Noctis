#!/usr/bin/env python3
"""Create, inspect, and validate Noctis-native Ars manifests."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ARTIFACT_FORMAT = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+)*@[1-9][0-9]*$"
)
SLOT = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
ROLES = ("executor", "support")
STATE_MODES = ("stateless", "documents", "external")
ACTIVATIONS = ("before", "on-request")


class ArsError(ValueError):
    """Raised when an Ars directory or manifest violates the native contract."""


def _mapping(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArsError(f"{context} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ArsError(f"{context} keys must be strings")
    return value


def _exact(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise ArsError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise ArsError(f"{context} has unknown fields: {', '.join(unknown)}")


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ArsError(f"{context} must be a lowercase hyphenated identifier")
    return value


def _contract(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ArsError(f"{context} must be a positive integer")
    return value


def _strings(
    value: Any, context: str, *, required: bool = False
) -> list[str]:
    if not isinstance(value, list):
        raise ArsError(f"{context} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ArsError(f"{context} items must be non-empty strings")
        result.append(item.strip())
    if required and not result:
        raise ArsError(f"{context} must not be empty")
    if len(result) != len(set(result)):
        raise ArsError(f"{context} contains duplicates")
    return result


def _relative(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArsError(f"{context} must be a non-empty relative POSIX path")
    value = value.strip()
    if "\\" in value or ":" in value:
        raise ArsError(f"{context} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise ArsError(f"{context} must stay inside the Ars directory")
    return path.as_posix()


def _resource(
    root: Path | None, value: Any, context: str, *, must_exist: bool
) -> str:
    relative = _relative(value, context)
    if root is not None and must_exist:
        candidate = root.joinpath(*PurePosixPath(relative).parts).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as error:
            raise ArsError(f"{context} escapes the Ars directory") from error
        if not candidate.is_file():
            raise ArsError(f"{context} does not exist: {relative}")
    return relative


def _ports(value: Any, context: str) -> dict[str, Any]:
    ports = _mapping(value, context)
    normalized: dict[str, Any] = {}
    for port_id in sorted(ports):
        _identifier(port_id, f"{context} port id")
        raw = _mapping(ports[port_id], f"{context}.{port_id}")
        _exact(raw, {"type", "formats", "required"}, f"{context}.{port_id}")
        formats = sorted(
            _strings(
                raw["formats"], f"{context}.{port_id}.formats", required=True
            )
        )
        for artifact_format in formats:
            if not ARTIFACT_FORMAT.fullmatch(artifact_format):
                raise ArsError(
                    f"{context}.{port_id}.formats contains invalid format "
                    f"'{artifact_format}'"
                )
        required = raw["required"]
        if not isinstance(required, bool):
            raise ArsError(f"{context}.{port_id}.required must be a boolean")
        normalized[port_id] = {
            "type": _identifier(raw["type"], f"{context}.{port_id}.type"),
            "formats": formats,
            "required": required,
        }
    return normalized


def _capabilities(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArsError("manifest.capabilities must be a list")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        context = f"manifest.capabilities[{index}]"
        raw = _mapping(item, context)
        _exact(
            raw,
            {"id", "contract", "inputs", "outputs", "side_effects"},
            context,
        )
        capability_id = _identifier(raw["id"], f"{context}.id")
        if capability_id in identifiers:
            raise ArsError(f"manifest.capabilities repeats '{capability_id}'")
        identifiers.add(capability_id)
        effects = sorted(_strings(raw["side_effects"], f"{context}.side_effects"))
        for effect in effects:
            _identifier(effect, f"{context}.side_effects item")
        normalized.append(
            {
                "id": capability_id,
                "contract": _contract(raw["contract"], f"{context}.contract"),
                "inputs": _ports(raw["inputs"], f"{context}.inputs"),
                "outputs": _ports(raw["outputs"], f"{context}.outputs"),
                "side_effects": effects,
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _supports(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArsError("manifest.supports must be a list")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        context = f"manifest.supports[{index}]"
        raw = _mapping(item, context)
        _exact(
            raw,
            {"id", "contract", "activation", "side_effects"},
            context,
        )
        support_id = _identifier(raw["id"], f"{context}.id")
        if support_id in identifiers:
            raise ArsError(f"manifest.supports repeats '{support_id}'")
        identifiers.add(support_id)
        activation = _strings(
            raw["activation"], f"{context}.activation", required=True
        )
        invalid = sorted(set(activation) - set(ACTIVATIONS))
        if invalid:
            raise ArsError(
                f"{context}.activation contains invalid values: "
                + ", ".join(invalid)
            )
        effects = sorted(_strings(raw["side_effects"], f"{context}.side_effects"))
        for effect in effects:
            _identifier(effect, f"{context}.side_effects item")
        normalized.append(
            {
                "id": support_id,
                "contract": _contract(raw["contract"], f"{context}.contract"),
                "activation": [item for item in ACTIVATIONS if item in activation],
                "side_effects": effects,
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _documents(
    value: Any, root: Path | None, *, must_exist: bool
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArsError("manifest.documents must be a list")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        context = f"manifest.documents[{index}]"
        raw = _mapping(item, context)
        _exact(raw, {"id", "contract", "file", "template", "tool"}, context)
        document_id = _identifier(raw["id"], f"{context}.id")
        if document_id in identifiers:
            raise ArsError(f"manifest.documents repeats '{document_id}'")
        identifiers.add(document_id)
        normalized.append(
            {
                "id": document_id,
                "contract": _contract(raw["contract"], f"{context}.contract"),
                "file": _relative(raw["file"], f"{context}.file"),
                "template": _resource(
                    root, raw["template"], f"{context}.template", must_exist=must_exist
                ),
                "tool": _resource(
                    root, raw["tool"], f"{context}.tool", must_exist=must_exist
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def _augmentations(
    value: Any,
    root: Path | None,
    documents: set[str],
    *,
    must_exist: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ArsError("manifest.augmentations must be a list")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, item in enumerate(value):
        context = f"manifest.augmentations[{index}]"
        raw = _mapping(item, context)
        _exact(raw, {"id", "target", "slot", "scope", "template"}, context)
        augmentation_id = _identifier(raw["id"], f"{context}.id")
        if augmentation_id in identifiers:
            raise ArsError(f"manifest.augmentations repeats '{augmentation_id}'")
        identifiers.add(augmentation_id)
        target = _identifier(raw["target"], f"{context}.target")
        if target not in documents:
            raise ArsError(f"{context}.target references unknown document '{target}'")
        scope = raw["scope"]
        if scope not in ("once", "each"):
            raise ArsError(f"{context}.scope must be 'once' or 'each'")
        slot = raw["slot"]
        if not isinstance(slot, str) or not SLOT.fullmatch(slot):
            raise ArsError(f"{context}.slot must be a stable dotted identifier")
        normalized.append(
            {
                "id": augmentation_id,
                "target": target,
                "slot": slot,
                "scope": scope,
                "template": _resource(
                    root, raw["template"], f"{context}.template", must_exist=must_exist
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["id"])


def validate_manifest(
    value: Any,
    *,
    root: Path | None = None,
    must_exist: bool = False,
) -> dict[str, Any]:
    manifest = _mapping(value, "manifest")
    _exact(
        manifest,
        {
            "version",
            "kind",
            "name",
            "role",
            "state",
            "capabilities",
            "supports",
            "documents",
            "augmentations",
        },
        "manifest",
    )
    if isinstance(manifest["version"], bool) or manifest["version"] != 1:
        raise ArsError("manifest.version must be 1")
    if manifest["kind"] != "ars":
        raise ArsError("manifest.kind must be 'ars'")
    name = _identifier(manifest["name"], "manifest.name")
    role = manifest["role"]
    if role not in ROLES:
        raise ArsError("manifest.role must be 'executor' or 'support'")
    state = _mapping(manifest["state"], "manifest.state")
    _exact(state, {"mode"}, "manifest.state")
    mode = state["mode"]
    if mode not in STATE_MODES:
        raise ArsError(
            "manifest.state.mode must be stateless, documents, or external"
        )

    capabilities = _capabilities(manifest["capabilities"])
    supports = _supports(manifest["supports"])
    documents = _documents(manifest["documents"], root, must_exist=must_exist)
    document_ids = {item["id"] for item in documents}
    augmentations = _augmentations(
        manifest["augmentations"],
        root,
        document_ids,
        must_exist=must_exist,
    )
    if role == "executor" and (not capabilities or supports):
        raise ArsError("executor Ars requires capabilities and forbids supports")
    if role == "support" and (not supports or capabilities):
        raise ArsError("support Ars requires supports and forbids capabilities")
    if mode == "documents" and not documents:
        raise ArsError("documents state requires at least one document")
    if mode != "documents" and (documents or augmentations):
        raise ArsError(f"{mode} state cannot declare documents or augmentations")

    return {
        "version": 1,
        "kind": "ars",
        "name": name,
        "role": role,
        "state": {"mode": mode},
        "capabilities": capabilities,
        "supports": supports,
        "documents": documents,
        "augmentations": augmentations,
    }


def _skill_metadata(root: Path) -> dict[str, Any]:
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        raise ArsError(f"Skill is missing SKILL.md: {root}")
    text = skill_file.read_text(encoding="utf-8-sig")
    if not text.startswith("---\n"):
        raise ArsError("SKILL.md is missing YAML frontmatter")
    marker = text.find("\n---", 4)
    if marker < 0:
        raise ArsError("SKILL.md frontmatter is not terminated")
    metadata = _mapping(yaml.safe_load(text[4:marker]) or {}, "SKILL.md frontmatter")
    _exact(metadata, {"name", "description"}, "SKILL.md frontmatter")
    _identifier(metadata["name"], "SKILL.md name")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        raise ArsError("SKILL.md description must not be empty")
    return metadata


def validate_skill(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ArsError(f"Skill directory does not exist: {root}")
    metadata = _skill_metadata(root)
    manifest_path = root / "ars.yaml"
    if not manifest_path.is_file():
        raise ArsError(f"Skill is missing ars.yaml: {root}")
    manifest = validate_manifest(
        yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig")),
        root=root,
        must_exist=True,
    )
    if metadata["name"] != root.name or manifest["name"] != root.name:
        raise ArsError("directory, SKILL.md name, and manifest.name must match")
    return manifest


def render_manifest(value: Any, *, root: Path | None = None) -> str:
    manifest = validate_manifest(value, root=root, must_exist=root is not None)
    return yaml.safe_dump(
        manifest,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _load_json(source: str) -> Any:
    if source == "-":
        return json.load(sys.stdin)
    with Path(source).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


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


def inspect_skill(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ArsError(f"Skill directory does not exist: {root}")
    if (root / "ars.yaml").is_file():
        try:
            manifest = validate_skill(root)
        except (ArsError, OSError, yaml.YAMLError) as error:
            return {"ok": False, "status": "invalid", "path": str(root), "error": str(error)}
        identifiers = (
            [item["id"] for item in manifest["capabilities"]]
            if manifest["role"] == "executor"
            else [item["id"] for item in manifest["supports"]]
        )
        return {
            "ok": True,
            "status": "native",
            "path": str(root),
            "name": manifest["name"],
            "role": manifest["role"],
            "state": manifest["state"]["mode"],
            "provides": identifiers,
        }
    status = "legacy" if (root / "noctis.yaml").is_file() else "external"
    return {"ok": True, "status": status, "path": str(root)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, inspect, and validate Noctis-native Ars Skills."
    )
    actions = parser.add_subparsers(dest="action", required=True)

    inspect = actions.add_parser("inspect")
    inspect.add_argument("--skill", type=Path, required=True)

    validate = actions.add_parser("validate")
    validate.add_argument("--skill", type=Path, required=True)

    create = actions.add_parser("create")
    create.add_argument("--skill", type=Path, required=True)
    create.add_argument("--input", required=True)
    create.add_argument("--replace", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.action == "inspect":
            result = inspect_skill(args.skill)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 1
        if args.action == "validate":
            manifest = validate_skill(args.skill)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "status": "valid",
                        "path": str(args.skill.resolve()),
                        "name": manifest["name"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        root = args.skill.resolve()
        if not root.is_dir():
            raise ArsError(f"Skill directory does not exist: {root}")
        _skill_metadata(root)
        candidate = render_manifest(_load_json(args.input), root=root)
        target = root / "ars.yaml"
        if args.dry_run:
            sys.stdout.write(candidate)
            return 0
        if target.exists():
            current = target.read_text(encoding="utf-8-sig")
            if current == candidate:
                status = "unchanged"
            elif not args.replace:
                diff = "".join(
                    difflib.unified_diff(
                        current.splitlines(keepends=True),
                        candidate.splitlines(keepends=True),
                        fromfile=str(target),
                        tofile="candidate",
                    )
                )
                print(
                    json.dumps(
                        {"ok": False, "status": "different", "path": str(target)},
                        ensure_ascii=False,
                    )
                )
                sys.stdout.write(diff)
                return 2
            else:
                _atomic_write(target, candidate)
                status = "replaced"
        else:
            _atomic_write(target, candidate)
            status = "created"
        print(
            json.dumps(
                {"ok": True, "status": status, "path": str(target)},
                ensure_ascii=False,
            )
        )
        return 0
    except (ArsError, OSError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
