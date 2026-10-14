# Enron email pipeline

A Python pipeline that reads raw Enron email files, extracts structured fields, stores them in SQLite, flags duplicate emails, and writes (or, with a flag, sends through a Gmail MCP server) a duplicate notice for each one.

One command runs everything and never sends email unless asked:

```
.venv/bin/python main.py
```

Results of the final run (5 mailboxes, about 32 seconds from scratch):

| Stage | Result |
|---|---|
| Extract | 41,264 files found, 40,651 parsed, 613 failed (all "no To header") |
| Load | 40,651 emails, 7,799 addresses, 179,245 recipient rows; a second load adds 0 |
| Duplicates | 12,762 duplicate groups, 23,816 emails flagged (22,902 same-Date folder copies, 914 re-sends) |
| Notices | 23,816 draft .eml files; live mode can send one notice per group (12,762) |
| Tests | 43 pytest tests, about 0.5 seconds, no dataset needed |

## Contents

- [How it works](#how-it-works)
- [Setup](#setup)
- [Running it](#running-it)
- [Output files](#output-files)
- [Gmail MCP server setup](#gmail-mcp-server-setup)
- [Mailbox selection](#mailbox-selection)
- [What the data looks like (EDA highlights)](#what-the-data-looks-like-eda-highlights)
- [Design decisions](#design-decisions)
- [Known limitations](#known-limitations)
- [Repository layout](#repository-layout)

## How it works

```
 maildir/<mailbox>/<folder>/<file>          5 picked mailboxes, 41,264 files
              |
              v
 src/extractor.py   (task 1)    decode utf-8/cp1252/latin-1, CRLF->LF, split at the first blank line,
              |                 parse only the header block, undo quoted-printable, cut the body at
              |                 reply/forward markers (src/markers.py), dates to UTC
              |                 bad files ------------------------------------------> error_log.txt
              |  records (streamed)
              v
 src/database.py    (task 2)    schema.sql -> enron.db: emails, addresses, email_recipients,
              |                 notifications; a repeated Message-ID is skipped
              v
 src/dedup.py       (task 3)    group by sender + normalized subject, rapidfuzz Indel on the body,
              |                 attach to the earliest original at 90+ ------> duplicates_report.csv
              v
 src/notifier.py    (task 4)    dry run (always): one .eml per flagged email --> output/replies/
              |                 --send-live: one notice per group, ledger in enron.db
              |                              ---------------------------------> output/send_log.csv
              |  mcp Python client (stdio)
              v
 mcp_server/gmail_server.py     MCP server, tool send_email --> smtp.gmail.com:587 (STARTTLS)
```

| Module | Job |
|---|---|
| `src/common.py` | file listing, decoding, CRLF->LF, header/body split, header repair, fingerprint, subject normalizing |
| `src/markers.py` | reply and forward markers, attachment cues and heading rules (shared by the EDA and the extractor) |
| `src/extractor.py` | every field from spec section 3, failure reasons, extraction stats |
| `src/database.py` | schema creation and an idempotent loader |
| `src/dedup.py` | duplicate groups, flags, report, plus a plain every-pair matcher for checking |
| `src/notifier.py` | draft notices, live sending through the MCP client, send ledger |
| `mcp_server/gmail_server.py` | the MCP server (official `mcp` SDK) with the `send_email` tool |
| `main.py` | runs the stages in order |

## Setup

You need Python 3.10 or newer (built and tested with 3.13.5).

```
git clone <this repo> enron-pipeline
cd enron-pipeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pins every package from the tested environment. The direct ones are `tqdm`, `rapidfuzz` (fuzzy matching), `mcp` (the official MCP Python SDK) and `pytest`; the rest are `mcp`'s dependencies.

Download the dataset (about 423 MB compressed, 2.5 GB extracted) and extract it in the repo folder, so that `maildir/` sits next to `main.py`:

```
curl -O https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
tar -xzf enron_mail_20150507.tar.gz          # creates maildir/ with 150 mailboxes
```

If the dataset is somewhere else, link it instead: `ln -s /path/to/maildir maildir`. `maildir`, the tarball, the databases, `.env` and `mcp_config.json` are all in `.gitignore`.

## Running it

| Command | What it does |
|---|---|
| `.venv/bin/python main.py` | extract, load, find duplicates, write the draft notices. Sends nothing. |
| `.venv/bin/python main.py --send-live` | the same, then sends at most 3 notices through the MCP server (see [Gmail MCP server setup](#gmail-mcp-server-setup)) |
| `.venv/bin/python main.py --send-live --limit 1` | send at most 1 notice this run |
| `.venv/bin/python main.py --only fischer-m` | run one mailbox into `dev.db` and `output_dev/` (both gitignored), so the real outputs are never overwritten |
| `.venv/bin/python main.py --only fischer-m --fresh` | the same, deleting `dev.db` first |
| `.venv/bin/python -m pytest` | the 43 tests (made-up emails, no dataset, no network) |

`--fresh` only works with `--only`, and `--send-live` can't be combined with `--only`. Both refusals protect the send ledger in `enron.db`. Running `main.py` again is safe: emails already in the database are skipped and the duplicate flags are recomputed. To rebuild `enron.db` from scratch, delete it yourself (that also deletes the record of notices already sent).

Other scripts:

| Command | What it does |
|---|---|
| `.venv/bin/python scripts/select_mailboxes.py` | scans all 150 mailboxes and writes `output/selection_manifest.csv` (about 2 minutes) |
| `.venv/bin/python scripts/eda.py` | surveys the 5 picked mailboxes and writes `docs/EDA.md` (about 25 seconds) |
| `.venv/bin/python -m src.extractor` | extraction stats only, no database |
| `.venv/bin/python -m src.dedup --check` | re-runs duplicate detection and compares the fast matcher with the plain every-pair one on 500 groups |
| `.venv/bin/python scripts/run_sample_queries.py` | runs `sample_queries.sql` against `enron.db` and refreshes the output comments in it |

## Output files

| File | Contents |
|---|---|
| `enron.db` | the SQLite database (gitignored, about 194 MB) |
| `error_log.txt` | one `path<TAB>reason` line per failed file (613 lines, all `no To header`) |
| `duplicates_report.csv` | every flagged email: duplicate_message_id, original_message_id, subject, from_address, duplicate_date, original_date, similarity_score (23,816 rows) |
| `output/replies/*.eml` | one draft notice per flagged email, in the spec's template, addressed to its sender (23,816 files) |
| `output/replies/manifest.csv` | which .eml file belongs to which Message-ID |
| `output/send_log.csv` | every live send attempt: timestamp, recipient, subject, status, error. Only the header row until `--send-live` is used. |
| `output/extraction_stats.txt` | files found, parsed and failed by reason; fallback encodings; field coverage; first markers; date range |
| `output/load_stats.txt` | inserted and skipped counts, table sizes before and after |
| `output/load_log.txt` | Message-ID conflicts and insert failures (none in the final run) |
| `output/dedup_stats.txt` | groups, flags, average group size, folder copies vs re-sends, short bodies |
| `output/selection_manifest.csv` | every mailbox with its selection numbers and why it was or wasn't picked |
| `schema.sql`, `sample_queries.sql` | the schema, and sample queries with their real output |

The database has four tables. `emails` holds every field from spec section 3 plus raw_date, raw_text, body_basis, attachment_evidence, normalized_subject, fingerprint, is_duplicate, duplicate_of, similarity_score, notification_sent and notification_date, with UNIQUE on message_id. `addresses` holds each address once. `email_recipients` has one row per email, address and type (to/cc/bcc), so recipients are never comma-separated strings. `notifications` is the send ledger. Dates are ISO 8601 UTC text, so they sort in time order; indexes cover date, from_address, subject and (from_address, normalized_subject). `sample_queries.sql` has emails per sender, a date range (with EXPLAIN showing the date index), CC recipients, duplicates joined to their originals, and contents found in more than one folder, each with its real output.

## Gmail MCP server setup

The pipeline never talks to SMTP itself. Live notices go through `mcp_server/gmail_server.py`, a small MCP server built with the official Python SDK. It has one tool:

```
send_email(to, subject, body, references="", intended_recipient="")
```

The tool sends through `smtp.gmail.com` port 587 with STARTTLS. It sets `Date`, `References`, a new `Message-ID` and `X-Intended-Recipient` itself, and returns `{status, to, message_id, date}`, or an error whose text starts with `not sent:`. It logs only to stderr and never prints the password.

1. **Create an App Password.** Turn on 2-Step Verification for the Google account, then open <https://myaccount.google.com/apppasswords> and create one. Google shows 16 characters in four groups; the server removes the spaces.
2. **Create `.env`** in the repo root (it's gitignored) from the example:
   ```
   cp .env.example .env
   ```
   and fill in `GMAIL_ADDRESS` (the account that sends), `GMAIL_APP_PASSWORD` and `NOTIFY_TO` (where live notices go, normally your own address). The server finds `.env` from its own path, so it works from any working directory.
3. **Register the server with Claude Code** (no secrets on the command line):
   ```
   claude mcp add gmail -- /absolute/path/to/enron-pipeline/.venv/bin/python /absolute/path/to/enron-pipeline/mcp_server/gmail_server.py
   ```
   Check it with `claude mcp list` or `/mcp` inside Claude Code. For other MCP clients, `mcp_config.json.example` shows the same server in the usual `mcpServers` format. Copy it to `mcp_config.json` (gitignored) if a client needs the file. With `.env` in place you can delete the `env` block.
4. **Try the tool from Claude Code** with a prompt like: *"Use the gmail MCP server's send_email tool to send an email to your.name@gmail.com (your NOTIFY_TO address) with the subject 'MCP test' and the body 'Testing send_email from Claude Code.' Then tell me the Message-ID it returned."*
5. **Send from the pipeline:** `.venv/bin/python main.py --send-live --limit 1`.

### What live mode does

- **Recipient override:** every live notice goes to `NOTIFY_TO`, not to the Enron sender, because those addresses aren't ours to email. The real sender is kept in the `X-Intended-Recipient` header and in the ledger's `intended_recipient` column. The dry-run drafts are addressed to the real senders, exactly as the template says.
- One notice per duplicate group, about the group's latest duplicate, at most `--limit` per run (default 3). The run prints how many groups are still waiting.
- A `pending` ledger row is written before each send and updated to `sent` or `failed` afterwards. Groups already sent are skipped. Failed groups are tried again next run. A row left `pending` by a crash is reported and never retried automatically, since the notice may already have gone out; check the Gmail Sent folder and fix that row by hand.
- On success the duplicate's `notification_sent` and `notification_date` are set, and every attempt is appended to `output/send_log.csv`.
- **The CONFIRM reply in the template isn't processed.** Nothing reads replies, so answering CONFIRM changes nothing in the database.
- Gmail limits how many emails a normal account can send per day, so don't try to send all 12,762 notices.

If the Google account has no App Passwords page (some Workspace and Advanced Protection accounts), replace the SMTP part of `send_email` with the Gmail API (OAuth with the `gmail.send` scope, `users.messages.send`) and keep the same tool name and arguments. The pipeline only depends on the tool.

## Mailbox selection

The spec asks for at least 5 mailboxes and 10,000 emails. `scripts/select_mailboxes.py` read all 150 mailboxes (517,401 files) and scored each one on the distinct emails it holds (copies in other folders counted once, by content fingerprint). Full details are in [docs/SELECTION.md](docs/SELECTION.md).

Rules:

1. at least 90% of emails have every mandatory field, and at least 500 distinct emails;
2. Cc, forwarded, quoted and attachment content each in at least 5% of emails, so every parser feature is exercised;
3. rank by the weakest of those four, then their average, then optional-header coverage;
4. Bcc not scored (it's an exact copy of Cc in all 68,456 emails that have it);
5. pick in rank order, skipping any mailbox that would push the total above 20,000 distinct emails, until there are 5 mailboxes and 12,000 distinct emails.

**Picked: sanders-r, mann-k, sager-e, shankman-j, fischer-m.** That's 41,264 files and 17,903 distinct emails. Of the 150 mailboxes, 98 failed rules 1 and 2, mostly because forwards appear in under 5% of their emails. The 20,000 cap skipped kaminski-v, dasovich-j and taylor-m.

**This is a purposive subset chosen to exercise the parser, not a random sample.** The picked mailboxes have about five times the corpus median forward rate (23.0% vs 4.8%) and more folder copies (42.9% vs 27.4%), so rates measured on them, such as the duplicate rate, don't describe the whole corpus.

## What the data looks like (EDA highlights)

From [docs/EDA.md](docs/EDA.md), over the 41,264 picked files:

- **Copies everywhere:** every file has its own Message-ID, but only 17,903 distinct contents exist. Outlook and Notes keep the same email in up to 8 folders.
- **Mixed line endings:** 93.2% of files have CRLF headers and LF body lines, so the reader turns CRLF into LF before splitting.
- **Encodings:** 41,253 files are plain ASCII and 11 need cp1252; none fall back to latin-1.
- **Quoted-printable:** 1,165 files are quoted-printable, and 37 Outlook `-----Original Message-----` lines only appear after decoding (they end in `=20`).
- **Dates:** only two formats exist (`-0700 (PDT)` and `-0800 (PST)`) and all parse. 84 files carry a null-date placeholder, `Mon, 31 Dec 1979 16:00:00 -0800 (PST)`.
- **Mandatory fields:** To is the only mandatory field ever missing (613 files, 1.5%). 1,300 files have an empty but present Subject.
- **Odd addresses:** these are the export's way of writing names and are kept as they are: `b..sanders@enron.com` (2,854 To entries), `.hall@enron.com`, `""thompson@enron.com`.
- **First reply/forward marker:** Lotus `Forwarded by` 27.7%, Outlook `Original Message` 9.1%, three Lotus reply-header shapes 20.9% together, none 42.2%. Of the Outlook blocks, 34% are forwards (FW: subject).
- **One malformed header:** a bare line break inside one Subject made the email module drop 12 headers; `repair_headers` fixes it.
- **Misfiled X-Origin:** in shankman-j, 660 files carry X-Origin `Skilling-J` and 38 `Dasovich-J`.

## Design decisions

Every rule has a one-line reason in the code and a full entry (what, why, alternatives, how it was checked) in [docs/DECISIONS.md](docs/DECISIONS.md). The main ones:

- **Every file is its own row (D4.1).** The spec makes message_id the duplicate check at insert. Folder copies have different Message-IDs, so they're loaded and then flagged by task 3. That keeps every source file traceable.
- **Only the real header block is parsed (D2.2).** X-To and `To:` lines inside forwarded text never count as recipients, and a stray line inside the header block is folded back in instead of ending the headers.
- **Body splitting (D2.4 to D2.6, D3.4).** The body is cut at the first reply or forward marker. Outlook blocks under an FW: subject become forwarded_content, since Outlook uses the same line for forwards. `>` lines are sorted one by one, and pure forwards fall back to the forwarded text, recorded in body_basis.
- **Dates (D3.1).** Converted to UTC ISO 8601, reading the zone in our own code, because Python 3.13's `parsedate_tz` treats an unknown zone as UTC.
- **Attachments (D2.7, D3.6).** Evidence comes from MIME parts, `<<file>>` placeholders in authored or forwarded text (forwards carry attachments, replies drop them, links don't count), or attach words in the sender's own text. Each email stores its evidence.
- **Duplicates (D5.1 to D5.3).** Same sender and normalized subject, then rapidfuzz Indel similarity of at least 90 on the body, decided on the whole-number distance. Identical texts skip the fuzzy step, and pairs too different in length are skipped. Each email attaches to the earliest original only, so chains don't spread. A plain every-pair version agrees on 500 sampled groups.
- **Safe sending (D6.4 to D6.6, D7.1).** There's a ledger with pending/sent/failed, a recipient override, a send limit, and flags that refuse to touch the real ledger from dev runs. Tests swap in a fake SMTP and can't start the real server.

## Known limitations

- **Short notes can hide different forwards.** Duplicates are judged on the body, as the spec says. 78 of the 914 re-send flags share only a short note (`print`, `fyi`) while the forwarded content behind it differs, so a person would call them different emails. Comparing the full text instead flags more, not fewer (24,513 vs 23,816), so the rule stays (D5.1).
- **One person, two addresses.** Duplicate grouping is by from_address, so Richard Sanders as `richard.sanders@enron.com` and as `b..sanders@enron.com` are two senders.
- **Most flags are folder copies.** 22,902 of the 23,816 flags are copies of the same email in other folders (same Date), not re-sends. Both match the spec's definition; the report tells them apart by comparing the two dates.
- **Heading rules are heuristics.** Most kept headings are real (`TABLE OF CONTENTS`, `3. Litigation and Other Contingencies`), but some noise stays (`MV SALVADOR CP 11.05.00`), and underlined headings are rare (5).
- **Some reply text stays in the body.** `wrote:` attribution lines stay in the body (92 files), and `>` lines indented with spaces aren't treated as quotes (80 files, mostly ASCII art).
- **Bogus dates are kept.** The 84 placeholder dates (1980-01-01 UTC) parse, so they're kept and sort first.
- **Loading never updates rows.** A repeated Message-ID is skipped, so extractor changes only reach the database after deleting `enron.db`, which also deletes the send ledger.
- **Drafts are rewritten every run.** Each run regenerates all drafts with a new Date (the template's `<current_timestamp>`).
- **CONFIRM replies aren't processed.**

## Repository layout

```
main.py                     runs the pipeline
schema.sql                  database schema
sample_queries.sql          sample queries with real output
src/                        common, markers, extractor, database, dedup, notifier
mcp_server/gmail_server.py  the MCP server with send_email
scripts/                    select_mailboxes.py, eda.py, run_sample_queries.py
tests/                      pytest tests on made-up emails
docs/                       SELECTION.md, EDA.md, DECISIONS.md, PROGRESS.md
output/                     drafts, send log, stats, selection manifest
error_log.txt               failed files
duplicates_report.csv       flagged duplicates
mcp_config.json.example     MCP client config with placeholders
.env.example                Gmail settings with placeholders
BUILD_PROMPT.md             the build plan given to Claude Code
AI_USAGE.md                 how AI tools were used
```
