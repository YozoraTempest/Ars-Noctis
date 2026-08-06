from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[3]
NOCTIS = REPOSITORY / "skills" / "noctis" / "scripts" / "noctis.py"
CASES = (
    ("implementation", REPOSITORY / "skills" / "implement" / "scripts" / "implementation.py", "direction", "completed"),
    ("review", REPOSITORY / "skills" / "code-review" / "scripts" / "review.py", "summary", "findings"),
    ("verification", REPOSITORY / "skills" / "verify" / "scripts" / "verification.py", "plan", "results"),
    ("scenarios", REPOSITORY / "skills" / "verify" / "scripts" / "scenarios.py", None, "scenarios"),
)


class AtomicDocumentTests(unittest.TestCase):
    def run_script(
        self, script: Path, *arguments: str, input_value: dict | None = None
    ) -> dict:
        result = subprocess.run(
            [sys.executable, str(script), *arguments],
            input=json.dumps(input_value, ensure_ascii=False) if input_value is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"command failed: {result.stderr}\n{result.stdout}")
        return json.loads(result.stdout)

    def test_each_atomic_skill_manages_and_preserves_its_document(self) -> None:
        for document_id, script, base_section, collection in CASES:
            with self.subTest(document=document_id), tempfile.TemporaryDirectory() as directory:
                task = Path(directory) / "task"
                task.mkdir()
                sections = {base_section: "Initial content"} if base_section else {}
                created = self.run_script(
                    script,
                    "create",
                    "--task",
                    str(task),
                    "--input",
                    "-",
                    input_value={"sections": sections},
                )
                self.assertEqual(created["revision"], 1)

                appended = self.run_script(
                    script,
                    "append",
                    "--task",
                    str(task),
                    "--section",
                    collection,
                    "--item",
                    "R01",
                    "--expected-revision",
                    "1",
                    input_value={"content": "### R01\n\nRecorded item"},
                )
                self.assertEqual(appended["revision"], 2)

                extension_file = task / "extension.md"
                extension_file.write_text("Additional workflow state", encoding="utf-8")
                extended = subprocess.run(
                    [
                        sys.executable,
                        str(NOCTIS),
                        "extend",
                        "insert",
                        "--document",
                        str(task / f"{document_id}.md"),
                        "--slot",
                        f"{document_id}.item.after",
                        "--scope",
                        "item",
                        "--item",
                        "R01",
                        "--id",
                        "verify:note",
                        "--content",
                        str(extension_file),
                        "--expected-revision",
                        "2",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if extended.returncode != 0:
                    self.fail(extended.stderr)

                expected_revision = 3
                if base_section:
                    updated = self.run_script(
                        script,
                        "update",
                        "--task",
                        str(task),
                        "--section",
                        base_section,
                        "--expected-revision",
                        "3",
                        input_value={"content": "Updated content"},
                    )
                    self.assertEqual(updated["revision"], 4)
                    expected_revision = 4

                item = self.run_script(
                    script,
                    "read",
                    "--task",
                    str(task),
                    "--item",
                    "R01",
                )
                self.assertIn("Additional workflow state", item["content"])
                self.assertEqual(item["revision"], expected_revision)
                if base_section:
                    section = self.run_script(
                        script,
                        "read",
                        "--task",
                        str(task),
                        "--section",
                        base_section,
                    )
                    self.assertEqual(section["content"], "Updated content")


if __name__ == "__main__":
    unittest.main()
