# task 4 tests: the draft template, the send ledger, and the MCP server over an in-process client
# every send goes to the FakeSMTP from conftest.py; nothing here can reach gmail

import asyncio
import csv
import os

from mcp import Client

from mcp_server import gmail_server
from src import notifier

EXPECTED_BODY='''This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  <2@test>
    Date Sent:   2001-05-15T23:39:00+00:00
    Subject:     RE: turbine contract

  Original Email on Record:
    Message-ID:  <1@test>
    Date Sent:   2001-05-14T23:39:00+00:00

  Similarity Score: 100%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.

No action is required if this is indeed a duplicate.
'''


def two_copies(maildir, email):
    """An original and one re-send of it."""
    root, write=maildir
    write('1', email(message_id='<1@test>', subject='turbine contract', body='Contract attached, please sign.'))
    write('2', email(message_id='<2@test>', date='Tue, 15 May 2001 16:39:00 -0700 (PDT)', subject='RE: turbine contract',
                     body='Contract attached, please sign.'))


def ledger(conn):
    rows=conn.execute('SELECT group_key, duplicate_message_id, intended_recipient, actual_recipient, status FROM notifications ORDER BY id')
    result=[]
    for row in rows:
        result.append(tuple(row))
    return result


def test_draft_follows_the_template(maildir, email, run_pipeline, out_dir, read_file):
    two_copies(maildir, email)
    conn=run_pipeline()
    assert notifier.write_drafts(conn, out_dir)==1
    text=read_file(os.path.join(out_dir, 'replies', '2_test.eml'))
    lines=text.split('\n')
    assert lines[0]=='To: kay.mann@enron.com'
    assert lines[1]=='Subject: [Duplicate Notice] Re: turbine contract'
    assert lines[2].startswith('Date: ') and lines[2].endswith('+0000')
    assert lines[3]=='References: <2@test>'
    assert lines[4]==''
    assert '\n'.join(lines[5:])==EXPECTED_BODY
    with open(os.path.join(out_dir, 'replies', 'manifest.csv'), newline='') as f:
        assert list(csv.reader(f))==[['file_name', 'message_id'], ['2_test.eml', '<2@test>']]
    # the send log exists from the start, with just its header
    assert read_file(os.path.join(out_dir, 'send_log.csv'))=='timestamp,recipient,subject,status,error\n'


def test_drafts_from_an_old_run_are_removed(maildir, email, run_pipeline, out_dir):
    two_copies(maildir, email)
    conn=run_pipeline()
    old=os.path.join(out_dir, 'replies', 'stale.eml')
    os.makedirs(os.path.dirname(old), exist_ok=True)
    with open(old, 'w') as f:
        f.write('left over')
    notifier.write_drafts(conn, out_dir)
    assert not os.path.exists(old)


def test_live_send_fills_the_ledger_and_skips_sent_groups(maildir, email, run_pipeline, out_dir, no_real_email):
    two_copies(maildir, email)
    conn=run_pipeline()
    result=notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)
    assert result['sent']==1
    assert ledger(conn)==[('<1@test>', '<2@test>', 'kay.mann@enron.com', 'me@example.com', 'sent')]
    row=conn.execute("SELECT notification_sent, notification_date FROM emails WHERE message_id='<2@test>'").fetchone()
    assert row[0]==1 and row[1] is not None
    # the notice went to NOTIFY_TO, with the real sender kept in its own header
    message=no_real_email.sent[0]
    assert message['To']=='me@example.com'
    assert message['X-Intended-Recipient']=='kay.mann@enron.com'
    assert message['References']=='<2@test>'
    assert message['Subject']=='[Duplicate Notice] Re: turbine contract'
    assert message.get_content()==EXPECTED_BODY
    # a second run sends nothing more for that group
    again=notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)
    assert again['sent']==0
    assert len(no_real_email.sent)==1


def test_failed_send_is_not_marked_sent(maildir, email, run_pipeline, out_dir, no_real_email):
    two_copies(maildir, email)
    conn=run_pipeline()
    no_real_email.fail_login=True
    result=notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)
    assert result['failed']==1
    assert ledger(conn)==[('<1@test>', '<2@test>', 'kay.mann@enron.com', 'me@example.com', 'failed')]
    assert conn.execute('SELECT SUM(notification_sent) FROM emails').fetchone()[0]==0
    error=conn.execute('SELECT error FROM notifications').fetchone()[0]
    assert 'SMTPAuthenticationError' in error
    with open(os.path.join(out_dir, 'send_log.csv'), newline='') as f:
        rows=list(csv.reader(f))
    assert rows[1][1:4]==['me@example.com', '[Duplicate Notice] Re: turbine contract', 'failed']
    # a failed group is tried again next time
    no_real_email.fail_login=False
    assert notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)['sent']==1


def test_pending_row_is_reported_not_retried(maildir, email, run_pipeline, out_dir, no_real_email):
    two_copies(maildir, email)
    conn=run_pipeline()
    # as if an earlier run crashed right after writing its pending row
    conn.execute('''INSERT INTO notifications (group_key, duplicate_message_id, intended_recipient, actual_recipient,
                    subject, status, created_at, updated_at) VALUES ('<1@test>', '<2@test>', 'kay.mann@enron.com',
                    'me@example.com', 's', 'pending', 'then', 'then')''')
    conn.commit()
    result=notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)
    assert result['sent']==0
    assert no_real_email.sent==[]
    assert [r[4] for r in ledger(conn)]==['pending']


