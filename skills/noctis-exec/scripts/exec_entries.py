"""Pure candidate selection for Noctis execution entry discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


ReadyItems = Callable[[dict[str, Any]], list[str]]


def entry_candidates(
    root: Path,
    path: Path,
    metadata: dict[str, Any],
    ready_items: ReadyItems,
) -> list[dict[str, Any]]:
    ready = set(ready_items(metadata["items"]))
    candidates = []
    for item_id, item in metadata["items"].items():
        status = item["status"]
        if status not in {"active", "blocked"} and item_id not in ready:
            continue
        candidates.append(
            {
                "record": path.relative_to(root).as_posix(),
                "id": item_id,
                "title": item["title"],
                "status": "ready" if item_id in ready else status,
                "track": item.get("track"),
                "capability": item.get("capability"),
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["id"])


def entry_summary(
    root: Path,
    path: Path,
    metadata: dict[str, Any],
    ready_items: ReadyItems,
) -> dict[str, Any]:
    return {
        "id": metadata["id"],
        "level": metadata["level"],
        "title": metadata["title"],
        "status": metadata["status"],
        "revision": metadata["revision"],
        "ready": ready_items(metadata["items"]),
        "entries": entry_candidates(root, path, metadata, ready_items),
        "path": path.relative_to(root).as_posix(),
    }


def root_candidates(
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
