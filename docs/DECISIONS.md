# Decisions

Every rule and threshold in the code has a one-line reason next to it and a full entry here: what we decided, why (a spec section or a number from the data), what else we considered, and how we checked it.

## Phase 0: setup

### D0.1 Extra .gitignore lines for SQLite side files
- **Decision:** besides the list in BUILD_PROMPT.md, ignore `*.db-journal`, `*.db-wal` and `*.db-shm`.
- **Why:** if a load crashes mid-transaction, SQLite leaves `enron.db-journal` next to the database. Committing that half-written state would be as bad as committing `enron.db` itself, which the list already ignores with `*.db`.
- **Considered:** using the list exactly as given. The extra lines can only stop a database side file from being committed, so nothing else changes.
- **Checked:** `git check-ignore -v` confirms maildir, ASSIGNMENT.md, .venv and enron.db are all ignored.

### D0.2 Pin every package from pip freeze
- **Decision:** requirements.txt is the full `.venv/bin/pip freeze` (35 lines), not just the four direct packages.
- **Why:** BUILD_PROMPT.md phase 0 asks for every tested version to be pinned. mcp 2.3.0 pulls in pydantic, anyio, starlette and httpx2, and their versions affect the MCP server.
- **Considered:** listing only tqdm, rapidfuzz, mcp and pytest. That's shorter, but a fresh install could then pull different transitive versions from the ones that were tested.
- **Checked:** phase 9 installs requirements.txt into a fresh venv and runs the pipeline and the tests.

## Phase 1: mailbox selection

### D1.1 Fingerprint uses the raw header values, as written
- **Decision:** fingerprint = md5 of the raw From, To, Cc, Date and Subject header values (joined with newlines) plus the body with whitespace collapsed. Header values are not whitespace-collapsed.
- **Why:** every file has its own Message-ID (41,264 files, 41,264 distinct IDs in the picked mailboxes), so copies of one email can only be matched by content. Collapsing whitespace inside the header values too gives the same 17,903 distinct emails, so the literal rule from BUILD_PROMPT.md is safe.
- **Considered:** (a) collapsing header whitespace: same count, so no gain; (b) leaving Date out: 17,642 distinct. That would merge 261 emails that match another on everything except the date, which are re-sends, not folder copies, and are Task 3's job.
- **Checked:** computed all three variants over the 41,264 picked files.

### D1.2 Selection rules kept as given
- **Decision:** rules 1 to 5 from BUILD_PROMPT.md phase 1 unchanged: at least 90% mandatory coverage and 500 distinct emails, each of cc/forwarded/quoted/attachment at least 5%, rank by weakest then average then low-priority coverage, pick under a 20,000 cap until 5 mailboxes and 12,000 distinct.
- **Why:** the numbers support each one. Mandatory coverage has a median of 93.8% across 150 mailboxes, and every miss is a missing To header (no mailbox lacks Message-ID, Date, From, a Subject header or a body). The forwarded feature is the one most often missing (median 4.8%, 44 mailboxes under 5%), which is exactly what rule 3 guards against. Thresholds are compared with integer math (`count*100>=90*distinct`) so a mailbox at exactly 90.0% isn't dropped by float rounding.
- **Considered:** ranking by the average alone. The earlier run in scratch_notes.md showed that picks mailboxes with 0% forwarded or quoted.
- **Checked:** the result matches the earlier run exactly: sanders-r, mann-k, sager-e, shankman-j, fischer-m; 41,264 files, 17,903 distinct. Ties in the ranking fall back to the mailbox name so the order is fixed between runs.

### D1.3 Bcc is left out of the scoring
- **Decision:** Bcc isn't a selection feature.
- **Why:** all 68,456 distinct emails with a non-empty Bcc header have Bcc equal to Cc (after collapsing whitespace), and no email has Bcc without Cc. The Enron export copied Cc into Bcc, so Bcc adds no information to score on.
- **Considered:** scoring Bcc as a fifth feature. It would just double-count Cc.
- **Checked:** counted across all 150 mailboxes in `scripts/select_mailboxes.py` (printed at the end of the run).

## Phase 2: EDA findings that change or refine the rules

All numbers are from docs/EDA.md (41,264 files in the 5 picked mailboxes).

