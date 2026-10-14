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
