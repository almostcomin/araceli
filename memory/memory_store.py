"""Persistent memory operations: save, search, update, and retrieval."""

from datetime import datetime, timezone
from typing import Any

from .database import DbPath, get_connection
from .models import MemoryRecord


CATEGORIES = (
    "preference",
    "personal",
    "decision",
    "task",
    "fact",
    "knowledge",
)

STATUSES = ("active", "superseded")

MAX_TITLE_LENGTH = 200
MAX_CONTENT_LENGTH = 4000
MAX_TAGS_LENGTH = 200
MAX_SOURCE_LENGTH = 500
MAX_QUERY_LENGTH = 200

DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
DEFAULT_SNAPSHOT_LIMIT = 15
MAX_SNAPSHOT_LIMIT = 50

_COLUMN_LIST = (
    "id, category, title, content, tags, status, source, "
    "created_at, updated_at"
)


def _utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _validate_text(
    value: Any,
    field_name: str,
    max_length: int,
    allow_empty: bool = False,
    hint: str | None = None,
) -> str:
    """Validate and normalize a text field."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")

    text = value.strip()

    if not text and not allow_empty:
        raise ValueError(f"{field_name} must not be empty.")

    if len(text) > max_length:
        message = (
            f"{field_name} exceeds the maximum length of "
            f"{max_length} characters."
        )

        if hint:
            message += f" {hint}"

        raise ValueError(message)

    return text


def _validate_category(category: Any) -> str:
    """Validate a memory category against the allowlist."""

    category = _validate_text(category, "category", 50)

    if category not in CATEGORIES:
        allowed = ", ".join(CATEGORIES)
        raise ValueError(f"category must be one of: {allowed}.")

    return category


def _validate_status(status: Any) -> str:
    """Validate a memory status against the allowlist."""

    status = _validate_text(status, "status", 20)

    if status not in STATUSES:
        allowed = ", ".join(STATUSES)
        raise ValueError(f"status must be one of: {allowed}.")

    return status


def _validate_limit(limit: Any, max_limit: int) -> int:
    """Validate a result limit."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")

    if not 1 <= limit <= max_limit:
        raise ValueError(f"limit must be between 1 and {max_limit}.")

    return limit


