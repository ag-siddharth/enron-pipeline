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
