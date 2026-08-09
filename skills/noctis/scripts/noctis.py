#!/usr/bin/env python3
"""Public CLI for the protocol-neutral Noctis runtime."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from noctislib.runtime import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
