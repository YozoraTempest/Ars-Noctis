from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "exec.py"


def load_module():
    spec = importlib.util.spec_from_file_location("noctis_exec_locking", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_live_process_lock_blocks_and_dead_process_lock_is_reclaimed(self) -> None:
        holder_source = """import importlib.util, pathlib, sys, time
script = pathlib.Path(sys.argv[1])
document = pathlib.Path(sys.argv[2])
stop = pathlib.Path(sys.argv[3])
spec = importlib.util.spec_from_file_location('holder_exec', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with module._document_lock(document):
    print('ready', flush=True)
    while not stop.exists():
        time.sleep(0.05)
"""
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "noctis.md"
            stop = Path(directory) / "stop"
            document.write_text("placeholder", encoding="utf-8")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    holder_source,
                    str(SCRIPT),
                    str(document),
                    str(stop),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "ready")
                with self.assertRaisesRegex(self.module.NoctisError, "locked"):
                    with self.module._document_lock(document):
                        self.fail("live lock was not enforced")
            finally:
                stop.touch()
                process.wait(timeout=10)
                process.stdout.close()
                process.stderr.close()

            lock_path = document.parent / ".noctis.md.noctis.lock"
            self.assertFalse(lock_path.exists())
            lock_path.write_text(
                json.dumps({"pid": 2147483647, "token": "abandoned"}),
                encoding="utf-8",
            )
            with self.module._document_lock(document):
                owner = json.loads(lock_path.read_text(encoding="utf-8"))
                self.assertEqual(owner["pid"], os.getpid())
            self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
