#!/usr/bin/env python3
"""Container readiness probe.

Invoked by Docker healthcheck (and CI) to determine whether the API container
is accepting traffic. Exits 0 only when /health/ready returns HTTP 200.
"""

from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    """Probe the API readiness endpoint and return a process exit code.

    Returns:
        int: 0 when the API reports HTTP 200, otherwise 1.
    """
    try:
        with urllib.request.urlopen("http://localhost:8000/health/ready", timeout=5) as resp:
            return 0 if resp.status == 200 else 1
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    sys.exit(main())
