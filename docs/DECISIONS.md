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

## Phase 3: extraction

### D3.1 The extractor reads the time zone itself
- **Decision:** `parse_date` takes the date and time fields from `email.utils.parsedate_tz` but reads the zone token after the time itself. A numeric `+HHMM`/`-HHMM` wins (`-0700 (PDT)` uses -0700). Otherwise the abbreviation must be one of UT, UTC, GMT, Z, EST, EDT, CST, CDT, MST, MDT, PST, PDT, AST, ADT, AKST, AKDT, HST. Anything else fails as `unparseable Date: unknown time zone X`, and a date with no zone fails as `unparseable Date: no time zone`. The result is UTC ISO 8601 (`2001-05-14T23:39:00+00:00`), and the raw header is kept in raw_date.
- **Why:** in Python 3.13, `parsedate_tz('... 16:39:00 XYZ')` and `parsedate_tz('... 16:39:00')` both return offset 0, so an unknown zone silently becomes UTC. BUILD_PROMPT.md says an unknown time zone is a failure.
- **Considered:** the private `email._parseaddr._timezones` table (private API, and it lacks AKST/HST); `parsedate_to_datetime` (same 0-offset behaviour).
- **Checked:** `XYZ` fails, `PST` gives 00:39 UTC the next day, `-0700 (PDT)` gives 23:39 UTC (broken-file test and a PST test file). All 41,264 real dates parse.

### D3.2 Every failing mandatory check is logged
- **Decision:** a failed file gets one `path<TAB>reasons` line in error_log.txt, listing every failing check joined by `; ` (for example `no Message-ID; unparseable Date: no Date header; ...`). The stats count each reason, so a file can count under several. An exception while reading or parsing becomes `could not parse: <type>: <message>`, and the run moves on.
- **Why:** an empty file fails six checks at once, and naming only the first hides the rest. The reason names are the ones listed in BUILD_PROMPT.md phase 3.
- **Considered:** one reason per file. Shorter, but less useful when debugging.
- **Checked:** broken-file test (empty file, random bytes, no headers, no blank line, unknown zone, `To: undisclosed-recipients:;`, an unreadable file): all logged, the good file next to them parsed, hidden files skipped. The real run logs 613 files, all `no To header`.

### D3.3 raw_text is the decoded text after the headers
- **Decision:** raw_text holds everything after the header block with quoted-printable or base64 undone (for multipart emails, the text/plain parts joined). body, quoted_content and forwarded_content are cut from it, so nothing is lost.
- **Why:** BUILD_PROMPT.md says "keep the full decoded text in raw_text" under the body rules. The headers are already stored field by field, and the fingerprint covers the raw file.
- **Considered:** the whole file including headers, which duplicates every header column.
- **Checked:** body is non-empty for all 40,651 parsed emails.

### D3.4 The body falls back to forwarded content first, then quoted content
- **Decision:** with no authored text, body takes forwarded_content if there is any, otherwise quoted_content, and body_basis records `forwarded` or `quoted`.
- **Why:** pure forwards are the common case (3,420 emails with basis `forwarded` against 77 `quoted`), and a forward's content is what the sender meant to deliver.
- **Checked:** extractor stats (body_basis table) and samples of each basis.

### D3.5 Headings come from the whole decoded text
- **Decision:** `find_headings` runs `markers.heading_kind` over every line of raw_text, so headings in forwarded content count too. `>` lines are never headings. Repeats within one email are dropped, and the rest are stored one per line in reading order.
- **Why:** the spec says "all the headings present in the email content". A forwarded newsletter's section titles are part of what the email delivers.
- **Checked:** 762 parsed emails (1.9%) have headings; samples are real (`E-MAIL NOTICE`, `FERC DOCUMENTS`, `3.  Litigation and Other Contingencies`).

