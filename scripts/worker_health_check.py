#!/usr/bin/env python3
"""Worker container health probe.

The worker has no HTTP port. This probe verifies that the process environment
can import worker wiring and that the database is reachable at the expected
migration head.
"""

from __future__ import annotations

import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from margin.settings import get_settings
from margin.storage.database import DatabaseSettings, create_database_engine


def main() -> int:
    """main."""
    settings = get_settings()
    config = Config("alembic.ini")
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    engine = create_database_engine(DatabaseSettings(url=str(settings.database_url)))
    try:
        with engine.connect() as connection:
            current_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            connection.exec_driver_sql("SELECT 1")
        return 0 if current_head == expected_head else 1
    except Exception:  # noqa: BLE001
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
