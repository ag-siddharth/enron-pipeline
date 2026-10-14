ultrathink

This folder is new. It has maildir/ (the full Enron dataset, 150 mailboxes), ASSIGNMENT.md (the spec and the final authority), scratch_notes.md (notes from my first attempt) and .venv with tqdm, rapidfuzz, mcp and pytest installed. Build the whole project end to end by working through the phases below in order.

After each phase: run it, check the numbers, update docs/PROGRESS.md (phase, status, key numbers, commit hash), add any real problem you hit and how you fixed it to scratch_notes.md, commit with a clear message, then keep going without waiting for me unless a stop condition happens. If you get cut off, I'll start a new conversation and say "continue from docs/PROGRESS.md", so keep that file accurate.

## Stop and ask me if
- you need my Gmail credentials. I'll create .env myself. Never ask me to paste a password into the chat.
- anything would send a real email. Never run --send-live yourself.
- the data contradicts something the spec depends on, like fewer than 10,000 valid emails.
- you'd need to change anything in maildir/ or outside this repo.

Never git push. Never edit maildir/.

## How to make decisions
Measure first, then decide. Every rule and threshold needs a reason: a line from the spec or a number from the data. Put a one-line reason in a comment where the rule lives, and a full entry in docs/DECISIONS.md: what we decided, why (spec section or data number), what else we considered, and how we checked it. If the data shows any rule below is wrong, change it, log why in DECISIONS.md, and mention it in the phase summary.

## Code style (this is how I write)
- Simple Python a student would write: small functions, plain for loops, plain dicts and lists. No classes unless there's a real need. No clever one-liners, no nested comprehensions, no heavy type hints.
- No spaces around = or comparison operators: total=0, total+=1, if score>=90:, if a==b:, if x!=y:. Keep a space after commas and around and, or, not, in.
- Comments are short, casual and in plain words, like my own notes, saying what a block does and why so I can follow it later. Example: # enron puts X-To in every email, so only the real To header counts
- At most a one-line docstring per function, and one or two comment lines at the top of each file saying what it does.
- Use except Exception as e, never a bare except. The pipeline must never crash on a bad file: catch it, log it, skip it.
- Plain print() for progress and stats. Don't run code formatters.
- Standard library first. The only third-party packages: tqdm, rapidfuzz, mcp (the official MCP Python SDK), pytest. Always run .venv/bin/python and .venv/bin/pip.

## Notes from an earlier exploration (re-verify all of it, don't trust it)
I explored this dataset once before (notes in scratch_notes.md). Treat these as hypotheses for phases 1 to 3 to confirm or correct:
- Plain text search is a trap: "To:" also matches "X-To:", and Cc lines inside quoted replies look like real Cc. Only parse the real header block.
- Every file has its own Message-ID, even when it's a copy of the same email in another folder. In some mailboxes over half the files are such copies.
- Every email has X-From/X-To/X-cc/X-bcc lines, often empty. Bcc looked like a copy of Cc.
- About 3% of emails have no To: header.
- Files use CRLF line endings, a few need cp1252 instead of utf-8, Content-Type was always text/plain, and dates looked like "-0800 (PST)".
- Replies: Outlook "-----Original Message-----", Lotus reply blocks starting "From: Name   12/12/2000 12:03 PM". Forwards: "---------------------- Forwarded by ...".

## Phase 0: setup
- Save this whole prompt, word for word, as BUILD_PROMPT.md, so a new session can pick it up.
- Before anything is committed, create .gitignore with: maildir (no trailing slash, so it also covers a symlink), *.tar.gz, .venv/, __pycache__/, .pytest_cache/, .DS_Store, *.db, .env, mcp_config.json, ASSIGNMENT.md, *.docx, output_dev/.
- Create CLAUDE.md with a short version of the stop rules, the code style and the .venv rule, plus "the plan is in BUILD_PROMPT.md, progress is in docs/PROGRESS.md", so later sessions keep the same rules.
- Check that .venv/bin/python is 3.10 or newer and that the four packages import. Write requirements.txt from .venv/bin/pip freeze so every tested version is pinned.
- Create docs/PROGRESS.md and docs/DECISIONS.md.
- Show me a short plan of all phases, then start right away.

## Phase 1: mailbox selection (scripts/select_mailboxes.py)
The spec wants at least 5 mailboxes and at least 10,000 emails, and asks me to document which ones and why.

