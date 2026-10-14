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
| 1 | mailbox selection (scripts/select_mailboxes.py, src/common.py) | done | 150 mailboxes, 517,401 files, 0 read errors; picked sanders-r, mann-k, sager-e, shankman-j, fischer-m = 41,264 files, 17,903 distinct (matches the earlier run) | e984d4f |
| 2 | EDA (scripts/eda.py, src/markers.py, docs/EDA.md) | done | 93.2% mixed CRLF/LF; 11 cp1252; 1,165 quoted-printable; 0 bad dates, 84 bogus 1980 placeholders; 613 files without To; 13,025 copy groups; 1,281 Outlook forwards; 7 rule changes (D2.1-D2.11) | 7bbc2fd |
| 3 | extraction (src/extractor.py) | done | 41,264 files: 40,651 parsed, 613 failed (all no To header); 11 cp1252, 1,165 quoted-printable, 1 header repair; body_basis 37,154 authored / 3,420 forwarded / 77 quoted; has_attachment 16.3%, headings 1.9%; dates 1980-01-01 (bogus) to 2002-07-12 | 770aaad |
| 4 | database (schema.sql, src/database.py, sample_queries.sql) | done | load 1: 40,651 emails, 7,799 addresses, 179,245 recipient rows; load 2: 0 added, 40,651 skipped, 0 conflicts; FK and integrity checks clean | a0f9820 |
| 5 | duplicates (src/dedup.py, duplicates_report.csv) | done | 9,081 sender+subject groups; 12,762 duplicate groups; 23,816 flagged (22,902 same-Date folder copies, 914 re-sends; 23,262 identical, 554 fuzzy); avg group 2.87, largest 51; 5,117 bodies under 50 chars; plain check 500 groups 0 mismatches | b70f74b |
| 6 | notifications and MCP (src/notifier.py, mcp_server/gmail_server.py) | done | dry run: 23,816 .eml drafts + manifest in about 5s; live mode: 12,762 groups, ledger checked with a fake SMTP (sent/skip/failed/pending); stdio server refuses without credentials; --send-live never run | c69c464 |
| 7 | main.py and tests | done | python main.py from scratch in 32s: 40,651 loaded, 23,816 flagged, 23,816 drafts; second run inserts 0, report byte-identical; 43 pytest tests pass in 0.5s | a9259b3 |
| 8 | docs (README.md, AI_USAGE.md) | done | README: setup, MCP setup, run, every output, selection, EDA, decisions, limitations, final-run numbers; AI_USAGE: tools, 5 quoted prompts, 18 real fixes, MCP section; [TODO: me] left for % split, lessons, chat model, second LLM, screenshot | b202f10 |
| 9 | final check (fresh clone, deliverables, git history) | done | fresh clone + fresh venv from requirements.txt (pip freeze identical): main.py same numbers, 43 tests pass, outputs byte-identical apart from draft Dates; every section 7 deliverable tracked; .env, mcp_config.json, *.db, maildir never in history | 381d9a3 |
| 10 | audit fixes (review against ASSIGNMENT.md) | done | 45 tests pass; a failed QUIT after Gmail accepted counts as sent; live order: 452 real re-send groups first, first notice "Organizational Changes" (99.98); short bodies 5,117 = 4,991 copies + 126 re-sends; 84 placeholder files = 74 loaded + 10 failed, 1 re-send group with a placeholder original (eThink); docs/EDA.md byte-identical after the eda.py rewrite; other outputs byte-identical, dedup_stats.txt gains one line | (next commit) |

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

### Phase 2
- `scripts/eda.py` takes about 25s and regenerates docs/EDA.md. The marker, heading and attachment rules live in `src/markers.py`, which the EDA and the extractor share.
- Rule changes from the data (details in docs/DECISIONS.md D2.1 to D2.11): CRLF to LF with mixed endings, a header repair for stray lines, decoding quoted-printable before splitting, Outlook blocks under FW: subjects counted as forwards, three Lotus reply shapes, `>` at column 0 only, placeholders counted in authored and forwarded text, precision filters for headings, 1980 dates kept, repeated recipients dropped, lowercase addresses.
- Hypotheses checked: To is missing in 1.5% of files here (not 3%); Content-Type is always text/plain, but CTE is quoted-printable in 1,165 files; Bcc equals Cc in all 10,832 picked files; every date is `-0700 (PDT)` or `-0800 (PST)`.

### Phase 3
- Run on its own with `.venv/bin/python -m src.extractor` (about 16s). It's a generator, so the loader can stream records instead of holding 40k emails in memory.
- Coverage over parsed emails: message_id, date, from, to, body, x_from, x_to, x_folder, x_origin and content_type 100%; subject 96.8% non-empty; cc/bcc 26.4%; forwarded_content 31.2%; quoted_content 28.1%.
- Broken-file test (in the scratchpad, not the repo): empty file, random bytes, no headers, no blank line (with and without text), unknown zone, undisclosed To, unreadable file, hidden file and folder, missing mailbox. All logged with specific reasons; the good file and the glued-body file parsed.
- Decisions D3.1 to D3.7: the zone is read by our code (Python 3.13 parsedate_tz returns 0 for unknown zones), all failing reasons are logged, raw_text is the decoded text after the headers, the body falls back to forwarded first, headings come from the whole text, link placeholders aren't attachments.

