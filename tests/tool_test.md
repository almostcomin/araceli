# File Operations Tools Documentation

## Available Tools

### list_files
Lists files in a directory of the current workspace.

**Parameters:**
- `directory` (optional, default: `"."`) — Relative path to the target directory

**Behavior by mode:**
- **Active project:** lists ALL files and directories regardless of
  extension. PDF documents are additionally classified in `pdf_files`
  (read them with `read_pdf`); a note explains how to read each kind.
  Files that cannot be decoded as text have no reader tool yet.
- **Araceli repository (no active project):** lists readable text
  files only, with excluded directories filtered out

### read_file
Reads a UTF-8 text file from the current workspace.

**Parameters:**
- `path` (required) — Relative path to the target file

**Behavior by mode:**
- **Active project:** any file is attempted as UTF-8 text regardless
  of extension. `.pdf` files return an error pointing to `read_pdf`.
  Binary or non-UTF-8 content returns an error explaining that no
  reader tool is available (ask the user)
- **Araceli repository:** only allowed text extensions
  (`.py`, `.md`, `.txt`, `.json`, `.csv`, `.html`, `.xml`, `.log`, ...)

- Maximum 256 KB; paths relative to the workspace root (no traversal,
  no absolute paths); SHA-256 provenance metadata included

### write_file
Creates or updates a text file in the current workspace.

**Parameters:**
- `path` (required) — Relative path where the file will be created/updated
- `content` (required) — Text content to write to the file

**Restrictions:**
- **Active project:** allowed anywhere inside the project directory
  with any extension
- **Araceli repository:** only `memory`, `tests`, or `docs`, with a
  text extension allowlist
- 256 KB content limit; existing files are automatically backed up
  before modification (backups live under `.backups/` in the Araceli
  repository); written bytes are verified by reading the file back

### save_memory
Stores a new persistent memory in the SQLite memory database
(`data/araceli.db`). Memories persist across conversation resets and
application restarts.

**Parameters:**
- `category` (required) — One of: `preference`, `personal`, `project`, `decision`, `task`, `fact`, `knowledge`
- `title` (required) — Short identifying label (max 200 characters)
- `content` (required) — The memory itself (max 4000 characters)
- `tags` (optional) — Comma-separated keywords (max 200 characters)
- `source` (optional) — Provenance note (max 500 characters)

**Restrictions:**
- Duplicate active memories with the same category and title are
  rejected; the model must use `update_memory` instead
- The database directory (`data/`) is not directly accessible to the
  model through file tools

### search_memories
Searches persistent memories by keyword across title, content, and tags.

**Parameters:**
- `query` (required) — Keyword or phrase to search for (max 200 characters)
- `category` (optional) — Category filter
- `limit` (optional) — Maximum results, 1–50 (default 20)

**Restrictions:**
- Returns active memories by default, most recently updated first
- SQL `LIKE` wildcards in the query are escaped and matched literally

### update_memory
Updates an existing persistent memory by id.

**Parameters:**
- `memory_id` (required) — Id of the memory to update
- `title`, `content`, `category`, `tags`, `status` (optional) — At
  least one is required. `status` accepts `active` or `superseded`.

**Restrictions:**
- Updates cannot create a duplicate of another active memory
- There is no physical deletion; obsolete memories are marked
  `superseded`

### read_pdf
Extracts text from a PDF document in the configured documents
directories (external directory from `data/documents_path.txt` plus
internal `data/documents/`).

**Parameters:**
- `path` (required) — Path relative to the documents directories,
  e.g. `bill.pdf`. Use `list_documents` to discover available files

**Restrictions:**
- Cannot escape the documents directories (no traversal, no absolute
  paths); the external root takes priority on name collisions
- Only `.pdf` files
- Maximum 10 MB and 50 pages; extracted text is capped at 100,000
  characters
- Scanned PDFs without a text layer return no text (a note explains it)
- Returns source metadata: SHA-256, size, page count, extraction
  timestamp, and which directory the file came from (the external
  absolute path is never exposed to the model)

### list_documents
Lists the PDF documents available in the configured documents
directories.

**Parameters:** none

**Restrictions:**
- Only lists `.pdf` files, up to 100 entries
- Returns name, size, modification time, and source directory marker
  for each document

### web_search
Searches the web through DuckDuckGo (no API key).

**Parameters:**
- `query` (required) — Generic search query (max 400 characters). Must
  never contain private data
- `max_results` (optional) — Between 1 and 10 (default 8)

**Restrictions:**
- Queries must be generic and non-identifying; private data (names,
  addresses, contract numbers, consumption figures) is forbidden
- Retries transient failures up to three times before reporting an
  error
- Returns titles, URLs and snippets with provenance metadata

### web_fetch
Fetches a public web page and returns its readable text.

**Parameters:**
- `url` (required) — Full http(s) URL

**Restrictions:**
- Only http/https on ports 80 and 443
- Only public addresses: private, loopback, link-local, reserved and
  multicast addresses are rejected (including redirect targets)
- Only `text/html`, `application/xhtml+xml` and `text/plain` content
- Maximum 512 KB raw and 24,000 characters of text; 15 second timeout
- Returns the final URL, content type, and fetch timestamp

## Usage Notes

1. All paths must be relative to the project root directory
2. No absolute paths or external resource access allowed
3. File operations are limited to text files only
4. Write operations respect backup mechanisms for existing files
