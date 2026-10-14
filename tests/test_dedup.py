# task 3 tests: the 90 boundary, chains, ties, bigger groups, and fast vs plain matching

import csv
import random

from src import dedup
from src import notifier

LETTERS='abcdefghijklmnopqrstuvwxyz'


def random_text(length, seed):
    """Lowercase letters only, so an X or Y put in later can never match anything."""
    picker=random.Random(seed)
    letters=[]
    for i in range(length):
        letters.append(picker.choice(LETTERS))
    return ''.join(letters)


def fake_email(message_id, date, body):
    return {'id': message_id, 'message_id': message_id, 'date': date, 'body': body}


def test_exact_90_boundary():
    # 900 vs 1,100 characters, the short one a prefix of the long one: distance 200, ratio exactly 90
    short=random_text(900, 1)
    long=short+random_text(200, 2)
    assert dedup.similarity(short, long)==90.0
    assert dedup.plain_similarity(short, long)==90.0
    # one character more and the length rule alone rules it out (20*900 < 9*2001)
    longer=long+'q'
    assert dedup.similarity(short, longer) is None
    assert dedup.plain_similarity(short, longer) is None


def test_identical_and_empty_texts():
    assert dedup.similarity('same words', 'same words')==100.0
    # two empty texts are never similar, even though they're equal
    assert dedup.similarity('', '') is None
    assert dedup.plain_similarity('', '') is None
    assert dedup.similarity('', 'something') is None


def test_similarity_chain_is_not_followed():
    a=random_text(1000, 3)
    # b changes 60 letters of a (94%), c changes another 60 letters of b (94% to b, 88% to a)
    b='X'*60+a[60:]
    c=b[:500]+'Y'*60+b[560:]
    assert dedup.similarity(a, b)>=90
    assert dedup.similarity(b, c)>=90
    assert dedup.similarity(a, c) is None
    group=[fake_email('<a>', '2001-01-01T00:00:00+00:00', a), fake_email('<b>', '2001-01-02T00:00:00+00:00', b),
           fake_email('<c>', '2001-01-03T00:00:00+00:00', c)]
    flags=dedup.match_group(group, dedup.similarity)
    # b attaches to a; c is compared with originals only, so it becomes a new original
    assert len(flags)==1
    assert flags[0][0]['message_id']=='<b>'
    assert flags[0][1]['message_id']=='<a>'


def test_equal_dates_break_ties_by_message_id(maildir, email, run_pipeline):
    root, write=maildir
    same='Mon, 14 May 2001 16:39:00 -0700 (PDT)'
    write('1', email(message_id='<b@test>', date=same, body='The same words in both copies.'))
    write('2', email(message_id='<a@test>', date=same, body='The same words in both copies.'))
    conn=run_pipeline()
    rows=conn.execute('SELECT message_id, is_duplicate, duplicate_of, similarity_score FROM emails ORDER BY message_id').fetchall()
    assert [tuple(r) for r in rows]==[('<a@test>', 0, None, None), ('<b@test>', 1, '<a@test>', 100.0)]


def test_group_of_three_or_more(maildir, email, run_pipeline, tmp_path):
    root, write=maildir
    text='Please send me the signed turbine contract by Friday so we can close.'
    write('1', email(message_id='<3@test>', date='Wed, 16 May 2001 09:00:00 -0700 (PDT)', subject='RE: contract', body=text))
    write('2', email(message_id='<1@test>', date='Mon, 14 May 2001 09:00:00 -0700 (PDT)', subject='contract', body=text))
    write('3', email(message_id='<2@test>', date='Tue, 15 May 2001 09:00:00 -0700 (PDT)', subject='Fwd: contract', body=text+' Thanks'))
    write('4', email(message_id='<other@test>', date='Tue, 15 May 2001 09:00:00 -0700 (PDT)', subject='contract', body='Something else entirely, about lunch.'))
    conn=run_pipeline()
    flagged=conn.execute('SELECT message_id, duplicate_of FROM emails WHERE is_duplicate=1 ORDER BY message_id').fetchall()
    # everything but the earliest is flagged, all pointing at the earliest
    assert [tuple(r) for r in flagged]==[('<2@test>', '<1@test>'), ('<3@test>', '<1@test>')]
    with open(str(tmp_path / 'duplicates_report.csv'), newline='') as f:
        rows=list(csv.reader(f))
    assert rows[0]==['duplicate_message_id', 'original_message_id', 'subject', 'from_address', 'duplicate_date',
                     'original_date', 'similarity_score']
    assert len(rows)==3
    # the live notice for this group is about the latest duplicate
    latest=notifier.latest_per_group(conn)
    assert len(latest)==1
    assert latest[0]['message_id']=='<3@test>'


def test_different_sender_or_subject_never_match(maildir, email, run_pipeline):
    root, write=maildir
    text='Exactly the same text in every one of these emails.'
    write('1', email(message_id='<1@test>', sender='kay.mann@enron.com', subject='a', body=text))
    write('2', email(message_id='<2@test>', sender='ben.jacoby@enron.com', subject='a', body=text))
    write('3', email(message_id='<3@test>', sender='kay.mann@enron.com', subject='b', body=text))
    conn=run_pipeline()
    assert conn.execute('SELECT COUNT(*) FROM emails WHERE is_duplicate=1').fetchone()[0]==0


def test_rerun_recomputes_the_flags(maildir, email, run_pipeline, tmp_path):
    root, write=maildir
    write('1', email(message_id='<1@test>', body='same body'))
    write('2', email(message_id='<2@test>', date='Tue, 15 May 2001 16:39:00 -0700 (PDT)', body='same body'))
    conn=run_pipeline()
    # a stale flag from somewhere else is cleared by the next run
    conn.execute("UPDATE emails SET is_duplicate=1, duplicate_of='<2@test>', similarity_score=1 WHERE message_id='<1@test>'")
    conn.commit()
    dedup.run(conn, str(tmp_path / 'again.csv'))
    rows=conn.execute('SELECT message_id, is_duplicate, duplicate_of FROM emails ORDER BY message_id').fetchall()
    assert [tuple(r) for r in rows]==[('<1@test>', 0, None), ('<2@test>', 1, '<1@test>')]


def test_optimized_matching_agrees_with_plain():
    # groups mixing exact copies, small edits, big edits and very different lengths
    picker=random.Random(42)
    for g in range(60):
        base=random_text(picker.randint(20, 400), g)
        group=[]
        for i in range(picker.randint(2, 9)):
            kind=picker.choice(['copy', 'small', 'big', 'short', 'long'])
            text=base
            if kind=='small':
                spot=picker.randint(0, len(base)-1)
                text=base[:spot]+'XY'+base[spot+1:]
            elif kind=='big':
                text=random_text(len(base), picker.randint(0, 10**6))
            elif kind=='short':
                text=base[:len(base)//2]
            elif kind=='long':
                text=base+base[:len(base)//3]
            date='2001-01-%02dT00:00:00+00:00' % picker.randint(1, 5)
            group.append(fake_email('<%d.%d>' % (g, i), date, text))
        group.sort(key=lambda e: (e['date'], e['message_id']))
        fast=[]
        for duplicate, original, score in dedup.match_group(group, dedup.similarity):
            fast.append((duplicate['message_id'], original['message_id'], score))
        plain=[]
        for duplicate, original, score in dedup.plain_match_group(group):
            plain.append((duplicate['message_id'], original['message_id'], score))
        assert fast==plain
