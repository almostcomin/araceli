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
-   `console.py`: console color helpers (ANSI, terminal detection,
    `NO_COLOR` support) with semantic roles.
-   `projects.py`: registry of user project workspaces
    (`data/projects.json`) and reading of the per-project context
    file (`.ARACELI_CONTEXT.md`).
-   `run.bat` / `run.sh`: launcher scripts (CMD / POSIX shells) that
    activate the virtual environment and start the application.
-   `memory/`: persistent memory package.
    -   `memory/database.py`: SQLite connection management and schema
        initialization. The database file is `data/araceli.db`.
    -   `memory/models.py`: the `MemoryRecord` dataclass.
    -   `memory/memory_store.py`: save, search, update, delete, and
        count operations with Python-side validation.
-   `docs/`: project documentation. `araceli_brief.md` is the compact
    runtime context injected at startup; `project_context.md` (this
    document) is development documentation and is not injected.
-   `tests/`: automated tests — `test_memory.py` (memory store,
    memory tool dispatch, console handlers), `test_tools.py`
    (calculator, file tools, tool dispatch), `test_pdf_web.py` (PDF
    and web tools), `test_server_context.py` (server context
    discovery, API error hints, token estimation, tool budget),
    `test_console.py` (color helpers), `test_projects.py` (project
    registry and commands) — plus tool documentation (`tool_test.md`).
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
2.  At startup, `main.py` loads `docs/araceli_brief.md` once, if the
    file exists and contains readable, non-empty UTF-8 text. The brief
    is the compact runtime context injected into every conversation;
    `docs/project_context.md` (this document) is development
    documentation and is NOT injected.
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
    `/forget <id>` (physically delete a memory), `/context` (context
    usage), `/project`
    (manage project workspaces: `status`, `list`, `info [name]`,
    `add <path>`, `remove <name>`, `load <name>`, `unload`), and `/exit`
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
    the model interaction, subject to `MAX_TOOL_ROUNDS` (configurable
    in `config.py`, default 16). When the budget is exhausted, a
    dedicated `ToolBudgetExceeded` exception is caught by the console
    loop and reported with guidance (files written during the turn
    persist; divide the task or `/reset` and continue), instead of a
    generic communication error.
    If the model emits a tool call as text markup instead of using the
    tool_calls mechanism, Python parses both markup styles the model
    uses (JSON objects and XML-ish function/parameter tags), executes
    it if valid, and returns the result to the conversation; answers
    consisting only of unparseable markup raise an error instead of
    reaching the user.
9.  The application displays the final answer and, when available,
    context-token usage (with the average generation speed in tokens
    per second). A `finish_reason` of `length` triggers a
    warning that the response may be incomplete.
10. If an interaction raises an exception, the previous conversation
    history is restored.

The runtime brief is loaded once per application execution. `/reset`
creates a new conversation using a freshly composed prompt (the
memory snapshot and the active project context are reread; the brief
and behavioral instructions are not) and prints the resulting context
usage. Loading or unloading a project (`/project load <name>`,
`/project unload`) also recomposes the prompt, starts a new
conversation, and prints the context usage.

Token counts are estimated (`estimate_tokens`, a chars/4 heuristic)
and shown as a per-component breakdown in the startup banner
(instructions, project brief, memory/manifest, tools); the same
estimate is printed by `/reset`, project load/unload, and `/context`
before the first model response. After each response the usage is
the exact value reported by the API.

If `docs/araceli_brief.md` is missing, empty, or cannot be read, the
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
-   `list_files(directory=".")`: lists files in the current workspace.
    In an active project it lists all files and directories regardless
    of extension (PDF documents classified in `pdf_files`, with a note
    explaining how to read each kind); in the repository it lists up
    to 200 readable text files with the usual exclusions.
-   `read_file(path)`: reads a UTF-8 text file. In an active project
    any file is attempted as UTF-8 text regardless of extension;
    `.pdf` returns an error pointing to `read_pdf`, and binary or
    non-UTF-8 content reports that no reader tool is available (the
    model is instructed to ask the user in that case). In the
    repository, only allowed text extensions. 256 KB limit.
-   `write_file(path, content)`: creates or updates files. In an
    active project, anywhere inside the project directory with any
    extension; without one, only under `memory/`, `tests/`, and
    `docs/` of the Araceli repository with a text extension allowlist.
    256 KB content limit. Before overwriting an existing file, it
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
-   `read_pdf(path, pages)`: extracts text from a PDF document. Search order:
    the active project directory (if one is active), then the
    configured documents directories. Paths are relative to those
    roots. Limits: 10 MB, 50 pages, 24,000 extracted characters
    (truncated results suggest using the optional `pages` parameter,
    e.g. `1-3`, to read specific ranges). Scanned PDFs without a text
    layer return no text.
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

Documents are read from up to two or three configured roots,
deduplicated by resolved path (a root pointing at the same directory
as another is only included once):

1.  **Active project directory** (when a project is active; primary
    root on name collisions).
2.  **External directory** (optional): the user defines it by writing
    a single absolute path into `data/documents_path.txt` (gitignored,
    part of `data/`). This keeps real private documents outside the
    repository, away from development tooling.
