#!/usr/bin/env python3
"""Run repository-wide Skill, Ars, runtime, trigger, and unittest validation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
ARS = SKILLS / "ars" / "scripts" / "ars.py"
ARS_NOCTIS = SKILLS / "ars" / "scripts" / "ars_noctis.py"
NOCTIS = SKILLS / "noctis" / "scripts" / "noctis.py"
EXAMPLE_PLAN = SKILLS / "noctis" / "assets" / "plan.example.json"
ARS_EXAMPLE_PLAN = SKILLS / "ars" / "assets" / "noctis-plan.example.json"
ARS_EXAMPLE_EXTENSION = SKILLS / "ars" / "assets" / "noctis-extension.example.json"
EVALS = ROOT / "scripts" / "validate_evals.py"


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
        cwd=ROOT,
        env=env,
        check=False,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def test_directories() -> list[Path]:
    result = []
    for directory in [ROOT / "tests", *sorted(SKILLS.glob("*/tests"))]:
        if directory.is_dir() and any(directory.glob("test_*.py")):
            result.append(directory)
    return result


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
        path for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
    )
    native = [path for path in skill_directories if (path / "ars.json").is_file()]
    suites = test_directories()
    if not suites:
        print("no unittest directories were discovered", file=sys.stderr)
        return 2

    try:
        run([python, str(EVALS)], env)
        for skill in native:
            run([python, str(ARS), "validate", "--skill", str(skill)], env)
        for skill in skill_directories:
            run([python, str(quick_validate), str(skill)], env)
        run(
            [
                python,
                str(NOCTIS),
                "plan-check",
                "--plan",
                str(EXAMPLE_PLAN),
            ],
            env,
        )
        run(
            [
                python,
                str(ARS_NOCTIS),
                "plan-adapt",
                "--project",
                str(ROOT),
                "--plan",
                str(ARS_EXAMPLE_PLAN),
                "--skills-root",
                str(SKILLS),
            ],
            env,
        )
        run(
            [
                python,
                str(ARS_NOCTIS),
                "extension-adapt",
                "--project",
                str(ROOT),
                "--extension",
                str(ARS_EXAMPLE_EXTENSION),
                "--skills-root",
                str(SKILLS),
            ],
            env,
        )
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
        f"Validation passed: {len(native)} Ars manifests, "
        f"{len(skill_directories)} Skills, {len(suites)} unittest suites."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
