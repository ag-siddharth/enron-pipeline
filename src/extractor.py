# task 1: walk the picked mailboxes and turn every raw email file into a dict of fields
# failed files go to error_log.txt as path<TAB>reason; run with python -m src.extractor to see the stats

import argparse
import email
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_tz

from src import common
from src import markers

# the 5 picked mailboxes, see docs/SELECTION.md for why these
MAILBOXES=['sanders-r', 'mann-k', 'sager-e', 'shankman-j', 'fischer-m']

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# python 3.13's parsedate_tz says 0 for an unknown zone or no zone at all, so the zone
# is read here instead. US abbreviations from the spec, in hours from UTC
ZONES={'UT': 0, 'UTC': 0, 'GMT': 0, 'Z': 0, 'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5, 'MST': -7, 'MDT': -6,
       'PST': -8, 'PDT': -7, 'AST': -4, 'ADT': -3, 'AKST': -9, 'AKDT': -8, 'HST': -10}
ZONE_AFTER_TIME=re.compile(r'\d{1,2}:\d{2}(?::\d{2})?\s+([+-]\d{4}|[A-Za-z]+)\b')

FIELDS_TO_COUNT=['message_id', 'date', 'from_address', 'to_addresses', 'subject', 'body', 'source_file',
                 'cc_addresses', 'bcc_addresses', 'x_from', 'x_to', 'x_cc', 'x_bcc', 'x_folder', 'x_origin',
                 'content_type', 'has_attachment', 'forwarded_content', 'quoted_content', 'headings']


def decode_words(value):
    """Decode =?charset?Q?...?= encoded words, leave anything else alone."""
    if '=?' not in value:
        return value
    try:
        return str(make_header(decode_header(value)))
    except Exception as e:
        # a broken encoded word stays as written rather than failing the email
        return value


def display_field(headers, name):
    """An optional display header unfolded and decoded; empty ones become None."""
    value=common.header_value(headers, name)
    if value is None:
        return None
    value=decode_words(common.unfold(value)).strip()
    if value=='':
        return None
    return value


def parse_date(raw):
    """Turn a Date header into UTC ISO 8601; returns (iso, None) or (None, why)."""
    if raw is None or raw.strip()=='':
        return None, 'no Date header'
    parts=parsedate_tz(raw)
    if parts is None:
        return None, 'cannot read the date'
    found=ZONE_AFTER_TIME.search(raw)
    if found is None:
        return None, 'no time zone'
    zone=found.group(1)
    if zone[0]=='+' or zone[0]=='-':
        hours=int(zone[1:3])
        minutes=int(zone[3:5])
        if hours>23 or minutes>59:
            return None, 'bad time zone offset '+zone
        offset=hours*3600+minutes*60
        if zone[0]=='-':
            offset=-offset
    elif zone.upper() in ZONES:
        offset=ZONES[zone.upper()]*3600
    else:
        return None, 'unknown time zone '+zone
    try:
        local=datetime(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5],
                       tzinfo=timezone(timedelta(seconds=offset)))
        return local.astimezone(timezone.utc).isoformat(), None
    except Exception as e:
        return None, 'date out of range'


def is_valid_address(addr):
    """An address needs text on both sides of an @."""
    if '@' not in addr:
        return False
    local, domain=addr.rsplit('@', 1)
    return local!='' and domain!=''


def parse_addresses(value):
    """Address list from a header: unfold, getaddresses, lowercase, drop empty and repeated ones."""
    found=[]
    if value is None:
        return found
    for name, addr in getaddresses([common.unfold(value)]):
        addr=addr.strip().lower()
        # the export sometimes lists one address twice under two display names
        if is_valid_address(addr) and addr not in found:
            found.append(addr)
    return found


