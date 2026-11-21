"""SQLite database access for the persistent memory system."""

import sqlite3

from pathlib import Path
from typing import Union


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "araceli.db"

DbPath = Union[Path, str, None]

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
"""


def get_connection(db_path: DbPath = None) -> sqlite3.Connection:
    """Open a SQLite connection with named-row access enabled."""

    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row

    return connection


def init_database(db_path: DbPath = None) -> Path:
    """Create the memory schema if it does not exist yet."""

    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH

    connection = get_connection(path)

    try:
        with connection:
            connection.executescript(SCHEMA)
    finally:
        connection.close()

    return path
