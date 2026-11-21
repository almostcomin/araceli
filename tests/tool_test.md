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

## Usage Notes

1. All paths must be relative to the project root directory
2. No absolute paths or external resource access allowed
3. File operations are limited to text files only
4. Write operations respect backup mechanisms for existing files