### D3.6 Link placeholders aren't attachments
- **Decision:** a `<<...>>` placeholder containing `mailto:`, `http:`/`https:` or `www.` doesn't count as attachment evidence. Placeholders with `@` inside a file name (`<<2RD@01!.DOC>>`) and OLE objects (`<< OLE Object: Picture >>`) still count.
- **Why:** Outlook writes links the same way as files (`<< File: mailto:cwoods@mayerbrown.com >>`). Of 7,015 placeholders, 6,627 end in a file extension, 300 are OLE objects or documents without an extension, and 41 are links.
- **Checked:** has_attachment went from 6,619 to 6,616 emails; the EDA attachment tables use the same `markers.file_placeholders`.

### D3.7 Field details
- **subject:** unfolded and with encoded words decoded, otherwise exactly as written (not stripped, Re:/Fwd: kept). An empty subject is allowed: 1,286 parsed emails have one.
- **from_address:** the first valid address of the From header, lowercased (D2.11).
- **to/cc/bcc:** `getaddresses` after unfolding, lowercased, entries without `local@domain` dropped, repeats dropped (D2.10). Bcc is stored even though it equals Cc everywhere (D1.3), because the spec says it must be captured.
- **content_type:** the full header value (`text/plain; charset=us-ascii`), unfolded.
- **x_ fields:** unfolded, decoded and stripped; empty ones become None (X-bcc is filled in only 4 parsed emails).
- **multipart:** text/plain parts become the text; parts with a filename or an `attachment` disposition become evidence, so multipart alone never sets has_attachment. No email here is multipart, so this is covered by a test in phase 7.
- **fingerprint:** computed on the raw body before quoted-printable decoding, so it is the same value the selection and the EDA counted.

## Phase 4: database

### D4.1 Every file with its own Message-ID is its own row
- **Decision:** the loader inserts every parsed file whose Message-ID isn't in the database yet, even when its content matches another file. A repeated Message-ID is skipped; if its fingerprint differs from the stored row it's logged as a conflict in output/load_log.txt.
- **Why:** the spec (task 2) makes the unique constraint on message_id the duplicate check at insert, and task 3 defines content duplicates by sender, subject and 90% body similarity. Folder copies have different Message-IDs (41,264 IDs for 41,264 files), so they're rows that task 3 then flags. That keeps every source_file traceable and lets the report show folder copies next to real re-sends.
- **Considered:** merging copies at ingestion by fingerprint, which was the earlier plan in scratch_notes.md. That would hide about 23,000 flags from duplicates_report.csv and drop the source_file of every copy.
- **Checked:** two loads in a row. Run 1 inserted 40,651 emails, 7,799 addresses and 179,245 recipient rows; run 2 inserted 0 and skipped 40,651 with 0 conflicts, and every table count was unchanged. `PRAGMA foreign_key_check` and `integrity_check` are clean. A made-up repeat with a different fingerprint was logged as a conflict.

### D4.2 Recipients live in two tables
- **Decision:** `addresses` holds each address once; `email_recipients` has one row per (email, type, address) with type `to`, `cc` or `bcc` and the position in the header. Repeated addresses in one header were already dropped by the extractor (D2.10), so the primary key (email_id, type, address_id) never collides.
- **Why:** the spec forbids comma-separated recipient strings. The position keeps the to/cc/bcc lists in their original order.
- **Considered:** a recipients table without addresses (repeats every address string 179,245 times instead of 7,799).
- **Checked:** sample queries 3a to 3c join through both tables.

### D4.3 Types: ISO text dates with a CHECK, 0/1 booleans
- **Decision:** date is TEXT that must match `____-__-__T__:__:__+00:00`, and every boolean is 0 or 1 under a CHECK. The NOT NULL columns are the mandatory fields plus the pipeline's own (raw_date, body_basis, raw_text, normalized_subject, fingerprint).
- **Why:** BUILD_PROMPT.md asks for ISO 8601 UTC text so dates sort in time order. SQLite has no DATETIME or BOOLEAN type, so the CHECKs stop bad values going in quietly.
- **Checked:** a record with `date='not a date'` failed the CHECK, was logged, and rolled back alone.

