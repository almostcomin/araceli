"""Araceli persistent memory package."""

from .database import DEFAULT_DB_PATH, init_database
from .memory_store import (
    CATEGORIES,
    get_recent_memories,
    save_memory,
    search_memories,
    update_memory,
)
from .models import MemoryRecord

__all__ = [
    "CATEGORIES",
    "DEFAULT_DB_PATH",
    "MemoryRecord",
    "get_recent_memories",
    "init_database",
    "save_memory",
    "search_memories",
    "update_memory",
]
