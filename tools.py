import ast
import hashlib
import json
import math
import operator
import shutil
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent

BACKUP_ROOT = PROJECT_ROOT / ".backups"

READABLE_EXTENSIONS = {
    ".py", ".md", ".sql", ".json", ".toml",
    ".txt", ".ini", ".cfg", ".yaml", ".yml",
}

WRITABLE_DIRECTORIES = {
    "memory",
    "tests",
    "docs",
}

EXCLUDED_DIRECTORIES = {
    ".venv",
    "__pycache__",
    ".git",
    ".backups",
    "data",
}

MAX_FILE_SIZE = 256 * 1024
MAX_EXPRESSION_LENGTH = 200
MAX_RESULT_MAGNITUDE = 1e100
MAX_EXPONENT = 100
MAX_LIST_RESULTS = 200


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def calculate(expression: str) -> int | float:
    """Evaluate a restricted arithmetic expression."""

    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Expression must be a non-empty string.")

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression is too long.")

    syntax_tree = ast.parse(expression, mode="eval")

    def evaluate_node(node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise ValueError("Only numeric constants are allowed.")

            result = node.value

        elif isinstance(node, ast.BinOp):
            function = _BINARY_OPERATORS.get(type(node.op))

            if function is None:
                raise ValueError("Unsupported binary operator.")

            left = evaluate_node(node.left)
            right = evaluate_node(node.right)

            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError("Exponent limit exceeded.")

            result = function(left, right)

        elif isinstance(node, ast.UnaryOp):
            function = _UNARY_OPERATORS.get(type(node.op))

            if function is None:
                raise ValueError("Unsupported unary operator.")

            result = function(evaluate_node(node.operand))

        else:
            raise ValueError("Unsupported expression.")

        if not math.isfinite(result) or abs(result) > MAX_RESULT_MAGNITUDE:
            raise ValueError("Result is outside the allowed range.")

        return result

    return evaluate_node(syntax_tree.body)


def _resolve_project_path(relative_path: str) -> Path:
    """Resolve a relative path and ensure it stays inside the project."""

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A non-empty relative path is required.")

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    if ".." in requested_path.parts:
        raise ValueError("Parent directory traversal is not allowed.")

    resolved_path = (PROJECT_ROOT / requested_path).resolve()

    if not resolved_path.is_relative_to(PROJECT_ROOT):
        raise ValueError("Path is outside the project directory.")

    relative_parts = resolved_path.relative_to(PROJECT_ROOT).parts

    if any(part.casefold() in EXCLUDED_DIRECTORIES for part in relative_parts):
        raise ValueError("Access to this directory is not allowed.")

    return resolved_path


def _validate_readable_file(path: Path) -> None:
    """Validate a file before reading it."""

    if path.suffix.lower() not in READABLE_EXTENSIONS:
        raise ValueError("File extension is not allowed.")

    if not path.is_file():
        raise FileNotFoundError("File not found.")

    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File exceeds the maximum allowed size.")


def list_files(directory: str = ".") -> dict[str, Any]:
    """List readable project files and record when the listing was made."""

    root = _resolve_project_path(directory)

    if not root.is_dir():
        raise NotADirectoryError("The requested path is not a directory.")

    results = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        try:
            resolved = path.resolve()

            if not resolved.is_relative_to(PROJECT_ROOT):
                continue

            relative_parts = resolved.relative_to(PROJECT_ROOT).parts

            if any(
                part.casefold() in EXCLUDED_DIRECTORIES
                for part in relative_parts
            ):
                continue

            if resolved.suffix.lower() not in READABLE_EXTENSIONS:
                continue

            results.append(resolved.relative_to(PROJECT_ROOT).as_posix())

        except (OSError, ValueError):
            continue

        if len(results) >= MAX_LIST_RESULTS:
            break

    return {
        "directory": root.relative_to(PROJECT_ROOT).as_posix() or ".",
        "files": results,
        "truncated": len(results) >= MAX_LIST_RESULTS,
        "source": {
            "source_type": "current_directory_listing",
            "listed_at": _utc_timestamp(),
        },
    }


def read_file(path: str) -> dict[str, Any]:
    """Read a UTF-8 text file and identify the exact bytes returned."""

    file_path = _resolve_project_path(path)
    _validate_readable_file(file_path)

    raw_content = file_path.read_bytes()

    if len(raw_content) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the maximum allowed size.")

    content = raw_content.decode("utf-8")
    relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()

    return {
        "path": relative_path,
        "content": content,
        "size": len(raw_content),
        "source": {
            "source_type": "current_file_read",
            "path": relative_path,
            "read_at": _utc_timestamp(),
            "size_bytes": len(raw_content),
            "sha256": hashlib.sha256(raw_content).hexdigest(),
        },
    }


def write_file(path: str, content: str) -> dict[str, Any]:
    """Write an authorized text file and verify the resulting bytes."""

    if not isinstance(content, str):
        raise ValueError("File content must be a string.")

    file_path = _resolve_project_path(path)
    relative_path = file_path.relative_to(PROJECT_ROOT)

    if not relative_path.parts:
        raise ValueError("A file path is required.")

    if relative_path.parts[0].casefold() not in WRITABLE_DIRECTORIES:
        raise PermissionError("Writing to this directory is not allowed.")

    if file_path.suffix.lower() not in READABLE_EXTENSIONS:
        raise ValueError("File extension is not allowed.")

    content_bytes = content.encode("utf-8")

    if len(content_bytes) > MAX_FILE_SIZE:
        raise ValueError("Content exceeds the maximum allowed file size.")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Revalidate after creating parent directories.
    file_path = _resolve_project_path(path)

    if file_path.is_dir():
        raise IsADirectoryError("The requested path is a directory.")

    backup_path = None

    if file_path.exists():
        if not file_path.is_file():
            raise ValueError("The requested path is not a regular file.")

        if file_path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("Existing file exceeds the backup size limit.")

        timestamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        backup_path = BACKUP_ROOT / timestamp / relative_path

        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, backup_path)

    file_path.write_bytes(content_bytes)

    written_bytes = file_path.read_bytes()
    verified = written_bytes == content_bytes

    if not verified:
        raise OSError("Written file verification failed.")

    return {
        "path": relative_path.as_posix(),
        "bytes_written": len(content_bytes),
        "backup": (
            backup_path.relative_to(PROJECT_ROOT).as_posix()
            if backup_path
            else None
        ),
        "operation": {
            "operation_type": "file_write",
            "completed_at": _utc_timestamp(),
            "verified": verified,
            "sha256": hashlib.sha256(written_bytes).hexdigest(),
        },
    }