def _escape_like(query: str) -> str:
    """Escape LIKE wildcards so search text matches literally."""

    return (
        query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _fetch_by_id(
    connection: Any,
    memory_id: int,
) -> MemoryRecord | None:
    """Fetch a single memory row by id."""

    row = connection.execute(
        f"SELECT {_COLUMN_LIST} FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()

    return MemoryRecord.from_row(row) if row is not None else None


def _fetch_active_duplicate(
    connection: Any,
    category: str,
    title: str,
    exclude_id: int | None = None,
) -> int | None:
    """Return the id of an active memory with the same category and title."""

    query = (
        "SELECT id FROM memories "
        "WHERE category = ? AND title = ? AND status = 'active'"
    )
    parameters: list[Any] = [category, title]

    if exclude_id is not None:
        query += " AND id != ?"
        parameters.append(exclude_id)

    row = connection.execute(query, parameters).fetchone()

    return int(row["id"]) if row is not None else None


def save_memory(
    category: str,
    title: str,
    content: str,
    tags: str = "",
    source: str | None = None,
    db_path: DbPath = None,
) -> MemoryRecord:
    """Create a new active memory and return the stored record."""

    category = _validate_category(category)
    title = _validate_text(title, "title", MAX_TITLE_LENGTH)
    content = _validate_text(
        content,
        "content",
        MAX_CONTENT_LENGTH,
        hint=(
            "Memory is for compact facts: store large reports as "
            "project files with write_file instead."
        ),
    )
    tags = _validate_text(tags or "", "tags", MAX_TAGS_LENGTH, True)

    if source is not None:
        source = _validate_text(source, "source", MAX_SOURCE_LENGTH, True)
        source = source or None

    timestamp = _utc_timestamp()

    connection = get_connection(db_path)

    try:
        with connection:
            duplicate_id = _fetch_active_duplicate(
                connection,
                category,
                title,
            )

            if duplicate_id is not None:
                raise ValueError(
                    "An active memory with this category and title "
                    f"already exists (id {duplicate_id}). "
                    "Use update_memory instead of creating a duplicate."
                )

            cursor = connection.execute(
                "INSERT INTO memories ("
                "category, title, content, tags, status, source, "
                "created_at, updated_at"
                ") VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (category, title, content, tags, source, timestamp, timestamp),
            )

            memory_id = int(cursor.lastrowid)

        record = _fetch_by_id(connection, memory_id)

    finally:
        connection.close()

    if record is None:
        raise RuntimeError("Memory was saved but could not be read back.")

    return record


def search_memories(
    query: str,
    category: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    status: str = "active",
    db_path: DbPath = None,
) -> list[MemoryRecord]:
    """Search memories by keyword across title, content, and tags."""

    query = _validate_text(query, "query", MAX_QUERY_LENGTH)

    if category is not None:
        category = _validate_category(category)

    if status is None:
        status = "active"

    if status != "all":
        status = _validate_status(status)

    limit = _validate_limit(limit, MAX_SEARCH_LIMIT)

    pattern = f"%{_escape_like(query)}%"

    conditions = [
        "(title LIKE ? ESCAPE '\\' "
        "OR content LIKE ? ESCAPE '\\' "
        "OR tags LIKE ? ESCAPE '\\')"
    ]
    parameters: list[Any] = [pattern, pattern, pattern]

    if category is not None:
        conditions.append("category = ?")
        parameters.append(category)

    if status != "all":
        conditions.append("status = ?")
        parameters.append(status)

    parameters.append(limit)

    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            f"SELECT {_COLUMN_LIST} FROM memories "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            parameters,
        ).fetchall()
    finally:
        connection.close()

    return [MemoryRecord.from_row(row) for row in rows]


def update_memory(
    memory_id: int,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
    tags: str | None = None,
    status: str | None = None,
    db_path: DbPath = None,
) -> MemoryRecord:
    """Update fields of an existing memory by its id."""

    if isinstance(memory_id, bool) or not isinstance(memory_id, int):
        raise ValueError("memory_id must be an integer.")

    if memory_id < 1:
        raise ValueError("memory_id must be a positive integer.")

    updates: dict[str, Any] = {}

    if title is not None:
        updates["title"] = _validate_text(title, "title", MAX_TITLE_LENGTH)

    if content is not None:
        updates["content"] = _validate_text(
            content,
            "content",
            MAX_CONTENT_LENGTH,
            hint=(
                "Memory is for compact facts: store large reports as "
                "project files with write_file instead."
            ),
        )

    if category is not None:
        updates["category"] = _validate_category(category)

    if tags is not None:
        updates["tags"] = _validate_text(tags, "tags", MAX_TAGS_LENGTH, True)

    if status is not None:
        updates["status"] = _validate_status(status)

    if not updates:
        raise ValueError("At least one field to update is required.")

    updates["updated_at"] = _utc_timestamp()

    assignments = ", ".join(f"{field} = ?" for field in updates)
    parameters = list(updates.values()) + [memory_id]

    connection = get_connection(db_path)

    try:
        with connection:
            existing = _fetch_by_id(connection, memory_id)

            if existing is None:
                raise ValueError(
                    "Memory not found: id "
                    f"{memory_id}. Use search_memories to find valid "
                    "memory ids. If you meant the project context "
                    "file, use write_file on .ARACELI_CONTEXT.md "
                    "instead."
                )

            if "category" in updates or "title" in updates:
                final_category = updates.get("category", existing.category)
                final_title = updates.get("title", existing.title)

                duplicate_id = _fetch_active_duplicate(
                    connection,
                    final_category,
                    final_title,
                    exclude_id=memory_id,
                )

                if duplicate_id is not None:
                    raise ValueError(
                        "Updating this memory would duplicate active "
                        f"memory id {duplicate_id} "
                        f"({final_category}: {final_title})."
                    )

            connection.execute(
                f"UPDATE memories SET {assignments} WHERE id = ?",
                parameters,
            )

        record = _fetch_by_id(connection, memory_id)

    finally:
        connection.close()

    if record is None:
        raise RuntimeError("Memory was updated but could not be read back.")

    return record


def get_recent_memories(
    limit: int = DEFAULT_SNAPSHOT_LIMIT,
    db_path: DbPath = None,
) -> list[MemoryRecord]:
    """Return the most recently updated active memories."""

    limit = _validate_limit(limit, MAX_SNAPSHOT_LIMIT)

    connection = get_connection(db_path)

    try:
        rows = connection.execute(
            f"SELECT {_COLUMN_LIST} FROM memories "
            "WHERE status = 'active' "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        connection.close()

    return [MemoryRecord.from_row(row) for row in rows]


def delete_memory(memory_id: int, db_path: DbPath = None) -> MemoryRecord:
    """Physically delete a memory by its id and return the deleted record."""

    if isinstance(memory_id, bool) or not isinstance(memory_id, int):
        raise ValueError("memory_id must be an integer.")

    if memory_id < 1:
        raise ValueError("memory_id must be a positive integer.")

    connection = get_connection(db_path)

    try:
        with connection:
            existing = _fetch_by_id(connection, memory_id)

            if existing is None:
                raise ValueError(
                    "Memory not found: id "
                    f"{memory_id}. Use /memory to see valid memory ids."
                )

            connection.execute(
                "DELETE FROM memories WHERE id = ?",
                (memory_id,),
            )
    finally:
        connection.close()

    return existing


def count_memories(status: str | None = None, db_path: DbPath = None) -> int:
    """Count memories, optionally filtered by status."""

    if status is not None:
        status = _validate_status(status)

    connection = get_connection(db_path)

    try:
        if status is None:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM memories"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM memories WHERE status = ?",
                (status,),
            ).fetchone()

        return int(row["total"])
    finally:
        connection.close()
