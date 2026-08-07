#!/usr/bin/env python3
"""Run repository-wide Ars, Skill, and unittest validation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
ARS_TOOL = SKILLS_ROOT / "ars" / "scripts" / "ars.py"
DOCUMENT_TOOL_SYNC = REPOSITORY_ROOT / "scripts" / "sync_document_tools.py"
EVAL_VALIDATOR = REPOSITORY_ROOT / "scripts" / "validate_evals.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick-validate",
        type=Path,
        required=True,
        help="Path to the official skill-creator quick_validate.py.",
    )
    return parser.parse_args()


def run(command: list[str], env: dict[str, str]) -> None:
    print("[RUN] " + " ".join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=env,
        check=False,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def test_directories() -> list[Path]:
    directories = []
    repository_tests = REPOSITORY_ROOT / "tests"
    if any(repository_tests.glob("test_*.py")):
        directories.append(repository_tests)
    directories.extend(
        path
        for path in sorted(SKILLS_ROOT.glob("*/tests"))
        if any(path.glob("test_*.py"))
    )
    return directories


def main() -> int:
    args = parse_args()
    quick_validate = args.quick_validate.resolve()
    if not quick_validate.is_file():
        print(f"quick_validate.py does not exist: {quick_validate}", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    python = sys.executable
    skill_directories = sorted(
        path for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").is_file()
    )
    native_ars = [path for path in skill_directories if (path / "ars.yaml").is_file()]
    suites = test_directories()
    if not suites:
        print("no unittest directories were discovered", file=sys.stderr)
        return 2

    try:
        run([python, str(DOCUMENT_TOOL_SYNC)], env)
        run([python, str(EVAL_VALIDATOR)], env)
        for skill in native_ars:
            run(
                [python, str(ARS_TOOL), "validate", "--skill", str(skill)],
                env,
            )
        for skill in skill_directories:
            run([python, str(quick_validate), str(skill)], env)
        for suite in suites:
            run(
                [
                    python,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(suite),
                    "-p",
                    "test_*.py",
                    "-v",
                ],
                env,
            )
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(
        f"Validation passed: {len(native_ars)} Ars manifests, "
        f"{len(skill_directories)} Skills, {len(suites)} unittest suites."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
