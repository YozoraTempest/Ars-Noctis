#!/usr/bin/env python3
"""Create and update this Skill's structured task document."""

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


DOCUMENT_ID = Path(__file__).stem
DOCUMENT_FILE = f"{DOCUMENT_ID}.md"
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class RecordError(ValueError):
    pass


def task_directory(value: Path) -> Path:
    path = value.resolve()
    return path.parent if path.name == "noctis.md" else path


def document_path(value: Path) -> Path:
    return task_directory(value) / DOCUMENT_FILE


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as error:
        raise RecordError(f"file does not exist: {path}") from error


def frontmatter(text: str) -> tuple[list[str], str, dict[str, Any]]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise RecordError("document is missing frontmatter")
    closing = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if closing is None:
        raise RecordError("document frontmatter is not terminated")
    header = lines[1:closing]
    metadata: dict[str, Any] = {}
    for line in header:
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith('"'):
            metadata[key] = json.loads(value)
        elif value.isdigit():
            metadata[key] = int(value)
        else:
            metadata[key] = value
    if metadata.get("document") != DOCUMENT_ID:
        raise RecordError(f"document must declare document: {DOCUMENT_ID}")
    revision = metadata.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RecordError("revision must be a positive integer")
    body = "\n".join(lines[closing + 1 :])
    if text.endswith("\n"):
        body += "\n"
    return header, body, metadata


def render(header: list[str], body: str) -> str:
    return "---\n" + "\n".join(header) + "\n---\n\n" + body.lstrip("\n")


def set_revision(header: list[str], revision: int) -> list[str]:
    result = list(header)
    for index, line in enumerate(result):
        if line.startswith("revision:"):
            result[index] = f"revision: {revision}"
            return result
    raise RecordError("document frontmatter is missing revision")


def slot_span(text: str, slot: str, start: int = 0, end: int | None = None) -> tuple[int, int]:
    limit = len(text) if end is None else end
    opening = re.compile(rf"(?m)^<!-- noctis:slot {re.escape(slot)} -->\s*$")
    closing = re.compile(r"(?m)^<!-- /noctis:slot -->\s*$")
    matches = list(opening.finditer(text, start, limit))
    if len(matches) != 1:
        raise RecordError(f"expected exactly one slot '{slot}'")
    finish = closing.search(text, matches[0].end(), limit)
    if finish is None:
        raise RecordError(f"slot '{slot}' is not terminated")
    return matches[0].end(), finish.start()


def item_span(text: str, item: str) -> tuple[int, int]:
    opening = re.compile(rf"(?m)^<!-- noctis:item {re.escape(item)} -->\s*$")
    closing = re.compile(r"(?m)^<!-- /noctis:item -->\s*$")
    matches = list(opening.finditer(text))
    if len(matches) != 1:
        raise RecordError(f"expected exactly one item '{item}'")
    finish = closing.search(text, matches[0].end())
    if finish is None:
        raise RecordError(f"item '{item}' is not terminated")
    return matches[0].start(), finish.end()


def replace_span(text: str, start: int, end: int, content: str) -> str:
    normalized = content.strip("\r\n")
    replacement = f"\n{normalized}\n" if normalized else "\n"
    return text[:start] + replacement + text[end:]


def input_content(source: str) -> str:
    stream = sys.stdin if source == "-" else Path(source).open(encoding="utf-8-sig")
    try:
        payload = json.load(stream)
    finally:
        if stream is not sys.stdin:
            stream.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
        raise RecordError("input JSON must contain string field 'content'")
    return payload["content"]


def atomic_write(path: Path, content: str) -> None:
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
def lock(path: Path) -> Iterator[None]:
    lock_path = path.parent / f".{path.name}.noctis.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RecordError(f"document is locked: {path}") from error
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def create(args: argparse.Namespace) -> dict[str, Any]:
    target = document_path(args.task)
    if target.exists():
        raise RecordError(f"document already exists: {target}")
    template = Path(__file__).resolve().parent.parent / "assets" / "templates" / DOCUMENT_FILE
    text = read_text(template)
    if args.input is not None:
        payload = json.loads(sys.stdin.read()) if args.input == "-" else json.loads(read_text(Path(args.input)))
        if not isinstance(payload, dict) or not isinstance(payload.get("sections", {}), dict):
            raise RecordError("create input must contain object field 'sections'")
        header, body, _ = frontmatter(text)
        for section, content in payload.get("sections", {}).items():
            if not isinstance(section, str) or not isinstance(content, str):
                raise RecordError("create sections must map strings to strings")
            start, end = slot_span(body, f"{DOCUMENT_ID}.{section}")
            body = replace_span(body, start, end, content)
        text = render(header, body)
    atomic_write(target, text)
    return {"ok": True, "document": DOCUMENT_ID, "path": str(target), "revision": 1}


