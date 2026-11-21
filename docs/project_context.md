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
-   `tools.py`: tool implementations, validation, execution, dispatch,
    and the active-workspace mechanism for file tools.
-   `projects.py`: registry of user project workspaces
    (`data/projects.json`) and reading of the per-project context file
    (`ARACELI_CONTEXT.md`).
-   `memory/`: persistent memory package.
    -   `memory/database.py`: SQLite connection management and schema
        initialization. The database file is `data/araceli.db`.
    -   `memory/models.py`: the `MemoryRecord` dataclass.
    -   `memory/memory_store.py`: save, search, update, and recent-
        memory operations with Python-side validation.
-   `docs/`: project documentation.
-   `tests/`: automated tests (`test_memory.py` for the memory system,
    `test_tools.py` for the calculator, file tools, and tool dispatch,
    `test_pdf_web.py` for PDF and web tools) and tool documentation
    (`tool_test.md`).
-   `data/`: application data directory; contains the SQLite memory
    database (`data/araceli.db`), the projects registry
    (`data/projects.json`), the internal documents directory
    (`data/documents/`), and the optional pointer file for the external
    documents directory (`data/documents_path.txt`). All are excluded
    from the model's general file access and from git.

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
6.  The console accepts user messages and supports these commands:
    `/reset` (new conversation), `/memory` (list active memories),
    `/forget <id>` (physically delete a memory), `/project`
    (manage project workspaces: `status`, `list`, `info [name]`,
    `add <path>`, `remove <name>`, `use <name>`, `off`), and `/exit`
    (quit). Memory management and project management commands are
    handled entirely by Python and are never exposed to the model.
    Activating or deactivating a project (or removing the active one)
    starts a new conversation automatically, because the system prompt
    must reflect the session scope. `/project info` never changes the
    workspace or the conversation.
7.  For each user message, `main.py` sends the conversation to the
    configured model.
8.  The model may request a tool. `main.py` dispatches it through
    `tools.py`, appends the result, prints a compact console line
    describing each execution (`[tool] name -> status`), and continues
    the model interaction, subject to `MAX_TOOL_ROUNDS` (currently 8).
    If the model emits a tool call as text markup instead of using the
    tool_calls mechanism, Python parses it, executes it if valid, and
    returns the result to the conversation; answers consisting only of
    markup raise an error instead of reaching the user.
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
    in the current workspace, using workspace-relative paths.
-   `read_file(path)`: reads an allowed UTF-8 text file in the current
    workspace, subject to extension and size restrictions.
-   `write_file(path, content)`: creates or updates files. In an
    active project, anywhere inside the project directory; without
    one, only under `memory/`, `tests/`, and `docs/` of the Araceli
    repository. It supports an extension allowlist (text formats
    including `.csv`, `.html`, `.xml`, `.log`) and a 256 KB content
    limit. Before overwriting an existing file, it creates a
    timestamped backup under `.backups/`.
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
-   `read_pdf(path)`: extracts text from a PDF document. Search order:
    the active project directory (if one is active), then the
    configured documents directories. Paths are relative to those
    roots. Limits: 10 MB, 50 pages, 100,000 extracted characters.
    Scanned PDFs without a text layer return no text.
-   `list_documents()`: lists the PDF documents available in the
    active project (if any) and the configured documents directories
    (name, size, modification time, and which root each belongs to).
    Only `.pdf` files are listed, up to 100 entries.
-   `web_search(query, max_results)`: generic web search through
    DuckDuckGo (`ddgs` package, no API key). Returns titles, URLs and
    snippets with provenance metadata. Retries transient failures up to
    three times.
-   `web_fetch(url)`: fetches a public http(s) page and returns its
    readable text (HTML stripped of scripts and styles) with the final
    URL, content type, and fetch timestamp. Limits: 512 KB raw, 24,000
    text characters, 15 second timeout.

There is no confirmed tool for general shell execution, arbitrary Python
execution, file deletion, memory deletion, or external API access
beyond the web tools above.

## Private Documents and Web Access

Documents are read from up to two configured roots:

1.  **External directory** (optional, preferred on name collision):
    the user defines it by writing a single absolute path into
    `data/documents_path.txt` (gitignored, part of `data/`). This is
    the intended place for real private documents that live outside
    the repository, keeping them away from development tooling.
2.  **Internal directory** (`data/documents/`, gitignored): useful for
    test and demo documents.

`read_pdf` is the only way to read documents from either root; it
cannot escape them (no traversal, no absolute paths), and it reports
which root each file came from without exposing the external absolute
path to the model. A misconfigured pointer file (relative path or
missing directory) raises a clear error.

Web access rules enforced by Python:

-   `web_fetch` only accepts http/https URLs on ports 80 and 443 that
    resolve to public addresses; private, loopback, link-local,
    reserved, and multicast addresses are rejected, including after
    redirects.
-   Only `text/html`, `application/xhtml+xml`, and `text/plain`
    content types are returned; binaries are rejected.
-   TLS verification uses the operating system trust store via
    `truststore` (Windows certificate store).
-   Known limitation: DNS rebinding between validation and fetch is
    not prevented (time-of-check/time-of-use).

Privacy model: private documents are analyzed locally; web queries
must remain generic. The system prompt forbids including private data
(names, addresses, contract numbers, consumption figures) in web
searches. Python cannot validate this semantically, so the queries are
visible to the user through the `[tool]` console lines.

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
    marked `superseded`. Physical deletion is available only to the
    user through the `/forget <id>` console command, backed by
    `memory_store.delete_memory`, which Python-side code can also call
    directly.