### D2.1 Convert CRLF to LF, and expect mixed endings
- **Decision:** the reader replaces every CRLF with LF before splitting at the first blank line; lone LF stays as is.
- **Why:** the hypothesis "files use CRLF" is only half right. 38,476 files (93.2%) have a CRLF header block with LF lines in the body, 2,786 are CRLF only, and none has a lone CR.
- **Considered:** splitting on `\r\n\r\n` in the raw bytes. That breaks on the 2 files with LF lines inside the header block.
- **Checked:** EDA line-ending table; every file splits into headers and body.

### D2.2 Repair stray lines in the header block
- **Decision:** `common.repair_headers` folds a header-block line that is neither `Name: value` nor a continuation into the header above it when more headers follow. If no header follows (or it's the first line), the blank line is missing and the body starts there.
- **Why:** sager-e/calendar/34 has a bare line break inside its Subject (`Subject: \nStatute of Limitations`). The email module takes the stray line as the start of the body and silently drops the other 12 headers. The same repair recovers headers in a few files of geaccone-t, hendrickson-s and kuykendall-t (their low-priority coverage went up 0.1 to 0.2 points when the selection was re-run).
- **Considered:** leaving the email module's behaviour as is. That loses X-Folder and Content-Type for that email, and the spec asks for malformed headers to be handled gracefully.
- **Checked:** the repair changes 1 of 41,264 picked files and 0 of the 7,329 in sanders-r; the selection re-run gives the same picks, 41,264 files and 17,903 distinct. It also handles a file with no headers or no blank line (tested on small strings).

### D2.3 Undo quoted-printable before looking for markers
- **Decision:** `common.decode_body` undoes quoted-printable (and base64, which never occurs here) before the body is split. It round-trips through the file's own encoding so no byte changes, then decodes the result with the same utf-8 / cp1252 / latin-1 chain.
- **Why:** 1,165 files are quoted-printable. Their marker lines end in `=20` and long lines are soft-wrapped with `=`, so 37 Outlook `-----Original Message-----` lines can only be found after decoding (9,945 vs 9,908).
- **Considered:** decoding only `=20`. Soft line breaks also cut `Forwarded by` lines in half.
- **Checked:** all 1,165 decoded bodies are valid utf-8 afterwards; the EDA counts markers after decoding.

### D2.4 An Outlook block under an FW: subject is forwarded content
- **Decision:** the first reply-style block (Outlook Original Message, Outlook header block, Lotus reply header) goes to `forwarded_content` when the subject starts with `FW:` or `Fwd:`, otherwise to `quoted_content`. Lotus `Forwarded by` lines are always forwards.
- **Why:** Outlook writes the same `-----Original Message-----` line for replies and forwards. 1,281 of the 3,740 emails whose first marker is that line (34%) have an FW: subject, so the rule "Outlook Original Message is a reply marker" would file a third of Outlook forwards as quoted replies. The subject's first prefix is what Outlook itself sets when forwarding.
- **Considered:** following BUILD_PROMPT.md literally (always quoted). It's simpler but wrong for 1,281 emails. Looking for "forward" words in the body instead was too fuzzy.
- **Checked:** EDA table "Reply-style first markers by subject prefix". Only 4 Lotus reply blocks have an FW: subject, so the rule barely touches them.

### D2.5 Three shapes of Lotus reply headers, plus Outlook blocks without a separator
- **Decision:** `markers.find_first_marker` treats all of these as the start of a reply block: `From: Name on 12/12/2000 12:03 PM` or `From:  Name     12/12/2000 12:03 PM` (`lotus_from_date`), `"Name" <addr> on 12/12/2000 12:03:00 PM` (`lotus_name_on_date`), a name line, a bare date line and a `To:` line 1 to 4 lines below (`lotus_name_date_block`, cut at the name line), and an Outlook `From:` line with `Sent:` or `Date:` right below it (`outlook_header_block`).
- **Why:** the hypothesis "Lotus reply blocks start with From: Name   date" covers only 2,929 files. 3,744 more start with the name / date / To: block and 1,943 with `Name <addr> on date`. 15,789 of 15,978 bare date lines have a To: line within 4 lines below. 30 Outlook blocks lost their separator line.
- **Considered:** cutting at the date line instead of the name line. That leaves the sender's name dangling at the end of the body.
- **Checked:** random samples of each shape in the exploration were all real reply headers. The EDA table "First marker in each file" has the counts.

### D2.6 > quoting counts at column 0 only
- **Decision:** a line is a `>` quote only if `>` is its very first character. Those lines go to quoted_content one by one, and markers are never looked for inside them.
- **Why:** 1,514 files have `>` lines at column 0. Another 80 have `>` only after spaces or tabs, and those are mostly ASCII-art tables (`  >-----|`) and deeply nested forwarded jokes.
- **Considered:** allowing leading whitespace. It gains 80 files but pulls in table borders.
- **Checked:** EDA marker table; samples of the indented lines.

### D2.7 Attachment evidence: placeholders in authored or forwarded text, words only in authored text
- **Decision:** `has_attachment` is true for a MIME attachment part or filename, a `<<file>>` placeholder in the authored text or the forwarded content, or an attach word in the authored text. The words are attach, attached, attaches, attaching, attachment and attachments.
- **Why:** forwards carry their attachments and replies drop them. 1,920 files have placeholders only in forwarded text, so ignoring forwarded content would miss real attachments, while the 1,374 with placeholders only inside quoted replies point at an earlier email's attachment. Words outside the authored text (7,214 files) are mostly about earlier emails in the chain, so the BUILD_PROMPT.md rule (sender's own text only) stays for words. `attachments` (2,792) and `attaching` (703) are as clear as `attached`, so they count too.
- **Considered:** words anywhere (too many false hits from quoted chains); placeholders only in authored text (misses 1,920 forwards).
- **Checked:** EDA "Attachment cues" table. No file has a MIME part (every Content-Type is text/plain), but the check stays for other data.

