# task 4: duplicate notices. the dry run writes one .eml per flagged duplicate to output/replies/,
# --send-live sends one notice per group through the MCP server's send_email tool (never smtp from here)

import asyncio
import csv
import glob
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime

from mcp import Client, StdioServerParameters

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SCRIPT=os.path.join(ROOT, 'mcp_server', 'gmail_server.py')
ENV_FILE=os.path.join(ROOT, '.env')
SEND_LOG_COLUMNS=['timestamp', 'recipient', 'subject', 'status', 'error']
# header text can't hold control characters or line breaks (a line break would start a new header);
# 5 subjects here have \x01 where a dash used to be
CONTROL_CHARS=re.compile(r'[\x00-\x08\x0a-\x1f\x7f]')

# the spec's template, word for word, from the first body line down
BODY_TEMPLATE='''This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {duplicate_id}
    Date Sent:   {duplicate_date}
    Subject:     {subject}

  Original Email on Record:
    Message-ID:  {original_id}
    Date Sent:   {original_date}

  Similarity Score: {score}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
'''

FLAGGED_SQL='''SELECT d.id, d.message_id, d.date, d.subject, d.from_address, d.similarity_score,
       o.message_id AS original_id, o.date AS original_date, o.subject AS original_subject
FROM emails d JOIN emails o ON o.message_id=d.duplicate_of
WHERE d.is_duplicate=1
ORDER BY o.date, o.message_id, d.date, d.message_id'''


def now_iso():
    """Current time as ISO 8601 UTC, the same format the database uses."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def clean(text):
    """Text that is safe on one header line."""
    return CONTROL_CHARS.sub(' ', text or '')


def format_score(score):
    """100.0 -> 100, 93.50 -> 93.5, 93.47 -> 93.47."""
    return ('%.2f' % score).rstrip('0').rstrip('.')


def notice_subject(row):
    """[Duplicate Notice] Re: <original_subject>"""
    return '[Duplicate Notice] Re: '+clean(row['original_subject'])


def notice_body(row):
    """The template body filled in for one flagged duplicate."""
    return BODY_TEMPLATE.format(duplicate_id=row['message_id'], duplicate_date=row['date'],
                                subject=clean(row['subject']), original_id=row['original_id'],
                                original_date=row['original_date'], score=format_score(row['similarity_score']))


def notice_text(row, sent_at):
    """The whole notice: the template's four header lines, a blank line, then the body."""
    lines=['To: '+clean(row['from_address']),
           'Subject: '+notice_subject(row),
           'Date: '+sent_at,
           'References: '+clean(row['message_id']),
           '']
    return '\n'.join(lines)+'\n'+notice_body(row)


def safe_file_name(message_id, used):
    """A file name made from the Message-ID, with anything odd turned into _ and no repeats."""
    name=re.sub(r'[^A-Za-z0-9._-]', '_', message_id.strip('<>'))
    if name=='' or name.startswith('.'):
        name='dup'+name
    candidate=name
    count=2
    while candidate in used:
        candidate=name+'_'+str(count)
        count+=1
    used.add(candidate)
    return candidate+'.eml'


