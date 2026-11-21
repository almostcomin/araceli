"""Registry of user project workspaces for Araceli."""

import hashlib
import json

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARACELI_ROOT = Path(__file__).resolve().parent

PROJECTS_FILE = ARACELI_ROOT / "data" / "projects.json"

CONTEXT_FILE_NAME = "ARACELI_CONTEXT.md"

MAX_CONTEXT_FILE_SIZE = 256 * 1024

_SYSTEM_DIRECTORY_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "system32",
    "$recycle.bin",
}


def _utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def load_projects(
    registry_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Load the registered projects from the registry file."""

    path = Path(registry_path) if registry_path else PROJECTS_FILE

    if not path.is_file():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read the projects registry: {error}")

    projects = data.get("projects")

    if not isinstance(projects, list):
        raise ValueError("Invalid projects registry format.")

    return projects


def save_projects(
    projects: list[dict[str, Any]],
    registry_path: Path | str | None = None,
) -> None:
    """Persist the projects registry."""

    path = Path(registry_path) if registry_path else PROJECTS_FILE

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": 1, "projects": projects},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def add_project(
    raw_path: str,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Register a project directory and return its registry entry."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A project path is required.")

    path_text = raw_path.strip().strip('"').strip("'")
    candidate = Path(path_text)

    if not candidate.is_absolute():
        raise ValueError("The project path must be absolute.")

    resolved = candidate.resolve()

    if resolved == ARACELI_ROOT:
        raise ValueError(
            "The Araceli application directory cannot be registered "
            "as a project."
        )

    if ARACELI_ROOT in resolved.parents or resolved in ARACELI_ROOT.parents:
        raise ValueError(
            "The project directory must be outside the Araceli "
            "application directory tree (and cannot contain it)."
        )

    if resolved == Path(resolved.anchor):
        raise ValueError("Drive roots cannot be registered as projects.")

    name_parts = {part.casefold() for part in resolved.parts}

    if name_parts & _SYSTEM_DIRECTORY_NAMES:
        raise ValueError(
            "System directories cannot be registered as projects."
        )

    if not resolved.is_dir():
        raise ValueError("The path is not an existing directory.")

    name = resolved.name

    projects = load_projects(registry_path)

    for entry in projects:
        if entry["path"].casefold() == str(resolved).casefold():
            raise ValueError(
                f"This directory is already registered as "
                f"'{entry['name']}'."
            )

        if entry["name"].casefold() == name.casefold():
            raise ValueError(
                f"A project named '{name}' is already registered."
            )

    entry = {
        "name": name,
        "path": str(resolved),
        "added_at": _utc_timestamp(),
    }

    projects.append(entry)
    save_projects(projects, registry_path)

    return entry


def remove_project(
    name: str,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    """Remove a project from the registry by name."""

    projects = load_projects(registry_path)

    for index, entry in enumerate(projects):
        if entry["name"].casefold() == name.strip().casefold():
            removed = projects.pop(index)
            save_projects(projects, registry_path)
            return removed

    raise ValueError(f"No project is registered with the name '{name}'.")


def find_project(
    name: str,
    registry_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Find a registered project by name (case-insensitive)."""

    for entry in load_projects(registry_path):
        if entry["name"].casefold() == name.strip().casefold():
            return entry

    return None


def read_project_context(
    project: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """Read a project's context file and describe the exact bytes read."""

    context_path = Path(project["path"]) / CONTEXT_FILE_NAME

    metadata: dict[str, Any] = {
        "source_type": "project_context_file",
        "project": project["name"],
        "path": CONTEXT_FILE_NAME,
        "read_at": _utc_timestamp(),
        "status": "loaded",
    }

    try:
        if not context_path.is_file():
            metadata["status"] = "not_found"
            return None, metadata

        raw_content = context_path.read_bytes()

        if len(raw_content) > MAX_CONTEXT_FILE_SIZE:
            metadata["status"] = "oversized"
            return None, metadata

        content = raw_content.decode("utf-8")

        metadata.update(
            {
                "size_bytes": len(raw_content),
                "sha256": hashlib.sha256(raw_content).hexdigest(),
            }
        )

    except (OSError, UnicodeError) as error:
        metadata["status"] = "load_error"
        metadata["error"] = str(error)
        return None, metadata

    if not content.strip():
        metadata["status"] = "empty"
        return None, metadata

    return content.strip(), metadata
