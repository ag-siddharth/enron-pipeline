# Progress

The plan is in BUILD_PROMPT.md (phases 0 to 9). Rules for every session are in CLAUDE.md.

## How to resume
1. Read this file, then `git log --oneline` to see the last phase commit.
2. Pick up at the first phase below that isn't `done`.
3. A phase's commit hash is filled in right after that phase is committed, so the newest row may show `(next commit)` until the following phase is committed.

## Status

| Phase | What | Status | Key numbers | Commit |
|---|---|---|---|---|
| 0 | setup: BUILD_PROMPT.md, .gitignore, CLAUDE.md, requirements.txt, docs | done | Python 3.13.5; tqdm 4.70.1, rapidfuzz 3.14.6, mcp 2.3.0, pytest 9.1.1 import fine | 9da6aac |
| 1 | mailbox selection (scripts/select_mailboxes.py, src/common.py) | done | 150 mailboxes, 517,401 files, 0 read errors; picked sanders-r, mann-k, sager-e, shankman-j, fischer-m = 41,264 files, 17,903 distinct (matches the earlier run) | (next commit) |
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

### Phase 1
- Scan takes about 1m45s single-threaded (about 190 µs per file), so no multiprocessing is needed.
- Funnel: 18 mailboxes under 500 distinct, 33 under 90% mandatory (always missing To), 47 with a feature under 5% (forwarded in 44), 52 eligible; the 20,000 cap skipped kaminski-v, dasovich-j and taylor-m.
- Hypotheses checked: every file has its own Message-ID (41,264 IDs for 41,264 picked files); copies are over half of mann-k (67.5%) and fischer-m (52.5%); Bcc equals Cc in all 68,456 emails that have it; no To header in 2.8% of the picked mailboxes' distinct emails (5.9% across all 150, so "about 3%" only holds for the picks).
- Seen while scanning: some files are quoted-printable (`=20`, soft breaks) and some mix CRLF headers with LF bodies. Phase 2 measures both.

