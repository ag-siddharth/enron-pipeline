# task 2 tests: loading twice adds nothing, conflicts are logged, recipients are normalized

from src import database
from src import extractor


def load_once(conn, root, tmp_path):
    stats=extractor.new_stats()
    records=extractor.extract(root, ['testbox'], str(tmp_path / 'error_log.txt'), stats)
    return database.load(conn, records, str(tmp_path / 'load_log.txt'))


def test_reloading_adds_nothing(maildir, email, tmp_path):
    root, write=maildir
    write('1', email(message_id='<1@test>', to='a@enron.com, b@enron.com', extra_headers=['Cc: c@enron.com', 'Bcc: c@enron.com']))
    write('2', email(message_id='<2@test>', to='a@enron.com'))
    conn=database.connect(str(tmp_path / 'test.db'))
    database.create_schema(conn)
    first=load_once(conn, root, tmp_path)
    counts=database.table_counts(conn)
    second=load_once(conn, root, tmp_path)
    assert first['inserted']==2
    assert second['inserted']==0
    assert second['already_there']==2
    assert second['conflicts']==0
    assert database.table_counts(conn)==counts
    assert counts=={'emails': 2, 'addresses': 3, 'email_recipients': 5, 'notifications': 0}


def test_repeated_message_id_with_new_content_is_a_conflict(maildir, email, tmp_path, read_file):
    root, write=maildir
    write('1', email(message_id='<same@test>', body='first version'))
    write('2', email(message_id='<same@test>', body='a different version'))
    conn=database.connect(str(tmp_path / 'test.db'))
    database.create_schema(conn)
    stats=load_once(conn, root, tmp_path)
    assert stats['inserted']==1
    assert stats['conflicts']==1
    assert 'conflict\t<same@test>\tmaildir/testbox/inbox/2' in read_file(str(tmp_path / 'load_log.txt'))


def test_recipients_are_rows_not_strings(maildir, email, tmp_path):
    root, write=maildir
    write('1', email(message_id='<1@test>', to='a@enron.com, b@enron.com', extra_headers=['Cc: b@enron.com']))
    conn=database.connect(str(tmp_path / 'test.db'))
    database.create_schema(conn)
    load_once(conn, root, tmp_path)
    rows=conn.execute('''SELECT r.type, r.position, a.address FROM email_recipients r JOIN addresses a ON a.id=r.address_id
                         ORDER BY r.type DESC, r.position''').fetchall()
    assert [tuple(r) for r in rows]==[('to', 1, 'a@enron.com'), ('to', 2, 'b@enron.com'), ('cc', 1, 'b@enron.com')]
    # b@enron.com is stored once even though it's used twice
    assert conn.execute('SELECT COUNT(*) FROM addresses').fetchone()[0]==2


def test_schema_rejects_bad_values(tmp_path):
    conn=database.connect(str(tmp_path / 'test.db'))
    database.create_schema(conn)
    failed=False
    try:
        conn.execute('''INSERT INTO emails (message_id, date, raw_date, from_address, subject, normalized_subject, body,
                        body_basis, raw_text, source_file, fingerprint) VALUES ('<x>', '14 May 2001', 'x', 'a@b', '', '', 'b',
                        'authored', 'b', 'f', 'fp')''')
    except Exception as e:
        failed=True
    assert failed
