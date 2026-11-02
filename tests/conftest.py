import asyncio
import os
import tempfile
from pathlib import Path

import pytest

_database_file = tempfile.NamedTemporaryFile(
    prefix="mini-saas-tests-",
    suffix=".sqlite3",
    delete=False,
)
TEST_DATABASE_PATH = Path(_database_file.name)
_database_file.close()
os.environ["DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
)
os.environ["SECRET_KEY"] = "pytest-only-mini-saas-secret"


@pytest.fixture(scope="session", autouse=True)
def temporary_database():
    yield TEST_DATABASE_PATH
    from app.database.base import engine

    asyncio.run(engine.dispose())
    for path in (
        TEST_DATABASE_PATH,
        Path(f"{TEST_DATABASE_PATH}-wal"),
        Path(f"{TEST_DATABASE_PATH}-shm"),
    ):
        path.unlink(missing_ok=True)
