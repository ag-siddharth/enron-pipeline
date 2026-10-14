# task 2: create the sqlite database from schema.sql and load the extracted records into it
# loading is safe to repeat: a Message-ID that's already there is skipped (and logged if its content differs)

import os
import sqlite3

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA=os.path.join(ROOT, 'schema.sql')

EMAIL_COLUMNS=['message_id', 'date', 'raw_date', 'from_address', 'subject', 'normalized_subject', 'body',
               'body_basis', 'forwarded_content', 'quoted_content', 'raw_text', 'source_file', 'x_from', 'x_to',
               'x_cc', 'x_bcc', 'x_folder', 'x_origin', 'content_type', 'has_attachment', 'attachment_evidence',
               'headings', 'fingerprint']
RECIPIENT_TYPES=[('to', 'to_addresses'), ('cc', 'cc_addresses'), ('bcc', 'bcc_addresses')]


def connect(path):
    """Open the database with foreign keys on and rows readable by column name."""
    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    # sqlite leaves foreign keys off unless every connection asks for them
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def create_schema(conn):
    """Run schema.sql; every statement is CREATE ... IF NOT EXISTS so it's safe to repeat."""
    with open(SCHEMA, encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()


def table_counts(conn):
    """Row counts of every table, for the before/after load check."""
    counts={}
    for table in ['emails', 'addresses', 'email_recipients', 'notifications']:
        counts[table]=conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    return counts


def address_id(conn, cache, address):
    """Id of an address, adding it the first time it's seen."""
    if address in cache:
        return cache[address]
    row=conn.execute('SELECT id FROM addresses WHERE address=?', (address,)).fetchone()
    if row is None:
        cursor=conn.execute('INSERT INTO addresses (address) VALUES (?)', (address,))
        cache[address]=cursor.lastrowid
    else:
        cache[address]=row['id']
    return cache[address]


def insert_email(conn, cache, record):
    """Insert one record and its recipients; returns the new email id."""
    values=[]
    for column in EMAIL_COLUMNS:
        value=record[column]
        if column=='has_attachment':
            value=1 if value else 0
        values.append(value)
    marks=', '.join(['?']*len(EMAIL_COLUMNS))
    sql='INSERT INTO emails ('+', '.join(EMAIL_COLUMNS)+') VALUES ('+marks+')'
    email_id=conn.execute(sql, values).lastrowid
    for kind, field in RECIPIENT_TYPES:
        position=1
        for address in record[field]:
            conn.execute('INSERT INTO email_recipients (email_id, address_id, type, position) VALUES (?, ?, ?, ?)',
                         (email_id, address_id(conn, cache, address), kind, position))
            position+=1
    return email_id


def load(conn, records, log_path):
    """Insert every record whose Message-ID is new, in one transaction; returns the counts."""
    stats={'seen': 0, 'inserted': 0, 'already_there': 0, 'conflicts': 0, 'insert_errors': 0}
    cache={}
    # one outer transaction; without it the first SAVEPOINT would start one and every RELEASE would commit
    conn.execute('BEGIN')
    with open(log_path, 'w', encoding='utf-8') as log:
        log.write('# conflicts and insert failures from the last load (message_id, source_file, detail)\n')
        for record in records:
            stats['seen']+=1
            row=conn.execute('SELECT fingerprint, source_file FROM emails WHERE message_id=?',
                             (record['message_id'],)).fetchone()
            if row is not None:
                # the spec makes message_id the duplicate check at insert, so a repeat is skipped
                stats['already_there']+=1
                if row['fingerprint']!=record['fingerprint']:
                    stats['conflicts']+=1
                    log.write('conflict\t%s\t%s\tdiffers from %s\n' % (record['message_id'], record['source_file'], row['source_file']))
                continue
            try:
                # a savepoint so one bad record rolls back alone, not the whole load
                conn.execute('SAVEPOINT one_email')
                insert_email(conn, cache, record)
                conn.execute('RELEASE one_email')
                stats['inserted']+=1
            except Exception as e:
                conn.execute('ROLLBACK TO one_email')
                conn.execute('RELEASE one_email')
                # an address added inside the rolled-back part is gone again, so forget the cached ids
                cache.clear()
                stats['insert_errors']+=1
                log.write('insert failed\t%s\t%s\t%s: %s\n' % (record['message_id'], record['source_file'], type(e).__name__, e))
    conn.commit()
    return stats


def load_lines(stats, before, after):
    """Readable lines for one load run."""
    lines=[]
    lines.append('records seen: %d' % stats['seen'])
    lines.append('inserted: %d' % stats['inserted'])
    lines.append('skipped, Message-ID already loaded: %d' % stats['already_there'])
    lines.append('  of those, content differs (conflict): %d' % stats['conflicts'])
    lines.append('insert errors: %d' % stats['insert_errors'])
    for table in ['emails', 'addresses', 'email_recipients', 'notifications']:
        lines.append('%-17s %7d -> %7d' % (table, before[table], after[table]))
    return lines
