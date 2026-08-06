#!/usr/bin/env python3
"""Operate Noctis task state and structured Markdown extensions."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator


IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXTENSION_ID = re.compile(
    r"^[a-z0-9]+(?:-[a-z0-9]+)*:[a-z0-9]+(?:-[a-z0-9]+)*$"
)
VALID_STATUSES = ("active", "completed", "blocked")


class NoctisError(ValueError):
    """Raised when a task or structured document violates its interface."""


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


def _top_level_metadata(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            metadata[key] = _parse_scalar(raw_value)
            index += 1
            continue
        values: list[Any] = []
        cursor = index + 1
        while cursor < len(lines):
            nested = lines[cursor]
            if nested and not nested.startswith((" ", "\t")):
                break
            match = re.fullmatch(r"  -\s+(.+)", nested)
            if match:
                values.append(_parse_scalar(match.group(1)))
            cursor += 1
        if values:
            metadata[key] = values
        index = cursor
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
        if isinstance(value, list):
            replacement = [f"{key}:", *[f"  - {_json_scalar(item)}" for item in value]]
        else:
            replacement = [f"{key}: {_json_scalar(value)}"]
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


def _validate_task(metadata: dict[str, Any]) -> None:
    _validate_common(metadata)
    if metadata["document"] != "task":
        raise NoctisError("tasks.md must declare document: task")
    status = metadata.get("status")
    if status not in VALID_STATUSES:
        raise NoctisError("task status must be active, completed, or blocked")
    stage = metadata.get("stage")
    if status == "completed":
        if stage is not None:
            raise NoctisError("completed task must not declare a stage")
    elif not isinstance(stage, str) or not IDENTIFIER.fullmatch(stage):
        raise NoctisError("active or blocked task must declare a valid stage")
    workflow = metadata.get("workflow")
    if not isinstance(workflow, list) or not workflow:
        raise NoctisError("task workflow must be a non-empty list")
    if any(not isinstance(item, str) or not IDENTIFIER.fullmatch(item) for item in workflow):
        raise NoctisError("task workflow contains an invalid stage id")


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


def _task_path(value: Path) -> Path:
    path = value.resolve()
    if path.name == "tasks.md" or path.suffix.lower() == ".md":
        return path
    return path / "tasks.md"


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


def create_task(args: argparse.Namespace) -> dict[str, Any]:
    path = _task_path(args.task)
    if path.exists():
        raise NoctisError(f"task already exists: {path}")
    payload = _load_json(args.input)
    title = payload.get("title")
    objective = payload.get("objective")
    snapshot = payload.get("workflowSnapshot")
    if not isinstance(title, str) or not title.strip():
        raise NoctisError("input.title must not be empty")
    if not isinstance(objective, str) or not objective.strip():
        raise NoctisError("input.objective must not be empty")
    if not isinstance(snapshot, dict) or not snapshot:
        raise NoctisError("input.workflowSnapshot must be a non-empty object")
    workflow = args.workflow
    if not workflow or any(not IDENTIFIER.fullmatch(item) for item in workflow):
        raise NoctisError("workflow contains an invalid stage id")
    if args.stage not in workflow:
        raise NoctisError("initial stage must be present in workflow")

    template_path = Path(__file__).resolve().parent.parent / "assets" / "templates" / "tasks.md"
    body = _read_text(template_path)
    body = body.replace("{{title}}", title.strip()).replace(
        "{{objective}}", objective.strip()
    )
    frontmatter = [
        "document: \"task\"",
        "template: \"noctis/task@1\"",
        "revision: 1",
        "status: \"active\"",
        f"stage: {_json_scalar(args.stage)}",
        "workflow:",
        *[f"  - {_json_scalar(stage)}" for stage in workflow],
        "workflow_snapshot:",
        *_yaml_lines(snapshot, 2),
    ]
    content = _render_document(frontmatter, body)
    _atomic_write(path, content)
    return {"ok": True, "status": "created", "path": str(path), "revision": 1}


def inspect_task(args: argparse.Namespace) -> dict[str, Any] | str:
    path = _task_path(args.task)
    text = _read_text(path)
    frontmatter, body = _frontmatter(text)
    metadata = _top_level_metadata(frontmatter)
    _validate_task(metadata)
    if args.format == "markdown":
        return text
    return {"ok": True, "path": str(path), "metadata": metadata, "content": body}


def transition_task(args: argparse.Namespace) -> dict[str, Any]:
    path = _task_path(args.task)
    with _document_lock(path):
        text = _read_text(path)
        frontmatter, body = _frontmatter(text)
        metadata = _top_level_metadata(frontmatter)
        _validate_task(metadata)
        if metadata["status"] == "completed":
            raise NoctisError("completed task cannot transition")
        if metadata["revision"] != args.expected_revision:
            raise NoctisError(
                f"revision mismatch: expected {args.expected_revision}, "
                f"found {metadata['revision']}"
            )
        if metadata["stage"] != args.from_stage:
            raise NoctisError(
                f"stage mismatch: expected {args.from_stage}, found {metadata['stage']}"
            )
        status = args.to_status
        if status == "completed":
            if args.to_stage is not None:
                raise NoctisError("completed transition cannot declare --to-stage")
            next_stage = None
        else:
            next_stage = args.to_stage or metadata["stage"]
            if not IDENTIFIER.fullmatch(next_stage):
                raise NoctisError("target stage is invalid")

        frontmatter = _replace_top_level(frontmatter, "status", status)
        frontmatter = _replace_top_level(frontmatter, "stage", next_stage)
        revision = metadata["revision"] + 1
        frontmatter = _replace_top_level(frontmatter, "revision", revision)
        _atomic_write(path, _render_document(frontmatter, body))
    return {
        "ok": True,
        "path": str(path),
        "status": status,
        "stage": next_stage,
        "revision": revision,
    }


def _task_files(root: Path) -> list[Path]:
    noctis_root = root / "Noctis"
    if not noctis_root.is_dir():
        return []
    files = {
        *noctis_root.glob("*/tasks/*/tasks.md"),
        *noctis_root.glob("*/tasks/*/*/tasks.md"),
    }
    return sorted(files, key=lambda path: path.as_posix().lower())


def scan_tasks(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    if not root.is_dir():
        raise NoctisError(f"project root does not exist: {root}")
    tasks: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in _task_files(root):
        try:
            frontmatter, _ = _frontmatter(_read_text(path))
            metadata = _top_level_metadata(frontmatter)
            _validate_task(metadata)
        except (OSError, UnicodeError, NoctisError) as error:
            errors.append(f"{path.relative_to(root).as_posix()}: {error}")
            continue
        if args.status != "all" and metadata["status"] != args.status:
            continue
        if args.stage != "all" and metadata.get("stage") != args.stage:
            continue
        relative = path.relative_to(root / "Noctis")
        parts = relative.parts
        tasks.append(
            {
                "status": metadata["status"],
                "stage": metadata.get("stage"),
                "workflow": metadata["workflow"],
                "revision": metadata["revision"],
                "domain": parts[0],
                "task": parts[2],
                "subtask": parts[3] if len(parts) == 5 else None,
                "path": path.relative_to(root).as_posix(),
            }
        )
    return {"ok": not errors, "projectRoot": str(root), "tasks": tasks, "errors": errors}


def _item_spans(text: str) -> list[tuple[str, int, int]]:
    start_pattern = re.compile(r"(?m)^<!-- noctis:item ([A-Za-z0-9][A-Za-z0-9._:-]*) -->\s*$")
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


def _slot_inner_spans(text: str, slot: str, start: int, end: int) -> list[tuple[int, int]]:
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


def _targets(text: str, slot: str, scope: str, item: str | None) -> list[tuple[str | None, int, int]]:
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


def _extension_span(text: str, extension_id: str, start: int, end: int) -> tuple[int, int, str] | None:
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
        for item_id, start, end in sorted(targets, key=lambda target: target[1], reverse=True):
            existing = _extension_span(body, args.id, start, end)
            if args.action == "insert":
                if existing is not None:
                    raise NoctisError(
                        f"extension '{args.id}' already exists"
                        + (f" in item '{item_id}'" if item_id else "")
                    )
                body = _insert_at_slot(body, start, end, _extension_block(args.id, content or ""))
                changed += 1
            elif args.action == "sync":
                if existing is None:
                    body = _insert_at_slot(body, start, end, _extension_block(args.id, content or ""))
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


def _stage(value: str) -> str:
    if value == "all" or IDENTIFIER.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError("stage must be 'all' or a valid stage id")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Noctis task and document toolchain.")
    groups = parser.add_subparsers(dest="group", required=True)

    task = groups.add_parser("task", help="Operate task state.")
    task_actions = task.add_subparsers(dest="action", required=True)

    create = task_actions.add_parser("create")
    create.add_argument("--task", type=Path, required=True)
    create.add_argument("--stage", required=True)
    create.add_argument("--workflow", nargs="+", required=True)
    create.add_argument("--input", default="-")

    inspect = task_actions.add_parser("inspect")
    inspect.add_argument("--task", type=Path, required=True)
    inspect.add_argument("--format", choices=("json", "markdown"), default="json")

    transition = task_actions.add_parser("transition")
    transition.add_argument("--task", type=Path, required=True)
    transition.add_argument("--from-stage", required=True)
    transition.add_argument("--to-stage")
    transition.add_argument(
        "--to-status", choices=VALID_STATUSES, default="active"
    )
    transition.add_argument("--expected-revision", type=int, required=True)

    scan = task_actions.add_parser("scan")
    scan.add_argument("--root", type=Path, required=True)
    scan.add_argument("--status", choices=("all", *VALID_STATUSES), default="all")
    scan.add_argument("--stage", type=_stage, default="all")

    extend = groups.add_parser("extend", help="Operate structured Markdown extensions.")
    extend_actions = extend.add_subparsers(dest="action", required=True)
    for name in ("insert", "upsert", "sync", "remove"):
        command = extend_actions.add_parser(name)
        command.add_argument("--document", type=Path, required=True)
        command.add_argument("--slot", required=True)
        command.add_argument("--scope", choices=("once", "each", "item"), required=True)
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
        if args.group == "task" and args.action == "create":
            result = create_task(args)
        elif args.group == "task" and args.action == "inspect":
            result = inspect_task(args)
        elif args.group == "task" and args.action == "transition":
            result = transition_task(args)
        elif args.group == "task" and args.action == "scan":
            result = scan_tasks(args)
        elif args.group == "extend" and args.action == "read":
            result = read_extension(args)
        else:
            result = mutate_extension(args)
    except (OSError, UnicodeError, json.JSONDecodeError, NoctisError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    _print_result(result)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