def ensure_send_log(path):
    """Create send_log.csv with its header row if it isn't there yet."""
    if os.path.exists(path) and os.path.getsize(path)>0:
        return
    with open(path, 'w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(SEND_LOG_COLUMNS)


def write_drafts(conn, out_dir):
    """Dry run: one .eml per flagged duplicate, addressed to its own sender, plus manifest.csv."""
    replies=os.path.join(out_dir, 'replies')
    os.makedirs(replies, exist_ok=True)
    # last run's drafts may belong to emails that aren't flagged any more
    for old in glob.glob(os.path.join(replies, '*.eml')):
        os.remove(old)
    sent_at=format_datetime(datetime.now(timezone.utc))
    used=set()
    count=0
    with open(os.path.join(replies, 'manifest.csv'), 'w', newline='', encoding='utf-8') as f:
        manifest=csv.writer(f)
        manifest.writerow(['file_name', 'message_id'])
        for row in conn.execute(FLAGGED_SQL):
            name=safe_file_name(row['message_id'], used)
            with open(os.path.join(replies, name), 'w', encoding='utf-8', newline='\n') as eml:
                eml.write(notice_text(row, sent_at))
            manifest.writerow([name, row['message_id']])
            count+=1
    ensure_send_log(os.path.join(out_dir, 'send_log.csv'))
    return count


def latest_per_group(conn):
    """For every original, its latest duplicate (by date, then message_id), in group order."""
    latest={}
    order=[]
    for row in conn.execute(FLAGGED_SQL):
        key=row['original_id']
        if key not in latest:
            order.append(key)
        # rows come in date order inside a group, so the last one seen is the latest
        latest[key]=row
    result=[]
    for key in order:
        result.append(latest[key])
    return result


def ledger_state(conn):
    """group_key -> 'sent' or 'pending' from the ledger; failed-only groups can be tried again."""
    state={}
    for row in conn.execute('SELECT group_key, status FROM notifications'):
        if row['status']=='sent':
            state[row['group_key']]='sent'
        elif row['status']=='pending' and state.get(row['group_key'])!='sent':
            state[row['group_key']]='pending'
    return state


def read_setting(name):
    """A setting from the environment, or else from the gitignored .env."""
    if os.environ.get(name):
        return os.environ[name]
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if line.startswith(name+'='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def stdio_server():
    """How to start our MCP server as a subprocess; passes on Gmail settings set in the shell."""
    # the mcp client only passes a few safe variables to the subprocess, so add ours explicitly.
    # with a .env file the server finds the settings itself
    env={}
    for name in ['GMAIL_ADDRESS', 'GMAIL_APP_PASSWORD']:
        if os.environ.get(name):
            env[name]=os.environ[name]
    return StdioServerParameters(command=sys.executable, args=[SERVER_SCRIPT], env=env)


def append_send_log(path, recipient, subject, status, error):
    """One line per attempt in output/send_log.csv."""
    ensure_send_log(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([now_iso(), recipient, subject, status, error or ''])


def start_attempt(conn, row, notify_to):
    """Write the ledger row as pending before anything is sent; returns its id."""
    stamp=now_iso()
    cursor=conn.execute('''INSERT INTO notifications (group_key, duplicate_message_id, intended_recipient,
                               actual_recipient, subject, status, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)''',
                        (row['original_id'], row['message_id'], row['from_address'], notify_to,
                         notice_subject(row), stamp, stamp))
    conn.commit()
    return cursor.lastrowid


def finish_attempt(conn, attempt_id, row, status, error, outbound_id):
    """Record how the attempt went; a sent one also marks the duplicate as notified."""
    stamp=now_iso()
    conn.execute('UPDATE notifications SET status=?, error=?, outbound_message_id=?, updated_at=? WHERE id=?',
                 (status, error, outbound_id, stamp, attempt_id))
    if status=='sent':
        conn.execute('UPDATE emails SET notification_sent=1, notification_date=? WHERE id=?', (stamp, row['id']))
    conn.commit()


def result_text(result):
    """The text the tool sent back."""
    parts=[]
    for item in result.content:
        if getattr(item, 'text', None):
            parts.append(item.text)
    return ' '.join(parts)


async def send_notices(conn, todo, notify_to, server, log_path):
    """Send each notice through send_email; returns (sent, failed, unknown)."""
    sent=0
    failed=0
    unknown=0
    async with Client(server) as client:
        for row in todo:
            subject=notice_subject(row)
            attempt_id=start_attempt(conn, row, notify_to)
            arguments={'to': notify_to, 'subject': subject, 'body': notice_body(row),
                       'references': row['message_id'], 'intended_recipient': row['from_address']}
            try:
                result=await client.call_tool('send_email', arguments)
            except Exception as e:
                # we can't tell whether it went out, so the row stays pending and nothing else is sent
                error='no answer from the MCP server: %s: %s' % (type(e).__name__, e)
                conn.execute('UPDATE notifications SET error=?, updated_at=? WHERE id=?', (error, now_iso(), attempt_id))
                conn.commit()
                append_send_log(log_path, notify_to, subject, 'pending', error)
                unknown+=1
                break
            if result.is_error:
                error=result_text(result)
                finish_attempt(conn, attempt_id, row, 'failed', error, None)
                append_send_log(log_path, notify_to, subject, 'failed', error)
                failed+=1
                print('  failed:', subject, '-', error)
                continue
            outbound=None
            if result.structured_content:
                outbound=result.structured_content.get('message_id')
            finish_attempt(conn, attempt_id, row, 'sent', None, outbound)
            append_send_log(log_path, notify_to, subject, 'sent', None)
            sent+=1
            print('  sent:', subject, '(for', row['from_address']+')')
    return sent, failed, unknown


def send_live(conn, out_dir, limit, server=None):
    """Live mode: at most limit notices, one per group about its latest duplicate, all to NOTIFY_TO."""
    notify_to=read_setting('NOTIFY_TO')
    if '@' not in notify_to:
        print('NOTIFY_TO is not set (environment or .env), so nothing was sent')
        return None
    if server is None:
        server=stdio_server()
    groups=latest_per_group(conn)
    state=ledger_state(conn)
    todo=[]
    already=0
    stuck=[]
    for row in groups:
        status=state.get(row['original_id'])
        if status=='sent':
            already+=1
        elif status=='pending':
            stuck.append(row)
        else:
            todo.append(row)
    print('groups: %d, already sent: %d, waiting: %d' % (len(groups), already, len(todo)))
    for row in stuck:
        # a pending row means an earlier run stopped mid-send; check the Gmail sent folder by hand
        print('  left pending by an earlier run, not retried:', row['original_id'])
    log_path=os.path.join(out_dir, 'send_log.csv')
    try:
        sent, failed, unknown=asyncio.run(send_notices(conn, todo[:limit], notify_to, server, log_path))
    except Exception as e:
        print('could not reach the MCP server: %s: %s' % (type(e).__name__, e))
        return None
    state=ledger_state(conn)
    waiting=0
    for row in groups:
        if row['original_id'] not in state:
            waiting+=1
    print('this run: %d sent, %d failed, %d unknown (left pending)' % (sent, failed, unknown))
    print('groups still waiting for a notice: %d (failed ones are tried again next run)' % waiting)
    return {'sent': sent, 'failed': failed, 'unknown': unknown, 'waiting': waiting}
