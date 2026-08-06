#!/usr/bin/env python3
"""Execute Noctis orchestration state and structured Markdown operations."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterator


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ARTIFACT_FORMAT = re.compile(
    r"^[a-z0-9]+(?:[.-][a-z0-9]+)*@[1-9][0-9]*$"
)
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
EXTENSION_ID = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*:[a-z0-9]+(?:-[a-z0-9]+)*$"
)
VALID_ITEM_STATUSES = ("pending", "active", "completed", "blocked")
VALID_ORCHESTRATION_STATUSES = ("active", "completed", "blocked")
VALID_LEVELS = ("task", "unit", "work")


class NoctisError(ValueError):
    """Raised when orchestration state or a structured document is invalid."""


def _json_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise NoctisError(f"unsupported scalar value: {value!r}")


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.startswith(('"', "'")):
        if value.startswith('"'):
            try:
                return json.loads(value)
            except json.JSONDecodeError as error:
                raise NoctisError(f"invalid quoted scalar: {value}") from error
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value.startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise NoctisError(f"invalid inline collection: {value}") from error
    return value


def _frontmatter(text: str) -> tuple[list[str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise NoctisError("document is missing frontmatter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body = "\n".join(lines[index + 1 :])
            if text.endswith("\n"):
                body += "\n"
            return lines[1:index], body
    raise NoctisError("document frontmatter is not terminated")


def _line_indent(line: str) -> int:
    if "\t" in line[: len(line) - len(line.lstrip())]:
        raise NoctisError("frontmatter indentation must use spaces")
    return len(line) - len(line.lstrip(" "))


def _parse_block(
    lines: list[str], index: int, indent: int
) -> tuple[dict[str, Any] | list[Any], int]:
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or _line_indent(lines[index]) < indent:
        raise NoctisError("frontmatter contains an empty nested value")
    is_list = lines[index][indent:].startswith("-")
    result: dict[str, Any] | list[Any] = [] if is_list else {}

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            raise NoctisError("frontmatter contains unexpected indentation")
        value = line[indent:]

        if is_list:
            if not isinstance(result, list) or not value.startswith("-"):
                raise NoctisError("frontmatter mixes list and mapping entries")
            raw = value[1:].strip()
            if raw:
                result.append(_parse_scalar(raw))
                index += 1
            else:
                child, index = _parse_block(lines, index + 1, indent + 2)
                result.append(child)
            continue

        if not isinstance(result, dict) or value.startswith("-") or ":" not in value:
            raise NoctisError("frontmatter mixes mapping and list entries")
        key, raw = value.split(":", 1)
        key = key.strip()
        if not key or key in result:
            raise NoctisError(f"frontmatter contains invalid or duplicate key: {key}")
        raw = raw.strip()
        if raw:
            result[key] = _parse_scalar(raw)
            index += 1
        else:
            child, index = _parse_block(lines, index + 1, indent + 2)
            result[key] = child
    return result, index


def _top_level_metadata(lines: list[str]) -> dict[str, Any]:
    metadata, index = _parse_block(lines, 0, 0)
    if index != len(lines) or not isinstance(metadata, dict):
        raise NoctisError("frontmatter root must be a mapping")
    return metadata


def _replace_top_level(
    lines: list[str], key: str, value: Any, *, after: str | None = None
) -> list[str]:
    start: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        current = line.split(":", 1)[0].strip()
        if current == key:
            start = index
            end = index + 1
            while end < len(lines) and (
                not lines[end] or lines[end].startswith((" ", "\t"))
            ):
                end += 1
            break

    replacement: list[str] = []
    if value is not None:
        replacement = _yaml_lines({key: value})
    if start is not None and end is not None:
        return [*lines[:start], *replacement, *lines[end:]]

    insertion = len(lines)
    if after is not None:
        for index, line in enumerate(lines):
            if not line.startswith((" ", "\t")) and line.startswith(f"{after}:"):
                insertion = index + 1
                while insertion < len(lines) and (
                    not lines[insertion]
                    or lines[insertion].startswith((" ", "\t"))
                ):
                    insertion += 1
                break
    return [*lines[:insertion], *replacement, *lines[insertion:]]


def _render_document(frontmatter: list[str], body: str) -> str:
    normalized_body = body.lstrip("\n")
    return "---\n" + "\n".join(frontmatter) + "\n---\n\n" + normalized_body


def _validate_common(metadata: dict[str, Any]) -> None:
    for key in ("document", "template", "revision"):
        if key not in metadata:
            raise NoctisError(f"document frontmatter is missing '{key}'")
    if not isinstance(metadata["document"], str) or not metadata["document"]:
        raise NoctisError("document must be a non-empty string")
    if not isinstance(metadata["template"], str) or not metadata["template"]:
        raise NoctisError("template must be a non-empty string")
    revision = metadata["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise NoctisError("revision must be a positive integer")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise NoctisError(f"file does not exist: {path}") from error


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


@contextlib.contextmanager
def _document_lock(path: Path) -> Iterator[None]:
    lock_path = path.parent / f".{path.name}.noctis.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise NoctisError(f"document is locked: {path}") from error
    try:
        os.close(descriptor)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _load_json(source: str) -> dict[str, Any]:
    stream = sys.stdin if source == "-" else Path(source).open(encoding="utf-8-sig")
    try:
        value = json.load(stream)
    finally:
        if stream is not sys.stdin:
            stream.close()
    if not isinstance(value, dict):
        raise NoctisError("input JSON must be an object")
    return value


def _yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key in sorted(value):
            child = value[key]
            if isinstance(child, dict) and not child:
                lines.append(f"{prefix}{key}: {{}}")
            elif isinstance(child, list) and not child:
                lines.append(f"{prefix}{key}: []")
            elif isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_json_scalar(child)}")
        return lines
    if isinstance(value, list):
        lines = []
        for child in value:
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}- {_json_scalar(child)}")
        return lines
    return [f"{prefix}{_json_scalar(value)}"]


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise NoctisError(f"{context} is missing: {', '.join(missing)}")
    if unknown:
        raise NoctisError(f"{context} has unknown fields: {', '.join(unknown)}")


def _non_empty(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NoctisError(f"{context} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, context: str, *, required: bool) -> list[str]:
    if not isinstance(value, list):
        raise NoctisError(f"{context} must be a list")
    normalized = [_non_empty(item, f"{context} item") for item in value]
    if required and not normalized:
        raise NoctisError(f"{context} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise NoctisError(f"{context} contains duplicates")
    return normalized


def _authority(value: Any, context: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    _exact_keys(value, {"allowed", "forbidden"}, context)
    return {
        "allowed": _string_list(
            value["allowed"], f"{context}.allowed", required=False
        ),
        "forbidden": _string_list(
            value["forbidden"], f"{context}.forbidden", required=False
        ),
    }


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise NoctisError(f"{context} must be a lowercase hyphenated identifier")
    return value


def _item_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or not ITEM_ID.fullmatch(value):
        raise NoctisError(f"{context} must be a stable item id")
    return value


def _relative_path(value: Any, context: str) -> str:
    path = _non_empty(value, context)
    if "\\" in path or ":" in path:
        raise NoctisError(f"{context} must use a relative POSIX path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
        raise NoctisError(f"{context} must stay inside its orchestration directory")
    return parsed.as_posix()


def _orchestration_path(value: Path) -> Path:
    path = value.resolve()
    if path.suffix.lower() == ".md":
        if path.name != "noctis.md":
            raise NoctisError("orchestration document must be named noctis.md")
        return path
    return path / "noctis.md"


def _binding(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    _exact_keys(value, {"contract", "executor", "supports"}, context)
    contract = value["contract"]
    if isinstance(contract, bool) or not isinstance(contract, int) or contract < 1:
        raise NoctisError(f"{context}.contract must be a positive integer")
    executor = value["executor"]
    if not isinstance(executor, dict):
        raise NoctisError(f"{context}.executor must be an object")
    _exact_keys(executor, {"id", "provider"}, f"{context}.executor")
    normalized_executor = {
        "id": _identifier(executor["id"], f"{context}.executor.id"),
        "provider": _identifier(
            executor["provider"], f"{context}.executor.provider"
        ),
    }
    supports = value["supports"]
    if not isinstance(supports, dict):
        raise NoctisError(f"{context}.supports must be an object")
    normalized_supports: dict[str, Any] = {}
    for support_id, raw in supports.items():
        support_id = _identifier(support_id, f"{context} support id")
        if not isinstance(raw, dict):
            raise NoctisError(f"{context}.supports.{support_id} must be an object")
        _exact_keys(
            raw,
            {"contract", "provider", "activation"},
            f"{context}.supports.{support_id}",
        )
        support_contract = raw["contract"]
        if (
            isinstance(support_contract, bool)
            or not isinstance(support_contract, int)
            or support_contract < 1
        ):
            raise NoctisError(
                f"{context}.supports.{support_id}.contract must be a positive integer"
            )
        activation = raw["activation"]
        if activation not in ("before", "on-request"):
            raise NoctisError(
                f"{context}.supports.{support_id}.activation is invalid"
            )
        normalized_supports[support_id] = {
            "activation": activation,
            "contract": support_contract,
            "provider": _identifier(
                raw["provider"], f"{context}.supports.{support_id}.provider"
            ),
        }
    return {
        "contract": contract,
        "executor": normalized_executor,
        "supports": normalized_supports,
    }


def _record(value: Any, context: str) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be null or an object")
    _exact_keys(value, {"document", "path"}, context)
    return {
        "document": _identifier(value["document"], f"{context}.document"),
        "path": _relative_path(value["path"], f"{context}.path"),
    }


def _artifact_format(value: Any, context: str) -> str:
    value = _non_empty(value, context)
    if not ARTIFACT_FORMAT.fullmatch(value):
        raise NoctisError(f"{context} must be a versioned artifact format")
    return value


def _artifact_port(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    _exact_keys(value, {"type", "formats", "required"}, context)
    formats = _string_list(value["formats"], f"{context}.formats", required=True)
    normalized_formats = [
        _artifact_format(item, f"{context}.formats item") for item in formats
    ]
    required = value["required"]
    if not isinstance(required, bool):
        raise NoctisError(f"{context}.required must be a boolean")
    return {
        "type": _identifier(value["type"], f"{context}.type"),
        "formats": normalized_formats,
        "required": required,
    }


def _artifact_ref(
    value: Any,
    context: str,
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    _exact_keys(value, {"type", "format", "location", "revision"}, context)
    normalized = {
        "type": _identifier(value["type"], f"{context}.type"),
        "format": _artifact_format(value["format"], f"{context}.format"),
        "location": _non_empty(value["location"], f"{context}.location"),
        "revision": value["revision"],
    }
    revision = normalized["revision"]
    if revision is not None:
        normalized["revision"] = _non_empty(revision, f"{context}.revision")
    if expected is not None:
        if normalized["type"] != expected["type"]:
            raise NoctisError(f"{context}.type does not match its artifact port")
        if normalized["format"] not in expected["formats"]:
            raise NoctisError(f"{context}.format does not match its artifact port")
    return normalized


def _artifact_binding(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    _exact_keys(value, {"inputs", "outputs"}, context)
    inputs = value["inputs"]
    outputs = value["outputs"]
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        raise NoctisError(f"{context}.inputs and outputs must be objects")

    normalized_inputs: dict[str, Any] = {}
    for input_id, raw in inputs.items():
        input_id = _identifier(input_id, f"{context} input id")
        if not isinstance(raw, dict):
            raise NoctisError(f"{context}.inputs.{input_id} must be an object")
        _exact_keys(
            raw,
            {"type", "formats", "required", "source"},
            f"{context}.inputs.{input_id}",
        )
        port = _artifact_port(
            {key: raw[key] for key in ("type", "formats", "required")},
            f"{context}.inputs.{input_id}",
        )
        source = raw["source"]
        if source is None:
            if port["required"]:
                raise NoctisError(
                    f"{context}.inputs.{input_id}.source is required"
                )
        elif not isinstance(source, dict):
            raise NoctisError(
                f"{context}.inputs.{input_id}.source must be null or an object"
            )
        elif set(source) == {"task", "output"}:
            source = {
                "task": _item_id(
                    source["task"], f"{context}.inputs.{input_id}.source.task"
                ),
                "output": _identifier(
                    source["output"],
                    f"{context}.inputs.{input_id}.source.output",
                ),
            }
        elif set(source) == {"artifact"}:
            source = {
                "artifact": _artifact_ref(
                    source["artifact"],
                    f"{context}.inputs.{input_id}.source.artifact",
                    expected=port,
                )
            }
        else:
            raise NoctisError(
                f"{context}.inputs.{input_id}.source must reference a Task output "
                "or contain one artifact"
            )
        normalized_inputs[input_id] = {**port, "source": source}

    normalized_outputs: dict[str, Any] = {}
    for output_id, raw in outputs.items():
        output_id = _identifier(output_id, f"{context} output id")
        normalized_outputs[output_id] = _artifact_port(
            raw, f"{context}.outputs.{output_id}"
        )
    return {"inputs": normalized_inputs, "outputs": normalized_outputs}


def _artifact_results(
    value: Any,
    binding: dict[str, Any],
    context: str,
    *,
    require_outputs: bool,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NoctisError(f"{context} must be an object")
    outputs = binding["outputs"]
    unknown = sorted(set(value) - set(outputs))
    if unknown:
        raise NoctisError(f"{context} contains unknown outputs: " + ", ".join(unknown))
    if require_outputs:
        missing = sorted(
            output_id
            for output_id, port in outputs.items()
            if port["required"] and output_id not in value
        )
        if missing:
            raise NoctisError(
                f"{context} is missing required outputs: " + ", ".join(missing)
            )
    return {
        output_id: _artifact_ref(
            artifact,
            f"{context}.{output_id}",
            expected=outputs[output_id],
        )
        for output_id, artifact in value.items()
    }


def _depends_on(value: Any, context: str) -> list[str]:
    if not isinstance(value, list):
        raise NoctisError(f"{context} must be a list")
    normalized = [_item_id(item, f"{context} item") for item in value]
    if len(normalized) != len(set(normalized)):
        raise NoctisError(f"{context} contains duplicates")
    return normalized


def _normalize_work_items(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        raise NoctisError("input.units must be a non-empty list")
    items: dict[str, Any] = {}
    for index, raw in enumerate(value):
        context = f"input.units[{index}]"
        if not isinstance(raw, dict):
            raise NoctisError(f"{context} must be an object")
        _exact_keys(raw, {"id", "title", "path", "dependsOn"}, context)
        unit_id = _item_id(raw["id"], f"{context}.id")
        if unit_id in items:
            raise NoctisError(f"duplicate unit id: {unit_id}")
        items[unit_id] = {
            "depends_on": _depends_on(raw["dependsOn"], f"{context}.dependsOn"),
            "outcome": None,
            "path": _relative_path(raw["path"], f"{context}.path"),
            "status": "pending",
            "title": _non_empty(raw["title"], f"{context}.title"),
        }
    return items


def _normalize_tracks(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        raise NoctisError("input.tracks must be a list")
    tracks: dict[str, Any] = {}
    for index, raw in enumerate(value):
        context = f"input.tracks[{index}]"
        if not isinstance(raw, dict):
            raise NoctisError(f"{context} must be an object")
        _exact_keys(raw, {"id", "label", "target"}, context)
        track_id = _identifier(raw["id"], f"{context}.id")
        if track_id in tracks:
            raise NoctisError(f"duplicate track id: {track_id}")
        tracks[track_id] = {
            "label": _non_empty(raw["label"], f"{context}.label"),
            "target": _non_empty(raw["target"], f"{context}.target"),
        }
    return tracks


def _normalize_tasks(
    value: Any, tracks: dict[str, Any], *, allow_fix: bool
) -> dict[str, Any]:
    if not isinstance(value, list) or not value:
        raise NoctisError("input.tasks must be a non-empty list")
    items: dict[str, Any] = {}
    for index, raw in enumerate(value):
        context = f"input.tasks[{index}]"
        if not isinstance(raw, dict):
            raise NoctisError(f"{context} must be an object")
        _exact_keys(
            raw,
            {
                "id",
                "title",
                "capability",
                "track",
                "dependsOn",
                "binding",
                "artifactBinding",
                "record",
            },
            context,
        )
        task_id = _item_id(raw["id"], f"{context}.id")
        if task_id in items:
            raise NoctisError(f"duplicate task id: {task_id}")
        capability = _identifier(raw["capability"], f"{context}.capability")
        if capability == "fix" and not allow_fix:
            raise NoctisError(
                "fix is a recovery capability and cannot appear in an initial Unit"
            )
        track = raw["track"]
        if track is not None:
            track = _identifier(track, f"{context}.track")
            if track not in tracks:
                raise NoctisError(f"{context}.track references unknown track '{track}'")
        items[task_id] = {
            "artifact_binding": _artifact_binding(
                raw["artifactBinding"], f"{context}.artifactBinding"
            ),
            "artifacts": {},
            "binding": _binding(raw["binding"], f"{context}.binding"),
            "capability": capability,
            "depends_on": _depends_on(raw["dependsOn"], f"{context}.dependsOn"),
            "outcome": None,
            "record": _record(raw["record"], f"{context}.record"),
            "status": "pending",
            "title": _non_empty(raw["title"], f"{context}.title"),
            "track": track,
        }
    return items


def _validate_dag(items: dict[str, Any]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            raise NoctisError(f"orchestration contains a cycle at '{item_id}'")
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in items[item_id]["depends_on"]:
            visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in items:
        visit(item_id)


def _ready_items(items: dict[str, Any]) -> list[str]:
    return sorted(
        item_id
        for item_id, item in items.items()
        if item["status"] == "pending"
        and all(items[dependency]["status"] == "completed" for dependency in item["depends_on"])
    )


def _aggregate_status(items: dict[str, Any]) -> str:
    if all(item["status"] == "completed" for item in items.values()):
        return "completed"
    if any(item["status"] == "active" for item in items.values()) or _ready_items(items):
        return "active"
    return "blocked"


def _validate_graph(items: Any, level: str) -> dict[str, Any]:
    if not isinstance(items, dict) or not items:
        raise NoctisError(f"{level} orchestration items must not be empty")
    normalized_ids = {
        _item_id(item_id, f"{level} item id") for item_id in items
    }
    if len(normalized_ids) != len(items):
        raise NoctisError(f"{level} orchestration contains duplicate item ids")
    for item_id, item in items.items():
        if not isinstance(item, dict):
            raise NoctisError(f"{level} item '{item_id}' must be an object")
        expected = (
            {"title", "path", "depends_on", "status", "outcome"}
            if level == "work"
            else {
                "title",
                "capability",
                "track",
                "depends_on",
                "status",
                "outcome",
                "artifact_binding",
                "artifacts",
                "binding",
                "record",
            }
        )
        _exact_keys(item, expected, f"{level} item '{item_id}'")
        _non_empty(item["title"], f"{level} item '{item_id}'.title")
        dependencies = _depends_on(
            item["depends_on"], f"{level} item '{item_id}'.depends_on"
        )
        unknown = sorted(set(dependencies) - set(items))
        if unknown:
            raise NoctisError(
                f"{level} item '{item_id}' depends on unknown items: "
                + ", ".join(unknown)
            )
        if item_id in dependencies:
            raise NoctisError(f"{level} item '{item_id}' cannot depend on itself")
        status = item["status"]
        if status not in VALID_ITEM_STATUSES:
            raise NoctisError(f"{level} item '{item_id}' has invalid status")
        outcome = item["outcome"]
        if status in ("completed", "blocked"):
            _non_empty(outcome, f"{level} item '{item_id}'.outcome")
        elif outcome is not None:
            raise NoctisError(
                f"{level} item '{item_id}' cannot have an outcome before it finishes"
            )
        if level == "work":
            _relative_path(item["path"], f"work item '{item_id}'.path")
        else:
            _identifier(
                item["capability"], f"unit task '{item_id}'.capability"
            )
            _binding(item["binding"], f"unit task '{item_id}'.binding")
            artifact_binding = _artifact_binding(
                item["artifact_binding"],
                f"unit task '{item_id}'.artifact_binding",
            )
            _artifact_results(
                item["artifacts"],
                artifact_binding,
                f"unit task '{item_id}'.artifacts",
                require_outputs=status == "completed",
            )
            _record(item["record"], f"unit task '{item_id}'.record")
    _validate_dag(items)
    if level != "work":
        for item_id, item in items.items():
            for input_id, port in item["artifact_binding"]["inputs"].items():
                source = port["source"]
                if source is None or "artifact" in source:
                    continue
                source_task = source["task"]
                source_output = source["output"]
                if source_task not in items:
                    raise NoctisError(
                        f"unit task '{item_id}' input '{input_id}' references "
                        f"unknown task '{source_task}'"
                    )
                if source_task not in item["depends_on"]:
                    raise NoctisError(
                        f"unit task '{item_id}' input '{input_id}' must reference "
                        "a direct dependency"
                    )
                source_outputs = items[source_task]["artifact_binding"]["outputs"]
                if source_output not in source_outputs:
                    raise NoctisError(
                        f"unit task '{item_id}' input '{input_id}' references "
                        f"unknown output '{source_task}.{source_output}'"
                    )
                output_port = source_outputs[source_output]
                if output_port["type"] != port["type"]:
                    raise NoctisError(
                        f"unit task '{item_id}' input '{input_id}' has "
                        "incompatible artifact types"
                    )
                if not set(output_port["formats"]) & set(port["formats"]):
                    raise NoctisError(
                        f"unit task '{item_id}' input '{input_id}' requires "
                        "an explicit adapter Task"
                    )
    for item_id, item in items.items():
        if item["status"] == "active":
            unfinished = [
                dependency
                for dependency in item["depends_on"]
                if items[dependency]["status"] != "completed"
            ]
            if unfinished:
                raise NoctisError(
                    f"{level} item '{item_id}' is active before dependencies complete: "
                    + ", ".join(unfinished)
                )
    return items


def _validate_orchestration(metadata: dict[str, Any]) -> dict[str, Any]:
    _validate_common(metadata)
    if metadata["document"] != "noctis":
        raise NoctisError("orchestration must declare document: noctis")
    level = metadata.get("level")
    if level not in VALID_LEVELS:
        raise NoctisError("orchestration level must be task, unit, or work")
    expected_template = {
        "task": "noctis/task@2",
        "unit": "noctis/unit@3",
        "work": "noctis/work@2",
    }[level]
    if metadata["template"] != expected_template:
        raise NoctisError(
            f"{level} orchestration must use template '{expected_template}'"
        )
    expected = {
        "document",
        "template",
        "revision",
        "level",
        "id",
        "status",
        "title",
        "objective",
        "completion_conditions",
        "authority",
        "items",
    }
    if level == "unit":
        expected |= {"workflow_template", "tracks"}
    _exact_keys(metadata, expected, "orchestration")
    _item_id(metadata["id"], "orchestration.id")
    _non_empty(metadata["title"], "orchestration.title")
    _non_empty(metadata["objective"], "orchestration.objective")
    _string_list(
        metadata["completion_conditions"],
        "orchestration.completion_conditions",
        required=True,
    )
    _authority(metadata["authority"], "orchestration.authority")
    items = _validate_graph(metadata["items"], level)
    if level == "unit":
        _identifier(metadata["workflow_template"], "orchestration.workflow_template")
        tracks = metadata["tracks"]
        if not isinstance(tracks, dict):
            raise NoctisError("orchestration.tracks must be an object")
        for track_id, track in tracks.items():
            _identifier(track_id, "track id")
            if not isinstance(track, dict):
                raise NoctisError(f"track '{track_id}' must be an object")
            _exact_keys(track, {"label", "target"}, f"track '{track_id}'")
            _non_empty(track["label"], f"track '{track_id}'.label")
            _non_empty(track["target"], f"track '{track_id}'.target")
        for task_id, task in items.items():
            track = task["track"]
            if track is not None and track not in tracks:
                raise NoctisError(
                    f"unit task '{task_id}' references unknown track '{track}'"
                )
    elif level == "task":
        if len(items) != 1:
            raise NoctisError("Task orchestration must contain exactly one Task")
        task_id, task = next(iter(items.items()))
        if task_id != metadata["id"]:
            raise NoctisError("Task orchestration id must match its Task id")
        if task["track"] is not None:
            raise NoctisError("Task orchestration cannot declare a Track")
        if task["depends_on"]:
            raise NoctisError("Task orchestration cannot declare dependencies")
    aggregate = _aggregate_status(items)
    if metadata["status"] != aggregate:
        raise NoctisError(
            f"orchestration status must be '{aggregate}', found '{metadata['status']}'"
        )
    return metadata


def _topological_order(items: dict[str, Any]) -> list[str]:
    remaining = set(items)
    completed: set[str] = set()
    order: list[str] = []
    while remaining:
        ready = sorted(
            item_id
            for item_id in remaining
            if set(items[item_id]["depends_on"]) <= completed
        )
        if not ready:
            raise NoctisError("orchestration contains a dependency cycle")
        order.extend(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return order


def _table_cell(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, list):
        value = ", ".join(value) if value else "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _artifact_summary(value: dict[str, Any]) -> str:
    if not value:
        return "-"
    return ", ".join(
        f"{artifact_id}={artifact['location']}"
        for artifact_id, artifact in sorted(value.items())
    )


def _markdown_list(values: list[str], empty: str) -> str:
    return "\n".join(f"- {value}" for value in values) if values else f"- {empty}"


def _notes(body: str) -> str:
    spans = _slot_inner_spans(body, "orchestration.notes", 0, len(body))
    if not spans:
        return ""
    if len(spans) != 1:
        raise NoctisError("orchestration document must contain one notes slot")
    return body[spans[0][0] : spans[0][1]].strip("\n")


def _render_orchestration_body(
    metadata: dict[str, Any], notes: str = ""
) -> str:
    template = (
        Path(__file__).resolve().parent.parent
        / "assets"
        / "templates"
        / f"{metadata['level']}.md"
    )
    body = _read_text(template)
    items = metadata["items"]
    replacements = {
        "{{title}}": metadata["title"],
        "{{objective}}": metadata["objective"],
        "{{completion_conditions}}": _markdown_list(
            metadata["completion_conditions"], "None"
        ),
        "{{authority_allowed}}": _markdown_list(
            metadata["authority"]["allowed"], "No additional authority"
        ),
        "{{authority_forbidden}}": _markdown_list(
            metadata["authority"]["forbidden"], "None"
        ),
        "{{notes}}": notes,
    }
    if metadata["level"] == "work":
        rows = [
            "| ID | Unit | Depends on | Status | Outcome | Path |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item_id in _topological_order(items):
            item = items[item_id]
            rows.append(
                "| "
                + " | ".join(
                    _table_cell(value)
                    for value in (
                        item_id,
                        item["title"],
                        item["depends_on"],
                        item["status"],
                        item["outcome"],
                        item["path"],
                    )
                )
                + " |"
            )
        replacements["{{items}}"] = "\n".join(rows)
    else:
        task_rows = [
            "| ID | Task | Capability | Track | Depends on | Status | Outcome | Artifacts |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for task_id in _topological_order(items):
            task = items[task_id]
            task_rows.append(
                "| "
                + " | ".join(
                    _table_cell(value)
                    for value in (
                        task_id,
                        task["title"],
                        task["capability"],
                        task["track"],
                        task["depends_on"],
                        task["status"],
                        task["outcome"],
                        _artifact_summary(task["artifacts"]),
                    )
                )
                + " |"
            )
        replacements["{{tasks}}"] = "\n".join(task_rows)
    if metadata["level"] == "unit":
        track_rows = [
            "| Track | Label | Target |",
            "| --- | --- | --- |",
        ]
        for track_id in sorted(metadata["tracks"]):
            track = metadata["tracks"][track_id]
            track_rows.append(
                "| "
                + " | ".join(
                    _table_cell(value)
                    for value in (track_id, track["label"], track["target"])
                )
                + " |"
            )
        if not metadata["tracks"]:
            track_rows.append("| - | No physical Track | - |")
        replacements["{{tracks}}"] = "\n".join(track_rows)
        replacements["{{workflow_template}}"] = metadata["workflow_template"]
    markers = re.compile("|".join(re.escape(marker) for marker in replacements))
    return markers.sub(lambda match: replacements[match.group(0)], body)


def _metadata_lines(metadata: dict[str, Any]) -> list[str]:
    order = (
        "document",
        "template",
        "revision",
        "level",
        "id",
        "status",
        "title",
        "objective",
        "completion_conditions",
        "authority",
        "workflow_template",
        "tracks",
        "items",
    )
    lines: list[str] = []
    for key in order:
        if key in metadata:
            lines.extend(_yaml_lines({key: metadata[key]}))
    return lines


def _write_orchestration(
    path: Path, metadata: dict[str, Any], *, notes: str = ""
) -> None:
    metadata["status"] = _aggregate_status(metadata["items"])
    _validate_orchestration(metadata)
    body = _render_orchestration_body(metadata, notes)
    _atomic_write(path, _render_document(_metadata_lines(metadata), body))


def create_orchestration(args: argparse.Namespace) -> dict[str, Any]:
    path = _orchestration_path(args.path)
    if path.exists() and not args.dry_run:
        raise NoctisError(f"orchestration already exists: {path}")
    payload = _load_json(args.input)
    if args.level == "work":
        _exact_keys(
            payload,
            {
                "id",
                "title",
                "objective",
                "completionConditions",
                "authority",
                "units",
            },
            "input",
        )
        items = _normalize_work_items(payload["units"])
        metadata = {
            "document": "noctis",
            "template": "noctis/work@2",
            "revision": 1,
            "level": "work",
            "id": _item_id(payload["id"], "input.id"),
            "status": "active",
            "title": _non_empty(payload["title"], "input.title"),
            "objective": _non_empty(payload["objective"], "input.objective"),
            "completion_conditions": _string_list(
                payload["completionConditions"],
                "input.completionConditions",
                required=True,
            ),
            "authority": _authority(payload["authority"], "input.authority"),
            "items": items,
        }
    elif args.level == "unit":
        _exact_keys(
            payload,
            {
                "id",
                "title",
                "objective",
                "completionConditions",
                "authority",
                "workflowTemplate",
                "tracks",
                "tasks",
            },
            "input",
        )
        tracks = _normalize_tracks(payload["tracks"])
        items = _normalize_tasks(payload["tasks"], tracks, allow_fix=False)
        metadata = {
            "document": "noctis",
            "template": "noctis/unit@3",
            "revision": 1,
            "level": "unit",
            "id": _item_id(payload["id"], "input.id"),
            "status": "active",
            "title": _non_empty(payload["title"], "input.title"),
            "objective": _non_empty(payload["objective"], "input.objective"),
            "completion_conditions": _string_list(
                payload["completionConditions"],
                "input.completionConditions",
                required=True,
            ),
            "authority": _authority(payload["authority"], "input.authority"),
            "workflow_template": _identifier(
                payload["workflowTemplate"], "input.workflowTemplate"
            ),
            "tracks": tracks,
            "items": items,
        }
    else:
        _exact_keys(
            payload,
            {
                "id",
                "title",
                "objective",
                "completionConditions",
                "authority",
                "capability",
                "binding",
                "artifactBinding",
                "record",
            },
            "input",
        )
        task_id = _item_id(payload["id"], "input.id")
        title = _non_empty(payload["title"], "input.title")
        items = _normalize_tasks(
            [
                {
                    "id": task_id,
                    "title": title,
                    "capability": payload["capability"],
                    "track": None,
                    "dependsOn": [],
                    "binding": payload["binding"],
                    "artifactBinding": payload["artifactBinding"],
                    "record": payload["record"],
                }
            ],
            {},
            allow_fix=False,
        )
        metadata = {
            "document": "noctis",
            "template": "noctis/task@2",
            "revision": 1,
            "level": "task",
            "id": task_id,
            "status": "active",
            "title": title,
            "objective": _non_empty(payload["objective"], "input.objective"),
            "completion_conditions": _string_list(
                payload["completionConditions"],
                "input.completionConditions",
                required=True,
            ),
            "authority": _authority(payload["authority"], "input.authority"),
            "items": items,
        }
    metadata["status"] = _aggregate_status(metadata["items"])
    _validate_orchestration(metadata)
    if args.dry_run:
        return {
            "ok": True,
            "status": "valid",
            "level": args.level,
            "path": str(path),
            "ready": _ready_items(items),
        }
    _write_orchestration(path, metadata)
    return {
        "ok": True,
        "status": "created",
        "level": args.level,
        "path": str(path),
        "revision": 1,
        "ready": _ready_items(items),
    }


def _load_orchestration(path_value: Path) -> tuple[Path, dict[str, Any], str]:
    path = _orchestration_path(path_value)
    frontmatter, body = _frontmatter(_read_text(path))
    metadata = _top_level_metadata(frontmatter)
    _validate_orchestration(metadata)
    return path, metadata, body


def inspect_orchestration(args: argparse.Namespace) -> dict[str, Any] | str:
    path, metadata, body = _load_orchestration(args.path)
    if args.id is not None:
        item_id = _item_id(args.id, "id")
        if item_id not in metadata["items"]:
            raise NoctisError(f"orchestration item does not exist: {item_id}")
        item = metadata["items"][item_id]
        if args.format == "markdown":
            return "\n".join(_yaml_lines({item_id: item})) + "\n"
        return {
            "ok": True,
            "path": str(path),
            "level": metadata["level"],
            "revision": metadata["revision"],
            "id": item_id,
            "item": item,
            "ready": item_id in _ready_items(metadata["items"]),
        }
    if args.format == "markdown":
        return body
    return {
        "ok": True,
        "path": str(path),
        "metadata": metadata,
        "ready": _ready_items(metadata["items"]),
    }


def _resolved_inputs(
    items: dict[str, Any], item_id: str
) -> tuple[dict[str, Any], list[str]]:
    item = items[item_id]
    if "artifact_binding" not in item:
        return {}, []
    resolved: dict[str, Any] = {}
    unresolved: list[str] = []
    for input_id, port in item["artifact_binding"]["inputs"].items():
        source = port["source"]
        artifact: dict[str, Any] | None = None
        if source is not None and "artifact" in source:
            artifact = source["artifact"]
            resolved_source: dict[str, Any] = {"external": True}
        elif source is not None:
            source_task = items[source["task"]]
            artifact = source_task["artifacts"].get(source["output"])
            resolved_source = {
                "task": source["task"],
                "output": source["output"],
                "provider": source_task["binding"]["executor"]["provider"],
                "record": source_task["record"],
            }
        if artifact is not None:
            resolved[input_id] = {
                "artifact": artifact,
                "source": resolved_source,
            }
        elif port["required"]:
            unresolved.append(input_id)
    return resolved, sorted(unresolved)


def mutate_item_status(args: argparse.Namespace) -> dict[str, Any]:
    path = _orchestration_path(args.path)
    with _document_lock(path):
        path, metadata, body = _load_orchestration(path)
        if metadata["revision"] != args.expected_revision:
            raise NoctisError(
                f"revision mismatch: expected {args.expected_revision}, "
                f"found {metadata['revision']}"
            )
        item_id = _item_id(args.id, "id")
        if item_id not in metadata["items"]:
            raise NoctisError(f"orchestration item does not exist: {item_id}")
        item = metadata["items"][item_id]
        if args.action == "start":
            if item["status"] != "pending":
                raise NoctisError(
                    f"start requires pending status, found {item['status']}"
                )
        elif args.action == "resume":
            if item["status"] != "blocked":
                raise NoctisError(
                    f"resume requires blocked status, found {item['status']}"
                )
        else:
            if item["status"] != "active":
                raise NoctisError(
                    f"finish requires active status, found {item['status']}"
                )

        if args.action in ("start", "resume"):
            unfinished = [
                dependency
                for dependency in item["depends_on"]
                if metadata["items"][dependency]["status"] != "completed"
            ]
            if unfinished:
                raise NoctisError(
                    f"item '{item_id}' has unfinished dependencies: "
                    + ", ".join(unfinished)
                )
            _, unresolved = _resolved_inputs(metadata["items"], item_id)
            if unresolved:
                raise NoctisError(
                    f"item '{item_id}' has unresolved required inputs: "
                    + ", ".join(unresolved)
                )
            item["status"] = "active"
            item["outcome"] = None
            if "artifacts" in item:
                item["artifacts"] = {}
        else:
            item["status"] = args.to_status
            item["outcome"] = _non_empty(args.outcome, "outcome")
            if "artifact_binding" in item:
                raw_artifacts = (
                    _load_json(args.artifacts) if args.artifacts is not None else {}
                )
                item["artifacts"] = _artifact_results(
                    raw_artifacts,
                    item["artifact_binding"],
                    "artifacts",
                    require_outputs=args.to_status == "completed",
                )
            elif args.artifacts is not None:
                raise NoctisError("Work items cannot publish Task artifacts")
        metadata["revision"] += 1
        _write_orchestration(path, metadata, notes=_notes(body))
    return {
        "ok": True,
        "path": str(path),
        "id": item_id,
        "itemStatus": item["status"],
        "orchestrationStatus": metadata["status"],
        "artifacts": item.get("artifacts", {}),
        "revision": metadata["revision"],
        "ready": _ready_items(metadata["items"]),
    }


def _ancestors(item_id: str, items: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    pending = list(items[item_id]["depends_on"])
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(items[dependency]["depends_on"])
    return result


def splice_tasks(args: argparse.Namespace) -> dict[str, Any]:
    path = _orchestration_path(args.path)
    payload = _load_json(args.input)
    _exact_keys(
        payload,
        {"sourceOutcome", "sourceArtifacts", "tasks", "tail"},
        "input",
    )
    with _document_lock(path):
        path, metadata, body = _load_orchestration(path)
        if metadata["level"] != "unit":
            raise NoctisError("task splice is only valid for Unit orchestration")
        if metadata["revision"] != args.expected_revision:
            raise NoctisError(
                f"revision mismatch: expected {args.expected_revision}, "
                f"found {metadata['revision']}"
            )
        source_id = _item_id(args.after, "after")
        if source_id not in metadata["items"]:
            raise NoctisError(f"source task does not exist: {source_id}")
        source = metadata["items"][source_id]
        if source["status"] != "active":
            raise NoctisError(
                f"task splice requires active source, found {source['status']}"
            )
        new_items = _normalize_tasks(
            payload["tasks"], metadata["tracks"], allow_fix=True
        )
        duplicates = sorted(set(new_items) & set(metadata["items"]))
        if duplicates:
            raise NoctisError("task splice reuses task ids: " + ", ".join(duplicates))
        tail = _item_id(payload["tail"], "input.tail")
        if tail not in new_items:
            raise NoctisError("input.tail must reference an inserted task")
        allowed_dependencies = set(new_items) | {source_id}
        for task_id, task in new_items.items():
            unknown = sorted(set(task["depends_on"]) - allowed_dependencies)
            if unknown:
                raise NoctisError(
                    f"inserted task '{task_id}' references tasks outside the splice: "
                    + ", ".join(unknown)
                )

        combined = {**metadata["items"], **new_items}
        _validate_dag(combined)
        for task_id in new_items:
            if source_id not in _ancestors(task_id, combined):
                raise NoctisError(
                    f"inserted task '{task_id}' must descend from source '{source_id}'"
                )
        missing_from_tail = sorted(set(new_items) - {tail} - _ancestors(tail, combined))
        if missing_from_tail:
            raise NoctisError(
                "splice tail must depend on every inserted task: "
                + ", ".join(missing_from_tail)
            )

        successors = [
            item_id
            for item_id, item in metadata["items"].items()
            if source_id in item["depends_on"]
        ]
        not_pending = [
            item_id
            for item_id in successors
            if metadata["items"][item_id]["status"] != "pending"
        ]
        if not_pending:
            raise NoctisError(
                "task splice can only rewire pending successors: "
                + ", ".join(not_pending)
            )
        for item_id in successors:
            dependencies = metadata["items"][item_id]["depends_on"]
            metadata["items"][item_id]["depends_on"] = [
                tail if dependency == source_id else dependency
                for dependency in dependencies
            ]
        source["status"] = "completed"
        source["outcome"] = _non_empty(payload["sourceOutcome"], "input.sourceOutcome")
        source["artifacts"] = _artifact_results(
            payload["sourceArtifacts"],
            source["artifact_binding"],
            "input.sourceArtifacts",
            require_outputs=True,
        )
        metadata["items"].update(new_items)
        metadata["revision"] += 1
        _write_orchestration(path, metadata, notes=_notes(body))
    return {
        "ok": True,
        "path": str(path),
        "source": source_id,
        "inserted": [
            task_id
            for task_id in _topological_order(metadata["items"])
            if task_id in new_items
        ],
        "tail": tail,
        "rewired": sorted(successors),
        "revision": metadata["revision"],
        "ready": _ready_items(metadata["items"]),
    }


def _orchestration_files(root: Path) -> list[Path]:
    noctis_root = root / "Noctis"
    if not noctis_root.is_dir():
        return []
    return sorted(
        noctis_root.rglob("noctis.md"), key=lambda path: path.as_posix().lower()
    )


def _read_project_orchestrations(
    root: Path,
) -> tuple[list[tuple[Path, dict[str, Any]]], list[str]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for path in _orchestration_files(root):
        try:
            frontmatter, _ = _frontmatter(_read_text(path))
            metadata = _top_level_metadata(frontmatter)
            _validate_orchestration(metadata)
        except (OSError, UnicodeError, NoctisError) as error:
            errors.append(f"{path.relative_to(root).as_posix()}: {error}")
            continue
        records.append((path.resolve(), metadata))
    return records, errors


def _find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "Noctis" / "registry.yaml").is_file():
            return candidate
    raise NoctisError(
        f"cannot locate a project Noctis/registry.yaml from: {start.resolve()}"
    )


def _entry_summary(
    root: Path, path: Path, metadata: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": metadata["id"],
        "level": metadata["level"],
        "title": metadata["title"],
        "status": metadata["status"],
        "revision": metadata["revision"],
        "ready": _ready_items(metadata["items"]),
        "path": path.relative_to(root).as_posix(),
    }


def _root_candidates(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    known = {path for path, _ in records}
    referenced: set[Path] = set()
    for path, metadata in records:
        if metadata["level"] != "work" or metadata["status"] == "completed":
            continue
        for item in metadata["items"].values():
            child = (path.parent / item["path"]).resolve()
            if child in known:
                referenced.add(child)
    return [
        (path, metadata)
        for path, metadata in records
        if metadata["status"] != "completed" and path not in referenced
    ]


def _entry_context(
    root: Path,
    path: Path,
    metadata: dict[str, Any],
    item_value: str | None,
) -> dict[str, Any]:
    items = metadata["items"]
    item_id = item_value
    if item_id is None and metadata["level"] == "task":
        item_id = metadata["id"]
    target: dict[str, Any] | None = None
    if item_id is not None:
        item_id = _item_id(item_id, "id")
        if item_id not in items:
            raise NoctisError(f"orchestration item does not exist: {item_id}")
        item = items[item_id]
        predecessors = [
            {
                "id": dependency,
                "status": items[dependency]["status"],
                "outcome": items[dependency]["outcome"],
                "artifacts": items[dependency].get("artifacts", {}),
            }
            for dependency in item["depends_on"]
        ]
        resolved_inputs, unresolved_inputs = _resolved_inputs(items, item_id)
        target = {
            "id": item_id,
            "item": item,
            "predecessors": predecessors,
            "resolvedInputs": resolved_inputs,
            "unresolvedInputs": unresolved_inputs,
        }
    return {
        "version": 2,
        "projectRoot": str(root),
        "record": str(path),
        "expectedRevision": metadata["revision"],
        "orchestration": {
            "level": metadata["level"],
            "id": metadata["id"],
            "title": metadata["title"],
            "objective": metadata["objective"],
            "completionConditions": metadata["completion_conditions"],
            "authority": metadata["authority"],
            "status": metadata["status"],
        },
        "active": sorted(
            item_id for item_id, item in items.items() if item["status"] == "active"
        ),
        "ready": _ready_items(items),
        "blocked": sorted(
            item_id for item_id, item in items.items() if item["status"] == "blocked"
        ),
        "target": target,
    }


def prepare_entry(args: argparse.Namespace) -> dict[str, Any]:
    start = (
        args.record
        if args.record is not None and args.record.is_absolute()
        else args.start
    )
    root = _find_project_root(start)
    records, warnings = _read_project_orchestrations(root)
    if args.record is not None:
        requested = args.record if args.record.is_absolute() else root / args.record
        path = _orchestration_path(requested)
        try:
            path.relative_to(root / "Noctis")
        except ValueError as error:
            raise NoctisError(
                "entry record must stay inside the project Noctis directory"
            ) from error
        matches = [metadata for candidate, metadata in records if candidate == path]
        if not matches:
            if path.exists():
                _load_orchestration(path)
            raise NoctisError(f"entry record does not exist: {path}")
        return {
            "ok": True,
            "status": "ready",
            "warnings": warnings,
            "entry": _entry_context(root, path, matches[0], args.id),
        }

    candidates = _root_candidates(records)
    summaries = [
        _entry_summary(root, path, metadata) for path, metadata in candidates
    ]
    if not candidates:
        return {
            "ok": True,
            "status": "not-found",
            "projectRoot": str(root),
            "candidates": [],
            "warnings": warnings,
        }
    if len(candidates) > 1:
        return {
            "ok": True,
            "status": "selection-required",
            "projectRoot": str(root),
            "candidates": summaries,
            "warnings": warnings,
        }
    path, metadata = candidates[0]
    return {
        "ok": True,
        "status": "ready",
        "warnings": warnings,
        "entry": _entry_context(root, path, metadata, args.id),
    }


def scan_orchestrations(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    if not root.is_dir():
        raise NoctisError(f"project root does not exist: {root}")
    project_records, errors = _read_project_orchestrations(root)
    records: list[dict[str, Any]] = []
    for path, metadata in project_records:
        if args.level != "all" and metadata["level"] != args.level:
            continue
        if args.status != "all" and metadata["status"] != args.status:
            continue
        records.append(
            {
                "id": metadata["id"],
                "level": metadata["level"],
                "status": metadata["status"],
                "revision": metadata["revision"],
                "ready": _ready_items(metadata["items"]),
                "path": path.relative_to(root).as_posix(),
            }
        )
    return {
        "ok": not errors,
        "projectRoot": str(root),
        "orchestrations": records,
        "errors": errors,
    }


def _item_spans(text: str) -> list[tuple[str, int, int]]:
    start_pattern = re.compile(
        r"(?m)^<!-- noctis:item ([A-Za-z0-9][A-Za-z0-9._:-]*) -->\s*$"
    )
    end_pattern = re.compile(r"(?m)^<!-- /noctis:item -->\s*$")
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    while True:
        start = start_pattern.search(text, cursor)
        if start is None:
            break
        end = end_pattern.search(text, start.end())
        if end is None:
            raise NoctisError(f"item '{start.group(1)}' is not terminated")
        if start_pattern.search(text, start.end(), end.start()) is not None:
            raise NoctisError("nested or overlapping item markers are not supported")
        spans.append((start.group(1), start.start(), end.end()))
        cursor = end.end()
    ids = [item_id for item_id, _, _ in spans]
    if len(ids) != len(set(ids)):
        raise NoctisError("document contains duplicate item ids")
    return spans


def _slot_inner_spans(
    text: str, slot: str, start: int, end: int
) -> list[tuple[int, int]]:
    start_marker = re.compile(rf"(?m)^<!-- noctis:slot {re.escape(slot)} -->\s*$")
    end_marker = re.compile(r"(?m)^<!-- /noctis:slot -->\s*$")
    spans: list[tuple[int, int]] = []
    cursor = start
    while True:
        opening = start_marker.search(text, cursor, end)
        if opening is None:
            break
        closing = end_marker.search(text, opening.end(), end)
        if closing is None:
            raise NoctisError(f"slot '{slot}' is not terminated")
        if start_marker.search(text, opening.end(), closing.start()) is not None:
            raise NoctisError(f"nested slot '{slot}' markers are not supported")
        spans.append((opening.end(), closing.start()))
        cursor = closing.end()
    return spans


def _targets(
    text: str, slot: str, scope: str, item: str | None
) -> list[tuple[str | None, int, int]]:
    if scope == "once":
        spans = _slot_inner_spans(text, slot, 0, len(text))
        if len(spans) != 1:
            raise NoctisError(f"scope once requires exactly one slot '{slot}'")
        return [(None, *spans[0])]

    items = _item_spans(text)
    if scope == "item":
        matching = [entry for entry in items if entry[0] == item]
        if not matching:
            raise NoctisError(f"item does not exist: {item}")
        items = matching
    targets: list[tuple[str | None, int, int]] = []
    for item_id, item_start, item_end in items:
        spans = _slot_inner_spans(text, slot, item_start, item_end)
        if len(spans) != 1:
            raise NoctisError(
                f"item '{item_id}' must contain exactly one slot '{slot}'"
            )
        targets.append((item_id, *spans[0]))
    if not targets:
        raise NoctisError(f"no target items found for slot '{slot}'")
    return targets


def _extension_span(
    text: str, extension_id: str, start: int, end: int
) -> tuple[int, int, str] | None:
    opening_pattern = re.compile(
        rf"(?m)^<!-- noctis:extension {re.escape(extension_id)} -->\s*$"
    )
    closing_pattern = re.compile(r"(?m)^<!-- /noctis:extension -->\s*$")
    matches = list(opening_pattern.finditer(text, start, end))
    if len(matches) > 1:
        raise NoctisError(f"duplicate extension '{extension_id}' in one slot")
    if not matches:
        return None
    opening = matches[0]
    closing = closing_pattern.search(text, opening.end(), end)
    if closing is None:
        raise NoctisError(f"extension '{extension_id}' is not terminated")
    content = text[opening.end() : closing.start()].strip("\n")
    return opening.start(), closing.end(), content


def _extension_block(extension_id: str, content: str) -> str:
    normalized = content.strip("\r\n")
    return (
        f"<!-- noctis:extension {extension_id} -->\n"
        f"{normalized}\n"
        "<!-- /noctis:extension -->"
    )


def _insert_at_slot(text: str, start: int, end: int, block: str) -> str:
    current = text[start:end]
    stripped = current.rstrip()
    prefix = "\n\n" if stripped else "\n"
    replacement = stripped + prefix + block + "\n"
    return text[:start] + replacement + text[end:]


def _content(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8-sig")


def mutate_extension(args: argparse.Namespace) -> dict[str, Any]:
    path = args.document.resolve()
    if not EXTENSION_ID.fullmatch(args.id):
        raise NoctisError("extension id must use provider:id format")
    content = None if args.action == "remove" else _content(args.content)
    with _document_lock(path):
        text = _read_text(path)
        frontmatter, body = _frontmatter(text)
        metadata = _top_level_metadata(frontmatter)
        _validate_common(metadata)
        if metadata["revision"] != args.expected_revision:
            raise NoctisError(
                f"revision mismatch: expected {args.expected_revision}, "
                f"found {metadata['revision']}"
            )
        targets = _targets(body, args.slot, args.scope, args.item)
        changed = 0
        for item_id, start, end in sorted(
            targets, key=lambda target: target[1], reverse=True
        ):
            existing = _extension_span(body, args.id, start, end)
            if args.action == "insert":
                if existing is not None:
                    raise NoctisError(
                        f"extension '{args.id}' already exists"
                        + (f" in item '{item_id}'" if item_id else "")
                    )
                body = _insert_at_slot(
                    body, start, end, _extension_block(args.id, content or "")
                )
                changed += 1
            elif args.action == "sync":
                if existing is None:
                    body = _insert_at_slot(
                        body, start, end, _extension_block(args.id, content or "")
                    )
                    changed += 1
            elif args.action == "upsert":
                block = _extension_block(args.id, content or "")
                if existing is None:
                    body = _insert_at_slot(body, start, end, block)
                    changed += 1
                elif body[existing[0] : existing[1]] != block:
                    body = body[: existing[0]] + block + body[existing[1] :]
                    changed += 1
            elif args.action == "remove" and existing is not None:
                body = body[: existing[0]] + body[existing[1] :]
                changed += 1

        if changed:
            revision = metadata["revision"] + 1
            frontmatter = _replace_top_level(frontmatter, "revision", revision)
            _atomic_write(path, _render_document(frontmatter, body))
        else:
            revision = metadata["revision"]
    return {
        "ok": True,
        "action": args.action,
        "document": str(path),
        "extension": args.id,
        "changed": changed,
        "revision": revision,
    }


def read_extension(args: argparse.Namespace) -> dict[str, Any] | str:
    path = args.document.resolve()
    if not EXTENSION_ID.fullmatch(args.id):
        raise NoctisError("extension id must use provider:id format")
    text = _read_text(path)
    frontmatter, body = _frontmatter(text)
    metadata = _top_level_metadata(frontmatter)
    _validate_common(metadata)
    occurrences: list[dict[str, Any]] = []
    items = _item_spans(body)
    opening_pattern = re.compile(
        rf"(?m)^<!-- noctis:extension {re.escape(args.id)} -->\s*$"
    )
    closing_pattern = re.compile(r"(?m)^<!-- /noctis:extension -->\s*$")
    seen_items: set[str | None] = set()
    for opening in opening_pattern.finditer(body):
        closing = closing_pattern.search(body, opening.end())
        if closing is None:
            raise NoctisError(f"extension '{args.id}' is not terminated")
        containing = [
            item_id
            for item_id, start, end in items
            if start <= opening.start() and closing.end() <= end
        ]
        item_id = containing[0] if containing else None
        if item_id in seen_items:
            location = f"item '{item_id}'" if item_id else "document scope"
            raise NoctisError(f"duplicate extension '{args.id}' in {location}")
        seen_items.add(item_id)
        occurrences.append(
            {
                "item": item_id,
                "content": body[opening.end() : closing.start()].strip("\n"),
            }
        )
    if args.item is not None:
        occurrences = [entry for entry in occurrences if entry["item"] == args.item]
    if args.format == "markdown":
        return "\n\n".join(entry["content"] for entry in occurrences) + (
            "\n" if occurrences else ""
        )
    return {
        "ok": True,
        "document": metadata["document"],
        "revision": metadata["revision"],
        "extension": args.id,
        "occurrences": occurrences,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Noctis execution lifecycle and structured document toolchain."
    )
    groups = parser.add_subparsers(dest="group", required=True)

    entry = groups.add_parser(
        "entry", help="Prepare a context-free entry into the execution lifecycle."
    )
    entry.add_argument("--start", type=Path, default=Path.cwd())
    entry.add_argument("--record", type=Path)
    entry.add_argument("--id")

    orchestration = groups.add_parser(
        "orchestration", help="Operate Task, Unit, and Work orchestration."
    )
    actions = orchestration.add_subparsers(dest="action", required=True)

    create = actions.add_parser("create")
    create.add_argument("--level", choices=VALID_LEVELS, required=True)
    create.add_argument("--path", type=Path, required=True)
    create.add_argument("--input", default="-")
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
    finish.add_argument(
        "--to-status", choices=("completed", "blocked"), required=True
    )
    finish.add_argument("--outcome", required=True)
    finish.add_argument(
        "--artifacts", help="Artifact JSON file, or '-' for standard input."
    )
    finish.add_argument("--expected-revision", type=int, required=True)

    splice = actions.add_parser("splice")
    splice.add_argument("--path", type=Path, required=True)
    splice.add_argument("--after", required=True)
    splice.add_argument("--expected-revision", type=int, required=True)
    splice.add_argument("--input", default="-")

    scan = actions.add_parser("scan")
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--level", choices=("all", *VALID_LEVELS), default="all")
    scan.add_argument(
        "--status",
        choices=("all", *VALID_ORCHESTRATION_STATUSES),
        default="all",
    )

    extend = groups.add_parser("extend", help="Operate structured Markdown extensions.")
    extend_actions = extend.add_subparsers(dest="action", required=True)
    for name in ("insert", "upsert", "sync", "remove"):
        command = extend_actions.add_parser(name)
        command.add_argument("--document", type=Path, required=True)
        command.add_argument("--slot", required=True)
        command.add_argument(
            "--scope", choices=("once", "each", "item"), required=True
        )
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


def _print_result(result: dict[str, Any] | str) -> None:
    if isinstance(result, str):
        sys.stdout.write(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    args = parse_args()
    try:
        if args.group == "entry":
            result = prepare_entry(args)
        elif args.group == "orchestration":
            if args.action == "create":
                result = create_orchestration(args)
            elif args.action == "inspect":
                result = inspect_orchestration(args)
            elif args.action in ("start", "resume", "finish"):
                result = mutate_item_status(args)
            elif args.action == "splice":
                result = splice_tasks(args)
            else:
                result = scan_orchestrations(args)
        elif args.action == "read":
            result = read_extension(args)
        else:
            result = mutate_extension(args)
    except (OSError, UnicodeError, json.JSONDecodeError, NoctisError) as error:
        print(
            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    _print_result(result)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
