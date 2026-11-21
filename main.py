import copy
import hashlib
import json

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import (
    API_KEY,
    BASE_URL,
    MODEL,
    CONTEXT_LENGTH,
    TEMPERATURE,
    MAX_TOKENS,
    SYSTEM_PROMPT_FILE,
)

from tools import execute_tool


ROOT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = ROOT_DIR / SYSTEM_PROMPT_FILE
PROJECT_CONTEXT_PATH = ROOT_DIR / "docs" / "project_context.md"

MAX_TOOL_ROUNDS = 5


TOOL_DEFINITIONS = [
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
                "List readable text files in a project directory. "
                "The result includes the directory and the time at which "
                "the listing was generated. Paths must be relative to "
                "the project root."
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
                "the project directory. The result includes Python-generated "
                "source metadata: relative path, read timestamp, byte size, "
                "and SHA-256 hash. This is a fresh disk read, not the "
                "startup snapshot."
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
                "Create or update a text file inside the authorized "
                "memory, tests or docs directories. Existing files are "
                "backed up automatically. The result reports the backup "
                "and whether the written bytes were verified by reading "
                "the file back."
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


def generate_response(
    client: OpenAI,
    messages: list[dict[str, Any]],
) -> tuple[str, int | None, str | None]:
    """Generate a response and handle tool calls."""

    for round_index in range(MAX_TOOL_ROUNDS + 1):

        request_arguments = {
            "model": MODEL,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }

        if round_index < MAX_TOOL_ROUNDS:
            request_arguments["tools"] = TOOL_DEFINITIONS
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

            return answer.strip(), context_tokens, finish_reason

        for tool_call in assistant_message.tool_calls:

            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments

            result_text = execute_tool(tool_name, arguments)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_text,
            })

    raise RuntimeError("Maximum tool call rounds exceeded.")


def main() -> None:
    """Application entry point."""

    print("=" * 55)
    print("             ARACELI - PERSONAL ASSISTANT")
    print("=" * 55)

    try:
        system_prompt, system_prompt_source = load_system_prompt()
        project_context, project_context_source = load_project_context()

        system_prompt = build_system_prompt(
            system_prompt,
            system_prompt_source,
            project_context,
            project_context_source,
        )

        client = create_client()

    except Exception as error:
        print(f"\nInitialization error: {error}")
        return

    messages = create_conversation(system_prompt)

    print(f"\nModel: {MODEL}")
    print(f"Server: {BASE_URL}")
    print(f"Context length: {CONTEXT_LENGTH:,} tokens")
    print("\nAraceli is ready.")
    print("Commands: /reset (new conversation), /exit (quit)")
    print("-" * 55)

    while True:

        try:
            user_input = input("\nYou: ").strip()

            if not user_input:
                continue

            command = user_input.lower()

            if command in ("/exit", "/quit", "/salir"):
                print("\nAraceli: Goodbye!")
                break

            if command == "/reset":
                messages = create_conversation(system_prompt)
                print("\n[Conversation reset]")
                continue

            previous_messages = copy.deepcopy(messages)

            messages.append({
                "role": "user",
                "content": user_input,
            })

            print("\nAraceli: ", end="", flush=True)

            try:
                answer, context_tokens, finish_reason = generate_response(
                    client,
                    messages,
                )

                print(answer)

                if context_tokens is not None:
                    available_tokens = max(
                        0,
                        CONTEXT_LENGTH - context_tokens,
                    )

                    usage_percentage = (
                        context_tokens / CONTEXT_LENGTH
                    ) * 100

                    available_percentage = max(
                        0.0,
                        100.0 - usage_percentage,
                    )

                    print(
                        f"\nContext usage: {usage_percentage:.1f}% "
                        f"({context_tokens:,} / {CONTEXT_LENGTH:,} tokens)"
                    )

                    print(
                        f"Available context: {available_percentage:.1f}% "
                        f"({available_tokens:,} tokens)"
                    )
                else:
                    print("\nContext usage: unavailable")

                if finish_reason == "length":
                    print(
                        "\nWARNING: RESPONSE MAY BE INCOMPLETE\n"
                        "The model reached a generation limit "
                        "(finish_reason: length).\n"
                        "This may be caused by MAX_TOKENS or the context limit."
                    )

            except Exception:
                messages = previous_messages
                raise

        except KeyboardInterrupt:
            print("\n\n[Interrupted]")
            continue

        except Exception as error:
            print(f"\n\nCommunication error: {error}")


if __name__ == "__main__":
    main()