def mime_parts(headers, text):
    """For a multipart email, return (plain text of its text parts, attachment names), else (None, [])."""
    content_type=(common.header_value(headers, 'Content-Type') or '').strip().lower()
    if not content_type.startswith('multipart/'):
        return None, []
    message=email.message_from_string(text)
    texts=[]
    names=[]
    for part in message.walk():
        if part.is_multipart():
            continue
        filename=part.get_filename()
        disposition=(part.get('Content-Disposition') or '').strip().lower()
        if filename or disposition.startswith('attachment'):
            names.append(filename or '(attachment with no name)')
            continue
        if part.get_content_type()=='text/plain':
            payload=part.get_payload(decode=True)
            if payload is not None:
                part_text, charset=common.decode_bytes(payload)
                texts.append(common.to_lf(part_text))
    return '\n'.join(texts), names


def split_body(text, subject):
    """Cut the decoded text into the sender's own text, quoted replies and forwarded content."""
    lines=text.split('\n')
    start, kind, marker=markers.find_first_marker(lines)
    if start is None:
        start=len(lines)
    # outlook writes the same Original Message line for forwards, so the subject decides (DECISIONS D2.4)
    if kind=='reply' and markers.FW_SUBJECT.match(subject or ''):
        kind='forward'

    # before the first marker, > lines are sorted out one by one so text written between them stays
    authored=[]
    quoted=[]
    for line in lines[:start]:
        if markers.is_quote_line(line):
            quoted.append(line)
        else:
            authored.append(line)
    block='\n'.join(lines[start:]).strip()

    parts={}
    parts['body']='\n'.join(authored).strip()
    parts['quoted_content']='\n'.join(quoted).strip()
    parts['forwarded_content']=''
    if kind=='forward':
        parts['forwarded_content']=block
    elif kind=='reply':
        if parts['quoted_content']=='':
            parts['quoted_content']=block
        else:
            parts['quoted_content']=parts['quoted_content']+'\n\n'+block
    parts['marker']=marker
    parts['kind']=kind

    # no text of the sender's own: the body falls back to what was forwarded or quoted
    parts['body_basis']='authored'
    if parts['body']=='':
        if parts['forwarded_content']!='':
            parts['body']=parts['forwarded_content']
            parts['body_basis']='forwarded'
        elif parts['quoted_content']!='':
            parts['body']=parts['quoted_content']
            parts['body_basis']='quoted'
    return parts


def find_attachments(headers, mime_names, parts):
    """Return (has_attachment, evidence text) from MIME parts, placeholders and attach words."""
    evidence=[]
    for name in mime_names:
        evidence.append('mime part: '+name)
    # a non-multipart email can still name a file in its own Content-Type or Content-Disposition
    filename=headers.get_filename()
    if filename:
        evidence.append('mime filename: '+filename)
    # forwards carry their attachments and replies drop them, so quoted text doesn't count (D2.7)
    own_text=''
    if parts['body_basis']=='authored':
        own_text=parts['body']
    for text in [own_text, parts['forwarded_content']]:
        for found in markers.file_placeholders(text):
            item='placeholder: '+found
            if item not in evidence:
                evidence.append(item)
    for found in markers.ATTACH_WORD.finditer(own_text):
        item='word: '+found.group(0).lower()
        if item not in evidence:
            evidence.append(item)
    if len(evidence)==0:
        return False, None
    return True, '; '.join(evidence)


def find_headings(text):
    """Every heading line in the decoded text, one per line, without repeats."""
    lines=text.split('\n')
    found=[]
    for i in range(len(lines)):
        if markers.heading_kind(lines, i) is not None:
            heading=lines[i].strip()
            if heading not in found:
                found.append(heading)
    if len(found)==0:
        return None
    return '\n'.join(found)