Put the shared helpers in src/common.py: decode raw bytes (utf-8, then cp1252, then latin-1, never dropping characters), convert CRLF to LF, split headers from body at the first blank line, parse only the header block with the email module, and fingerprint = md5 of the raw From, To, Cc, Date and Subject headers plus the text after the headers with whitespace collapsed. The extractor reuses these, so the counts match.

Scan all 150 mailboxes. Count copies once: skip any file whose fingerprint was already seen in that mailbox. Over the distinct emails, measure per mailbox:
- mandatory coverage: Message-ID, Date, From and To are non-empty, a Subject header exists (it may be empty), and the body is non-empty
- cc %: a non-empty real Cc header
- forwarded %: the text after the headers contains "forwarded by" or "forwarded message" (any case)
- quoted %: it contains "original message" or a line starting with ">"
- attachment %: it contains "attach" (any case) or a <<...>> placeholder
- low-priority coverage: X-From, X-To, X-Folder, X-Origin and Content-Type are all non-empty

Then:
1. Keep mailboxes with at least 90% mandatory coverage and at least 500 distinct emails (most emails must parse; tiny mailboxes don't show enough variety).
2. Keep only those where cc, forwarded, quoted and attachment are each at least 5% (every parser feature needs real data to prove it works).
3. Rank by the weakest of those four, then their average, then low-priority coverage (an average hides a feature at 0%; one missing feature should sink a mailbox).
4. Leave Bcc out of the scoring if it really is a copy of Cc.
5. Pick in rank order, skipping any mailbox that would push the total above 20,000 distinct emails, until there are at least 5 mailboxes and at least 12,000 distinct emails. Count the total as distinct fingerprints across the picked mailboxes. (12,000 is the spec's 10,000 plus headroom for failed parses; the cap keeps runs fast.)

My earlier run of these rules picked sanders-r, mann-k, sager-e, shankman-j and fischer-m (41,264 files, 17,903 distinct). If you get something different, explain why.

Write output/selection_manifest.csv (every mailbox, its numbers, and either picked or the reason it wasn't) and a short docs/SELECTION.md with the rules and the results. Say plainly that this is a purposive subset chosen to exercise the parser, not a random sample.

## Phase 2: EDA (scripts/eda.py writes docs/EDA.md)
Survey the 5 picked mailboxes and write the results as tables in docs/EDA.md:
- files per mailbox and folder
- line endings
- encodings, and which files needed a fallback
- Content-Transfer-Encoding values
- headers with =?...?= encoded words
- date formats, and the earliest and latest dates (call out obviously bogus ones)
- missing or empty mandatory headers
- address formats: wrapped, Name <addr>, broken ones like .dan@enron.com
- Bcc vs Cc equality
- copies: files sharing a fingerprint, and how many of those also share the same Date
- how often each reply or forward marker appears: Outlook Original Message, Lotus Forwarded by, Lotus reply blocks, other forward lines, lines starting with >
- <<file>> placeholders, and attach/attached/attachment mentions
- heading-like lines

Then check every rule in this prompt against these numbers and adjust where needed.

## Phase 3: extraction (src/extractor.py)
Task 1 and every field in section 3.
- Walk only the 5 picked mailboxes (list at the top of the file), in sorted order, skipping hidden files.
- Decode and split with src/common.py, and record which files needed a fallback encoding. If a file declares quoted-printable or base64, decode its body accordingly.
- Parse only the header block, so X-To or a To: line inside a forwarded email never counts as the real To. Decode =?...?= encoded words in display fields.
- message_id: trimmed, not case-folded. date: UTC ISO 8601, handling numeric offsets and US abbreviations (PST, EST, CDT...); keep the raw date too; an unknown time zone is a failure. from_address: just the address. to/cc/bcc: lists from getaddresses after unfolding, lowercased, empty entries dropped. subject: exactly as written. source_file: relative path like maildir/sanders-r/inbox/12.
- x_from, x_to, x_cc, x_bcc, x_folder, x_origin, content_type. Empty ones become None.
- body is the sender's own text:
  - Cut at reply block markers (Outlook Original Message, Lotus reply blocks) into quoted_content, and at forward markers into forwarded_content. Nested messages stay inside their block.
  - For > quoting, sort line by line, so new text written between quoted lines stays in body.
  - If there's no authored text at all (a pure forward or a quote-only email), body holds the forwarded or quoted text, and body_basis records which ("authored", "forwarded" or "quoted").
  - Keep the full decoded text in raw_text.
- has_attachment: MIME attachment parts or filenames, a <<file>> placeholder, or attach/attached/attachment in the sender's own text. multipart alone doesn't count. Store attachment_evidence.
- headings: standalone lines of 60 characters or less that are ALL CAPS, underlined with ---- or ====, or numbered titles like "1. Overview". Skip header-like lines (From:, To:, Sent:, cc:, Subject:). Store one per line.
- fingerprint from src/common.py.
- Mandatory failures get a specific reason: no Message-ID, unparseable Date, no From address, no To header, To has no valid address, no Subject header, empty message. Write path<TAB>reason lines to error_log.txt in the repo root.
- Print stats: files found, parsed, failed by reason, the % of parsed emails that have each field, and the earliest and latest date.
- Test it on a few broken files in a temp folder (empty file, random bytes, no headers, no blank line) to show it logs them and moves on.

## Phase 4: database (schema.sql, src/database.py, sample_queries.sql)
Task 2.
- emails: every section 3 field plus raw_date, raw_text, body_basis, attachment_evidence, normalized_subject, fingerprint (indexed, not unique), is_duplicate, duplicate_of (foreign key to emails.message_id), similarity_score, notification_sent, notification_date. UNIQUE on message_id only.
- addresses (each address once) and email_recipients (email, address, type to/cc/bcc), so recipients are never comma-separated strings.
- notifications: one row per send attempt (group key, duplicate message_id, intended recipient, actual recipient, subject, status pending/sent/failed, error, outbound Message-ID, timestamps). This is the send ledger, kept separate from the duplicate flags.
- Indexes on date, from_address, subject, and (from_address, normalized_subject). Turn on PRAGMA foreign_keys. Store dates as ISO 8601 UTC text so they sort in time order.
- Every file with a distinct Message-ID is its own record, even when its content matches another file. The spec makes message_id the duplicate check at insert, and content duplicates are Task 3's job. A repeated Message-ID is skipped; if its content differs, log it as a conflict.
- Loading twice must add nothing. Show me the counts from both runs.
- sample_queries.sql: emails per sender (top 10), emails in a date range, emails with CC recipients, duplicates joined to their originals, and contents that appear in more than one folder. Run each one and paste the real output under it as a comment.

## Phase 5: duplicates (src/dedup.py writes duplicates_report.csv)
Task 3.
- Normalized subject: repeatedly strip leading Re:/Fw:/Fwd: in any case and spacing, collapse whitespace, lowercase.
- Group by from_address + normalized subject. Only groups of 2+ go further.
- Compare the body with whitespace collapsed (body already holds the fallback text for pure forwards). Never call two empty texts similar.
- Walk each group in date order, ties broken by message_id:
  - Attach each email to the earliest original it scores 90+ against; otherwise it becomes a new original.
  - Identical texts score 100 without fuzzy matching (the fast path for folder copies).
  - Otherwise skip a pair when 20*min(m,n) < 9*(m+n), because fuzz.ratio can't reach 90 then.
  - Decide the 90 from rapidfuzz's whole-number Indel distance, not a rounded float.
- Recompute is_duplicate, duplicate_of and similarity_score (against the referenced original) in one transaction on every run. Don't touch the notifications ledger.
- duplicates_report.csv in the repo root with exactly these columns: duplicate_message_id, original_message_id, subject, from_address, duplicate_date, original_date, similarity_score. Every flagged email.
- Print and log: groups found, emails flagged, average group size, how many flagged emails are same-Date folder copies vs real re-sends, and how many have bodies under 50 characters.
- Check the optimized matching against a plain compare-every-pair version on a small sample. They must give the same results.

## Phase 6: notifications and MCP (src/notifier.py, mcp_server/gmail_server.py)
Task 4.
- mcp_server/gmail_server.py: a small MCP server built with the official SDK, with one tool, send_email(to, subject, body, references, intended_recipient).
  - It sends through smtp.gmail.com port 587 with STARTTLS, logging in with GMAIL_ADDRESS and GMAIL_APP_PASSWORD from the environment, or from a gitignored .env in the repo root (found relative to the server file, not the working directory).
  - It sets Date, References, a new Message-ID and X-Intended-Recipient itself, and returns a clear success or error.
  - Protocol messages go only on stdout; all logging goes on stderr. It never prints the password.
- mcp_config.json.example: the mcpServers structure for this server with placeholder values. .env.example: placeholder keys GMAIL_ADDRESS, GMAIL_APP_PASSWORD, NOTIFY_TO.
- The notice must follow this template exactly. The first four lines are the email's headers; everything after the first blank line is the body, blank lines and indentation included:

To: <sender_of_latest_duplicate>
Subject: [Duplicate Notice] Re: <original_subject>
Date: <current_timestamp>
References: <message_id_of_latest_duplicate>

This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  <message_id_of_latest_duplicate>
    Date Sent:   <date_of_latest_duplicate>
    Subject:     <subject>

  Original Email on Record:
    Message-ID:  <message_id_of_earliest_original>
    Date Sent:   <date_of_earliest_original>

  Similarity Score: <similarity_percentage>%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.

- Dry run (the default): one .eml per flagged duplicate in output/replies/, addressed to its sender as the template says, with Date = now and References = that duplicate's message_id. Use safe file names, and write output/replies/manifest.csv mapping each file name to its message_id.
- --send-live: one notice per group, about the latest duplicate, sent through the MCP server's send_email tool using the mcp Python client. No direct SMTP from the pipeline.
  - Send it to NOTIFY_TO, with intended_recipient set to the real sender.
  - Write the ledger row as pending before sending and update it afterwards. Skip groups already sent. Don't retry a row left pending by a crash; report it instead.
  - Send at most --limit notices (default 3), and print how many groups are still pending.
  - Append every attempt to output/send_log.csv (timestamp, recipient, subject, status, error). On success, set notification_sent and notification_date.
- The CONFIRM reply in the template isn't processed. Say so in the README.
- Don't run --send-live. Test the server with an in-process MCP client call against a fake SMTP connection instead.

## Phase 7: main.py and tests
- python main.py runs extract, load, dedup and drafts, and never sends. Flags: --send-live, --limit N, --only <mailbox> (uses dev.db and the output_dev/ folder, both gitignored, so it can't overwrite the real outputs), and --fresh (rebuilds only the dev database).
- tests/ with pytest, using small fake emails so no maildir is needed: the exact-90 boundary (900 vs 1,100 characters), a similarity chain, equal dates, a group of 3+, X-To vs To, folded To, missing To, empty message, multipart without an attachment, reloading adds nothing, a failed send isn't marked sent, optimized vs plain matching agree.
- Run the full pipeline from scratch and the tests. Everything must pass.

## Phase 8: docs
- README.md:
  - what it does, with an architecture diagram
  - setup: Python 3.10+, venv, requirements, downloading and extracting the dataset into maildir/
  - MCP setup: App Password, .env, claude mcp add without any secrets
  - how to run it, and every output file
  - mailbox selection: method, rules and results from docs/SELECTION.md, and that it's a purposive subset, not a random sample
  - EDA highlights, and design decisions with links to docs/DECISIONS.md
  - the recipient override in live mode, and known limitations
  - real numbers from the final run throughout
- AI_USAGE.md: the sections in spec section 6 plus the MCP section from 4.3.
  - Build it only from scratch_notes.md (which includes my earlier exploration), docs/PROGRESS.md, git history and BUILD_PROMPT.md. Don't invent anything.
  - Quote real prompts (BUILD_PROMPT.md is one of them) and say why each was shaped that way. List real failed attempts and how they were fixed.
  - Tools: Claude chat for analysis, exploration and planning, including drafting this build prompt; Claude Code (version and model from /status) for the build; and a second LLM that reviewed the plan.
  - Put [TODO: me] for the % split of what I wrote vs what AI wrote, the lessons learned, and the MCP screenshot and log, which only I can fill in.

## Phase 9: final check
- Clone the repo into a temp folder, make a fresh venv, install requirements.txt, symlink maildir, then run python main.py and pytest.
- Check every deliverable in spec section 7 exists at the right path. Check git history has never contained .env, mcp_config.json, enron.db or maildir.
- Finish with a summary: what was built, the key numbers, the deliverables checklist, and a numbered list of what I still have to do myself: create the App Password and .env, the exact claude mcp add command (no secrets in it), the exact prompt to test send_email from Claude Code, python main.py --send-live --limit 1, screenshots into docs/screenshots/, the [TODO: me] parts, git push, and what to do if my Google account has no App Passwords page (switch the server to the Gmail API with OAuth, keeping the same send_email tool).
