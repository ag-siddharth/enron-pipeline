-- sqlite schema for the enron pipeline (task 2)
-- dates are ISO 8601 UTC text like 2001-05-14T23:39:00+00:00, so sorting the text sorts by time
-- foreign keys only work with PRAGMA foreign_keys=ON, which src/database.py sets on every connection

-- one row per email file with a distinct Message-ID (copies in other folders are their own rows,
-- task 3 flags them as duplicates)
CREATE TABLE IF NOT EXISTS emails (
    id                  INTEGER PRIMARY KEY,
    message_id          TEXT NOT NULL UNIQUE,        -- the exact-duplicate check at insert
    date                TEXT NOT NULL CHECK (date LIKE '____-__-__T__:__:__+00:00'),
    raw_date            TEXT NOT NULL,               -- the Date header as written
    from_address        TEXT NOT NULL,
    subject             TEXT NOT NULL,               -- as written, Re:/Fwd: kept, may be ''
    normalized_subject  TEXT NOT NULL,               -- Re:/Fw:/Fwd: stripped, lowercased, for task 3
    body                TEXT NOT NULL,               -- the sender's own text (or the fallback, see body_basis)
    body_basis          TEXT NOT NULL CHECK (body_basis IN ('authored', 'forwarded', 'quoted')),
    forwarded_content   TEXT,
    quoted_content      TEXT,
    raw_text            TEXT NOT NULL,               -- full decoded text after the headers
    source_file         TEXT NOT NULL,               -- like maildir/sanders-r/inbox/12.
    x_from              TEXT,
    x_to                TEXT,
    x_cc                TEXT,
    x_bcc               TEXT,
    x_folder            TEXT,
    x_origin            TEXT,
    content_type        TEXT,
    has_attachment      BOOLEAN NOT NULL DEFAULT 0 CHECK (has_attachment IN (0, 1)),
    attachment_evidence TEXT,                        -- why has_attachment is set
    headings            TEXT,                        -- one heading per line
    fingerprint         TEXT NOT NULL,               -- md5 of the raw headers and body, same for folder copies
    is_duplicate        BOOLEAN NOT NULL DEFAULT 0 CHECK (is_duplicate IN (0, 1)),
    duplicate_of        TEXT REFERENCES emails(message_id),
    similarity_score    REAL,                        -- against duplicate_of, 0 to 100
    notification_sent   BOOLEAN NOT NULL DEFAULT 0 CHECK (notification_sent IN (0, 1)),
    notification_date   TEXT
);

-- every address once
CREATE TABLE IF NOT EXISTS addresses (
    id      INTEGER PRIMARY KEY,
    address TEXT NOT NULL UNIQUE
);

-- to/cc/bcc recipients, one row per email, address and type (never comma-separated strings)
CREATE TABLE IF NOT EXISTS email_recipients (
    email_id   INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    address_id INTEGER NOT NULL REFERENCES addresses(id),
    type       TEXT NOT NULL CHECK (type IN ('to', 'cc', 'bcc')),
    position   INTEGER NOT NULL,                     -- order in the header, from 1
    PRIMARY KEY (email_id, type, address_id)
);

-- the send ledger: one row per notification attempt, kept apart from the duplicate flags
CREATE TABLE IF NOT EXISTS notifications (
    id                   INTEGER PRIMARY KEY,
    group_key            TEXT NOT NULL REFERENCES emails(message_id),  -- message_id of the group's original
    duplicate_message_id TEXT NOT NULL REFERENCES emails(message_id),  -- the latest duplicate it's about
    intended_recipient   TEXT NOT NULL,              -- the real sender of that duplicate
    actual_recipient     TEXT NOT NULL,              -- NOTIFY_TO in live mode
    subject              TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    error                TEXT,
    outbound_message_id  TEXT,                       -- Message-ID the MCP server gave the notice
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

-- the spec's indexes, plus the ones task 3 and the ledger look things up by
CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_from ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_subject ON emails(subject);
CREATE INDEX IF NOT EXISTS idx_emails_from_subject ON emails(from_address, normalized_subject);
CREATE INDEX IF NOT EXISTS idx_emails_fingerprint ON emails(fingerprint);
CREATE INDEX IF NOT EXISTS idx_emails_duplicate_of ON emails(duplicate_of);
CREATE INDEX IF NOT EXISTS idx_recipients_address ON email_recipients(address_id);
CREATE INDEX IF NOT EXISTS idx_notifications_group ON notifications(group_key);
