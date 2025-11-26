# GitHub Copilot Instructions for OCR Project

## Project Overview

An AI-powered OCR application that extracts text from images and Excalidraw drawings using OpenAI or OpenRouter vision models.

**Key Features:**
- Dual API support (OpenAI and OpenRouter)
- Thread-safe provider switching
- Excalidraw drawing OCR
- Clipboard integration
- Batch processing
- Smart caching to avoid reprocessing

## Tech Stack

- **Language**: Python 3.9+
- **APIs**: OpenAI Vision API, OpenRouter API
- **Image Processing**: Pillow, cairosvg
- **Rendering**: Node.js (Excalidraw rendering)
- **Issue Tracking**: bd (beads)

## Coding Guidelines

### Testing
- Always test changes with actual image/Excalidraw files
- Use test files in subdirectories to avoid cluttering repo
- Verify both OpenAI and OpenRouter providers work

### Code Style
- Follow PEP 8 conventions
- Use type hints for function signatures
- Add docstrings to all public functions
- Keep security in mind (path validation, input sanitization)

### Git Workflow
- Always commit `.beads/issues.jsonl` with code changes
- Run `bd sync` at end of work sessions
- Use meaningful commit messages following existing style

## Issue Tracking with bd

**CRITICAL**: This project uses **bd** for ALL task tracking. Do NOT create markdown TODO lists.

### Essential Commands

```bash
# Find work
bd ready --json                    # Unblocked issues
bd stale --days 30 --json          # Forgotten issues

# Create and manage
bd create "Title" -t bug|feature|task -p 0-4 --json
bd update <id> --status in_progress --json
bd close <id> --reason "Done" --json

# Search
bd list --status open --priority 1 --json
bd show <id> --json

# Sync (CRITICAL at end of session!)
bd sync  # Force immediate export/commit/push
```

### Workflow

1. **Check ready work**: `bd ready --json`
2. **Claim task**: `bd update <id> --status in_progress`
3. **Work on it**: Implement, test, document
4. **Discover new work?** `bd create "Found bug" -p 1 --deps discovered-from:<parent-id> --json`
5. **Complete**: `bd close <id> --reason "Done" --json`
6. **Sync**: `bd sync` (flushes changes to git immediately)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

## Project Structure

```
ocr/
├── ocr.py               # General image OCR script
├── excalidraw_ocr.py    # Excalidraw-specific OCR
├── ocr_lib.py           # Shared OCR library
├── excalidraw_renderer.js  # Node.js Excalidraw renderer
├── .env                 # API keys (DO NOT COMMIT)
├── .env.example         # Example configuration
├── requirements.txt     # Python dependencies
├── package.json         # Node.js dependencies
└── .beads/
    ├── beads.db         # SQLite database (DO NOT COMMIT)
    └── issues.jsonl     # Git-synced issue storage
```

## Available Resources

### MCP Server (Recommended)
Use the beads MCP server for native function calls instead of shell commands:
- Install: `pip install beads-mcp`
- Functions: `mcp__beads__ready()`, `mcp__beads__create()`, etc.

### Scripts
- `ocr.py` - General purpose image OCR
- `excalidraw_ocr.py` - Excalidraw drawing OCR with caching
- `install_cairo.sh` - Install cairo dependencies

### Key Documentation
- **AGENTS.md** - Comprehensive AI agent guide
- **README.md** - User-facing documentation
- **.env.example** - Environment configuration template

## Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Run `bd sync` at end of sessions
- ✅ Test with both OpenAI and OpenRouter providers
- ✅ Validate file paths to prevent path traversal
- ✅ Store AI planning docs in `history/` directory
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT commit `.env` or `.beads/beads.db`
- ❌ Do NOT commit API keys

## Security Considerations

- All file paths are validated through `validate_output_path()`
- Thread-safe API provider switching with locking
- Rate limiting (10 requests/minute)
- Secure temporary file handling (0o600 permissions)
- HTTPS certificate verification enabled
- Input size validation (images, Excalidraw files)

---

**For detailed workflows and advanced features, see [AGENTS.md](../AGENTS.md)**