def mandatory_problems(record, headers):
    """List every mandatory field that is missing, using the reasons from the build prompt."""
    problems=[]
    if record['message_id']=='':
        problems.append('no Message-ID')
    if record['date'] is None:
        problems.append('unparseable Date: '+record['date_problem'])
    if record['from_address'] is None:
        problems.append('no From address')
    if common.header_value(headers, 'To') is None:
        problems.append('no To header')
    elif len(record['to_addresses'])==0:
        problems.append('To has no valid address')
    if common.header_value(headers, 'Subject') is None:
        problems.append('no Subject header')
    if record['raw_text'].strip()=='':
        problems.append('empty message')
    return problems


def parse_file(path, maildir):
    """Parse one file; returns (record, problems, notes). record is None when it failed."""
    notes=[]
    item=common.read_email(path)
    headers=item['headers']
    if item['encoding']!='utf-8':
        notes.append('encoding '+item['encoding'])
    if item['repaired']:
        notes.append('header block repaired')

    # undo quoted-printable or base64 before anything looks at the body (D2.3)
    transfer=common.header_value(headers, 'Content-Transfer-Encoding')
    try:
        text, charset=common.decode_body(item['body'], transfer, item['encoding'])
        if charset is not None:
            notes.append('decoded '+transfer.strip().lower())
    except Exception as e:
        text=item['body']
        notes.append('could not undo '+str(transfer).strip().lower())
    plain, mime_names=mime_parts(headers, item['text'])
    if plain is not None:
        text=plain
        notes.append('multipart')

    record={}
    record['message_id']=(common.header_value(headers, 'Message-ID') or '').strip()
    record['raw_date']=common.header_value(headers, 'Date')
    record['date'], record['date_problem']=parse_date(record['raw_date'])
    senders=parse_addresses(common.header_value(headers, 'From'))
    record['from_address']=None
    if len(senders)>0:
        record['from_address']=senders[0]
    record['to_addresses']=parse_addresses(common.header_value(headers, 'To'))
    record['cc_addresses']=parse_addresses(common.header_value(headers, 'Cc'))
    record['bcc_addresses']=parse_addresses(common.header_value(headers, 'Bcc'))
    subject=common.header_value(headers, 'Subject')
    record['subject']=None
    if subject is not None:
        # exactly as written: unfolded and decoded, nothing stripped or normalized
        record['subject']=decode_words(common.unfold(subject))
    record['normalized_subject']=common.normalize_subject(record['subject'] or '')
    record['source_file']='maildir/'+os.path.relpath(path, maildir).replace(os.sep, '/')
    record['x_from']=display_field(headers, 'X-From')
    record['x_to']=display_field(headers, 'X-To')
    record['x_cc']=display_field(headers, 'X-cc')
    record['x_bcc']=display_field(headers, 'X-bcc')
    record['x_folder']=display_field(headers, 'X-Folder')
    record['x_origin']=display_field(headers, 'X-Origin')
    record['content_type']=display_field(headers, 'Content-Type')

    record['raw_text']=text
    parts=split_body(text, record['subject'])
    record['body']=parts['body']
    record['body_basis']=parts['body_basis']
    record['forwarded_content']=parts['forwarded_content'] or None
    record['quoted_content']=parts['quoted_content'] or None
    record['first_marker']=parts['marker']
    record['has_attachment'], record['attachment_evidence']=find_attachments(headers, mime_names, parts)
    record['headings']=find_headings(text)
    record['fingerprint']=item['fingerprint']

    problems=mandatory_problems(record, headers)
    if len(problems)>0:
        return None, problems, notes
    return record, [], notes


def new_stats():
    """Counters for one extraction run."""
    stats={'files': 0, 'parsed': 0, 'failed': 0, 'reasons': {}, 'notes': {}, 'fields': {}, 'basis': {},
           'markers': {}, 'fallback_files': [], 'earliest': None, 'latest': None}
    for name in FIELDS_TO_COUNT:
        stats['fields'][name]=0
    return stats


def bump(counter, key):
    counter[key]=counter.get(key, 0)+1