def execute_tool(name: str, arguments: str) -> str:
    """Execute a tool and return a Python-generated execution record."""

    execution_id = uuid.uuid4().hex
    started_at = _utc_timestamp()
    target = None

    try:
        parsed_arguments = json.loads(arguments)

        if not isinstance(parsed_arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")

        if name == "calculate":
            if set(parsed_arguments) != {"expression"}:
                raise ValueError("Invalid calculator arguments.")

            result = calculate(parsed_arguments["expression"])

        elif name == "list_files":
            if set(parsed_arguments) - {"directory"}:
                raise ValueError("Invalid list_files arguments.")

            target = parsed_arguments.get("directory", ".")
            result = list_files(target)

        elif name == "read_file":
            if set(parsed_arguments) != {"path"}:
                raise ValueError("Invalid read_file arguments.")

            target = parsed_arguments["path"]
            result = read_file(target)

        elif name == "write_file":
            if set(parsed_arguments) != {"path", "content"}:
                raise ValueError("Invalid write_file arguments.")

            target = parsed_arguments["path"]
            result = write_file(
                target,
                parsed_arguments["content"],
            )

        else:
            raise ValueError(f"Unknown tool: {name}")

        envelope = {
            "execution": {
                "id": execution_id,
                "tool": name,
                "status": "success",
                "started_at": started_at,
                "completed_at": _utc_timestamp(),
                "target": target,
            },
            "result": result,
        }

    except Exception as error:
        envelope = {
            "execution": {
                "id": execution_id,
                "tool": name,
                "status": "error",
                "started_at": started_at,
                "completed_at": _utc_timestamp(),
                "target": target,
            },
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
        }

    return json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
    )
