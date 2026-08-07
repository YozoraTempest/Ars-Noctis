from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = SKILL_ROOT.parent
ARS_SCRIPT = SKILL_ROOT / "scripts" / "ars.py"


def load_script():
    spec = importlib.util.spec_from_file_location("ars_tool", ARS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(name: str = "sample") -> dict:
    return {
        "version": 1,
        "kind": "ars",
        "name": name,
        "role": "executor",
        "state": {"mode": "stateless"},
        "capabilities": [
            {
                "id": "sample",
                "contract": 1,
                "inputs": {},
                "outputs": {},
                "side_effects": [],
            }
        ],
        "supports": [],
        "documents": [],
        "augmentations": [],
    }


class ArsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def run_tool(self, *arguments: str, ok: bool = True):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(ARS_SCRIPT), *arguments],
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if ok and result.returncode != 0:
            self.fail(f"command failed: {result.stderr}\n{result.stdout}")
        if not ok and result.returncode == 0:
            self.fail(f"command unexpectedly succeeded: {result.stdout}")
        return result

    def test_repository_native_ars_are_valid(self) -> None:
        for name in (
            "ars",
            "to-ars",
            "noctis",
            "noctis-exec",
            "noctis-continue",
            "implement",
            "code-review",
            "verify",
        ):
            with self.subTest(skill=name):
                validated = self.module.validate_skill(SKILLS_ROOT / name)
                self.assertEqual(validated["name"], name)

    def test_inspect_distinguishes_external_and_legacy_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()
            self.assertEqual(
                self.module.inspect_skill(external)["status"], "external"
            )
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "noctis.yaml").write_text("version: 1\n", encoding="utf-8")
            self.assertEqual(self.module.inspect_skill(legacy)["status"], "legacy")

    def test_create_is_deterministic_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "sample"
            root.mkdir()
            (root / "SKILL.md").write_text(
                "---\nname: sample\ndescription: Sample Ars for validation.\n---\n\n# Sample\n",
                encoding="utf-8",
            )
            input_file = root / "manifest.json"
            input_file.write_text(json.dumps(manifest()), encoding="utf-8")
            created = self.run_tool(
                "create", "--skill", str(root), "--input", str(input_file)
            )
            self.assertEqual(json.loads(created.stdout)["status"], "created")
            unchanged = self.run_tool(
                "create", "--skill", str(root), "--input", str(input_file)
            )
            self.assertEqual(json.loads(unchanged.stdout)["status"], "unchanged")

            changed = manifest()
            changed["capabilities"][0]["side_effects"] = ["filesystem-write"]
            input_file.write_text(json.dumps(changed), encoding="utf-8")
            protected = self.run_tool(
                "create", "--skill", str(root), "--input", str(input_file), ok=False
            )
            self.assertEqual(protected.returncode, 2)
            self.assertIn("different", protected.stdout)

    def test_invalid_format_and_state_are_rejected(self) -> None:
        value = manifest()
        value["capabilities"][0]["outputs"] = {
            "result": {
                "type": "result",
                "formats": ["missing-version"],
                "required": True,
            }
        }
        with self.assertRaisesRegex(self.module.ArsError, "invalid format"):
            self.module.validate_manifest(value)

        value = manifest()
        value["documents"] = [
            {
                "id": "record",
                "contract": 1,
                "file": "record.md",
                "template": "assets/record.md",
                "tool": "scripts/record.py",
            }
        ]
        with self.assertRaisesRegex(self.module.ArsError, "stateless state"):
            self.module.validate_manifest(value)

    def test_many_ports_and_unit_documents_are_normalized(self) -> None:
        value = manifest()
        value["capabilities"][0]["inputs"] = {
            "sources": {
                "type": "result",
                "formats": ["sample.result@1"],
                "required": True,
                "cardinality": "many",
            }
        }
        normalized = self.module.validate_manifest(value)
        self.assertEqual(
            normalized["capabilities"][0]["inputs"]["sources"]["cardinality"],
            "many",
        )

        value = manifest()
        value["state"] = {"mode": "documents"}
        value["documents"] = [
            {
                "id": "scenarios",
                "contract": 1,
                "scope": "unit",
                "file": "scenarios.md",
                "template": "assets/scenarios.md",
                "tool": "scripts/scenarios.py",
            }
        ]
        normalized = self.module.validate_manifest(value)
        self.assertEqual(normalized["documents"][0]["scope"], "unit")

        value["documents"][0]["scope"] = "work"
        with self.assertRaisesRegex(self.module.ArsError, "scope"):
            self.module.validate_manifest(value)


if __name__ == "__main__":
    unittest.main()
