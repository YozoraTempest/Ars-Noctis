from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = SKILL_ROOT / "scripts" / "init_registry.py"


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_input() -> dict:
    return {
        "version": 2,
        "default_workflow": "reviewed",
        "executors": {
            "code-review": {"provider": "code-review", "source": "manifest"},
            "implement": {"provider": "implement", "source": "manifest"},
            "verify": {"provider": "verify", "source": "manifest"},
        },
        "supports": {},
        "capabilities": {
            "fix": {"contract": 1, "executor": "implement", "supports": {}},
            "implement": {
                "contract": 1,
                "executor": "implement",
                "supports": {},
            },
            "review": {
                "contract": 1,
                "executor": "code-review",
                "supports": {},
            },
            "verify": {"contract": 1, "executor": "verify", "supports": {}},
        },
        "workflow_templates": {
            "reviewed": {
                "description": "默认工程修改",
                "tasks": {
                    "implement": {"capability": "implement", "depends_on": []},
                    "review": {
                        "capability": "review",
                        "depends_on": ["implement"],
                    },
                },
            },
            "verified": {
                "description": "包含实际行为验收",
                "tasks": {
                    "implement": {"capability": "implement", "depends_on": []},
                    "review": {
                        "capability": "review",
                        "depends_on": ["implement"],
                    },
                    "verify": {
                        "capability": "verify",
                        "depends_on": ["review"],
                    },
                },
            },
        },
    }


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script("init_registry", INIT_SCRIPT)

    def test_default_registry_matches_golden_file(self) -> None:
        expected = (SKILL_ROOT / "assets" / "registry.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(self.module.render_registry(registry_input()), expected)

    def test_install_does_not_replace_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status, target, _ = self.module.install_registry(root, registry_input())
            self.assertEqual(status, "created")
            original = target.read_text(encoding="utf-8")
            changed = registry_input()
            changed["workflow_templates"]["reviewed"]["description"] = "另一种说明"
            status, _, diff = self.module.install_registry(root, changed)
            self.assertEqual(status, "different")
            self.assertIn("另一种说明", diff)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            status, _, _ = self.module.install_registry(root, changed, replace=True)
            self.assertEqual(status, "replaced")

    def test_workflow_allows_repeated_capability(self) -> None:
        value = registry_input()
        tasks = value["workflow_templates"]["reviewed"]["tasks"]
        tasks["second-implement"] = {
            "capability": "implement",
            "depends_on": [],
        }
        tasks["review"]["depends_on"].append("second-implement")
        self.module.validate_registry(value)

    def test_fix_and_cycles_are_rejected_in_normal_workflows(self) -> None:
        value = registry_input()
        value["workflow_templates"]["reviewed"]["tasks"]["repair"] = {
            "capability": "fix",
            "depends_on": ["review"],
        }
        with self.assertRaisesRegex(self.module.RegistryError, "recovery capability"):
            self.module.validate_registry(value)
        value = registry_input()
        value["workflow_templates"]["reviewed"]["tasks"]["implement"][
            "depends_on"
        ] = ["review"]
        with self.assertRaisesRegex(self.module.RegistryError, "dependency cycle"):
            self.module.validate_registry(value)


if __name__ == "__main__":
    unittest.main()
