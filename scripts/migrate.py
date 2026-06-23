#!/usr/bin/env python3
"""Run Alembic migrations inside container.

Used as the migration service entry point in docker-compose so the API and
worker containers can start against an already-migrated database.
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    """main."""
    return subprocess.call(["alembic", "upgrade", "head"])


if __name__ == "__main__":
    sys.exit(main())
