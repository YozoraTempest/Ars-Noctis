#!/usr/bin/env python3
"""Check or regenerate standalone Artifact contract modules."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "artifact_contract.py"
TARGETS = (
    ROOT / "skills" / "ars" / "scripts" / "artifact_contract.py",
    ROOT / "skills" / "noctis" / "scripts" / "artifact_contract.py",
    ROOT / "skills" / "noctis-exec" / "scripts" / "artifact_contract.py",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    content = SOURCE.read_bytes()
    different = [
        target
        for target in TARGETS
        if not target.is_file() or target.read_bytes() != content
    ]
    if args.write:
        for target in different:
            write_atomic(target, content)
    elif different:
        for target in different:
            print(target.relative_to(ROOT).as_posix())
        return 1
    action = "updated" if args.write else "verified"
    print(f"{action} {len(TARGETS)} standalone Artifact contract modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
