import copy
import hashlib
import json
import re
import sys
import urllib.request

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI

    from tools import execute_tool, set_workspace
except ModuleNotFoundError as error:
    _root = Path(__file__).resolve().parent
    print("=" * 55)
    print("MISSING DEPENDENCY")
    print(f"    {error}")
    print()
    print("This usually means the wrong virtual environment is active.")
    print("Activate the virtual environment of THIS project directory:")
    print(f"    CMD:        {_root}\\.venv\\Scripts\\activate.bat")
    print(f"    PowerShell: {_root}\\.venv\\Scripts\\Activate.ps1")
    print("    Git Bash:   source "
          f"{_root}/.venv/Scripts/activate")
    print()
    print("Or start the app without activation:")
    print(f"    {_root}/.venv/Scripts/python.exe main.py")
    print()
    print("Or use the launchers: run.bat (CMD) / run.sh (Git Bash)")
    print()
    print("If the dependency is still missing, install requirements:")
    print("    pip install -r requirements.txt")
    print("=" * 55)
    raise SystemExit(1)

from config import (
    API_KEY,
    BASE_URL,
    MODEL,
    CONTEXT_LENGTH,
    TEMPERATURE,
    MAX_TOKENS,
    SYSTEM_PROMPT_FILE,
)

from memory import (
    DEFAULT_DB_PATH,
    count_memories,
    delete_memory,
    get_recent_memories,
    init_database,
)
from memory.memory_store import MAX_SNAPSHOT_LIMIT

import projects

from console import (
    ARACELI_INPUT,
    ARACELI_TEXT,
    SYSTEM_ERROR,
    SYSTEM_MESSAGE,
    USER_INPUT,
    init_colors,
    paint,
)


ROOT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = ROOT_DIR / SYSTEM_PROMPT_FILE
PROJECT_CONTEXT_PATH = ROOT_DIR / "docs" / "project_context.md"

MAX_TOOL_ROUNDS = 8

MEMORY_SNAPSHOT_LIMIT = 15
MEMORY_CONTENT_PREVIEW_LENGTH = 300


BASE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression using a restricted "
                "arithmetic calculator. The tool response includes a "
                "Python-generated execution ID and execution status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string"}
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in a directory of the current workspace: "
                "the active project directory if one is active, "
                "otherwise the Araceli repository. In an active "
                "project it lists ALL files and directories "
                "regardless of extension, with PDF documents "
                "classified in pdf_files (read them with read_pdf). "
                "In the repository it lists readable text files only. "
                "The result includes the time at which the listing was "
                "generated. Paths must be relative to the workspace "
                "root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Relative directory path. Defaults to '.'.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the current contents of a UTF-8 text file inside "
                "the current workspace: the active project directory "
                "if one is active, otherwise the Araceli repository. "
                "In an active project any file is attempted as UTF-8 "
                "text; PDF files must be read with read_pdf, and "
                "files that cannot be decoded as text have no reader "
                "tool (ask the user). In the repository only allowed "
                "text extensions can be read. The result includes "
                "Python-generated source metadata: relative path, "
                "read timestamp, byte size, and SHA-256 hash. This is "
                "a fresh disk read, not a startup snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or update a text file. In an active project, "
                "writing is allowed anywhere inside the project "
                "directory with any extension. Without an active "
                "project, writing is restricted to the memory, tests "
                "and docs directories of the Araceli repository with "
                "a text extension allowlist. Existing files are "
                "backed up automatically. The result reports the "
                "backup and whether the written bytes were verified by "
                "reading the file back."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pdf",
            "description": (
                "Extract text from a PDF document. Search order: the "
                "active project directory if one is active, then the "
                "configured documents directories. The path is "
                "relative to those roots, e.g. 'bill.pdf'. The result "
                "includes the extracted text, page count and source "
                "metadata (SHA-256, extraction timestamp). Scanned "
                "PDFs without a text layer return no text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path relative to the document roots, "
                            "e.g. 'gas_bill_november.pdf'. Use "
                            "list_documents to discover available files."
                        ),
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": (
                "List the PDF documents available in the active "
                "project (if any) and the configured documents "
                "directories, with name, size and modification time. "
                "Use it to discover which documents can be read with "
                "read_pdf. Takes no arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web with generic, non-identifying queries "
                "and return titles, URLs and snippets. Never include "
                "private data (names, addresses, contract numbers, "
                "consumption figures from private documents) in the "
                "query. Use web_fetch to read a specific result page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Generic search query in the appropriate "
                            "language for the topic."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": (
                            "Maximum results (1-10, default 8)."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a public http(s) page and return its readable "
                "text with the final URL and fetch timestamp. Only "
                "public addresses on ports 80/443 are allowed. Use it "
                "to read pages found with web_search and cite their "
                "URLs as sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full http(s) URL to fetch.",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
]

