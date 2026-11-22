# Araceli

Araceli is a local-first personal AI assistant. It runs entirely on
your own computer, communicates with a language model served locally
through LM Studio, and uses a set of Python-controlled tools to act on
your behalf: reading and writing project files, analyzing private PDF
documents, keeping persistent memory, and performing controlled web
research.

The language model provides reasoning and decision-making; Python
provides execution, permissions, verification, and control.

## Scope

Araceli is designed to be a genuinely useful assistant, not a
chatbot with predefined commands. Its core capabilities:

- **Conversation** with a local model through a console interface,
  in Spanish, with tool calling.
- **Persistent memory** backed by SQLite: user-level and general
  knowledge (preferences, personal context, decisions, tasks, facts)
  that survives conversation resets and application restarts. Memory
  is independent of projects: project work data lives in each
  project's own context file, never in global memory.
- **File access** under strict Python-enforced permissions: allowed
  extensions, size limits, excluded directories, and automatic
  backups before every overwrite. When a user activates one of their
  registered project workspaces, the file tools operate inside that
  project for the session.
- **Private document analysis**: PDF text extraction from a private
  documents directory that no other tool can reach.
- **Controlled web research**: generic web searches and page reading
  with protections against private-network access (SSRF), binary
  downloads, and oversized content.
- **Execution provenance**: every tool call returns a Python-generated
  execution record (unique id, timestamps, status, SHA-256 where
  applicable) so claims about actions are backed by evidence.

### Design principles

- **Local-first and private.** Private data never leaves your machine.
  The memory database and private documents are excluded from git and
  from the model's general file access. Web searches use generic,
  non-identifying queries only.
- **Python is the security boundary.** The model can only propose
  actions; Python validates arguments, enforces path and size limits,
  restricts network access, and decides which tools exist. Model
  instructions are never a substitute for application-side validation.
- **Truthfulness and verification.** Araceli distinguishes startup
  snapshots from current file contents, and must never claim an action
  succeeded without a successful execution record.
- **Controlled autonomy.** Araceli plans and executes multi-step tasks
  within its permissions, and asks for authorization before external
  or consequential actions.

## Requirements

- **Python 3.13** (tested on Windows 11; the project is plain Python
  and should be portable with minor path adjustments).
