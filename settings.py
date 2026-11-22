"""Persisted user settings for Araceli.

Stored in data/settings.json (gitignored). Python-side only: the
model has no tool to read or change these values.
"""

import json
import re

from pathlib import Path


SETTINGS_FILE = Path(__file__).resolve().parent / "data" / "settings.json"

DEFAULT_LANGUAGE = "es"

_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2}(-[A-Za-z]{2})?$")


def load_settings(settings_path: Path | str | None = None) -> dict:
    """Load the persisted settings, or an empty dict if missing/invalid."""

    path = Path(settings_path) if settings_path else SETTINGS_FILE

    if not path.is_file():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def save_settings(
    settings: dict,
    settings_path: Path | str | None = None,
) -> None:
    """Persist the settings dict."""

    path = Path(settings_path) if settings_path else SETTINGS_FILE

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_language_code(code: str) -> bool:
    """Return whether a language code matches the accepted format."""

    return isinstance(code, str) and bool(
        _LANGUAGE_PATTERN.fullmatch(code.strip())
    )


def load_conversation_language(settings_path: Path | str | None = None) -> str:
    """Return the configured conversation language (default: es)."""

    settings = load_settings(settings_path)
    language = settings.get("conversation_language", DEFAULT_LANGUAGE)

    return language if validate_language_code(language) else DEFAULT_LANGUAGE


def save_conversation_language(
    language: str,
    settings_path: Path | str | None = None,
) -> None:
    """Persist the conversation language (2-letter code, lowercased)."""

    if not validate_language_code(language.strip().lower()):
        raise ValueError(
            f"Invalid language code: '{language}'. Use a 2-letter ISO "
            "code (e.g. es, en, fr)."
        )

    settings = load_settings(settings_path)
    settings["conversation_language"] = language.strip().lower()
    save_settings(settings, settings_path)