MEMORY_CATEGORY_ENUM = [
    "preference",
    "personal",
    "project",
    "decision",
    "task",
    "fact",
    "knowledge",
]

MEMORY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Store a new persistent memory that remains available "
                "across conversation resets and application restarts. "
                "Search first to avoid duplicates: if an active memory "
                "with the same category and title exists, update it "
                "with update_memory instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Memory category."
                        ),
                        "enum": MEMORY_CATEGORY_ENUM,
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "Short identifying label "
                            "(max 200 characters)."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "The memory itself (max 4000 characters)."
                        ),
                    },
                    "tags": {
                        "type": "string",
                        "description": (
                            "Optional comma-separated keywords "
                            "(max 200 characters)."
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Optional provenance note about where this "
                            "information comes from."
                        ),
                    },
                },
                "required": ["category", "title", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": (
                "Search persistent memories by keyword across title, "
                "content and tags. Returns active memories by default, "
                "most recently updated first. Use this to check the "
                "current complete state of memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword or phrase to search for."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter.",
                        "enum": MEMORY_CATEGORY_ENUM,
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "Maximum number of results (1-50, default 20)."
                        ),
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": (
                "Update an existing persistent memory by id. Use this "
                "to correct or refine a memory, or to mark it as "
                "superseded when it is no longer current."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "integer",
                        "description": "Id of the memory to update.",
                    },
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": MEMORY_CATEGORY_ENUM,
                    },
                    "tags": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "superseded"],
                    },
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
        },
    },
]


def _utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _load_startup_text(path: Path) -> tuple[str, dict[str, Any]]:
    """Read a startup text file and describe the exact bytes loaded."""

    raw_content = path.read_bytes()
    content = raw_content.decode("utf-8")

    try:
        relative_path = path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        relative_path = str(path)

    source_metadata = {
        "source_type": "startup_file_snapshot",
        "path": relative_path,
        "loaded_at": _utc_timestamp(),
        "size_bytes": len(raw_content),
        "sha256": hashlib.sha256(raw_content).hexdigest(),
        "status": "loaded",
    }

    return content, source_metadata


def load_system_prompt() -> tuple[str, dict[str, Any]]:
    """Load the assistant's system instructions and source metadata."""

    if not PROMPT_PATH.is_file():
        raise FileNotFoundError(
            f"System prompt file not found: {PROMPT_PATH}"
        )

    return _load_startup_text(PROMPT_PATH)


def load_project_context() -> tuple[str | None, dict[str, Any]]:
    """Load the project's technical context and source metadata."""

    try:
        if not PROJECT_CONTEXT_PATH.is_file():
            print(
                "\n[WARNING] Project context file not found. "
                "Starting without project-specific context."
            )
            return None, {
                "source_type": "startup_file_snapshot",
                "path": "docs/project_context.md",
                "status": "not_found",
            }

        content, metadata = _load_startup_text(PROJECT_CONTEXT_PATH)

    except (OSError, UnicodeError) as error:
        print(
            f"\n[WARNING] Could not load project context: {error}"
        )
        return None, {
            "source_type": "startup_file_snapshot",
            "path": "docs/project_context.md",
            "status": "load_error",
            "error": str(error),
        }

    if not content.strip():
        print(
            "\n[WARNING] Project context file is empty. "
            "Starting without project-specific context."
        )
        metadata["status"] = "empty"
        return None, metadata

    return content.strip(), metadata


