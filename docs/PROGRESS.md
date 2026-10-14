# Progress

The plan is in BUILD_PROMPT.md (phases 0 to 9). Rules for every session are in CLAUDE.md.

## How to resume
1. Read this file, then `git log --oneline` to see the last phase commit.
2. Pick up at the first phase below that isn't `done`.
3. A phase's commit hash is filled in right after that phase is committed, so the newest row may show `(next commit)` until the following phase is committed.

## Status

| Phase | What | Status | Key numbers | Commit |
|---|---|---|---|---|
| 0 | setup: BUILD_PROMPT.md, .gitignore, CLAUDE.md, requirements.txt, docs | done | Python 3.13.5; tqdm 4.70.1, rapidfuzz 3.14.6, mcp 2.3.0, pytest 9.1.1 import fine | (next commit) |
| 1 | mailbox selection (scripts/select_mailboxes.py, src/common.py) | todo | | |
| 2 | EDA (scripts/eda.py, docs/EDA.md) | todo | | |
| 3 | extraction (src/extractor.py) | todo | | |
| 4 | database (schema.sql, src/database.py, sample_queries.sql) | todo | | |
| 5 | duplicates (src/dedup.py, duplicates_report.csv) | todo | | |
| 6 | notifications and MCP (src/notifier.py, mcp_server/gmail_server.py) | todo | | |
| 7 | main.py and tests | todo | | |
| 8 | docs (README.md, AI_USAGE.md) | todo | | |
| 9 | final check (fresh clone, deliverables, git history) | todo | | |

## Notes per phase

### Phase 0
- Dataset: 150 mailboxes, 517,401 email files plus one maildir/.DS_Store (2.5 GB).
- Claude Code 2.1.295 (`claude --version`), model Opus 5.5 (claude-opus-5-5).
- The installed mcp is 2.3.0: FastMCP was renamed to `mcp.server.mcpserver.MCPServer`, and the client is `mcp.Client`, which takes a `StdioServerParameters` for a subprocess or a server object for in-process tests.
