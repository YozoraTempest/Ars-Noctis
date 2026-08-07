#!/usr/bin/env python3
"""Check or regenerate standalone structured-document tools."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "document_tool.py"
TARGETS = (
    ROOT / "skills" / "implement" / "scripts" / "implementation.py",
    ROOT / "skills" / "code-review" / "scripts" / "review.py",
    ROOT / "skills" / "verify" / "scripts" / "scenarios.py",
    ROOT / "skills" / "verify" / "scripts" / "verification.py",
)


def write_atomic(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def sync(*, write: bool) -> list[Path]:
    content = SOURCE.read_bytes()
    different = [
        target
        for target in TARGETS
        if not target.is_file() or target.read_bytes() != content
    ]
    if write:
        for target in different:
            write_atomic(target, content)
    return different


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Regenerate divergent Skill copies."
    )
    args = parser.parse_args()
    different = sync(write=args.write)
    if different and not args.write:
        for path in different:
            print(path.relative_to(ROOT).as_posix())
        return 1
    action = "updated" if args.write else "verified"
    print(f"{action} {len(TARGETS)} standalone document tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
