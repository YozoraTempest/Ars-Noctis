#!/usr/bin/env python3
"""Public CLI and import surface for the Noctis runtime."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from noctis_runtime import *  # noqa: F401,F403,E402


if __name__ == "__main__":
    raise SystemExit(main())
