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
-   `memory/`: persistent memory package.
    -   `memory/database.py`: SQLite connection management and schema
        initialization. The database file is `data/araceli.db`.
    -   `memory/models.py`: the `MemoryRecord` dataclass.
    -   `memory/memory_store.py`: save, search, update, and recent-
        memory operations with Python-side validation.
-   `docs/`: project documentation.
-   `tests/`: automated memory tests (`test_memory.py`) and tool
    documentation (`tool_test.md`).
-   `data/`: application data directory; contains the SQLite memory
    database. Excluded from the model's file access and from git.

The model proposes tool calls. Python code validates and executes them.
Instructions given to the model are not a substitute for
application-side validation.

## Startup and Conversation Lifecycle

1.  `main.py` loads `system_prompt.md`.
2.  At startup, `main.py` loads `docs/project_context.md` once, if the
    file exists and contains readable, non-empty UTF-8 text.
3.  `main.py` initializes the memory database (`data/araceli.db`),
    creating the schema if needed, and builds a memory snapshot from
    the most recently updated active memories (default 15). If memory
    initialization fails, the application prints a warning and starts
    without memory tools.
4.  The project context and the memory snapshot are appended to the
    system prompt as separate technical reference sections. They
    supplement, but do not replace, behavioral instructions.
5.  `main.py` creates the LM Studio client and initializes an in-memory
    conversation with the combined system prompt.
6.  The console accepts user messages and supports `/reset` and exit
    commands.
7.  For each user message, `main.py` sends the conversation to the
    configured model.
8.  The model may request a tool. `main.py` dispatches it through
    `tools.py`, appends the result, prints a compact console line
    describing each execution (`[tool] name -> status`), and continues
    the model interaction, subject to `MAX_TOOL_ROUNDS`.
9.  The application displays the final answer and, when available,
    context-token usage. A `finish_reason` of `length` triggers a
    warning that the response may be incomplete.
10. If an interaction raises an exception, the previous conversation
    history is restored.

The project context is loaded once per application execution. `/reset`
creates a new conversation using the already combined system prompt; it
does not reread the project context file. Unlike the project context,
the memory snapshot is refreshed on `/reset`, because memory contents
change during normal use.

If `docs/project_context.md` is missing, empty, or cannot be read, the
application displays a warning and continues without project-specific
context.

Conversation history exists only in process memory. It is lost when the
application exits; `/reset` starts a new conversation. Persistent
memories survive both.

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
-   `save_memory(category, title, content, tags, source)`: stores a new
    persistent memory in SQLite. Categories are validated against a
    Python allowlist (`preference`, `personal`, `project`, `decision`,
    `task`, `fact`, `knowledge`). Duplicate active memories with the
    same category and title are rejected.
-   `search_memories(query, category, limit)`: keyword search across
    title, content, and tags using SQL `LIKE` with escaped wildcards.
    Returns active memories by default, most recently updated first.
-   `update_memory(memory_id, ...)`: updates fields of an existing
    memory by id, including changing its status to `superseded`.

There is no confirmed tool for general shell execution, arbitrary Python
execution, file deletion, memory deletion, internet search, or external
API access.

## Persistent Memory

Persistent memory is stored in `data/araceli.db` (SQLite, created on
first use). The schema is a single `memories` table with indexes on
`category` and `status`.

Python-side restrictions enforced by `memory/memory_store.py`:

-   Category allowlist: `preference`, `personal`, `project`, `decision`,
    `task`, `fact`, `knowledge`.
-   Status allowlist: `active`, `superseded`.
-   Maximum lengths: title 200, content 4000, tags 200, source 500,
    query 200 characters.
-   Search and snapshot limits between 1 and 50 results.
-   No duplicate active memories sharing category and title (enforced
    on both save and update).
-   No physical deletion through model tools; obsolete memories are
    marked `superseded`.

Memory results are returned through the same execution envelope as
other tools, so the model can cite memory ids and update timestamps as
evidence. The startup system prompt includes a snapshot section with
metadata (load timestamp and record count) that distinguishes the
snapshot from the current state retrievable through `search_memories`.

## File Access and Security

File tools use project-relative paths and restrict file extensions, file
sizes, and accessible directories. Normal listing and reading exclude
`.venv`, `__pycache__`, `.git`, `.backups`, and `data`. Writing is
restricted to `memory/`, `tests/`, and `docs/`. As a result, the model
cannot access the memory database file directly; all memory access goes
through the validated memory tools.

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
`docs/project_context.md` once at application startup. - Persistent
memory using SQLite (`data/araceli.db`) with save, search, and update
tools, a startup memory snapshot, and snapshot refresh on `/reset`. -
Automated unit tests for the memory store and the memory tool dispatch
(`tests/test_memory.py`, run with `python -m unittest discover -s tests
-t .`). - Version control with git and a private GitHub repository;
`data/`, `.venv/`, `.backups/`, and `__pycache__/` are not tracked.

Not implemented: - Conversation summarization, pruning, or compaction. -
Internet search or external integrations. - Automatic discovery of the
effective LM Studio context length. - Physical memory deletion through
model tools. - Semantic or embedding-based memory search. - A persistent
tool-execution audit log (deliberately deferred). - Automated tests for
the file tools and the conversation loop.

## Development Priorities

1.  Evaluate memory retrieval quality with real usage before
    considering FTS5 or embedding-based search.
2.  Add focused automated tests for the file tools and conversation
    handling.
3.  Consider conversation summarization or pruning when context usage
    approaches the configured limit.
4.  Revisit a persistent execution log only if unexplained tool or file
    incidents occur.

This document describes the current implementation. When it conflicts
with source code, inspect the code and update this document. Clearly
distinguish implemented behavior from planned work.