### D2.8 Precision filters for headings
- **Decision:** `markers.heading_kind` keeps the three kinds from BUILD_PROMPT.md (ALL CAPS, underlined, numbered; standalone; 60 characters or less; header-like lines skipped) and adds filters: no line ending in `.?!;,` or containing `<<`, `http`, `@` or `/`; ALL CAPS needs 4+ letters, at least half of its characters letters, no inner colon, and 2+ words or a 6+ letter word; numbered and underlined titles must be Title Case and 8 words or less.
- **Why:** the raw rules keep 4,530 ALL CAPS lines, and the most common are `FYI` (284), initials like `JWVS` (115), `[IMAGE]`, `<<FILE.DOC>>` and itinerary names like `MANN/C KAY`. Numbered candidates are mostly list items (`3. The agreement reference in 6.7.1`), and underline candidates are sentences sitting above a separator line.
- **Considered:** the raw rules (noisy); a dictionary of heading words (too narrow and hard to justify).
- **Checked:** the kept lists in docs/EDA.md: 1,286 caps, 267 numbered, 5 underlined, almost all real headings (`TABLE OF CONTENTS`, `PRIVILEGED AND CONFIDENTIAL`, `3. Litigation and Other Contingencies`). Some noise is left (`MV SALVADOR CP 11.05.00`), listed as a known limitation.

### D2.9 Bogus 1980 dates are kept, not failed
- **Decision:** the 84 files dated `Mon, 31 Dec 1979 16:00:00 -0800 (PST)` (1980-01-01 00:00 UTC) parse normally and are stored. They're called out in the EDA and the README, not dropped.
- **Why:** the spec's failure reason is an *unparseable* date, and this one parses. It's a null-date placeholder from the export, and dropping it would throw away 84 otherwise complete emails.
- **Considered:** treating dates before 1990 as failures, or nulling them. Both invent a rule the spec doesn't have.
- **Checked:** the EDA date table; all 41,264 dates parse, with only two offset/abbreviation pairs (-0700 PDT, -0800 PST).

### D2.10 Recipient lists drop repeated addresses
- **Decision:** to/cc/bcc lists keep the first occurrence of each address, in order.
- **Why:** 718 To headers and 44 Cc headers list the same address twice (the export maps different display names to one address). The recipients table has one row per email, address and type, so a repeat adds nothing.
- **Considered:** a position column that keeps repeats. It complicates every recipient query for no information.
- **Checked:** EDA address table.

### D2.11 Addresses are lowercased, and valid means it has an @
- **Decision:** from_address and every recipient are lowercased. A recipient entry counts as valid when it has text on both sides of an `@`. Broken but consistent forms like `b..sanders@enron.com`, `.hall@enron.com` and `""thompson@enron.com` are kept exactly as they are.
- **Why:** BUILD_PROMPT.md asks for lowercased recipients. From is lowercased too so duplicate grouping can't split one sender in two. Not one of the 190,594 address entries in these mailboxes has an uppercase letter or lacks an @, so this changes nothing here but protects the grouping. The broken forms are how the export wrote Enron addresses (2,854 double-dot To entries), and they're still stable identifiers.
- **Considered:** "fixing" `b..sanders` to `b.sanders`, which would invent addresses.
- **Checked:** EDA address table.