### Phase 4
- enron.db (gitignored) is in the repo root, 191 MB. The load takes about 23s.
- `scripts/run_sample_queries.py` refreshes the outputs in sample_queries.sql. Queries 4a/4b (duplicates) show 0 rows until phase 5 has run, so refresh them after dedup.
- Two loads in a row: run 1 inserted 40,651; run 2 inserted 0 and skipped 40,651 with no conflicts; all table counts unchanged.

### Phase 5
- `.venv/bin/python -m src.dedup --check` takes about 5s; it writes duplicates_report.csv (23,816 rows) and output/dedup_stats.txt, and refreshes the flags in one transaction.
- Re-running gives a byte-identical report. The notifications table and notification_sent are untouched (0 and 0).
- Comparing on body (the spec) vs body+forwarded vs raw_text: 23,816 / 24,101 / 24,513 flags. Kept body; the 78 re-send flags with a different forwarded payload are a known limitation (D5.1).

### Phase 6
- Never ran --send-live against Gmail. All live-mode checks used a copy of enron.db, the in-process server (`Client(gmail_server.mcp)`) and a fake SMTP class (scratch scripts; phase 7 turns them into pytest tests).
- output/replies/*.eml change on every run (Date = now), so they're committed once, after the final from-scratch run in phase 7, not here.
- mcp_config.json.example and .env.example hold placeholders only. .env and mcp_config.json are gitignored, and neither exists yet.

### Phase 7
- `python main.py` = extract + load + dedup + drafts, about 32s from scratch. `--only <mailbox>` uses dev.db and output_dev/ (fischer-m takes 1.5s). `--fresh` only works with `--only`. `--send-live` can't be combined with `--only`.
- Tests: tests/test_extractor.py (21), test_dedup.py (8), test_database.py (4), test_notifier.py (10). They cover every case in BUILD_PROMPT.md phase 7 plus dates, splitting, attachments, headings, the header repair, the template, the ledger and the server.
- The final outputs committed here come from the from-scratch run: error_log.txt, duplicates_report.csv, output/*.txt, output/replies/, output/send_log.csv (header only, nothing sent).

### Phase 8
- README.md and AI_USAGE.md use the numbers from the phase 7 from-scratch run. AI_USAGE.md is built only from scratch_notes.md, this file, the git history and BUILD_PROMPT.md.
- Left for the user ([TODO: me] in AI_USAGE.md): the % split, lessons learned, the Claude chat model, which second LLM reviewed the plan, the actual Claude Code prompt and reply for send_email, real MCP setup issues, and the live-send screenshot and log line.
- The Write tool's hook timed out on README.md twice, so README.md and AI_USAGE.md were written with shell heredocs.

### Phase 9
- Clone in the scratchpad, fresh venv (Python 3.13.5) from requirements.txt, maildir symlinked: `main.py` gave 41,264 / 40,651 / 613 / 23,816 flagged / 23,816 drafts, and pytest passed 43.
- Compared with the repo, these were byte-identical: duplicates_report.csv, error_log.txt, extraction/dedup stats, load_log.txt, manifest.csv, send_log.csv, and every .eml apart from its Date line. load_stats.txt differed (the repo's came from the phase 7 re-run), so the repo was re-run from scratch once and all outputs re-committed from that run.
- `git log --all --name-only` has never listed .env, mcp_config.json, any .db file, maildir, ASSIGNMENT.md or .venv. The examples hold placeholders only.
- All phases are done. What's left is for the user (see README.md "Gmail MCP server setup" and the [TODO: me] parts of AI_USAGE.md): App Password and .env, claude mcp add, one live send, screenshots, the TODOs, git push.


### Phase 10 (audit fixes, after the build)
- A full audit against ASSIGNMENT.md (counts, spot checks, MCP stdout, git history, style, docs) found no spec failures. The fixes here are the small issues it found, done with the user's go-ahead.
- Code: QUIT handling in mcp_server/gmail_server.py (D6.9), live send order in src/notifier.py (`is_resend`, `send_order`, D6.8), the short-body split in the dedup stats, `str=''` defaults in send_email, the rules table in scripts/eda.py split into short lines. Two new tests; each fails when its fix is removed.
- Docs: query 1's Expected note, three AI_USAGE.md wordings, README (test count, 32 to 38 seconds, side effects of `-m src.extractor` and `--check`, re-sends first, QUIT, short-body split, placeholder dates, the eThink case, `Re: Re:`), DECISIONS D5.1 (4,899 corrected to 4,991), D5.5, D6.6, D6.7, D6.8, D6.9.
- Outputs: `python main.py` re-run; duplicates_report.csv, error_log.txt, extraction_stats.txt, load_log.txt, manifest.csv, send_log.csv, selection_manifest.csv and docs/EDA.md are byte-identical to the phase 9 commit. output/dedup_stats.txt gains the short-body split line. The drafts and load_stats.txt were restored to the phase 9 from-scratch run (re-running only changes the drafts' Date lines and makes load_stats say "inserted: 0").
- Still for the user: App Password and .env, claude mcp add, one live send, screenshots, the [TODO: me] parts of AI_USAGE.md, git push.
