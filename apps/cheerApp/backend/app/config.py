"""Runtime configuration — env-var driven, no config framework needed yet."""
from __future__ import annotations

import os


def database_url() -> str:
    """Async SQLAlchemy URL (postgresql+asyncpg://...).

    Defaults to the docker-compose Postgres for local dev
    (see ../docker-compose.yml) so `uvicorn app.main:app` works out of the
    box after `docker compose up -d db`.
    """
    return os.environ.get(
        "CHEERAPP_DATABASE_URL",
        "postgresql+asyncpg://cheerapp:cheerapp@localhost:5433/cheerapp",
    )