### D4.4 One transaction per load, one savepoint per email
- **Decision:** a load is one explicit `BEGIN ... COMMIT`, and each email is inserted inside its own SAVEPOINT. A failing insert rolls back only that email (and its recipients), is logged in output/load_log.txt, and the run goes on. The address-id cache is cleared after a rollback.
- **Why:** the pipeline must never crash on bad input, and one transaction keeps the load fast (about 23s for 40,651 emails). Without the explicit BEGIN, Python's sqlite3 lets the first SAVEPOINT start the transaction, and then every RELEASE commits, which means 40,000 separate commits.
- **Checked:** the conflict and rollback test (one good, one repeat with different content, one bad date, one good) gives 2 inserted, 1 conflict, 1 insert error, with the addresses table consistent.

### D4.5 The notifications ledger is its own table
- **Decision:** `notifications` has one row per send attempt: group_key (the group's original message_id), duplicate_message_id, intended and actual recipient, subject, status (`pending`, `sent` or `failed`, under a CHECK), error, outbound_message_id, created_at, updated_at. Dedup never touches it.
- **Why:** BUILD_PROMPT.md phase 4 asks for it, and keeping it apart means re-running dedup can't make the pipeline forget what it already sent.

### D4.6 Indexes and sample query outputs
- **Decision:** indexes on date, from_address and subject (the spec), (from_address, normalized_subject) for task 3's grouping, fingerprint (not unique), duplicate_of, email_recipients.address_id and notifications.group_key. The outputs in sample_queries.sql are written by `scripts/run_sample_queries.py`, which runs each query against enron.db and replaces the comment under it.
- **Why:** the "real output" can't drift from the database if a script writes it. EXPLAIN QUERY PLAN (query 2c) shows the date range query using idx_emails_date.

## Phase 5: duplicates

### D5.1 Compare the body field, as the spec says
- **Decision:** two emails in a sender+subject group are compared on `body` with whitespace collapsed. That's the sender's own text, or the forwarded/quoted fallback for pure forwards (D3.4).
- **Why:** the spec defines a duplicate on "body content", and body is the field the spec separates from forwarded and quoted content. Measured on the real data with three choices of comparison text:

  | Compared text | Flagged | Re-sends (later Date) |
  |---|---|---|
  | body (chosen) | 23,816 | 914 |
  | body + forwarded_content | 24,101 | 1,843 |
  | raw_text (everything) | 24,513 | 2,787 |

  Longer texts flag more, not fewer: two forwards of the same big document with different notes look 90% alike, and replies in one thread share their quoted history.
- **Considered:** the two other columns of the table, and an extra rule for short notes.
- **Known limitation:** 78 of the 914 re-send flags have different forwarded content behind the same note, 63 of them with a note under 50 characters (`print`, `fyi`, `Please print.` on a recurring subject like "Freight weekly report"). Under the spec's definition those are duplicates, but a person would likely call them different emails. They're 0.3% of all flags, so the rule stays and the README lists it.
- **Checked:** the stats print how many flags have a body under 50 characters (5,117) and split them: 4,991 folder copies with the same Date and 126 re-sends. (An earlier version of this entry said 4,899 folder copies. That number measured the raw body length, but the 50-character test runs on the whitespace-collapsed text, which gives 4,991.)

### D5.2 Attach to the earliest original that scores 90+, never to a duplicate
- **Decision:** each group is walked in (date, message_id) order. An email is compared only with the group's originals, earliest first, and attaches to the first one that scores 90 or more; otherwise it becomes a new original. duplicate_of always points at an original, and similarity_score is the score against that original.
- **Why:** BUILD_PROMPT.md phase 5. It also stops chains (A~B and B~C don't make C a duplicate of A unless C itself scores 90+ against A). Originals are pairwise under 90 by construction, because a later one would have attached to an earlier one.
- **Checked:** no duplicate is dated before its original and no original is itself flagged (both 0 in SQL). Running dedup twice gives a byte-identical duplicates_report.csv (same md5).

### D5.3 The 90 is decided on whole numbers
- **Decision:** ratio >= 90 is tested as `10*distance <= m+n`, with rapidfuzz `Indel.distance(a, b, score_cutoff=(m+n)//10)`. Identical texts score 100 with no fuzzy call, and pairs with `20*min(m,n) < 9*(m+n)` are skipped because the ratio can't reach 90. The stored score is `100*(m+n-d)/(m+n)` rounded to 2 decimals.
- **Why:** BUILD_PROMPT.md phase 5. A float near 90.0 could round either way; the integer test can't. The real data has a pair at exactly 90.0 (`Re: Enron Center Garage`, sample query 4b).
- **Checked:** `--check` runs a plain version (full Indel distance for every pair, no shortcuts) on 500 random groups of up to 40 emails (1,798 emails): 0 mismatches. The full run takes about 5s.

### D5.4 Empty subjects form groups too
- **Decision:** an empty normalized subject is a group key like any other.
- **Why:** the spec's rule is "same subject after normalizing", and two empty subjects are the same. The body test still decides. The biggest candidate groups are empty-subject ones (kay.mann@enron.com: 809 emails, 242 distinct contents).

### D5.5 Bogus 1980 dates barely matter
- **Decision:** no special case.
- **Why:** of the 74 parsed emails dated 1980-01-01, 17 are flagged against 1980 originals (folder copies of each other) and only 1 flag pairs a 1980 original with a later duplicate.
- **That one flag:** `Your eThink Password` from ethink@enron.com, in sager-e as `all_documents/1211.` (Notes export, placeholder date) and `enron___general/1.` (Outlook export, 2001-06-12), score 100. It's one email whose Date was lost in the Notes export, so it's really a copy, but the stats count it as 1 of the 914 re-sends because the Dates differ. The matching stays as it is; live mode sends this group with the folder copies (D6.8), and the README lists it as a known limitation.
- **Checked (audit):** the 84 placeholder files are 74 loaded plus 10 that fail for no To header. The first 18 rows of duplicates_report.csv have a 1980 original: the 17 copies and this one.

## Phase 6: notifications and MCP

### D6.1 A small custom MCP server on the official SDK, sending through Gmail SMTP
- **Decision:** `mcp_server/gmail_server.py` is our own server built with the official MCP Python SDK (mcp 2.3.0, `MCPServer`). It has one tool, `send_email`, which sends through smtp.gmail.com:587 with STARTTLS and a Google App Password.
- **Why:** the spec allows "an existing open-source server or build a custom one" that supports send_email, and BUILD_PROMPT.md limits third-party packages to tqdm, rapidfuzz, mcp and pytest. SMTP with an App Password needs only the standard library, and a server we wrote can set Date, References, Message-ID and X-Intended-Recipient exactly as the template needs.
- **Considered:** an npm Gmail MCP server with OAuth (brings Node and a Google Cloud project), and the Gmail API with OAuth from Python (needs google-api-python-client, which isn't allowed). The README explains how to switch to the Gmail API if the account has no App Passwords page, keeping the same tool.
- **Checked:** in-process MCP client calls against a fake SMTP class (connect to 587, EHLO, STARTTLS, EHLO, login, send, quit), a failed login, missing credentials, and the real server started over stdio with no credentials (refuses, nothing sent).

### D6.2 The tool's contract
- **Decision:** `send_email(to, subject, body, references='', intended_recipient='')` returns `{status, to, message_id, date}` as structured content. Any problem raises `ToolError`, which reaches the client as an `is_error` result whose text starts with `not sent:`. references and intended_recipient are optional so Claude Code can call the tool with just to, subject and body.
- **Why:** the pipeline needs a clear yes or no plus the outbound Message-ID for the ledger, and an LLM calling the tool needs a readable error. A bare `-> dict` gave only JSON text; `-> dict[str, str]` makes the SDK publish an output schema and fill structured_content.
- **Checked:** both shapes seen from the client in the in-process test.

### D6.3 Credentials come from the environment, then .env; never printed
- **Decision:** the server reads GMAIL_ADDRESS and GMAIL_APP_PASSWORD from its environment, or else from `.env` in the repo root, found from the server file's own path. The spaces Google shows in an App Password are removed. Logs go to stderr and never contain the password; SMTP errors are passed on as the server's reply text.
- **Why:** BUILD_PROMPT.md phase 6. `claude mcp add` can then register the server with no secrets on the command line. The mcp stdio client passes only a short list of safe variables (PATH, HOME, ...) to the server process, so the notifier forwards the two GMAIL variables when they're set in the shell.
- **Checked:** the stdio test with no .env reports the missing settings by path, without contacting SMTP.

### D6.4 Live notices go to NOTIFY_TO
- **Decision:** in live mode every notice is sent to NOTIFY_TO (your own inbox). The real sender of the duplicate goes into X-Intended-Recipient and into the ledger's intended_recipient. The dry-run drafts are addressed to the real sender, as the template says.
- **Why:** the Enron addresses aren't ours to email (and mostly no longer exist). The spec says to send to "an email address (preferably your own gmail account)".

### D6.5 The ledger makes sends safe to repeat
- **Decision:** before each send a `pending` row goes into notifications (committed). Afterwards it becomes `sent` (with the outbound Message-ID; the duplicate gets notification_sent=1 and notification_date) or `failed` (with the error). Groups with a `sent` row are skipped. Groups with a `pending` row are reported and never retried automatically. Groups whose rows are all `failed` are tried again. If the MCP call raises (no answer), the row stays pending with the error noted and the run stops. Every attempt is appended to output/send_log.csv (timestamp, recipient, subject, status, error).
- **Why:** BUILD_PROMPT.md phase 6. A pending row from a crash may or may not have gone out, and retrying it could send a notice twice.
- **Checked:** on a copy of enron.db with the in-process server and a fake SMTP: run 1 (limit 2) sent 2; run 2 skipped those and sent 2 more; a failed login left a `failed` row with notification_sent still 0; a planted pending row was reported and left alone while the failed group was retried and sent.

### D6.6 One draft per flagged email, one live notice per group
- **Decision:** the dry run writes one .eml for each of the 23,816 flagged duplicates, addressed to that duplicate's sender with References set to its Message-ID. Live mode sends one notice per duplicate group (12,762) about the group's latest duplicate (latest date, then highest message_id), at most `--limit` per run (default 3). Groups are taken in the report's order (original date, then message_id), with real re-sends moved to the front (D6.8).
- **Why:** the spec's deliverables ask for drafts "for all flagged duplicates" and for live notices "for each duplicate group ... the latest". The default limit stops a first live run from sending 12,762 emails.

### D6.7 Draft format
- **Decision:** each .eml is exactly the template: To, Subject, Date and References, a blank line, then the body with its blank lines and indentation. Lines end in LF. Date is the run time in RFC 2822 form (`Wed, 14 Oct 2026 07:46:20 +0000`). Date Sent shows the stored UTC ISO date, so it can be matched against duplicates_report.csv. The score drops trailing zeros (`100%`, `93.5%`). Control characters and line breaks in header text are replaced with spaces: 5 subjects contain `\x01`, and a line break would start a new header.
- **`Re: Re:` subjects:** the subject is `[Duplicate Notice] Re: <original_subject>`, taken literally, so an original subject that already starts with `Re:` gives `[Duplicate Notice] Re: Re: ...`. Stripping the extra prefix was considered, but the spec gives the template word for word and the original subject is meant to be kept as written (section 3.1, "Preserve Re:/Fwd: prefixes").
- **Safe file names:** the Message-ID without `<>`, with anything other than letters, digits, `.`, `_` and `-` replaced by `_` (`22062940.1075845797850.JavaMail.evans_thyme.eml`). A repeat gets `_2`. output/replies/manifest.csv maps every file to its Message-ID. Old .eml files are removed before each dry run, so drafts for emails that are no longer flagged don't stay behind.

### D6.8 Live mode sends real re-sends first
- **Decision:** before the limit is applied, the groups are split into real re-sends and folder copies, each part kept in report order, and the re-sends go first. A group is a real re-send when its latest duplicate's Date is later than the original's and the original's Date isn't the 1980 placeholder (`is_resend` and `send_order` in src/notifier.py). That gives 452 re-send groups out of 12,762. The matching and the drafts are unchanged.
- **Why:** `--limit` lets only a few notices out per run, and a notice about a real re-send is the useful one. In report order, `--limit 1` sent `TurboPark closing`, a 1980-dated folder copy at 100%. Ordering by date difference alone would still send a 1980-dated email first: the eThink group (D5.5) has the earliest original of all 453 groups with different Dates, and it's a copy whose Date was lost. With the placeholder rule the first notice is `Organizational Changes` (richard.sanders@enron.com, 1999-07-06, sent again 3 minutes later, score 99.98).
- **Considered:** sorting by score so fuzzy matches go first (it would mix the order up for no clear gain); leaving report order (the demo notice would be a 1980 copy).
- **Checked:** `test_real_resends_go_out_before_folder_copies` builds a placeholder group, a same-Date copy group and a re-send group, in that report order, and expects the re-send first, then the other two in report order. The test fails with the old order and also without the placeholder rule.

### D6.9 A failing QUIT after Gmail accepted the message still counts as sent
- **Decision:** `send_email` reports `not sent` only if connecting, STARTTLS, login or sending fails. QUIT runs afterwards, on its own; if it raises, it's logged to stderr, the socket is closed, and the result stays `sent`.
- **Why:** the old code called QUIT in a `finally` inside the same `try`, so a dropped connection at the very end turned a delivered notice into `not sent`. The ledger would mark it `failed`, and the next run would send it again.
- **Checked:** `test_failed_quit_after_gmail_accepted_counts_as_sent` makes the fake SMTP raise `SMTPServerDisconnected` on QUIT. The tool returns `sent`, and through the pipeline the ledger row is `sent`, notification_sent is 1, and a second run sends nothing. The test fails against the old server code.

## Phase 7: main.py and tests

### D7.1 --fresh never touches enron.db, and --send-live never runs with --only
- **Decision:** `--fresh` only deletes dev.db and must come with `--only`; to rebuild enron.db you delete it yourself. `--send-live` is refused together with `--only`. Bad combinations exit with code 2 and a message.
- **Why:** enron.db also holds the notifications ledger, and deleting it by accident would forget which groups were already notified. One ledger (in enron.db) is the only way "skip groups already sent" can hold.
- **Checked:** `main.py --fresh`, `main.py --only fischer-m --send-live` and `main.py --only nobody` all exit 2 with their message.

### D7.2 Every stage's stats are printed and kept
- **Decision:** main.py prints each stage's stats and writes them to output/extraction_stats.txt, load_stats.txt and dedup_stats.txt (output_dev/ with --only). Load conflicts and insert failures go to output/load_log.txt.
- **Why:** the spec asks for extraction and duplicate statistics to be logged, and the README quotes these files.

### D7.3 Tests can't send email
- **Decision:** an autouse fixture in tests/conftest.py replaces smtplib.SMTP with a fake, sets fake Gmail settings, points both .env lookups at a missing file, and makes `notifier.stdio_server` raise, so live-mode tests have to use the in-process server.
- **Why:** BUILD_PROMPT.md says never send a real email. Once you create .env, a test that started the real server as a subprocess would read it and could send for real.
- **Checked:** 43 tests passed at phase 7 (45 after phase 10), in under a second with no maildir. Breaking the code on purpose made the matching test fail each time: `distance>=limit` at the 90 boundary, a failed send recorded as sent, and attaching to the newest original instead of the earliest.

### D7.4 Drafts are committed once, after the final run
- **Decision:** output/replies/ (23,816 .eml files plus manifest.csv) is committed from the final from-scratch run only.
- **Why:** every draft's Date is the run time, so each run rewrites all 23,816 files. Committing them every phase would add tens of thousands of changed files for nothing.