def count_record(stats, record):
    """Add one parsed record to the field coverage counts."""
    stats['parsed']+=1
    for name in FIELDS_TO_COUNT:
        value=record[name]
        if value is not None and value!='' and value!=[] and value is not False:
            stats['fields'][name]+=1
    bump(stats['basis'], record['body_basis'])
    bump(stats['markers'], record['first_marker'] or '(no marker)')
    if stats['earliest'] is None or record['date']<stats['earliest']:
        stats['earliest']=record['date']
    if stats['latest'] is None or record['date']>stats['latest']:
        stats['latest']=record['date']


def walk(maildir, mailboxes):
    """Every email file of the mailboxes, sorted, hidden files skipped."""
    paths=[]
    for mailbox in mailboxes:
        folder=os.path.join(maildir, mailbox)
        if not os.path.isdir(folder):
            print('  mailbox not found, skipping:', folder)
            continue
        for path in common.list_email_files(folder):
            paths.append(path)
    return paths


def extract(maildir, mailboxes, error_log, stats):
    """Yield one record per good file; bad files go to error_log as path<TAB>reason."""
    paths=walk(maildir, mailboxes)
    with open(error_log, 'w', encoding='utf-8') as log:
        for path in paths:
            stats['files']+=1
            source='maildir/'+os.path.relpath(path, maildir).replace(os.sep, '/')
            try:
                record, problems, notes=parse_file(path, maildir)
            except Exception as e:
                # never crash on a bad file: log it and move on
                record=None
                problems=['could not parse: '+type(e).__name__+': '+str(e)]
                notes=[]
            for note in notes:
                bump(stats['notes'], note)
                if note.startswith('encoding '):
                    stats['fallback_files'].append(source+' ('+note[9:]+')')
            if record is None:
                stats['failed']+=1
                for problem in problems:
                    bump(stats['reasons'], problem.split(':')[0])
                log.write(source+'\t'+'; '.join(problems)+'\n')
                continue
            count_record(stats, record)
            yield record


def stats_lines(stats):
    """Readable lines for the extraction stats."""
    lines=[]
    lines.append('files found: %d' % stats['files'])
    lines.append('parsed: %d' % stats['parsed'])
    lines.append('failed: %d' % stats['failed'])
    for reason in sorted(stats['reasons']):
        lines.append('  %-28s %d' % (reason, stats['reasons'][reason]))
    lines.append('fallback encodings: %d' % len(stats['fallback_files']))
    for path in stats['fallback_files']:
        lines.append('  '+path)
    for note in sorted(stats['notes']):
        if not note.startswith('encoding '):
            lines.append('%s: %d' % (note, stats['notes'][note]))
    lines.append('field coverage over parsed emails:')
    for name in FIELDS_TO_COUNT:
        share=0.0
        if stats['parsed']>0:
            share=100.0*stats['fields'][name]/stats['parsed']
        lines.append('  %-18s %6d  %5.1f%%' % (name, stats['fields'][name], share))
    lines.append('body_basis:')
    for name in sorted(stats['basis']):
        lines.append('  %-18s %6d' % (name, stats['basis'][name]))
    lines.append('first marker:')
    for name in sorted(stats['markers']):
        lines.append('  %-26s %6d' % (name, stats['markers'][name]))
    lines.append('earliest date: %s' % stats['earliest'])
    lines.append('latest date: %s' % stats['latest'])
    return lines


def main():
    parser=argparse.ArgumentParser(description='extract the picked mailboxes and print the stats')
    parser.add_argument('--maildir', default=os.path.join(ROOT, 'maildir'))
    parser.add_argument('--mailboxes', nargs='*', default=MAILBOXES)
    parser.add_argument('--error-log', default=os.path.join(ROOT, 'error_log.txt'))
    args=parser.parse_args()
    stats=new_stats()
    for record in extract(args.maildir, args.mailboxes, args.error_log, stats):
        pass
    for line in stats_lines(stats):
        print(line)
    print('wrote', args.error_log)


if __name__=='__main__':
    main()