def build_system_prompt(
    system_prompt: str,
    system_prompt_source: dict[str, Any],
    project_context: str | None,
    project_context_source: dict[str, Any],
    memory_section: str | None = None,
    active_project_section: str | None = None,
) -> str:
    """Combine behavioral instructions, startup context and source manifest."""

    combined_prompt = system_prompt.rstrip()

    if project_context:
        combined_prompt += (
            "\n\n"
            "The following section contains technical reference "
            "information about the project. It supplements the "
            "behavioral instructions above and does not replace them.\n\n"
            "## Project Context — Startup Snapshot\n\n"
            f"{project_context}"
        )

    if memory_section:
        combined_prompt += memory_section

    if active_project_section:
        combined_prompt += active_project_section

    source_manifest = {
        "description": (
            "This manifest records files actually loaded by Python "
            "during this application startup. It is a startup snapshot, "
            "not a live description of files currently on disk. Use "
            "read_file to inspect current file contents."
        ),
        "system_prompt": system_prompt_source,
        "project_context": project_context_source,
    }

    combined_prompt += (
        "\n\n"
        "## Runtime Source Manifest\n\n"
        "The following JSON was generated by Python at startup. "
        "Treat it as authoritative metadata about the startup files "
        "loaded into this process. Do not infer the current disk state "
        "from this manifest.\n\n"
        "Tool provenance rules: every tool response contains an "
        "execution record generated by Python. Treat an operation as "
        "completed only when execution.status is 'success'. For read_file, "
        "use result.source as evidence of a fresh disk read and preserve "
        "its path, read_at timestamp and SHA-256 when relevant. For "
        "write_file, report success only when execution.status is "
        "'success' and result.operation.verified is true. An error status "
        "means the requested operation did not complete successfully. "
        "A directory listing is only a snapshot from its listed_at time. "
        "Never claim a tool ran or succeeded without a corresponding "
        "successful execution record in the conversation.\n\n"
        "```json\n"
        f"{json.dumps(source_manifest, ensure_ascii=False, indent=2)}\n"
        "```"
    )

    return combined_prompt


def build_memory_snapshot_section() -> str:
    """Build the persistent memory snapshot section for the system prompt."""

    records = get_recent_memories(MEMORY_SNAPSHOT_LIMIT)

    metadata = {
        "description": (
            "Persistent memories loaded by Python from the memory "
            "database. This is a snapshot of the most recently "
            "updated active memories; use the search_memories tool "
            "for the current complete state of memory."
        ),
        "snapshot_type": "memory_snapshot",
        "loaded_at": _utc_timestamp(),
        "record_count": len(records),
        "limits": {
            "snapshot_records": MEMORY_SNAPSHOT_LIMIT,
            "content_preview_characters": MEMORY_CONTENT_PREVIEW_LENGTH,
        },
    }

    section = (
        "\n\n"
        "## Persistent Memory — Startup Snapshot\n\n"
        "The following memories were loaded by Python at startup from "
        "the persistent memory database. This snapshot may be outdated "
        "or incomplete: use the search_memories tool to retrieve the "
        "current state of memory, save_memory to add new memories, and "
        "update_memory to modify or supersede existing ones.\n\n"
        "```json\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
    )

    if not records:
        section += "No active memories are stored yet."
        return section

    entries = []

    for record in records:
        preview = record.content

        if len(preview) > MEMORY_CONTENT_PREVIEW_LENGTH:
            preview = (
                preview[:MEMORY_CONTENT_PREVIEW_LENGTH].rstrip()
                + " [...]"
            )

        entries.append(
            f"- [#{record.id} | {record.category} | {record.title} | "
            f"updated {record.updated_at}]\n  {preview}"
        )

    section += "\n".join(entries)

    return section


def build_active_project_section(
    active_project: dict[str, Any],
) -> str:
    """Build the active project section for the system prompt."""

    context_text, context_metadata = projects.read_project_context(
        active_project
    )

    metadata = {
        "description": (
            "The active project workspace for this session. While it "
            "is active, the file tools (list_files, read_file, "
            "write_file) operate on this project directory."
        ),
        "project": active_project["name"],
        "activated_at": _utc_timestamp(),
        "context_file": context_metadata,
    }

    section = (
        "\n\n"
        f"## Active Project — {active_project['name']}\n\n"
        "This session has an active project workspace. While it is "
        "active, the file tools (list_files, read_file, write_file) "
        "operate on this project directory: paths are relative to the "
        "project root, and write access covers the entire project. "
        "read_pdf and list_documents also include the PDF documents "
        "inside the project.\n\n"
        "The working method for an active project is based on the "
        "hidden context file .ARACELI_CONTEXT.md at the project root. "
        "It is the working memory of the project and the only state "
        "that survives beyond this conversation: create it if it does "
        "not exist, and keep it accurate and as compact as possible — "
        "it is injected into every conversation, so its size "
        "permanently consumes context window. It must contain: "
        "project description and goal, working instructions and "
        "method, decisions taken, general work state (current phase, "
        "in one or two sentences), and next steps. Prefer general "
        "rules over enumerations: an instruction like 'processed data "
        "is read from the generated .txt files' replaces any list of "
        "analyzed documents, which is derivable from the project "
        "files themselves. Do not duplicate file contents in the "
        "context file: reference files by name. Do not log individual "
        "actions: the record of the work is the generated files "
        "themselves. Update it only when something not derivable from "
        "the files changes: a new instruction from the user, a "
        "decision, a change of method or phase, or the general state "
        "after closing a unit of work. When the user asks for "
        "concrete results (a comparison, a report, a table), generate "
        "the corresponding files inside the project with descriptive "
        "names. Python reads this file when the project is activated.\n\n"
        "```json\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
    )

    if context_text:
        section += (
            "### Project Context File — Snapshot Read at Activation\n\n"
            f"{context_text}"
        )
    elif context_metadata.get("status") in ("not_found", "empty"):
        section += (
            "No usable project context file exists yet. Creating "
            ".ARACELI_CONTEXT.md at the project root is the first step "
            "of the work in this project."
        )
    else:
        section += (
            "The project context file could not be read (status: "
            f"{context_metadata.get('status')}). Consider recreating "
            "it with write_file."
        )

    return section