3.  **Internal directory** (`data/documents/`, gitignored): useful for
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
    application restarts. `/project load <name>` activates it and
    `/project unload` deactivates it; both start a new conversation
    and print the resulting context usage. Loading also reports the
    approximate token cost of the project context file; unloading
    frees those tokens.
    While a project is active, `tools.set_workspace` (Python-side
    only) scopes the file tools to the project directory with full
    access: `list_files` lists every file and directory regardless of
    extension (PDFs classified separately), `read_file` attempts any
    file as UTF-8 text, and `write_file` allows any extension
    anywhere inside the project. Files that no tool can read (binary
    formats such as images) produce explicit errors instructing the
    model to ask the user for a tool rather than assume their
    contents. `read_pdf` and `list_documents` treat the active
    project directory as the primary documents root. Without an active
    project, the tools operate on the Araceli repository with the
    usual restrictions (text extension allowlists, excluded
    directories, restricted write targets).
-   **Project context file:** each project keeps the hidden file
    `.ARACELI_CONTEXT.md` at its root, written by Araceli through the
    normal `write_file` tool. It is the working memory of the project:
    description and goal, working instructions and method, decisions
    taken, general work state, and next steps — kept as compact as
    possible, since it is injected into every conversation and its
    size permanently consumes context window. The model is instructed
    to prefer general rules over enumerations (state derivable from
    project files is not duplicated: for example, an instruction that
    processed data is read from generated `.txt` files replaces any
    list of analyzed documents), to reference files by name instead of
    copying their contents, and to update the file only when something
    not derivable from the files changes (new instructions, decisions,
    phase changes, or closing a unit of work). When a project is
    activated (and on every `/reset`), Python reads it and injects it
    into the system prompt as a snapshot with provenance metadata
    (read timestamp, SHA-256, status). A missing, empty, or oversized
    context file is reported as such, and the model is instructed to
    create it as the first     step of the work. Araceli also generates
    result files (reports, comparisons) and temporary working files
    inside the project when the user asks for them. When a
    verification reveals that the context file does not match observed
    reality (files that do not exist, results that are absent), the
    model must reconcile it immediately: remove or mark unverified
    what is false and reflect what was actually verified.
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
    reporting (verified against the server at startup).
-   `MAX_TOOL_ROUNDS`: tool-call round budget per turn (default 16).
-   `SYSTEM_PROMPT_FILE`: system prompt filename.

LM Studio must be running with the configured model loaded. At
startup, the application verifies the model's effective context
length through LM Studio's native API and warns when it is smaller
than the configured one; usage reporting uses the verified value.

The direct dependencies are `openai`, `pypdf` (PDF text extraction),
`ddgs` (DuckDuckGo search), `truststore` (Windows certificate
store for TLS), and `fonttools` (embedded font parsing), pinned in
`requirements.txt`. Rebuild the environment
with `python -m venv .venv` followed by
`.venv\Scripts\pip install -r requirements.txt`. Run the test suite
with `python -m unittest discover -s tests -t .`. The launcher
scripts `run.bat` (CMD) and `run.sh` (POSIX shells such as Git Bash)
activate the virtual environment and start the application; if a
dependency is missing at startup, the import guard prints
shell-specific activation instructions for CMD, PowerShell, and Git
Bash.

## Current Status

Implemented:

-   Local LM Studio integration through the OpenAI Python client;
    console conversation loop; bounded tool-calling loop with a
    configurable round budget (`config.py`, default 16) and a
    dedicated budget-exhaustion report.
-   Restricted arithmetic (whitespace-normalized multi-line
    expressions) and workspace file tools; file validation and
    pre-overwrite backups; full file access inside active project
    workspaces (any extension, text attempted as UTF-8).
-   Persistent memory (SQLite) with save/search/update tools, a
    startup snapshot refreshed on `/reset`, and user-side `/memory`
    and `/forget` commands.
-   Project workspaces: registry (`add`, `list`, `remove`, `info`),
    per-session activation (`load`, `unload`) with context-cost
    reporting, workspace-scoped file tools, and the per-project
    `.ARACELI_CONTEXT.md` context file (compact, snapshot-injected,
    reconciled against reality after failed verifications).
-   PDF analysis (`read_pdf` with page selection, `list_documents`)
    over the active project and the configured documents directories.
-   Controlled web research (`web_search`, `web_fetch`) with SSRF
    protections, content-type limits, retries, and OS-trust-store
    TLS.
-   Resilience: startup dependency guard with shell-specific
    activation instructions; launchers `run.bat` / `run.sh`; parsing
    of both embedded tool-markup styles; console output resilient to
    console encodings.
-   Colored console output (`console.py`) with semantic roles
    (`USER_INPUT`, `ARACELI_INPUT`/`ARACELI_TEXT`, `SYSTEM_MESSAGE`,
    `SYSTEM_ERROR`) and `NO_COLOR` support.
-   Startup verification of the server context length (LM Studio
    native API) with warnings; API error transparency with targeted
    hints; context usage reported after every context-changing action
    (responses, `/reset`, project load/unload), including tokens per
    second after model responses.
-   Automated test suite: 228 tests
    (`python -m unittest discover -s tests -t .`).
-   Version control with git and a private GitHub repository; `data/`,
    `.venv/`, `.backups/`, and `__pycache__/` are not tracked.

Not implemented:

-   Conversation summarization, pruning, or compaction.
-   Physical memory deletion through model tools.
-   Semantic or embedding-based memory search.
-   OCR for scanned PDFs without a text layer.
-   Web search quality guarantees (some sites return HTTP 403 to
    automated access).
-   A persistent tool-execution audit log (deliberately deferred).
-   Comprehensive automated tests for the conversation loop (the tool
    budget has coverage; the full loop does not).

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
