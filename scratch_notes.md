# Scratch notes (for AI_USAGE.md)

## Mailbox selection (exploration in Claude chat, review and fixes in Claude Code)
- First script searched the whole file as text. "To:" also matched "X-To:", so every mailbox showed 100% mandatory. Fixed by reading headers with the email module: real coverage was ~96-99%, the gap was missing To: lines.
- A bare `except: pass` also swallowed Ctrl+C, so I couldn't stop the script. Fixed with `except Exception`.
- Ranking by the average of the optional fields picked mailboxes with 0% forwarded/quoted. I pushed back; switched to ranking by the weakest field.
- Claude Code's review found every file has its own Message-ID, so "unique" counted files. Over half were copies of the same email in different folders. Switched to a content fingerprint, re-picked 5 mailboxes (17,903 distinct), decided to merge copies at ingestion.
- Claude Code used a different Python than my terminal and stubbed out tqdm. Fixed with .venv and a CLAUDE.md rule to always use .venv/bin/python.
- Shell commands with # comments broke in zsh (comments aren't skipped by default) and created junk folders.

## Build with Claude Code (BUILD_PROMPT.md, one long session)
- Phase 1 re-ran my selection rules from scratch and got the same 5 mailboxes (41,264 files, 17,903 distinct), so the earlier pick holds.
- Phase 2: sager-e/calendar/34 has a bare line break inside its Subject. The email module took the next line as the start of the body and silently dropped the other 12 headers. Fixed with repair_headers in src/common.py, which folds a stray line back into the header above when more headers follow. Re-ran the selection to check the picks didn't move.
- Phase 2: quoted-printable files end marker lines with =20 ("-----Original Message-----=20"), so 37 Outlook markers were invisible until the body was decoded. Decode first, then split.
- Phase 2: the prompt said Outlook Original Message is a reply marker, but 1,281 of 3,740 of those emails are FW: forwards (Outlook uses the same line for both). Changed the rule: FW: subject means forwarded_content.
- Phase 2: the first heading rule was mostly noise (FYI, initials like JWVS, [IMAGE], <<FILE.DOC>>). Added precision filters and checked the kept list by eye.
- Phase 2: <<file>> and Name <addr> vanished from the markdown tables because GitHub reads them as HTML tags. Wrapped them in backticks.
- Phase 3: Python 3.13's email.utils.parsedate_tz returns offset 0 for an unknown zone and for a date with no zone at all, so "XYZ" quietly became UTC. Read the zone token in our own code and fail unknown zones, as the prompt asks.
- Phase 3: "<< File: mailto:cwoods@mayerbrown.com >>" made has_attachment true. That's an Outlook link, not a file. Placeholders with mailto/http/www are now skipped (41 of 7,015).
- Phase 4: caught before the first run. In Python's sqlite3, a SAVEPOINT outside a transaction starts one, so every RELEASE would have committed and the load would have been 40k separate commits. Added an explicit BEGIN. Also clear the address cache after a rolled-back email, so a rolled-back address id isn't reused.
- Phase 4: one person, two sender addresses. Richard Sanders sends as richard.sanders@enron.com (3,119 rows) and b..sanders@enron.com (337). Dedup groups by from_address, so it can't link the two. Noted as a limitation, not fixed (that would be inventing identity rules).
- Phase 5: short notes make different forwards look identical. Shankman's "print" on the weekly freight report scores 100 against last week's "print". Tried comparing body+forwarded and the full text instead: both flag more (24,101 and 24,513 against 23,816) because forwards of one big document with different notes look alike. Kept the spec's body rule and wrote down the 78 likely false positives as a limitation.
- Phase 6: the installed mcp is 2.3.0, where FastMCP is now MCPServer (`from mcp.server.fastmcp import FastMCP` raises ModuleNotFoundError pointing at the migration guide), and the client is `mcp.Client`. Read the installed SDK before writing the server instead of going from v1 examples.
- Phase 6: a tool returning a bare `dict` gave the client only JSON text, with structured_content None. Changed the return type to `dict[str, str]` and the SDK published an output schema and filled structured_content.
- Phase 6: the mcp stdio client passes only a short list of "safe" environment variables to the server process, so GMAIL_* exported in the shell would never reach it. The server reads .env next to itself, and the notifier forwards the two GMAIL variables explicitly.
- Phase 7: all 43 tests passed on the first run, which proves little by itself. Broke the code on purpose to check they bite: an off-by-one at the 90 boundary, a failed send recorded as sent, and attaching to the newest original. The right test failed each time.
- Phase 7: made sure tests can never send for real once .env exists. An autouse fixture swaps in a fake SMTP and blocks the subprocess server, so live-mode tests must use the in-process one.
- Phase 8: the editor's Write tool timed out twice in a row on README.md (its hook didn't answer), so the file was written with a shell heredoc instead. Same content, just a different way to put it on disk.
- Phase 9: diffing a fresh clone's outputs against the repo turned up one mismatch. output/load_stats.txt in the repo came from phase 7's re-run check ("inserted: 0"), not the from-scratch load. Re-ran the pipeline from scratch once, so every committed output comes from one run. The report, error log and stats were byte-identical; only load_stats.txt and the drafts' Date lines changed.

## Audit after the build (Claude Code, checked against ASSIGNMENT.md)
- The server called QUIT in a `finally` inside the same try as the send. If Gmail accepted the notice and then dropped the connection at QUIT, the tool said "not sent", the ledger marked it failed and the next run would have sent it again. QUIT now runs on its own after the send and can't change the result. A test makes the fake SMTP fail QUIT; it fails against the old code.
- Asked for live sends to put real re-sends before folder copies. Measured first: sorting by "Dates differ" alone would still make the first notice a 1980 email, because the eThink password group has the earliest original. That group is one email exported from Notes (date lost, placeholder) and from Outlook (2001-06-12), so it's a copy too. Added the placeholder rule to the send order only, not the matching. First notice is now "Organizational Changes" at 99.98.
- DECISIONS D5.1 said 4,899 of the 5,117 short-body flags were folder copies. That number measured the raw body length, but the 50-character test runs on the collapsed text: it's 4,991 copies and 126 re-sends. The stats print the split now.
- sample_queries.sql query 1 said all five mailbox owners are near the top. Only four are; mary.fischer@enron.com sent 85 of these emails and is 36th.
- AI_USAGE.md said the time zone bug was "found by testing the library before writing the parser". No note says when it was found, so that part was cut.
- Split the long table rows in scripts/eda.py into short lines and checked that docs/EDA.md comes out byte-identical (same md5).
- Audit tooling: the shell's grep (ugrep) treats the 11 cp1252 files as binary and skipped their Message-ID lines until run with -a, and it refuses long context patterns. Counted in Python instead.