def query_server_context() -> int | None:
    """Ask LM Studio for the loaded model's effective context length.

    Uses LM Studio's native API (GET /api/v0/models) and returns the
    loaded_context_length of the configured model, or None when the
    endpoint is unavailable, the format changed, or the model is not
    loaded.
    """

    try:
        api_root = BASE_URL.rstrip("/").removesuffix("/v1")
        url = f"{api_root}/api/v0/models"

        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))

    except (OSError, ValueError):
        return None

    for model in payload.get("data", []):
        if model.get("id") != MODEL:
            continue

        loaded_context = model.get("loaded_context_length")

        if isinstance(loaded_context, int) and loaded_context > 0:
            return loaded_context

        return None

    return None


def create_client() -> OpenAI:
    """Create an OpenAI-compatible client connected to LM Studio."""

    return OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=120.0,
    )


def create_conversation(
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Create a new conversation with the system prompt."""

    return [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]


def _print_tool_execution(tool_name: str, result_text: str) -> None:
    """Print a compact console line describing a tool execution."""

    status = "unknown"
    target = None
    error_message = None

    try:
        envelope = json.loads(result_text)
        execution = envelope.get("execution")

        if isinstance(execution, dict):
            status = execution.get("status", "unknown")
            target = execution.get("target")

        error = envelope.get("error")

        if isinstance(error, dict):
            error_message = error.get("message")

    except json.JSONDecodeError:
        pass

    line = f"\n[tool] {tool_name} -> {status}"

    if target is not None:
        line += f" | target: {target}"

    if error_message:
        line += f" | {error_message}"

    if status == "error":
        print(paint(line, *SYSTEM_ERROR))
    else:
        print(paint(line, *SYSTEM_MESSAGE))


def _extract_api_error_detail(error: Exception) -> str:
    """Return a readable message for API errors, including the body.

    The OpenAI client's str() often stops at "Error code: 400", but
    the response body carries the server's actual explanation.
    """

    body = getattr(error, "body", None)

    if isinstance(body, str) and body.strip():
        return f"{error}: {body}"

    if isinstance(body, dict):
        try:
            return f"{error}: {json.dumps(body, ensure_ascii=False)}"
        except (TypeError, ValueError):
            return str(error)

    return str(error)


def _context_size_hint(error: Exception) -> str | None:
    """Return a targeted hint when the server rejected a request
    because it exceeded the model's context size."""

    body = getattr(error, "body", None)

    payload: Any = None

    if isinstance(body, dict):
        payload = body
    elif isinstance(body, str):
        start = body.find("{")

        if start != -1:
            try:
                payload = json.loads(body[start:])
            except json.JSONDecodeError:
                return None

    if not isinstance(payload, dict):
        return None

    error_object = payload.get("error")

    if not isinstance(error_object, dict):
        return None

    if error_object.get("type") != "exceed_context_size_error":
        return None

    return (
        "The model's context in LM Studio is smaller than this "
        f"request. Raise the model's context length in LM Studio "
        f"(currently {error_object.get('n_ctx')} tokens) and try again."
    )


def _clean_answer(answer: str) -> str:
    """Remove model-emitted tool-call markup from a final answer."""

    if "<tool_call>" not in answer:
        return answer

    cleaned = re.sub(
        r"<tool_call>.*?</tool_call>", "", answer, flags=re.DOTALL
    )
    cleaned = cleaned.split("<tool_call>")[0]

    return cleaned.strip()


_EMBEDDED_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def _try_execute_embedded_call(
    answer: str,
    tool_definitions: list[dict[str, Any]],
) -> tuple[str, str] | None:
    """Execute a tool call the model embedded as text markup."""

    match = _EMBEDDED_CALL_PATTERN.search(answer)

    if match is None:
        return None

    try:
        payload = json.loads(match.group(1))
        name = payload.get("name")
        arguments = payload.get("arguments", {})

        if not isinstance(name, str) or not isinstance(arguments, dict):
            return None

        arguments_text = json.dumps(arguments)
    except (json.JSONDecodeError, TypeError):
        return None

    known_tools = {
        definition["function"]["name"]
        for definition in tool_definitions
    }

    if name not in known_tools:
        return None

    result_text = execute_tool(name, arguments_text)

    return result_text, name


def generate_response(
    client: OpenAI,
    messages: list[dict[str, Any]],
    tool_definitions: list[dict[str, Any]],
) -> tuple[str, int | None, str | None]:
    """Generate a response and handle tool calls."""

    for round_index in range(MAX_TOOL_ROUNDS + 1):

        request_arguments = {
            "model": MODEL,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }

        if tool_definitions and round_index < MAX_TOOL_ROUNDS:
            request_arguments["tools"] = tool_definitions
            request_arguments["tool_choice"] = "auto"

        response = client.chat.completions.create(**request_arguments)

        assistant_message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        usage = response.usage
        context_tokens = None

        if usage:
            context_tokens = (
                usage.prompt_tokens + usage.completion_tokens
            )

        messages.append(
            assistant_message.model_dump(exclude_none=True)
        )

        if finish_reason == "length":
            answer = assistant_message.content or ""
            return answer.strip(), context_tokens, finish_reason

        if not assistant_message.tool_calls:
            answer = assistant_message.content

            if not answer:
                raise RuntimeError("The model returned an empty response.")

            if "<tool_call>" in answer:
                executed = _try_execute_embedded_call(
                    answer, tool_definitions
                )

                if executed is not None:
                    result_text, called_name = executed

                    _print_tool_execution(called_name, result_text)

                    messages.append({
                        "role": "user",
                        "content": (
                            "[Tool execution notice] Your tool call "
                            "was received as plain text and executed "
                            "by Python. Use the tool_calls mechanism "
                            "for tool calls. Execution result:\n"
                            + result_text
                        ),
                    })

                    continue

                answer = _clean_answer(answer)

                if not answer:
                    raise RuntimeError(
                        "The model returned a malformed response "
                        "(embedded tool markup instead of an answer)."
                    )

                print(
                    paint(
                        "\n[WARNING] The model embedded tool-call markup "
                        "in its answer; it was removed.",
                        *SYSTEM_ERROR,
                    )
                )

            return answer.strip(), context_tokens, finish_reason

        for tool_call in assistant_message.tool_calls:

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments

            result_text = execute_tool(tool_name, arguments)

            _print_tool_execution(tool_name, result_text)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_text,
            })

    raise RuntimeError("Maximum tool call rounds exceeded.")