`/memory` lists up to the 50 most recently updated active memories
with their ids, categories, titles and update timestamps, plus the
total active and superseded counts. `/forget <id>` requires an
explicit numeric id and prints the deleted record as confirmation;
invalid or unknown ids delete nothing.

Memory results are returned through the same execution envelope as
other tools, so the model can cite memory ids and update timestamps as
evidence. The startup system prompt includes a snapshot section with
metadata (load timestamp and record count) that distinguishes the
snapshot from the current state retrievable through `search_memories`.

## Project Workspaces

Users can register project directories (outside the Araceli
repository) and grant Araceli per-session access to exactly one of
them.

-   **Registry:** `data/projects.json` (gitignored). Managed only
    through the `/project` console command: `add` validates that the
    path is absolute, exists, is not a drive root or system directory,
    is not the Araceli repository or inside/containing it, and is not
    already registered (by path or by folder name, case-insensitive).
    `remove` deletes the registry entry; the directory is untouched.
-   **Active project:** at most one per session, not persisted across
    application restarts. `/project use <name>` activates it and
    `/project off` deactivates it; both start a new conversation.
    While a project is active, `tools.set_workspace` (Python-side
    only) scopes `list_files`, `read_file`, and `write_file` to the
    project directory: paths are relative to its root, write access
    covers the whole project, and repository-specific exclusions do
    not apply. `read_pdf` and `list_documents` treat the active
    project directory as the primary documents root. Without an active
    project, the tools operate on the Araceli repository with the
    usual restrictions.
-   **Project context file:** each project keeps the hidden file
    `.ARACELI_CONTEXT.md` at its root, written by Araceli through the
    normal `write_file` tool. It is the working memory of the project:
    description and goal, working instructions received from the
    user, work completed, decisions taken, pending tasks, and next
    steps. When a project is activated (and on every `/reset`),
    Python reads it and injects it into the system prompt as a
    snapshot with provenance metadata (read timestamp, SHA-256,
    status). A missing, empty, or oversized context file is reported
    as such, and the model is instructed to create it as the first
    step of the work. Araceli also generates result files (reports,
    comparisons) and temporary working files inside the project when
    the user asks for them.
-   **Project summaries:** `/project info` (no argument) shows a
    read-only summary of the active project; `/project info <name>`
    shows it for any registered project without activating it. The
    summary includes the project name, directory, registration date,
    a capped file count (with PDF count), and the content of the
    context file with its status. It never changes the workspace or
    the conversation.
-   The model has no tool to change the workspace or the active
    project; only the user can, through console commands. Workspace
    writes still produce backups under `.backups/` and are verified
    by reading the bytes back.

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

The direct dependencies are `openai`, `pypdf` (PDF text extraction),
`ddgs` (DuckDuckGo search), and `truststore` (Windows certificate
store for TLS), pinned in `requirements.txt`. Rebuild the environment
with `python -m venv .venv` followed by
`.venv\Scripts\pip install -r requirements.txt`. Run the test suite
with `python -m unittest discover -s tests -t .`.

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
User-side memory management console commands: `/memory` (list) and
`/forget <id>` (physical delete, never exposed to the model). -
Automated unit tests for the memory store and the memory tool dispatch
(`tests/test_memory.py`, run with `python -m unittest discover -s tests
-t .`). - Version control with git and a private GitHub repository;
`data/`, `.venv/`, `.backups/`, and `__pycache__/` are not tracked. -
`requirements.txt`
pinning the direct dependency (`openai`). -
Automated unit tests for the calculator, file tools, and tool dispatch
in addition to the memory tests (91 tests total). - PDF document
analysis through `read_pdf` over the private `data/documents/`
directory. - Controlled web research through `web_search` and
`web_fetch` with SSRF protections, content-type limits, and
OS-trust-store TLS. - Tool-call reliability hardening: 8 tool rounds,
execution of tool calls embedded as text markup by the model, and
removal of markup from final answers. - Console output resilient to
characters outside the console encoding. - Automated tests for PDF and
web tools (128 tests total). - Project workspaces: user-side registry
(`/project add`, `list`, `remove`), per-session activation (`use`,
`off`), workspace-scoped file tools, and the per-project
`ARACELI_CONTEXT.md` context file with snapshot injection (164 tests
total).

Not implemented: - Conversation summarization, pruning, or compaction. -
Automatic discovery of the
effective LM Studio context length. - Physical memory deletion through
model tools. - Semantic or embedding-based memory search. - OCR for
scanned PDFs without a text layer. - Web search quality guarantees:
some sites block automated access (HTTP 403) and the model must fall
back to other sources. - A persistent
tool-execution audit log (deliberately deferred). - Automated tests for
the conversation loop (command handling, model interaction).

## Development Priorities

1.  Build the self-development capability (roadmap Phase 5): a
    user-gated development mode (`/dev on` / `/dev off`, default off)
    exposing a `write_source` tool restricted to an allowlist of
    source files (root `*.py`, `memory/`, `tests/`, `system_prompt.md`,
    `docs/`; excluding `config.py`, `requirements.txt`, and `data/`).
    Every write must produce a backup, pass syntax validation, and
    run the full test suite automatically, with the result returned
    to the model so it can iterate until the suite is green. Git
    history remains the final safety net, and changes require an
    application restart to take effect.
2.  Use Araceli on real tasks and record friction points.
3.  Evaluate memory retrieval quality with real usage before
    considering FTS5 or embedding-based search.
4.  Consider conversation summarization or pruning when context usage
    approaches the configured limit.
5.  Revisit a persistent execution log only if unexplained tool or file
    incidents occur.
This document describes the current implementation. When it conflicts
with source code, inspect the code and update this document. Clearly
distinguish implemented behavior from planned work.
