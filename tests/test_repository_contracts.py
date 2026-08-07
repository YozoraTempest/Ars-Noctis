from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
ARS = SKILLS / "ars" / "scripts" / "ars.py"
EXPECTED = {"ars", "noctis", "implement", "code-review", "verify"}


class RepositoryContractTests(unittest.TestCase):
    def test_repository_contains_five_independent_skill_entrypoints(self) -> None:
        actual = {
            path.name for path in SKILLS.iterdir() if (path / "SKILL.md").is_file()
        }
        self.assertEqual(actual, EXPECTED)
        for name in EXPECTED:
            with self.subTest(skill=name):
                root = SKILLS / name
                self.assertTrue((root / "agents" / "openai.yaml").is_file())
        self.assertFalse((SKILLS / "noctis" / "ars.json").exists())

    def test_every_manifest_validates_through_public_cli(self) -> None:
        for name in EXPECTED - {"noctis"}:
            result = subprocess.run(
                [sys.executable, str(ARS), "validate", "--skill", str(SKILLS / name)],
                cwd=ROOT,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            with self.subTest(skill=name):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["ok"])

    def test_manifests_expose_only_discovery_contract(self) -> None:
        expected_fields = {"schema", "id", "version", "capabilities"}
        capability_fields = {"id", "description", "accepts", "returns", "effects"}
        for name in EXPECTED - {"noctis"}:
            manifest = json.loads((SKILLS / name / "ars.json").read_text(encoding="utf-8"))
            with self.subTest(skill=name):
                self.assertEqual(set(manifest), expected_fields)
                self.assertEqual(manifest["schema"], "ars.skill/v1")
                self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
                for capability in manifest["capabilities"]:
                    self.assertEqual(set(capability), capability_fields)
                    self.assertEqual(capability["accepts"], "ars.task/v1")
                    self.assertEqual(capability["returns"], "ars.result/v1")

    def test_no_legacy_manifest_or_split_noctis_entrypoint_remains(self) -> None:
        self.assertFalse(any(SKILLS.glob("*/ars.yaml")))
        for retired in ("to-ars", "noctis-exec", "noctis-continue"):
            self.assertFalse((SKILLS / retired / "SKILL.md").exists())

    def test_atomic_skills_do_not_own_orchestration_state(self) -> None:
        for name in ("implement", "code-review", "verify"):
            root = SKILLS / name
            instructions = (root / "SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn("ars.task/v1", instructions)
                self.assertIn("ars.result/v1", instructions)
                self.assertFalse(any((root / "scripts").glob("*.py")))
                self.assertIn("不", instructions)

    def test_noctis_is_the_single_owner_of_runtime_state(self) -> None:
        instructions = (SKILLS / "noctis" / "SKILL.md").read_text(encoding="utf-8")
        operations = (SKILLS / "noctis" / "references" / "operations.md").read_text(encoding="utf-8")
        self.assertIn(".ars/runs/<run-id>/", instructions)
        self.assertIn("不要手工编辑 `.ars/runs/`", operations)
        self.assertIn("noctis/cache.sqlite3", operations)
        self.assertTrue((SKILLS / "noctis" / "scripts" / "noctis.py").is_file())
        self.assertTrue((SKILLS / "noctis" / "scripts" / "noctis_runtime.py").is_file())
        self.assertFalse((SKILLS / "noctis" / "ars.json").exists())

    def test_noctis_cache_is_local_and_git_json_is_authoritative(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(".ars/runs/<run-id>/", readme)
        self.assertIn("Git 元数据目录", readme)
        self.assertIn("追加式 JSON + Git", readme)
        self.assertNotIn("SQLite Run 与 Task 状态", readme)

    def test_openai_metadata_default_prompts_name_the_skill(self) -> None:
        for name in EXPECTED:
            content = (SKILLS / name / "agents" / "openai.yaml").read_text(encoding="utf-8")
            with self.subTest(skill=name):
                self.assertIn(f"${name}", content)

    def test_readme_records_framework_choices_and_non_goals(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for framework in ("Agent Skills", "MCP", "A2A", "LangGraph", "CrewAI", "OpenAI Agents SDK", "AutoGen"):
            self.assertIn(framework, readme)
        self.assertIn("不实现网络传输", readme)
        self.assertIn("Python 3.11+ 标准库", readme)


if __name__ == "__main__":
    unittest.main()
