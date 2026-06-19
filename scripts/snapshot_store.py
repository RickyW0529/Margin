#!/usr/bin/env python3
"""CLI to write/read snapshots for storage audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from margin.core.snapshot_store import FileSnapshotStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Margin snapshot store CLI")
    parser.add_argument("--base-path", default=str(Path.home() / ".margin" / "snapshots"))
    sub = parser.add_subparsers(dest="command")

    write_parser = sub.add_parser("write")
    write_parser.add_argument("--type", required=True)
    write_parser.add_argument("--object-id", required=True)
    write_parser.add_argument("--payload", required=True, help="JSON string")

    read_parser = sub.add_parser("read")
    read_parser.add_argument("snapshot_id", nargs="?")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--type", required=True)
    list_parser.add_argument("--object-id", required=True)

    args = parser.parse_args(argv)
    store = FileSnapshotStore(args.base_path)

    if args.command == "write":
        entry = store.write(
            object_type=args.type,
            object_id=args.object_id,
            payload=json.loads(args.payload),
        )
        print(
            json.dumps(
                {
                    "snapshot_id": entry.snapshot_id,
                    "sha256": entry.sha256,
                    "path": str(entry.snapshot_path),
                }
            )
        )
        return 0
    if args.command == "read":
        entry = store.read(args.snapshot_id)
        print(
            json.dumps(
                {
                    "snapshot_id": entry.snapshot_id,
                    "sha256": entry.sha256,
                    "path": str(entry.snapshot_path),
                }
            )
        )
        return 0
    if args.command == "list":
        entries = store.list_snapshots(args.type, args.object_id)
        print(json.dumps([{"snapshot_id": e.snapshot_id, "sha256": e.sha256} for e in entries]))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
