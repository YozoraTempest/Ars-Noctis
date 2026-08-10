from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SKILL_ROOT.parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "ars.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ars_cli", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ars = load_module()

    def test_all_native_repository_skills_validate(self) -> None:
        expected = {
            "ars",
            "spec",
            "design",
            "implement",
            "test",
            "code-review",
            "verify",
        }
        actual = set()
        for path in sorted((REPOSITORY_ROOT / "skills").iterdir()):
            if (path / "ars.json").is_file():
                manifest = self.ars.validate_skill(path)
                actual.add(manifest["id"])
        self.assertEqual(actual, expected)

    def test_manifest_rejects_unknown_fields_and_effects(self) -> None:
        manifest = {
            "schema": "ars.skill/v1",
            "id": "sample",
            "version": "1.0.0",
            "capabilities": [
                {
                    "id": "sample.run",
                    "description": "Run a sample task.",
                    "accepts": "ars.task/v1",
                    "returns": "ars.result/v1",
                    "effects": ["shell.anything"],
                }
            ],
        }
        with self.assertRaisesRegex(self.ars.ArsError, "unknown values"):
            self.ars.validate_manifest(manifest)
        manifest["capabilities"][0]["effects"] = []
        manifest["private_state"] = "state.md"
        with self.assertRaisesRegex(self.ars.ArsError, "unknown fields"):
            self.ars.validate_manifest(manifest)

    def test_skill_identity_must_match_directory_and_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample"
            root.mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: other\ndescription: Use for a sample operation.\n---\n",
                encoding="utf-8",
            )
            (root / "ars.json").write_text(
                json.dumps(
                    {
                        "schema": "ars.skill/v1",
                        "id": "sample",
                        "version": "1.0.0",
                        "capabilities": [
                            {
                                "id": "sample.run",
                                "description": "Run a sample task.",
                                "accepts": "ars.task/v1",
                                "returns": "ars.result/v1",
                                "effects": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(self.ars.ArsError, "must match"):
                self.ars.validate_skill(root)

    def test_standard_skill_without_manifest_is_not_treated_as_invalid_ars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample"
            root.mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: sample\ndescription: Sample.\n---\n",
                encoding="utf-8",
            )
            self.assertEqual(self.ars.inspect_skill(root)["status"], "standard")

    def test_arbitrary_directory_is_not_reported_as_a_standard_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(self.ars.ArsError, "not an Agent Skill"):
                self.ars.inspect_skill(Path(directory))

    def test_optional_agent_skills_metadata_does_not_break_identity_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample"
            root.mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: sample\ndescription: Sample capability.\nlicense: MIT\nmetadata:\n  owner: example\n---\n",
                encoding="utf-8",
            )
            manifest = {
                "schema": "ars.skill/v1",
                "id": "sample",
                "version": "1.0.0",
                "capabilities": [
                    {
                        "id": "sample.run",
                        "description": "Run a sample task.",
                        "accepts": "ars.task/v1",
                        "returns": "ars.result/v1",
                        "effects": [],
                    }
                ],
            }
            (root / "ars.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(self.ars.validate_skill(root)["id"], "sample")


if __name__ == "__main__":
    unittest.main()
