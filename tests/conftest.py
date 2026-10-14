# shared test helpers: fake enron-style emails, a fake smtp server, and a guard so no test can reach gmail
# no test needs maildir/; every email is made up here

import os
import smtplib

import pytest

from mcp_server import gmail_server
from src import database
from src import dedup
from src import extractor
from src import notifier


class FakeSMTP:
    """Stands in for smtplib.SMTP and keeps what would have been sent."""
    sent=[]
    fail_login=False
    fail_quit=False
    closed=False

    def __init__(self, host, port, timeout=None):
        self.host=host
        self.port=port

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b'5.7.8 Username and Password not accepted')

    def send_message(self, message):
        FakeSMTP.sent.append(message)

    def quit(self):
        # like gmail dropping the connection after it has already accepted the message
        if FakeSMTP.fail_quit:
            raise smtplib.SMTPServerDisconnected('Connection unexpectedly closed')

    def close(self):
        FakeSMTP.closed=True


@pytest.fixture(autouse=True)
def no_real_email(monkeypatch, tmp_path):
    """Every test gets the fake smtp, fake settings and no .env, so nothing can ever reach gmail."""
    FakeSMTP.sent=[]
    FakeSMTP.fail_login=False
    FakeSMTP.fail_quit=False
    FakeSMTP.closed=False
    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setattr(gmail_server, 'ENV_FILE', str(tmp_path / 'missing.env'))
    monkeypatch.setattr(notifier, 'ENV_FILE', str(tmp_path / 'missing.env'))

    def no_subprocess():
        raise RuntimeError('tests must use the in-process server, never the real one')
    monkeypatch.setattr(notifier, 'stdio_server', no_subprocess)
    monkeypatch.setenv('GMAIL_ADDRESS', 'pipeline.test@gmail.com')
    monkeypatch.setenv('GMAIL_APP_PASSWORD', 'abcd efgh ijkl mnop')
    monkeypatch.setenv('NOTIFY_TO', 'me@example.com')
    return FakeSMTP


def build_email(message_id='<1@test>', date='Mon, 14 May 2001 16:39:00 -0700 (PDT)', sender='kay.mann@enron.com',
                to='jeff.dasovich@enron.com', subject='Hello', body='Hi there.', extra_headers=None,
                content_type='text/plain; charset=us-ascii', x_to='Dasovich, Jeff'):
    """Raw text of a fake enron-style email; pass None to leave a header out."""
    lines=[]
    if message_id is not None:
        lines.append('Message-ID: '+message_id)
    if date is not None:
        lines.append('Date: '+date)
    if sender is not None:
        lines.append('From: '+sender)
    if to is not None:
        lines.append('To: '+to)
    if subject is not None:
        lines.append('Subject: '+subject)
    lines.append('Mime-Version: 1.0')
    lines.append('Content-Type: '+content_type)
    lines.append('Content-Transfer-Encoding: 7bit')
    lines.append('X-From: Mann, Kay')
    lines.append('X-To: '+x_to)
    lines.append('X-cc: ')
    lines.append('X-bcc: ')
    lines.append('X-Folder: \\Kay_Mann_June2001\\Notes Folders\\Inbox')
    lines.append('X-Origin: Mann-K')
    for header in extra_headers or []:
        lines.append(header)
    # enron files have CRLF headers, so the fakes do too
    return '\r\n'.join(lines)+'\r\n\r\n'+body


@pytest.fixture
def email():
    """The fake email builder."""
    return build_email


@pytest.fixture
def maildir(tmp_path):
    """A temp maildir with one mailbox; returns (maildir path, function that writes a file into it)."""
    root=tmp_path / 'maildir'
    inbox=root / 'testbox' / 'inbox'
    inbox.mkdir(parents=True)

    def write(name, text):
        path=inbox / name
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_bytes(text.encode('utf-8'))
        return str(path)
    return str(root), write


@pytest.fixture
def run_pipeline(tmp_path, maildir):
    """Extract the temp maildir, load it into a temp db and run dedup; returns the connection."""
    root, write=maildir

    def run():
        conn=database.connect(str(tmp_path / 'test.db'))
        database.create_schema(conn)
        stats=extractor.new_stats()
        records=extractor.extract(root, ['testbox'], str(tmp_path / 'error_log.txt'), stats)
        database.load(conn, records, str(tmp_path / 'load_log.txt'))
        dedup.run(conn, str(tmp_path / 'duplicates_report.csv'))
        return conn
    return run


def read(path):
    """Whole file as text."""
    with open(path, encoding='utf-8') as f:
        return f.read()


@pytest.fixture
def read_file():
    return read


@pytest.fixture
def out_dir(tmp_path):
    """A temp output folder like output/."""
    folder=tmp_path / 'output'
    os.makedirs(str(folder))
    return str(folder)
