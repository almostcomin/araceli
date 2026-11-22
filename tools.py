import ast
import hashlib
import ipaddress
import io
import json
import logging
import math
import operator
import shutil
import socket
import ssl
import time
import urllib.parse
import urllib.request
import uuid
import warnings

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ddgs import DDGS
from pypdf import PdfReader

from memory import memory_store


# pypdf emits per-font warnings when embedded fonts cannot be fully
# parsed. They do not block text extraction, but they would flood the
# console; errors still surface through the execution envelopes.
logging.getLogger("pypdf").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", module=r"pypdf.*")


PROJECT_ROOT = Path(__file__).resolve().parent

try:
    import truststore

    _FETCH_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    _FETCH_SSL_CONTEXT = ssl.create_default_context()

BACKUP_ROOT = PROJECT_ROOT / ".backups"

READABLE_EXTENSIONS = {
    ".py", ".md", ".sql", ".json", ".toml",
    ".txt", ".ini", ".cfg", ".yaml", ".yml",
    ".csv", ".tsv", ".html", ".htm", ".xml",
    ".svg", ".log",
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

MAX_PDF_FILE_SIZE = 10 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_PDF_TEXT_CHARS = 24_000
MAX_DOCUMENT_LIST_RESULTS = 100

DEFAULT_WEB_RESULTS = 8
MAX_WEB_RESULTS = 10
MAX_QUERY_LENGTH = 400
WEB_SEARCH_ATTEMPTS = 3
WEB_SEARCH_RETRY_DELAY_SECONDS = 2.0

FETCH_TIMEOUT_SECONDS = 15
MAX_FETCH_BYTES = 512 * 1024
MAX_FETCH_TEXT_CHARS = 24_000
ALLOWED_FETCH_PORTS = {80, 443}


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


_ACTIVE_WORKSPACE: Path | None = None


def set_workspace(workspace: Path | str | None) -> Path | None:
    """Set the active project workspace for the file tools.

    This is a Python-side control: the model has no tool to change
    the workspace. Only the application (driven by the user) calls it.
    """

    global _ACTIVE_WORKSPACE

    if workspace is None:
        _ACTIVE_WORKSPACE = None
        return None

    _ACTIVE_WORKSPACE = Path(workspace).resolve()

    return _ACTIVE_WORKSPACE


def get_workspace() -> Path | None:
    """Return the active project workspace, if any."""

    return _ACTIVE_WORKSPACE


def _workspace_root() -> Path:
    """Return the root the file tools currently operate on."""

    if _ACTIVE_WORKSPACE is not None:
        return _ACTIVE_WORKSPACE

    return PROJECT_ROOT


def calculate(expression: str) -> int | float:
    """Evaluate a restricted arithmetic expression.

    Newlines and extra whitespace are normalized first, so multi-line
    expressions (for example one amount per line) parse correctly.
    """

    if not isinstance(expression, str):
        raise ValueError("Expression must be a non-empty string.")

    normalized = " ".join(expression.split())

    if not normalized:
        raise ValueError("Expression must be a non-empty string.")

    if len(normalized) > MAX_EXPRESSION_LENGTH:
        raise ValueError("Expression is too long.")

    syntax_tree = ast.parse(normalized, mode="eval")

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
    """Resolve a relative path inside the current workspace."""

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A non-empty relative path is required.")

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    if ".." in requested_path.parts:
        raise ValueError("Parent directory traversal is not allowed.")

    workspace_root = _workspace_root()
    resolved_path = (workspace_root / requested_path).resolve()

    if not resolved_path.is_relative_to(workspace_root):
        raise ValueError("Path is outside the project directory.")

    if _ACTIVE_WORKSPACE is None:
        relative_parts = resolved_path.relative_to(PROJECT_ROOT).parts

        if any(
            part.casefold() in EXCLUDED_DIRECTORIES
            for part in relative_parts
        ):
            raise ValueError("Access to this directory is not allowed.")

    return resolved_path


def _validate_readable_file(path: Path) -> None:
    """Validate a file before reading it."""

    if not path.is_file():
        raise FileNotFoundError("File not found.")

    if path.suffix.lower() == _PDF_SUFFIX:
        raise ValueError(
            "PDF files cannot be read with read_file. "
            "Use read_pdf instead."
        )

    if _ACTIVE_WORKSPACE is None and (
        path.suffix.lower() not in READABLE_EXTENSIONS
    ):
        raise ValueError("File extension is not allowed.")

    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("File exceeds the maximum allowed size.")


_PDF_SUFFIX = ".pdf"


def list_files(directory: str = ".") -> dict[str, Any]:
    """List files in the current workspace with a time-stamped record.

    In an active project, all files and directories are listed
    regardless of extension, with PDF documents classified separately.
    In the Araceli repository, only readable text files are listed.
    """

    root = _resolve_project_path(directory)

    if not root.is_dir():
        raise NotADirectoryError("The requested path is not a directory.")

    workspace_root = _workspace_root()
    workspace_mode = _ACTIVE_WORKSPACE is not None

    files: list[str] = []
    directories: list[str] = []
    pdf_files: list[str] = []
    truncated = False

    for path in sorted(root.rglob("*")):
        try:
            resolved = path.resolve()

            if not resolved.is_relative_to(workspace_root):
                continue

            if resolved.is_dir():
                if workspace_mode:
                    relative_dir = resolved.relative_to(
                        workspace_root
                    ).as_posix()

                    if (
                        relative_dir != "."
                        and len(directories) < MAX_LIST_RESULTS
                    ):
                        directories.append(relative_dir)

                continue

            if not resolved.is_file():
                continue

            if not workspace_mode:
                relative_parts = resolved.relative_to(PROJECT_ROOT).parts

                if any(
                    part.casefold() in EXCLUDED_DIRECTORIES
                    for part in relative_parts
                ):
                    continue

                if resolved.suffix.lower() not in READABLE_EXTENSIONS:
                    continue

            if len(files) >= MAX_LIST_RESULTS:
                truncated = True
                break

            relative_path = resolved.relative_to(workspace_root).as_posix()
            files.append(relative_path)

            if workspace_mode and resolved.suffix.lower() == _PDF_SUFFIX:
                pdf_files.append(relative_path)

        except (OSError, ValueError):
            continue

    result: dict[str, Any] = {
        "directory": root.relative_to(workspace_root).as_posix() or ".",
        "files": files,
        "truncated": truncated,
        "source": {
            "source_type": "current_directory_listing",
            "listed_at": _utc_timestamp(),
        },
    }

    if workspace_mode:
        result["directories"] = directories
        result["pdf_files"] = pdf_files

        if pdf_files:
            result["note"] = (
                f"{len(pdf_files)} PDF document(s): use read_pdf. "
                "All other files: try read_file (UTF-8 text). Files "
                "that cannot be decoded as text have no reader tool "
                "yet; ask the user if you need them."
            )

    return result


def read_file(path: str) -> dict[str, Any]:
    """Read a UTF-8 text file and identify the exact bytes returned."""

    file_path = _resolve_project_path(path)
    _validate_readable_file(file_path)

    raw_content = file_path.read_bytes()

    if len(raw_content) > MAX_FILE_SIZE:
        raise ValueError("File exceeds the maximum allowed size.")

    try:
        content = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(
            "The file is not UTF-8 text (binary content or "
            "unsupported encoding). No reader tool is available for "
            "this content; ask the user if you need it."
        )
    relative_path = file_path.relative_to(_workspace_root()).as_posix()

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
    workspace_root = _workspace_root()
    relative_path = file_path.relative_to(workspace_root)

    if not relative_path.parts:
        raise ValueError("A file path is required.")

    if _ACTIVE_WORKSPACE is None:
        if (
            relative_path.parts[0].casefold()
            not in WRITABLE_DIRECTORIES
        ):
            raise PermissionError(
                "Writing to this directory is not allowed."
            )

    if _ACTIVE_WORKSPACE is None and (
        file_path.suffix.lower() not in READABLE_EXTENSIONS
    ):
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

        backup_branch = (
            Path("workspace") if _ACTIVE_WORKSPACE is not None else Path()
        )

        backup_path = (
            BACKUP_ROOT / timestamp / backup_branch / relative_path
        )

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


def save_memory(
    category: str,
    title: str,
    content: str,
    tags: str = "",
    source: str | None = None,
) -> dict[str, Any]:
    """Store a new persistent memory and return the saved record."""

    record = memory_store.save_memory(category, title, content, tags, source)

    return {"memory": record.to_dict()}


def search_memories(
    query: str,
    category: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search persistent memories by keyword."""

    records = memory_store.search_memories(query, category, limit)

    return {
        "query": query,
        "category": category,
        "count": len(records),
        "memories": [record.to_dict() for record in records],
    }


def update_memory(
    memory_id: int,
    title: str | None = None,
    content: str | None = None,
    category: str | None = None,
    tags: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update an existing persistent memory by id."""

    record = memory_store.update_memory(
        memory_id,
        title,
        content,
        category,
        tags,
        status,
    )

    return {"memory": record.to_dict()}


def _get_document_roots() -> list[tuple[Path, str]]:
    """Return the configured document roots, deduplicated.

    When a project workspace is active, it is the primary documents
    root. Additional roots come from data/documents_path.txt (a single
    line with an absolute path to a directory outside the project) and
    the internal data/documents/ directory. Roots pointing at the same
    directory are only included once, in priority order.
    """

    roots: list[tuple[Path, str]] = []
    seen_roots: set[str] = set()

    def _add_root(root_path: Path, root_kind: str) -> None:
        key = str(root_path).casefold()

        if key not in seen_roots:
            seen_roots.add(key)
            roots.append((root_path, root_kind))

    if _ACTIVE_WORKSPACE is not None:
        _add_root(_ACTIVE_WORKSPACE, "workspace")

    pointer_path = PROJECT_ROOT / "data" / "documents_path.txt"

    if pointer_path.is_file():
        pointer_text = pointer_path.read_text(
            encoding="utf-8-sig"
        ).strip()

        if pointer_text:
            external_root = Path(pointer_text)

            if not external_root.is_absolute():
                raise ValueError(
                    "The configured documents path must be absolute "
                    "(check data/documents_path.txt)."
                )

            if not external_root.is_dir():
                raise ValueError(
                    "The configured documents directory does not exist "
                    "(check data/documents_path.txt)."
                )

            _add_root(external_root.resolve(), "external")

    internal_root = (PROJECT_ROOT / "data" / "documents").resolve()
    _add_root(internal_root, "internal")

    return roots


def _resolve_document_path(
    relative_path: str,
) -> tuple[Path, str, str]:
    """Resolve a document path against the configured roots.

    Returns the resolved path, the root kind and the path relative
    to that root.
    """

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("A non-empty relative path is required.")

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    if ".." in requested_path.parts:
        raise ValueError("Parent directory traversal is not allowed.")

    for root, root_kind in _get_document_roots():
        resolved_path = (root / requested_path).resolve()

        if not resolved_path.is_relative_to(root):
            continue

        if resolved_path.is_file():
            return (
                resolved_path,
                root_kind,
                resolved_path.relative_to(root).as_posix(),
            )

    raise FileNotFoundError(
        "Document not found in the configured documents directories. "
        "Use list_documents to see the available files."
    )


def _parse_page_selection(pages: str, page_count: int) -> list[int]:
    """Parse a page selection like "1-3", "2" or "1,3-5" (1-based)."""

    if not isinstance(pages, str) or not pages.strip():
        raise ValueError(
            "pages must be a non-empty selection like '1-3' or '1,3-5'."
        )

    selected: list[int] = []

    for part in pages.split(","):
        part = part.strip()

        if not part:
            raise ValueError(f"Invalid page selection: '{part}'.")

        if "-" in part:
            start_text, _, end_text = part.partition("-")
            start_text = start_text.strip()
            end_text = end_text.strip()

            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"Invalid page range: '{part}'.")

            start, end = int(start_text), int(end_text)

            if start < 1 or end < start:
                raise ValueError(f"Invalid page range: '{part}'.")

            selected.extend(range(start, end + 1))
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid page selection: '{part}'.")

            selected.append(int(part))

    selected = sorted(set(selected))

    if selected[0] < 1:
        raise ValueError("Page numbers start at 1.")

    if selected[-1] > page_count:
        raise ValueError(
            f"Page selection exceeds the document page count "
            f"({page_count} pages)."
        )

    return selected


def read_pdf(path: str, pages: str | None = None) -> dict[str, Any]:
    """Extract text from a PDF in the active workspace or documents directories."""

    if not isinstance(path, str) or not path.strip():
        raise ValueError("A non-empty relative path is required.")

    if Path(path).suffix.lower() != ".pdf":
        raise ValueError("Only PDF documents are supported.")

    file_path, root_kind, relative_path = _resolve_document_path(path)

    file_size = file_path.stat().st_size

    if file_size > MAX_PDF_FILE_SIZE:
        raise ValueError("Document exceeds the maximum allowed size.")

    raw_bytes = file_path.read_bytes()

    reader = PdfReader(io.BytesIO(raw_bytes))

    page_count = len(reader.pages)

    if page_count > MAX_PDF_PAGES:
        raise ValueError("Document exceeds the maximum allowed page count.")

    if pages is not None:
        selected_pages = _parse_page_selection(pages, page_count)

        pages_text = [
            reader.pages[index - 1].extract_text() or ""
            for index in selected_pages
        ]
    else:
        selected_pages = list(range(1, page_count + 1))

        pages_text = [page.extract_text() or "" for page in reader.pages]

    full_text = "\n\n".join(pages_text)

    truncated = False

    if len(full_text) > MAX_PDF_TEXT_CHARS:
        full_text = full_text[:MAX_PDF_TEXT_CHARS]
        truncated = True

    note = None

    if not full_text.strip():
        note = (
            "No text could be extracted. The document may be a "
            "scanned image without a text layer."
        )
    elif truncated:
        note = (
            "Text was truncated because it exceeds the size limit. "
            "Use the pages parameter to read specific page ranges."
        )

    return {
        "path": relative_path,
        "documents_dir": root_kind,
        "page_count": page_count,
        "pages_read": selected_pages,
        "text": full_text,
        "text_truncated": truncated,
        "note": note,
        "source": {
            "source_type": "pdf_text_extraction",
            "path": relative_path,
            "documents_dir": root_kind,
            "extracted_at": _utc_timestamp(),
            "size_bytes": file_size,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        },
    }


def list_documents() -> dict[str, Any]:
    """List PDF documents in the active workspace and documents directories."""

    documents: list[dict[str, Any]] = []
    truncated = False

    for root, root_kind in _get_document_roots():
        if truncated:
            break

        for file_path in sorted(root.rglob("*.pdf")):
            try:
                resolved_path = file_path.resolve()

                if not resolved_path.is_relative_to(root):
                    continue

                file_stat = resolved_path.stat()

                documents.append(
                    {
                        "name": resolved_path.relative_to(root).as_posix(),
                        "size_bytes": file_stat.st_size,
                        "modified_at": (
                            datetime.fromtimestamp(
                                file_stat.st_mtime,
                                tz=timezone.utc,
                            )
                            .isoformat(timespec="seconds")
                            .replace("+00:00", "Z")
                        ),
                        "documents_dir": root_kind,
                    }
                )
            except OSError:
                continue

            if len(documents) >= MAX_DOCUMENT_LIST_RESULTS:
                truncated = True
                break

    return {
        "count": len(documents),
        "truncated": truncated,
        "documents": documents,
        "source": {
            "source_type": "document_listing",
            "listed_at": _utc_timestamp(),
        },
    }


def web_search(
    query: str,
    max_results: int = DEFAULT_WEB_RESULTS,
) -> dict[str, Any]:
    """Search the web with DuckDuckGo and return generic results."""

    if not isinstance(query, str):
        raise ValueError("query must be a string.")

    query = query.strip()

    if not query:
        raise ValueError("query must not be empty.")

    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(
            f"query exceeds the maximum length of "
            f"{MAX_QUERY_LENGTH} characters."
        )

    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer.")

    if not 1 <= max_results <= MAX_WEB_RESULTS:
        raise ValueError(
            f"max_results must be between 1 and {MAX_WEB_RESULTS}."
        )

    results: list[dict[str, Any]] = []
    last_error: Exception | None = None

    for attempt in range(WEB_SEARCH_ATTEMPTS):
        try:
            results = list(
                DDGS().text(query, max_results=max_results)
            )
            break
        except Exception as error:
            last_error = error

            if attempt + 1 < WEB_SEARCH_ATTEMPTS:
                time.sleep(WEB_SEARCH_RETRY_DELAY_SECONDS)

    else:
        raise RuntimeError(f"Web search failed: {last_error}")

    formatted = [
        {
            "title": result.get("title", ""),
            "url": result.get("href", ""),
            "snippet": result.get("body", ""),
        }
        for result in results
        if result.get("href")
    ]

    return {
        "query": query,
        "count": len(formatted),
        "results": formatted,
        "source": {
            "source_type": "web_search",
            "engine": "duckduckgo",
            "searched_at": _utc_timestamp(),
        },
    }


_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "nav",
    "br", "li", "tr", "table", "ul", "ol", "h1", "h2", "h3", "h4",
    "h5", "h6", "blockquote", "pre", "form",
}