- **[LM Studio](https://lmstudio.ai)** serving an OpenAI-compatible
  API at `http://127.0.0.1:1234/v1` with a tool-calling model loaded
  (the project currently uses `qwen/qwen3.5-9b`; the application
  verifies the model's effective context length at startup).
- Python dependencies (installed from `requirements.txt`):
  - `openai` — API client for LM Studio
  - `pypdf` — PDF text extraction
  - `ddgs` — DuckDuckGo web search (no API key required)
  - `truststore` — operating-system certificate store for TLS

No other services, accounts, or API keys are needed.

## Setup

1. Clone the repository and create a virtual environment:

   ```bat
   cd /d <path-to-your-Araceli-folder>
   python -m venv .venv
   .venv\Scripts\activate.bat
   ```

2. Install the dependencies:

   ```bat
   pip install -r requirements.txt
   ```

3. Configure LM Studio:

   - Load a tool-calling chat model (default: `qwen/qwen3.5-9b`).
   - Start the local server bound to `127.0.0.1:1234`.
   - Set the model context length (default expected: 24,576 tokens).
   - Keep the server bound to localhost; do not expose it to the
     network.

4. Optional: configure where Araceli reads your private PDF documents.

   By default, PDFs placed in `data/documents/` are readable through
   the `read_pdf` tool. For real private documents that live outside
   the repository, create a file `data/documents_path.txt` containing
   a single line with the absolute path of your documents folder
   (for example `D:\MyDocuments`). That file is gitignored, the folder
   is only accessible through `read_pdf`, and the model never sees the
   absolute path.

## Running

Use the launcher for your shell (recommended):

```text
run.bat        CMD (double-click also works)
./run.sh       Git Bash / POSIX shells
```

Or activate the virtual environment manually:

```bat
.venv\Scripts\activate.bat
python main.py
```

If a dependency is missing at startup, the application prints
shell-specific activation instructions instead of a raw traceback.

Console commands:

| Command | Description |
|---|---|
| `/reset` | Start a new conversation (memory snapshot is refreshed) |
| `/memory` | List active memories with ids, categories and titles |
| `/forget <id>` | Physically delete a memory by id |
| `/context [compact]` | Show context usage; `compact` summarizes the conversation and frees tokens |
| `/project` | Manage project workspaces (see below) |
| `/exit` | Quit the application |

### Project workspaces

You can register your own project directories and grant Araceli
per-session access to one of them:

```text
/project add D:\MyFolder     Register a project directory
/project list                List registered projects
/project info [name]         Show a project summary (context, progress, pending work)
/project load MyFolder        Activate it (new conversation starts)
/project unload              Deactivate (back to no active project)
/project remove MyFolder     Remove it from the registry
```

Activating a project reports how many tokens its context file adds and
the resulting context usage; unloading frees them.

While a project is active, the file tools operate inside its
directory (read, list, and write anywhere in the project), and its
PDF documents are readable through `read_pdf`. Araceli maintains a
hidden `.ARACELI_CONTEXT.md` file at the project root — the working
memory of the project (description, instructions, decisions, general
progress, next steps), kept as compact as possible — so work can
resume in future sessions, and generates result or temporary files
inside the project when you ask for them. The model has no tool to
change the active project; only you can.

The context file is Araceli's sole responsibility: she creates it,
updates it, reconciles it after verifications, and prunes it without
asking permission (editing it is never a destructive operation).
Classification is hers too: user-level facts (how the user wants to
be called, preferences) go to global memory; project work data
(analysis, medias, comparisons, extracted data) stays only in the
project context file and project files.

Every tool execution is shown in the console as a compact
`[tool] name -> status` line, so you can see what the assistant
actually does and whether each operation succeeded. Console output is
color-coded (user prompts, assistant replies, tool executions, and
warnings use different colors); set the `NO_COLOR` environment
variable to disable colors. Context usage is reported after each
response and after every action that changes the context (loading or
unloading a project, resetting the conversation), and the startup
banner shows an approximate token breakdown of everything loaded
(instructions, project brief, memory, tools).

## Tools available to the model

| Tool | Purpose |
|---|---|
| `calculate` | Arithmetic with whitelisted math functions (`round`, `abs`, `min`, `max`, `sqrt`) — AST-based, no arbitrary code |
| `list_files` | List ALL files and directories of the active project (text-only in the repository) |
| `read_file` | Read any file as UTF-8 text in the active project (text allowlist in the repository) |
| `write_file` | Write any extension anywhere in the active project; repository restricted |
| `save_memory` | Store a persistent memory (user-level facts; validated categories and limits) |
| `search_memories` | Keyword search across persistent memories |
| `update_memory` | Update or supersede a memory by id |
| `read_pdf` | Extract text from a PDF in the configured documents directories, with optional page selection |
| `list_documents` | List available PDF documents with name, size and date |
| `web_search` | Generic web search via DuckDuckGo |
| `web_fetch` | Read a public web page as text (SSRF-protected) |

## Project layout

```text
Araceli/
├── main.py              # Startup, console loop, tool-call handling
├── config.py            # LM Studio connection and generation settings
├── tools.py             # Tool implementations, validation, dispatch
├── projects.py          # Project workspace registry
├── system_prompt.md     # Behavioral instructions (Spanish)
├── requirements.txt     # Pinned direct dependencies
├── memory/              # Persistent memory package (SQLite)
│   ├── database.py      # Connection and schema
│   ├── models.py        # MemoryRecord dataclass
│   └── memory_store.py  # Save, search, update, delete operations
├── data/                # Local data (gitignored)
│   ├── araceli.db       # Memory database (created on first run)
│   ├── projects.json    # Project workspace registry
│   ├── documents/       # Internal PDF documents directory
│   └── documents_path.txt  # Optional pointer to an external documents folder
├── tests/               # Automated test suite (unittest)
└── docs/                # Technical project documentation
```

## Testing

The project includes an automated test suite (235 tests) covering the
memory store, memory and file tool dispatch, the calculator with its
function whitelist, file access restrictions, PDF extraction with
page selection, web tool protections, console color helpers, and the
project registry and commands:

```bat
python -m unittest discover -s tests -t .
```

## Roadmap

Planned work, in priority order (details in
`docs/project_context.md`):

- **Self-development capability (Phase 5):** a user-gated
  development mode (`/dev on` / `/dev off`) exposing a guarded
  source-writing tool, with automatic backups, syntax validation,
  and the full test suite run after every write. Git history
  remains the final safety net.
- **Real-task usage:** run Araceli on real workloads and record
  friction points.
- **Memory retrieval:** evaluate FTS5 or embedding-based search
  only after real usage shows it is needed.
- **Conversation auto-summarization:** automatic compaction when
  the context fills up (`/context compact` exists as the manual
  tool today).
- **OCR for scanned PDFs** without a text layer.
- **Alternative web search backends** if DuckDuckGo quality
  degrades.
- **Comprehensive conversation-loop tests** (the tool budget has
  coverage; the full loop does not).

## Privacy notes

- `data/` (memory database, private documents, and the optional
  external documents pointer), `.venv/`, and `.backups/` are
  gitignored and never leave your machine.
- Web searches must be generic; the system prompt forbids including
  private data in queries, and every executed query is visible in the
  console.
- `web_fetch` only reaches public http/https addresses on ports
  80/443; local and private network addresses are rejected.

## Status

Araceli is under active development. Implemented: conversation with
tool calling, persistent memory, user-side memory management, file
tools with backups, PDF analysis, and controlled web research. See
`docs/project_context.md` for the detailed current state and
development priorities.

The project should grow progressively: reliability, privacy,
transparency, and maintainability take precedence over adding
features quickly.
