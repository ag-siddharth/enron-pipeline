# task 1 tests: header parsing, failure reasons, body splitting, attachments, dates, broken files

from src import extractor


def parse(maildir, name, text):
    """Write one fake file and parse it."""
    root, write=maildir
    path=write(name, text)
    return extractor.parse_file(path, root)


def test_x_to_is_never_the_real_to(maildir, email):
    # no real To header, but X-To is filled and the forwarded text has a To: line
    body='FYI\r\n\r\n----- Forwarded by Kay Mann/Corp/Enron on 05/14/2001 04:39 PM -----\r\nTo: someone@enron.com\r\n\r\nold text'
    record, problems, notes=parse(maildir, '1', email(to=None, x_to='Someone Else', body=body))
    assert record is None
    assert problems==['no To header']


def test_real_to_wins_over_x_to(maildir, email):
    record, problems, notes=parse(maildir, '1', email(to='a.person@enron.com', x_to='Somebody Else <other@enron.com>'))
    assert record['to_addresses']==['a.person@enron.com']
    assert record['x_to']=='Somebody Else <other@enron.com>'


def test_folded_to_with_names(maildir, email):
    folded='a@enron.com, B@Enron.com,\r\n\tc@enron.com, "Doe, Jane" <jane.doe@enron.com>,\r\n\ta@enron.com'
    record, problems, notes=parse(maildir, '1', email(to=folded))
    # lowercased, display names dropped, the repeated a@enron.com kept once
    assert record['to_addresses']==['a@enron.com', 'b@enron.com', 'c@enron.com', 'jane.doe@enron.com']


def test_missing_to_is_logged_and_the_run_goes_on(maildir, email, tmp_path, read_file):
    root, write=maildir
    write('1', email(message_id='<good@test>'))
    write('2', email(message_id='<no-to@test>', to=None))
    stats=extractor.new_stats()
    log=str(tmp_path / 'error_log.txt')
    records=list(extractor.extract(root, ['testbox'], log, stats))
    assert len(records)==1
    assert stats['files']==2
    assert stats['failed']==1
    assert read_file(log)=='maildir/testbox/inbox/2\tno To header\n'


def test_to_with_no_valid_address(maildir, email):
    record, problems, notes=parse(maildir, '1', email(to='undisclosed-recipients:;'))
    assert problems==['To has no valid address']


def test_empty_message(maildir, email):
    record, problems, notes=parse(maildir, '1', email(body='   \r\n\r\n'))
    assert problems==['empty message']


def test_every_failing_check_is_named(maildir):
    record, problems, notes=parse(maildir, '1', '')
    assert problems==['no Message-ID', 'unparseable Date: no Date header', 'no From address', 'no To header',
                      'no Subject header', 'empty message']


def test_broken_files_never_crash(maildir, tmp_path):
    root, write=maildir
    write('empty', '')
    write('random', bytes(range(256))*8)
    write('no_headers', 'just some words\nand more words\n')
    write('no_blank_line', 'Message-ID: <x@test>\r\nDate: Mon, 14 May 2001 16:39:00 -0700\r\nFrom: a@enron.com\r\nTo: b@enron.com\r\nSubject: hi\r\n')
    write('.DS_Store', 'hidden files are skipped')
    stats=extractor.new_stats()
    records=list(extractor.extract(root, ['testbox'], str(tmp_path / 'log.txt'), stats))
    assert records==[]
    assert stats['files']==4
    assert stats['failed']==4


def test_dates_go_to_utc():
    assert extractor.parse_date('Mon, 14 May 2001 16:39:00 -0700 (PDT)')==('2001-05-14T23:39:00+00:00', None)
    assert extractor.parse_date('Mon, 14 May 2001 16:39:00 PST')==('2001-05-15T00:39:00+00:00', None)
    assert extractor.parse_date('14 May 01 16:39 CDT')==('2001-05-14T21:39:00+00:00', None)
    # python 3.13 would call these UTC, the extractor fails them
    assert extractor.parse_date('Mon, 14 May 2001 16:39:00 XYZ')==(None, 'unknown time zone XYZ')
    assert extractor.parse_date('Mon, 14 May 2001 16:39:00')==(None, 'no time zone')
    assert extractor.parse_date('garbage')==(None, 'cannot read the date')


def test_encoded_subject_is_decoded_and_kept_as_written(maildir, email):
    record, problems, notes=parse(maildir, '1', email(subject='=?ANSI_X3.4-1968?Q?RE:_Mr_X=3Fs_situation?='))
    assert record['subject']=='RE: Mr X?s situation'
    assert record['normalized_subject']=='mr x?s situation'


def test_outlook_reply_goes_to_quoted(maildir, email):
    body='Sounds good.\r\n\r\n -----Original Message-----\r\nFrom: \tMann, Kay\r\nSent:\tMonday, May 14, 2001 4:39 PM\r\n\r\nShall we meet?'
    record, problems, notes=parse(maildir, '1', email(subject='RE: lunch', body=body))
    assert record['body']=='Sounds good.'
    assert record['body_basis']=='authored'
    assert record['quoted_content'].startswith('-----Original Message-----')
    assert record['forwarded_content'] is None


def test_outlook_forward_goes_to_forwarded(maildir, email):
    body='See below.\r\n\r\n-----Original Message-----\r\nFrom: \tSmith, Bob\r\nSent:\tMonday, May 14, 2001 4:39 PM\r\n\r\nThe numbers.'
    record, problems, notes=parse(maildir, '1', email(subject='FW: numbers', body=body))
    assert record['body']=='See below.'
    assert record['forwarded_content'].endswith('The numbers.')
    assert record['quoted_content'] is None


