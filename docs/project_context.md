# Araceli --- Project Context

## Overview

Araceli is a local Python assistant that communicates with a language
model served by LM Studio through its OpenAI-compatible API. The model
can request a limited set of Python tools; the application validates and
executes those requests.

User-facing conversation is in Spanish (Spain). Source code,
identifiers, comments, technical documentation, logs, and SQL are in
English.

## Architecture

-   `main.py`: application startup, console interface, conversation
    history, model requests, and tool-call loop.
-   `config.py`: LM Studio connection and model-generation settings.
-   `system_prompt.md`: behavioral instructions loaded as the system
    message.
-   `tools.py`: tool definitions, validation, execution, and dispatch.
-   `memory/`: reserved for memory functionality; persistent memory is
    not implemented.
-   `docs/`: project documentation.
-   `tests/`: currently contains tool-related documentation; a complete
    automated test suite is not confirmed.
-   `data/`: application data directory.

The model proposes tool calls. Python code validates and executes them.
Instructions given to the model are not a substitute for
application-side validation.

## Startup and Conversation Lifecycle

1.  `main.py` loads `system_prompt.md`.
2.  At startup, `main.py` loads `docs/project_context.md` once, if the
    file exists and contains readable, non-empty UTF-8 text.
3.  The project context is appended to the system prompt as a separate
    technical reference section. It supplements, but does not replace,
    behavioral instructions.
4.  `main.py` creates the LM Studio client and initializes an in-memory
    conversation with the combined system prompt.
5.  The console accepts user messages and supports `/reset` and exit
    commands.
6.  For each user message, `main.py` sends the conversation to the
    configured model.
7.  The model may request a tool. `main.py` dispatches it through
    `tools.py`, appends the result, and continues the model interaction,
    subject to `MAX_TOOL_ROUNDS`.
8.  The application displays the final answer and, when available,
    context-token usage. A `finish_reason` of `length` triggers a
    warning that the response may be incomplete.
9.  If an interaction raises an exception, the previous conversation
    history is restored.

The project context is loaded once per application execution. `/reset`
creates a new conversation using the already combined system prompt; it
does not reread the project context file.

If `docs/project_context.md` is missing, empty, or cannot be read, the
application displays a warning and continues without project-specific
context.

Conversation history exists only in process memory. It is lost when the
application exits; `/reset` starts a new conversation.

## Available Tools

The model can request these tools:

-   `calculate(expression)`: evaluates arithmetic using restricted AST
    parsing. It does not execute arbitrary Python or support variables
    or function calls.
-   `list_files(directory=".")`: lists up to 200 readable text files
    using project-relative paths.
-   `read_file(path)`: reads an allowed UTF-8 text file within the
    project, subject to extension and size restrictions.
-   `write_file(path, content)`: creates or updates files only under
    `memory/`, `tests/`, and `docs/`. It supports an extension allowlist
    and a 256 KB content limit. Before overwriting an existing file, it
    creates a timestamped backup under `.backups/`.

There is no confirmed tool for general shell execution, arbitrary Python
execution, file deletion, internet search, or external API access.

## File Access and Security

File tools use project-relative paths and restrict file extensions, file
sizes, and accessible directories. Normal listing and reading exclude
`.venv`, `__pycache__`, `.git`, `.backups`, and `data`. Writing is
restricted to `memory/`, `tests/`, and `docs/`.

Path checks provide safeguards but are not a complete security boundary
against a hostile local filesystem. Protection against symlink/junction
traversal and time-of-check/time-of-use races has not been established.
Existing files are backed up before overwrite; atomic backup or write
behavior is not established.

## Configuration

`config.py` defines:

-   `BASE_URL`: LM Studio API endpoint.
-   `API_KEY`: API client key.
-   `MODEL`: model identifier.
-   `TEMPERATURE`: generation temperature.
-   `MAX_TOKENS`: maximum generated tokens per request.
-   `CONTEXT_LENGTH`: configured context length used for usage
    reporting.
-   `SYSTEM_PROMPT_FILE`: system prompt filename.

LM Studio must be running with the configured model loaded. The
application does not currently retrieve the loaded model's effective
context length automatically.

## Current Status

Implemented: - Local LM Studio integration through the OpenAI Python
client. - Console conversation loop and in-memory history. - Bounded
tool-calling loop. - Restricted arithmetic and project-file tools. -
File validation and pre-overwrite backups. - Context-usage reporting
when the API returns usage data. - Warning for responses terminated with
`finish_reason="length"`. - Automatic loading of
`docs/project_context.md` once at application startup. - Reuse of the
combined system prompt after `/reset`, without rereading the project
context file.

Not implemented: - Persistent memory or SQLite storage. - Conversation
summarization, pruning, or compaction. - Internet search or external
integrations. - Automatic discovery of the effective LM Studio context
length. - A confirmed comprehensive automated test suite.

## Development Priorities

1.  Design and implement persistent memory for relevant memories,
    projects, decisions, conversation summaries, and source references.
2.  Add focused automated tests for tools, file access, conversation
    handling, and memory.
3.  Consider conversation summarization or pruning when context usage
    approaches the configured limit.

This document describes the current implementation. When it conflicts
with source code, inspect the code and update this document. Clearly
distinguish implemented behavior from planned work.