_SKIP_TAGS = {"script", "style", "noscript", "template"}


class _HTMLTextExtractor(HTMLParser):
    """Extract readable text from an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return

        if self._in_title:
            self.title += data
        else:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self._chunks)
        lines = [" ".join(line.split()) for line in raw_text.splitlines()]

        cleaned: list[str] = []

        for line in lines:
            if line or (cleaned and cleaned[-1]):
                cleaned.append(line)

        return "\n".join(cleaned).strip()


def _validate_public_http_url(url: str) -> str:
    """Validate an http(s) URL that points at a public host."""

    if not isinstance(url, str) or not url.strip():
        raise ValueError("A non-empty URL is required.")

    validated_url = url.strip()
    parsed = urllib.parse.urlparse(validated_url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs are allowed.")

    if not parsed.hostname:
        raise ValueError("The URL must include a host name.")

    try:
        port = parsed.port
    except ValueError:
        raise ValueError("The URL contains an invalid port.")

    if port is not None and port not in ALLOWED_FETCH_PORTS:
        raise ValueError("Only ports 80 and 443 are allowed.")

    try:
        address_infos = socket.getaddrinfo(
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as error:
        raise ValueError(f"Could not resolve host: {error}")

    for address_info in address_infos:
        address = ipaddress.ip_address(address_info[4][0])

        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError(
                "Requests to private or local addresses are not allowed."
            )

    return validated_url


def web_fetch(url: str) -> dict[str, Any]:
    """Fetch a public web page and return its readable text."""

    validated_url = _validate_public_http_url(url)

    request = urllib.request.Request(
        validated_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AraceliPersonalAssistant/0.1"
            ),
            "Accept": (
                "text/html, application/xhtml+xml, text/plain;q=0.9, "
                "*/*;q=0.5"
            ),
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=FETCH_TIMEOUT_SECONDS,
        context=_FETCH_SSL_CONTEXT,
    ) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        raw_body = response.read(MAX_FETCH_BYTES + 1)

    if len(raw_body) > MAX_FETCH_BYTES:
        raise ValueError("The page exceeds the maximum allowed size.")

    _validate_public_http_url(final_url)

    content_type_lower = content_type.lower()

    if "text/html" in content_type_lower or "xhtml" in content_type_lower:
        extractor = _HTMLTextExtractor()
        extractor.feed(raw_body.decode(charset, errors="replace"))
        page_text = extractor.get_text()
        page_title = extractor.title.strip()
    elif "text/plain" in content_type_lower or not content_type_lower:
        page_text = raw_body.decode(charset, errors="replace")
        page_title = ""
    else:
        raise ValueError(f"Unsupported content type: {content_type}")

    truncated = False

    if len(page_text) > MAX_FETCH_TEXT_CHARS:
        page_text = page_text[:MAX_FETCH_TEXT_CHARS]
        truncated = True

    return {
        "url": final_url,
        "title": page_title,
        "text": page_text,
        "text_truncated": truncated,
        "source": {
            "source_type": "web_page_fetch",
            "url": final_url,
            "fetched_at": _utc_timestamp(),
            "content_type": content_type,
            "size_bytes": len(raw_body),
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

        elif name == "save_memory":
            if set(parsed_arguments) - {
                "category", "title", "content", "tags", "source"
            }:
                raise ValueError("Invalid save_memory arguments.")

            missing = {"category", "title", "content"} - set(
                parsed_arguments
            )

            if missing:
                raise ValueError(
                    "Missing save_memory arguments: "
                    f"{', '.join(sorted(missing))}."
                )

            target = parsed_arguments["title"]
            result = save_memory(
                parsed_arguments["category"],
                parsed_arguments["title"],
                parsed_arguments["content"],
                parsed_arguments.get("tags", ""),
                parsed_arguments.get("source"),
            )

        elif name == "search_memories":
            if set(parsed_arguments) - {"query", "category", "limit"}:
                raise ValueError("Invalid search_memories arguments.")

            if "query" not in parsed_arguments:
                raise ValueError(
                    "Missing search_memories argument: query."
                )

            target = parsed_arguments["query"]
            result = search_memories(
                parsed_arguments["query"],
                parsed_arguments.get("category"),
                parsed_arguments.get("limit", 20),
            )

        elif name == "update_memory":
            if set(parsed_arguments) - {
                "memory_id", "title", "content", "category", "tags", "status"
            }:
                raise ValueError("Invalid update_memory arguments.")

            if "memory_id" not in parsed_arguments:
                raise ValueError(
                    "Missing update_memory argument: memory_id."
                )

            if set(parsed_arguments) == {"memory_id"}:
                raise ValueError(
                    "At least one field to update is required."
                )

            memory_id = parsed_arguments["memory_id"]

            if isinstance(memory_id, bool) or not isinstance(memory_id, int):
                raise ValueError("memory_id must be an integer.")

            target = memory_id
            result = update_memory(
                memory_id,
                parsed_arguments.get("title"),
                parsed_arguments.get("content"),
                parsed_arguments.get("category"),
                parsed_arguments.get("tags"),
                parsed_arguments.get("status"),
            )

        elif name == "read_pdf":
            if set(parsed_arguments) - {"path", "pages"}:
                raise ValueError("Invalid read_pdf arguments.")

            target = parsed_arguments["path"]
            result = read_pdf(target, parsed_arguments.get("pages"))

        elif name == "list_documents":
            if set(parsed_arguments):
                raise ValueError("list_documents takes no arguments.")

            target = None
            result = list_documents()

        elif name == "web_search":
            if set(parsed_arguments) - {"query", "max_results"}:
                raise ValueError("Invalid web_search arguments.")

            if "query" not in parsed_arguments:
                raise ValueError("Missing web_search argument: query.")

            target = parsed_arguments["query"]
            result = web_search(
                parsed_arguments["query"],
                parsed_arguments.get("max_results", DEFAULT_WEB_RESULTS),
            )

        elif name == "web_fetch":
            if set(parsed_arguments) != {"url"}:
                raise ValueError("Invalid web_fetch arguments.")

            target = parsed_arguments["url"]
            result = web_fetch(target)

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