def test_pure_lotus_forward_falls_back_to_forwarded_text(maildir, email):
    body='---------------------- Forwarded by Kay Mann/Corp/Enron on 05/14/2001 04:39 PM ---------------------------\n\n\nBen Jacoby@ECT\n05/14/2001 02:00 PM\nTo: Kay Mann/Corp/Enron@Enron\ncc: \nSubject: turbines\n\nThe GE turbines ship Friday.'
    record, problems, notes=parse(maildir, '1', email(body=body))
    assert record['body_basis']=='forwarded'
    assert record['body']==record['forwarded_content']
    assert record['body'].endswith('ship Friday.')


def test_lotus_reply_block_cuts_at_the_name_line(maildir, email):
    body='Yes, Friday works.\n\nKay\n\n\n\n\nBen Jacoby@ECT\n05/14/2001 02:00 PM\nTo: Kay Mann/Corp/Enron@Enron\ncc: \nSubject: turbines\n\nCan we talk Friday?'
    record, problems, notes=parse(maildir, '1', email(subject='Re: turbines', body=body))
    assert record['body']=='Yes, Friday works.\n\nKay'
    assert record['quoted_content'].startswith('Ben Jacoby@ECT')


def test_gt_quoting_is_sorted_line_by_line(maildir, email):
    body='> first quoted line\nmy answer to it\n> second quoted line\nmy second answer'
    record, problems, notes=parse(maildir, '1', email(body=body))
    assert record['body']=='my answer to it\nmy second answer'
    assert record['quoted_content']=='> first quoted line\n> second quoted line'


def test_quoted_printable_is_undone_before_splitting(maildir, email):
    body='Thanks=20\r\n\r\n-----Original Message-----=20\r\nFrom: Mann, Kay=20\r\n\r\nA long line that was soft=\r\n wrapped.'
    text=email(body=body).replace('Content-Transfer-Encoding: 7bit', 'Content-Transfer-Encoding: quoted-printable')
    record, problems, notes=parse(maildir, '1', text)
    assert record['body']=='Thanks'
    assert 'soft wrapped.' in record['quoted_content']
    assert 'decoded quoted-printable' in notes


def test_multipart_without_attachment(maildir, email):
    body=('--XYZ\r\nContent-Type: text/plain; charset=us-ascii\r\n\r\nPlain words here.\r\n'
          '--XYZ\r\nContent-Type: text/html\r\n\r\n<p>Plain words here.</p>\r\n--XYZ--\r\n')
    record, problems, notes=parse(maildir, '1', email(body=body, content_type='multipart/alternative; boundary="XYZ"'))
    assert record['body']=='Plain words here.'
    assert record['has_attachment'] is False
    assert record['attachment_evidence'] is None


def test_multipart_with_an_attachment(maildir, email):
    body=('--XYZ\r\nContent-Type: text/plain\r\n\r\nReport below.\r\n'
          '--XYZ\r\nContent-Type: application/pdf; name="report.pdf"\r\nContent-Disposition: attachment; filename="report.pdf"\r\n'
          'Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQK\r\n--XYZ--\r\n')
    record, problems, notes=parse(maildir, '1', email(body=body, content_type='multipart/mixed; boundary="XYZ"'))
    assert record['has_attachment'] is True
    assert 'mime part: report.pdf' in record['attachment_evidence']


def test_attachment_cues_follow_the_rules(maildir, email):
    # a word in the sender's own text counts
    record, problems, notes=parse(maildir, '1', email(body='Please see the attached draft.'))
    assert record['attachment_evidence']=='word: attached'
    # a placeholder only inside a quoted reply does not, and neither does a link placeholder
    body='Thanks.\n\n-----Original Message-----\nFrom: Bob\nSent: today\n\n <<draft.doc>>\n << File: mailto:bob@x.com >>'
    record, problems, notes=parse(maildir, '2', email(subject='RE: draft', body=body))
    assert record['has_attachment'] is False
    # a placeholder in forwarded content does, forwards carry their attachments
    record, problems, notes=parse(maildir, '3', email(subject='FW: draft', body=body.replace('Thanks.', 'Here.')))
    assert record['attachment_evidence']=='placeholder: <<draft.doc>>'


def test_headings(maildir, email):
    body='Hi all,\n\nTABLE OF CONTENTS\n\n1. Overview\n\nThe deal closes Friday.\n\nFYI\n\n3. The agreement reference in 6.7.1\n\nKay'
    record, problems, notes=parse(maildir, '1', email(body=body))
    assert record['headings']=='TABLE OF CONTENTS\n1. Overview'


def test_header_repair_keeps_headers_after_a_broken_subject(maildir):
    text=('Message-ID: <r@test>\r\nDate: Mon, 11 Jun 2001 19:03:04 -0700 (PDT)\r\nFrom: a@enron.com\r\n'
          'Subject: \nStatute of Limitations\r\nTo: b@enron.com\r\nX-Folder: \\Inbox\r\n\r\nbody text')
    record, problems, notes=parse(maildir, '1', text)
    assert record['subject'].strip()=='Statute of Limitations'
    assert record['to_addresses']==['b@enron.com']
    assert record['x_folder']=='\\Inbox'
    assert 'header block repaired' in notes
