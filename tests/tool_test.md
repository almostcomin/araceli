# File Operations Tools Documentation

## Available Tools

### list_files
Lists readable text files in a project directory.

**Parameters:**
- `directory` (optional, default: `"."`) — Relative path to the target directory

**Restrictions:**
- Only returns readable text files
- Paths must be relative to the project root
- Cannot access external or system directories outside the project structure

### read_file
Reads a UTF-8 encoded text file from within the project directory.

**Parameters:**
- `path` (required) — Relative path to the target file

**Restrictions:**
- File must exist within the project directory structure
- Only reads text files in UTF-8 encoding
- Cannot read binary files or external resources
- Path must be relative to the project root

### write_file
Creates or updates a text file inside authorized directories.

**Parameters:**
- `path` (required) — Relative path where the file will be created/updated
- `content` (required) — Text content to write to the file

**Restrictions:**
- Only operates within authorized directories: `memory`, `tests`, or `docs`
- Existing files are automatically backed up before modification
- Cannot write outside these authorized directories
- File encoding is UTF-8

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

## Usage Notes

1. All paths must be relative to the project root directory
2. No absolute paths or external resource access allowed
3. File operations are limited to text files only
4. Write operations respect backup mechanisms for existing files
