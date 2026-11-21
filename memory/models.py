"""Data model for persistent memory records."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    """A single persistent memory entry stored in SQLite."""

    id: int
    category: str
    title: str
    content: str
    tags: str
    status: str
    source: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-serializable dictionary."""

        return asdict(self)

    @classmethod
    def from_row(cls, row: Any) -> "MemoryRecord":
        """Build a record from a database row with named columns."""

        return cls(
            id=int(row["id"]),
            category=row["category"],
            title=row["title"],
            content=row["content"],
            tags=row["tags"],
            status=row["status"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