def test_limit_caps_the_sends(maildir, email, run_pipeline, out_dir, no_real_email):
    root, write=maildir
    for i in range(4):
        # four groups, each an original and a later copy
        subject='topic %d' % i
        write('a%d' % i, email(message_id='<a%d@test>' % i, subject=subject, body='text number %d' % i))
        write('b%d' % i, email(message_id='<b%d@test>' % i, date='Tue, 15 May 2001 16:39:00 -0700 (PDT)', subject=subject, body='text number %d' % i))
    conn=run_pipeline()
    result=notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)
    assert result['sent']==3
    assert result['waiting']==1


def test_real_resends_go_out_before_folder_copies(maildir, email, run_pipeline, out_dir, no_real_email):
    root, write=maildir
    # the oldest group: a placeholder-dated original and a later copy. its real Date was lost, so it's no re-send
    write('p1', email(message_id='<p1@test>', date='Mon, 31 Dec 1979 16:00:00 -0800 (PST)', subject='password', body='your password'))
    write('p2', email(message_id='<p2@test>', date='Mon, 11 Jun 2001 18:04:00 -0700 (PDT)', subject='password', body='your password'))
    # next: the same email in two folders, same Date
    write('c1', email(message_id='<c1@test>', subject='copy', body='same text in two folders'))
    write('c2', email(message_id='<c2@test>', subject='copy', body='same text in two folders'))
    # the newest group, but really sent again a day later with a small change
    write('r1', email(message_id='<r1@test>', date='Tue, 15 May 2001 09:00:00 -0700 (PDT)', subject='resend', body='please sign the contract'))
    write('r2', email(message_id='<r2@test>', date='Wed, 16 May 2001 09:00:00 -0700 (PDT)', subject='RE: resend', body='please sign the contract!'))
    conn=run_pipeline()
    # with --limit 1 the re-send goes first, although its group comes last in the report
    assert notifier.send_live(conn, out_dir, 1, server=gmail_server.mcp)['sent']==1
    assert ledger(conn)[0][:2]==('<r1@test>', '<r2@test>')
    assert '97.96%' in no_real_email.sent[0].get_content()
    # the rest follow in report order
    notifier.send_live(conn, out_dir, 5, server=gmail_server.mcp)
    order=[]
    for row in ledger(conn):
        order.append(row[1])
    assert order==['<r2@test>', '<p2@test>', '<c2@test>']


def test_no_notify_to_means_nothing_is_sent(maildir, email, run_pipeline, out_dir, no_real_email, monkeypatch):
    two_copies(maildir, email)
    conn=run_pipeline()
    monkeypatch.delenv('NOTIFY_TO')
    assert notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp) is None
    assert ledger(conn)==[]


def call_server(arguments):
    """Call send_email through an in-process MCP client."""
    async def run():
        async with Client(gmail_server.mcp) as client:
            return await client.call_tool('send_email', arguments)
    return asyncio.run(run())


def test_server_sets_its_own_headers(no_real_email):
    result=call_server({'to': 'me@example.com', 'subject': 'hi', 'body': 'line one\n\n  indented\n',
                        'references': '<dup@test>', 'intended_recipient': 'kay.mann@enron.com'})
    assert result.is_error is False
    assert result.structured_content['status']=='sent'
    message=no_real_email.sent[0]
    assert message['From']=='pipeline.test@gmail.com'
    assert message['Message-ID']==result.structured_content['message_id']
    assert message['Date'] is not None
    assert message['References']=='<dup@test>'
    assert message['X-Intended-Recipient']=='kay.mann@enron.com'
    assert message.get_content()=='line one\n\n  indented\n'


def test_server_refuses_without_credentials(no_real_email, monkeypatch):
    monkeypatch.delenv('GMAIL_APP_PASSWORD')
    result=call_server({'to': 'me@example.com', 'subject': 'hi', 'body': 'x'})
    assert result.is_error is True
    assert 'GMAIL_APP_PASSWORD' in result.content[0].text
    assert no_real_email.sent==[]


def test_server_reports_smtp_errors_without_the_password(no_real_email):
    no_real_email.fail_login=True
    result=call_server({'to': 'me@example.com', 'subject': 'hi', 'body': 'x'})
    assert result.is_error is True
    assert 'SMTPAuthenticationError' in result.content[0].text
    assert 'abcd' not in result.content[0].text


def test_failed_quit_after_gmail_accepted_counts_as_sent(maildir, email, run_pipeline, out_dir, no_real_email):
    # gmail took the message, then the connection dropped on QUIT
    no_real_email.fail_quit=True
    result=call_server({'to': 'me@example.com', 'subject': 'hi', 'body': 'x'})
    assert result.is_error is False
    assert result.structured_content['status']=='sent'
    assert no_real_email.closed is True
    # through the pipeline: marked sent, and a second run doesn't send it again
    two_copies(maildir, email)
    conn=run_pipeline()
    assert notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)['sent']==1
    assert ledger(conn)==[('<1@test>', '<2@test>', 'kay.mann@enron.com', 'me@example.com', 'sent')]
    assert conn.execute("SELECT notification_sent FROM emails WHERE message_id='<2@test>'").fetchone()[0]==1
    assert notifier.send_live(conn, out_dir, 3, server=gmail_server.mcp)['sent']==0
    assert len(no_real_email.sent)==2