def read(args: argparse.Namespace) -> dict[str, Any] | str:
    target = document_path(args.task)
    text = read_text(target)
    _, body, metadata = frontmatter(text)
    content = body
    if args.item is not None:
        start, end = item_span(body, args.item)
        content = body[start:end]
        if args.section is not None:
            inner_start, inner_end = slot_span(
                body, f"{DOCUMENT_ID}.{args.section}", start, end
            )
            content = body[inner_start:inner_end].strip("\n")
    elif args.section is not None:
        start, end = slot_span(body, f"{DOCUMENT_ID}.{args.section}")
        content = body[start:end].strip("\n")
    if args.format == "markdown":
        return content + ("\n" if content and not content.endswith("\n") else "")
    return {
        "ok": True,
        "document": DOCUMENT_ID,
        "revision": metadata["revision"],
        "section": args.section,
        "item": args.item,
        "content": content,
    }


def mutate(args: argparse.Namespace) -> dict[str, Any]:
    target = document_path(args.task)
    content = input_content(args.input)
    with lock(target):
        text = read_text(target)
        header, body, metadata = frontmatter(text)
        if metadata["revision"] != args.expected_revision:
            raise RecordError(
                f"revision mismatch: expected {args.expected_revision}, found {metadata['revision']}"
            )
        if args.action == "update":
            region_start, region_end = (0, len(body))
            if args.item is not None:
                region_start, region_end = item_span(body, args.item)
            start, end = slot_span(
                body, f"{DOCUMENT_ID}.{args.section}", region_start, region_end
            )
            body = replace_span(body, start, end, content)
        else:
            if not ITEM_ID.fullmatch(args.item):
                raise RecordError("append item id is invalid")
            if re.search(rf"(?m)^<!-- noctis:item {re.escape(args.item)} -->\s*$", body):
                raise RecordError(f"item already exists: {args.item}")
            start, end = slot_span(body, f"{DOCUMENT_ID}.{args.section}")
            item = (
                f"<!-- noctis:item {args.item} -->\n"
                f"{content.strip()}\n\n"
                f"<!-- noctis:slot {DOCUMENT_ID}.item.after -->\n"
                "<!-- /noctis:slot -->\n"
                "<!-- /noctis:item -->"
            )
            existing = body[start:end].rstrip()
            body = replace_span(body, start, end, existing + ("\n\n" if existing else "") + item)
        revision = metadata["revision"] + 1
        atomic_write(target, render(set_revision(header, revision), body))
    return {"ok": True, "document": DOCUMENT_ID, "revision": revision}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Manage {DOCUMENT_ID}.md with revision-checked writes.",
        epilog=(
            "JSON: create accepts {\"sections\": {\"<section>\": \"text\"}}; "
            "update/append accept {\"content\": \"markdown\"}."
        ),
    )
    commands = parser.add_subparsers(dest="action", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument(
        "--task", type=Path, required=True, help="Task directory or noctis.md path."
    )
    create_parser.add_argument(
        "--input", help="Optional sections JSON file, or '-' for standard input."
    )
    read_parser = commands.add_parser("read")
    read_parser.add_argument("--task", type=Path, required=True)
    read_parser.add_argument("--section", help="Read one owned slot.")
    read_parser.add_argument("--item", help="Read one stable collection item.")
    read_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    for name in ("update", "append"):
        command = commands.add_parser(name)
        command.add_argument("--task", type=Path, required=True)
        command.add_argument("--section", required=True, help="Owned slot or collection.")
        command.add_argument("--item", required=name == "append", help="Stable item ID.")
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument(
            "--input", default="-", help="Content JSON file, or '-' for standard input."
        )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = create(args) if args.action == "create" else read(args) if args.action == "read" else mutate(args)
    except (OSError, UnicodeError, json.JSONDecodeError, RecordError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    if isinstance(result, str):
        sys.stdout.write(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