def print_memory_listing() -> None:
    """Print active memories for the /memory console command."""

    records = get_recent_memories(MAX_SNAPSHOT_LIMIT)
    active_count = count_memories(status="active")
    superseded_count = count_memories(status="superseded")

    print(
        paint(
            f"\n[Memory] {active_count} active, "
            f"{superseded_count} superseded",
            *SYSTEM_MESSAGE,
        )
    )

    if not records:
        print(paint("No active memories.", *SYSTEM_MESSAGE))
        return

    for record in records:
        print(
            paint(
                f"  #{record.id} | {record.category} | {record.title} "
                f"| updated {record.updated_at}",
                *SYSTEM_MESSAGE,
            )
        )

    if active_count > len(records):
        print(
            paint(
                f"  (showing the {len(records)} most recent of "
                f"{active_count} active memories)",
                *SYSTEM_MESSAGE,
            )
        )


def forget_memory(memory_id: int) -> None:
    """Delete a memory by id for the /forget console command."""

    try:
        deleted = delete_memory(memory_id)
    except ValueError as error:
        print(paint(f"\n[Memory] Could not delete: {error}", *SYSTEM_ERROR))
        return

    print(
        paint(
            f"\n[Memory] Deleted #{deleted.id} | {deleted.category} | "
            f"{deleted.title}",
            *SYSTEM_MESSAGE,
        )
    )


_PROJECT_USAGE = (
    "Usage: /project [status | list | info [name] | add <path> | "
    "remove <name> | use <name> | off]"
)

_PROJECT_FILE_COUNT_CAP = 500


