#!/usr/bin/env python3
"""Run Alembic migrations inside container."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    return subprocess.call(["alembic", "upgrade", "head"])


if __name__ == "__main__":
    sys.exit(main())