def _format_project_info(project: dict[str, Any], is_active: bool) -> str:
    """Format a read-only project summary for /project info."""

    context_text, context_metadata = projects.read_project_context(project)

    directory = Path(project["path"])

    file_count = 0
    pdf_count = 0
    count_capped = False

    try:
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue

            file_count += 1

            if file_path.suffix.lower() == ".pdf":
                pdf_count += 1

            if file_count >= _PROJECT_FILE_COUNT_CAP:
                count_capped = True
                break
    except OSError:
        pass

    status_text = " (active)" if is_active else ""

    lines = [
        f"Project: {project['name']}{status_text}",
        f"Directory: {project['path']}",
        f"Registered: {project.get('added_at', 'unknown')}",
        f"Files: {file_count}{'+' if count_capped else ''} "
        f"({pdf_count} PDFs)",
        "",
    ]

    if context_text:
        size_kb = context_metadata.get("size_bytes", 0) / 1024

        lines.append(
            f"--- {projects.CONTEXT_FILE_NAME} "
            f"({context_metadata['status']}, {size_kb:.1f} KB) ---"
        )
        lines.append(context_text)
    else:
        status_description = {
            "not_found": "does not exist yet",
            "empty": "is empty",
            "oversized": "is too large to display",
            "load_error": "could not be read",
        }.get(context_metadata.get("status"), "is not available")

        lines.append(
            f"{projects.CONTEXT_FILE_NAME} {status_description}. Ask "
            "Araceli to create or update it while working on this "
            "project."
        )

    return "\n".join(lines)


def _handle_project_command(
    user_input: str,
    active_project: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None, bool]:
    """Handle a /project console command.

    Returns (message, new_active_project, workspace_changed).
    """

    tokens = user_input.strip().split(maxsplit=2)

    subcommand = tokens[1].lower() if len(tokens) > 1 else "status"
    argument = tokens[2].strip() if len(tokens) > 2 else ""

    if subcommand == "status":
        if active_project is None:
            return (
                "No active project. Use /project set <name> to "
                "activate one, or /project add <path> to register a "
                "new project.",
                active_project,
                False,
            )

        return (
            f"Active project: {active_project['name']}",
            active_project,
            False,
        )

    if subcommand == "list":
        entries = projects.load_projects()

        if not entries:
            return (
                "No projects registered. Use /project add <path>.",
                active_project,
                False,
            )

        lines = [f"Registered projects: {len(entries)}"]

        for entry in entries:
            marker = (
                " (active)"
                if active_project is not None
                and entry["name"] == active_project["name"]
                else ""
            )

            missing = (
                " [missing]"
                if not Path(entry["path"]).is_dir()
                else ""
            )

            lines.append(
                f"  {entry['name']}{marker}{missing} — {entry['path']}"
            )

        return ("\n".join(lines), active_project, False)

    if subcommand == "info":
        if argument:
            entry = projects.find_project(argument)

            if entry is None:
                return (
                    f"No project is registered with the name "
                    f"'{argument}'.",
                    active_project,
                    False,
                )

            is_active = (
                active_project is not None
                and entry["name"] == active_project["name"]
            )

            return (
                _format_project_info(entry, is_active),
                active_project,
                False,
            )

        if active_project is None:
            registered = len(projects.load_projects())

            if registered:
                return (
                    f"No active project ({registered} registered). "
                    "Use /project use <name> to activate one, or "
                    "/project info <name> to inspect one without "
                    "activating it.",
                    active_project,
                    False,
                )

            return (
                "No active project and no projects registered. Use "
                "/project add <path> to register one.",
                active_project,
                False,
            )

        return (
            _format_project_info(active_project, True),
            active_project,
            False,
        )

    if subcommand == "add":
        try:
            entry = projects.add_project(argument)
        except ValueError as error:
            return (
                f"Could not add project: {error}",
                active_project,
                False,
            )

        return (
            f"Project added: {entry['name']} ({entry['path']})\n"
            f"Activate it with: /project use {entry['name']}",
            active_project,
            False,
        )

    if subcommand == "remove":
        try:
            removed = projects.remove_project(argument)
        except ValueError as error:
            return (
                f"Could not remove project: {error}",
                active_project,
                False,
            )

        was_active = (
            active_project is not None
            and removed["name"] == active_project["name"]
        )

        message = f"Project removed: {removed['name']}"

        if was_active:
            message += " (it was active; it has been deactivated)"

        return (message, None if was_active else active_project, was_active)

    if subcommand == "set":
        if not argument:
            return (_PROJECT_USAGE, active_project, False)

        entry = projects.find_project(argument)

        if entry is None:
            return (
                f"No project is registered with the name '{argument}'.",
                active_project,
                False,
            )

        if not Path(entry["path"]).is_dir():
            return (
                "The project directory no longer exists: "
                f"{entry['path']}",
                active_project,
                False,
            )

        return (f"Active project: {entry['name']}", entry, True)

    if subcommand == "off":
        if active_project is None:
            return ("No active project.", active_project, False)

        return (
            f"Project deactivated: {active_project['name']}",
            None,
            True,
        )

    return (_PROJECT_USAGE, active_project, False)


def main() -> None:
    """Application entry point."""

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass

    init_colors()

    print(paint("=" * 55, *SYSTEM_MESSAGE))
    print(paint("             ARACELI - PERSONAL ASSISTANT", *SYSTEM_MESSAGE))
    print(paint("=" * 55, *SYSTEM_MESSAGE))

    try:
        behavioral_prompt, behavioral_source = load_system_prompt()
        project_context, project_context_source = load_project_context()
    except Exception as error:
        print(paint(f"\nInitialization error: {error}", *SYSTEM_ERROR))
        return

    memory_enabled = False

    try:
        init_database()
        build_memory_snapshot_section()
        memory_enabled = True
    except Exception as error:
        print(
            paint(
                f"\n[WARNING] Memory initialization failed: {error}",
                *SYSTEM_ERROR,
            )
        )
        print(
            paint(
                "Starting without persistent memory tools.",
                *SYSTEM_ERROR,
            )
        )

    active_project: dict[str, Any] | None = None

    def compose_prompt(
        current_project: dict[str, Any] | None,
    ) -> str:
        """Compose the full system prompt for a conversation start."""

        prompt_memory_section = None

        if memory_enabled:
            try:
                prompt_memory_section = build_memory_snapshot_section()
            except Exception as error:
                print(
                    paint(
                        f"\n[WARNING] Could not refresh memory "
                        f"snapshot: {error}",
                        *SYSTEM_ERROR,
                    )
                )

        project_section = (
            build_active_project_section(current_project)
            if current_project is not None
            else None
        )

        return build_system_prompt(
            behavioral_prompt,
            behavioral_source,
            project_context,
            project_context_source,
            prompt_memory_section,
            project_section,
        )

    system_prompt = compose_prompt(active_project)

    tool_definitions = BASE_TOOL_DEFINITIONS + (
        MEMORY_TOOL_DEFINITIONS if memory_enabled else []
    )

    server_context = query_server_context()

    context_limit = (
        server_context if server_context is not None else CONTEXT_LENGTH
    )

    if server_context is not None and server_context < CONTEXT_LENGTH:
        print(
            paint(
                f"\n[WARNING] Server model context: "
                f"{server_context:,} tokens - smaller than the "
                f"configured {CONTEXT_LENGTH:,}. Requests larger than "
                f"{server_context:,} tokens will fail. Raise the "
                "model's context length in LM Studio.",
                *SYSTEM_ERROR,
            )
        )

    try:
        client = create_client()
    except Exception as error:
        print(paint(f"\nInitialization error: {error}", DIM))
        return

    messages = create_conversation(system_prompt)

    print(paint(f"\nModel: {MODEL}", *SYSTEM_MESSAGE))
    print(paint(f"Server: {BASE_URL}", *SYSTEM_MESSAGE))
    if server_context is not None:
        print(
            paint(
                f"Context length: {server_context:,} tokens "
                "(server, verified at startup)",
                *SYSTEM_MESSAGE,
            )
        )
    else:
        print(
            paint(
                f"Context length: {CONTEXT_LENGTH:,} tokens "
                "(server verification unavailable)",
                *SYSTEM_MESSAGE,
            )
        )

    if memory_enabled:
        print(
            paint(
                f"Memory: enabled ({DEFAULT_DB_PATH.name})",
                *SYSTEM_MESSAGE,
            )
        )
    else:
        print(
            paint(
                "Memory: disabled (initialization failed)",
                *SYSTEM_MESSAGE,
            )
        )

    print(paint("Active project: none", *SYSTEM_MESSAGE))

    print(paint("\nAraceli is ready.", *SYSTEM_MESSAGE))
    print(paint("Commands:", *SYSTEM_MESSAGE))
    print(paint("\t/reset (new conversation)", *SYSTEM_MESSAGE))
    print(paint("\t/memory (list memories)", *SYSTEM_MESSAGE))
    print(paint("\t/forget <id> (delete memory)", *SYSTEM_MESSAGE))
    print(
        paint(
            "\t/project [status|list|info|add|remove|set|off] "
            "(manage project workspaces)",
            *SYSTEM_MESSAGE,
        )
    )
    print(paint("\t/exit (quit)", *SYSTEM_MESSAGE))

    print(paint("-" * 55, *SYSTEM_MESSAGE))

    while True:

        try:
            user_input = input("\n" + paint("You: ", *USER_INPUT)).strip()

            if not user_input:
                continue

            command = user_input.lower()

            if command in ("/exit", "/quit", "/salir"):
                print(
                    "\n"
                    + paint("Araceli: ", *ARACELI_INPUT)
                    + paint("Goodbye!", *ARACELI_TEXT)
                )
                break

            if command == "/reset":
                system_prompt = compose_prompt(active_project)
                messages = create_conversation(system_prompt)
                print(paint("\n[Conversation reset]", *SYSTEM_MESSAGE))
                continue

            if command == "/project" or command.startswith("/project "):
                message, new_active, changed = _handle_project_command(
                    user_input,
                    active_project,
                )

                print(paint(f"\n{message}", *SYSTEM_MESSAGE))

                if changed:
                    active_project = new_active

                    if active_project is not None:
                        set_workspace(active_project["path"])
                    else:
                        set_workspace(None)

                    system_prompt = compose_prompt(active_project)
                    messages = create_conversation(system_prompt)
                    print(paint("\n[New conversation started]", *SYSTEM_MESSAGE))

                continue

            if command == "/memory":
                if not memory_enabled:
                    print(paint("\n[Memory] Memory is disabled.", *SYSTEM_MESSAGE))
                    continue

                try:
                    print_memory_listing()
                except Exception as error:
                    print(
                        paint(
                            f"\n[Memory] Could not list memories: "
                            f"{error}",
                            *SYSTEM_MESSAGE,
                        )
                    )

                continue

            if command.startswith("/forget"):
                if not memory_enabled:
                    print(paint("\n[Memory] Memory is disabled.", *SYSTEM_MESSAGE))
                    continue

                argument = user_input[len("/forget"):].strip()

                if not argument.isdigit():
                    print(
                        paint(
                            "\nUsage: /forget <id>  (see /memory for ids)",
                            *SYSTEM_MESSAGE,
                        )
                    )
                    continue

                try:
                    forget_memory(int(argument))
                except Exception as error:
                    print(
                        paint(
                            f"\n[Memory] Could not delete: {error}",
                            *SYSTEM_MESSAGE,
                        )
                    )

                continue

            previous_messages = copy.deepcopy(messages)

            messages.append({
                "role": "user",
                "content": user_input,
            })

            print("\n" + paint("Araceli: ", *ARACELI_INPUT), end="", flush=True)

            try:
                answer, context_tokens, finish_reason = generate_response(
                    client,
                    messages,
                    tool_definitions,
                )

                print(paint(answer, *ARACELI_TEXT))

                if context_tokens is not None:
                    available_tokens = max(
                        0,
                        context_limit - context_tokens,
                    )

                    usage_percentage = (
                        context_tokens / context_limit
                    ) * 100

                    if usage_percentage >= 90:
                        context_style = SYSTEM_ERROR
                    else:
                        context_style = SYSTEM_MESSAGE

                    print(
                        paint(
                            f"\nContext: {usage_percentage:.1f}% "
                            f"({context_tokens:,}/{context_limit:,} "
                            f"tokens) - {available_tokens:,} free",
                            *context_style,
                        )
                    )
                else:
                    print(paint("\nContext usage: unavailable", *SYSTEM_MESSAGE))

                if finish_reason == "length":
                    print(
                        paint(
                            "\nWARNING: RESPONSE MAY BE INCOMPLETE\n"
                            "The model reached a generation limit "
                            "(finish_reason: length).\n"
                            "This may be caused by MAX_TOKENS or the "
                            "context limit.",
                            *SYSTEM_ERROR,
                        )
                    )

            except Exception:
                messages = previous_messages
                raise

        except KeyboardInterrupt:
            print(paint("\n\n[Interrupted]", *SYSTEM_MESSAGE))
            continue

        except Exception as error:
            error_message = _extract_api_error_detail(error)
            context_hint = _context_size_hint(error)

            if context_hint:
                error_message += f"\n{context_hint}"

            print(
                paint(
                    f"\n\nCommunication error: {error_message}",
                    *SYSTEM_ERROR,
                )
            )


if __name__ == "__main__":
    main()
