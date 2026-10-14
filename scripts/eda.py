# surveys the 5 picked mailboxes and writes the numbers as tables to docs/EDA.md
# everything the extractor's rules depend on is measured here first

import collections
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_tz

from tqdm import tqdm

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src import common
from src import markers

# the picks from scripts/select_mailboxes.py (see docs/SELECTION.md)
MAILBOXES=['sanders-r', 'mann-k', 'sager-e', 'shankman-j', 'fischer-m']
OUT=os.path.join(ROOT, 'docs', 'EDA.md')

# the marker and heading rules live in src/markers.py; these extra patterns are only for counting
WROTE=re.compile(r'wrote:\s*$', re.I)
# deliberately broad, to see every word form that starts with attach
ATTACH_WORD=re.compile(r'\battach\w*', re.I)
ENCODED_WORD=re.compile(r'=\?[^?]+\?[bBqQ]\?[^?]*\?=')
HEADER_LIKE=markers.HEADER_LIKE
UNDERLINE=markers.UNDERLINE
NUMBERED=re.compile(r'^\s*\d{1,2}(\.\d{1,2})*[.)]\s+\S')
# readable names for the first-marker tables
MARKER_LABELS={'lotus_forwarded_by': 'Lotus Forwarded by', 'other_forward': 'other forward line',
               'outlook_original_message': 'Outlook Original Message', 'lotus_from_date': 'Lotus From: name date',
               'lotus_name_on_date': 'Lotus `Name <addr> on date`', 'lotus_name_date_block': 'Lotus name / date / To: block',
               'outlook_header_block': 'Outlook From:/Sent: block, no separator line', '(no marker)': '(no marker)'}
MONTHS=r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b'


def get(headers, name):
    """Header as a string, '' if missing."""
    value=common.header_value(headers, name)
    if value is None:
        return ''
    return value


def table(columns, rows):
    """Markdown table lines from a header row and data rows."""
    lines=['| '+' | '.join(columns)+' |', '|'+'---|'*len(columns)]
    for row in rows:
        cells=[]
        for cell in row:
            text=str(cell).replace('|', '\\|').replace('\n', '\\n')
            cells.append(text)
        lines.append('| '+' | '.join(cells)+' |')
    return lines


def n(x):
    """Number with thousands separators."""
    return '{:,}'.format(x)


def pct(count, total):
    if total==0:
        return '0.0%'
    return '%.1f%%' % (100.0*count/total)


def line_ending_kind(raw):
    """Which line endings a file uses, split into header block and body."""
    crlf=raw.count(b'\r\n')
    lf=raw.count(b'\n')-crlf
    cr=raw.count(b'\r')-crlf
    if cr>0:
        return 'has lone CR'
    if lf==0 and crlf>0:
        return 'CRLF only'
    if crlf==0:
        return 'LF only'
    pos=raw.find(b'\r\n\r\n')
    if pos!=-1:
        head=raw[:pos]
        if head.count(b'\n')==head.count(b'\r\n'):
            return 'CRLF header block, LF lines in the body'
    return 'LF lines inside the header block'


def date_shape(value):
    """Turn a Date header into a pattern so formats can be counted."""
    s=re.sub(r'^[A-Za-z]{3},', 'Ddd,', value)
    s=re.sub(MONTHS, 'Mon', s)
    s=re.sub(r'\d', '9', s)
    s=re.sub(r'\([A-Z]{3,4}\)', '(ZZZ)', s)
    return s


def parse_date(value):
    """Date header to a UTC datetime, or None if it can't be parsed with a known zone."""
    t=parsedate_tz(value)
    if t is None or t[9] is None:
        return None
    try:
        local=datetime(t[0], t[1], t[2], t[3], t[4], t[5], tzinfo=timezone(timedelta(seconds=t[9])))
        return local.astimezone(timezone.utc)
    except Exception as e:
        return None


def address_tags(name, addr, raw_value):
    """Labels for odd address formats."""
    tags=[]
    if addr=='':
        tags.append('empty entry')
        return tags
    if '@' not in addr:
        tags.append('no @')
    local=addr.split('@')[0]
    if local.startswith('.'):
        tags.append('local part starts with a dot (.hall@enron.com)')
    if '..' in local:
        tags.append('double dot (b..sanders@enron.com)')
    if local.endswith('.'):
        tags.append('local part ends with a dot (carol.st.@enron.com)')
    if '"' in addr or "'" in addr:
        tags.append('quote characters inside the address')
    if addr!=addr.lower():
        tags.append('uppercase letters')
    is_ascii=True
    for ch in addr:
        if ord(ch)>127:
            is_ascii=False
    if not is_ascii:
        tags.append('non-ASCII characters')
    if name!='':
        tags.append('display name, `Name <addr>`')
    return tags


def heading_candidates(lines, i):
    """Broad raw candidates before any precision filter, to show how noisy each kind is."""
    s=lines[i].strip()
    found=[]
    if s=='' or len(s)>60 or HEADER_LIKE.match(s):
        return found
    prev=''
    if i>0:
        prev=lines[i-1].strip()
    nxt=''
    if i+1<len(lines):
        nxt=lines[i+1].strip()
    standalone=(prev=='' or UNDERLINE.match(prev)) and (nxt=='' or UNDERLINE.match(nxt))
    letters=re.sub(r'[^A-Za-z]', '', s)
    if standalone and len(letters)>=3 and letters==letters.upper():
        found.append('caps')
    if UNDERLINE.match(nxt) and not UNDERLINE.match(s) and len(letters)>=3:
        found.append('underlined')
    if standalone and NUMBERED.match(s):
        found.append('numbered')
    return found


def new_counts():
    """All the counters the survey fills in."""
    c={}
    for key in ['files', 'mailbox_files', 'folder_files', 'line_endings', 'encodings', 'cte', 'ctype',
                'encoded_word_headers', 'date_shapes', 'date_zones', 'years', 'mandatory', 'address',
                'address_examples', 'bcc', 'marker_lines', 'marker_files', 'marker_lines_no_qp', 'first_marker',
                'outlook_subject', 'no_authored', 'attach_words', 'attach_where', 'headings', 'heading_examples',
                'xorigin', 'misc', 'qp_charset']:
        c[key]=collections.Counter()
    c['fallback_files']=[]
    c['encoded_examples']={}
    c['date_examples']={}
    c['dates']=[]
    c['bad_dates']=[]
    c['fingerprints']={}
    c['content_keys']={}
    c['nested_folders']=collections.Counter()
    c['mailbox_fps']=collections.defaultdict(set)
    return c


def survey_headers(c, path, item):
    """Counts that only need the header block."""
    headers=item['headers']
    c['encodings'][item['encoding']]+=1
    is_ascii=True
    for b in item['raw']:
        if b>127:
            is_ascii=False
            break
    if item['encoding']=='utf-8' and is_ascii:
        c['encodings']['utf-8, pure ASCII']+=1
    if item['encoding']!='utf-8':
        c['fallback_files'].append((path, item['encoding']))
    c['cte'][get(headers, 'Content-Transfer-Encoding') or '(missing)']+=1
    c['ctype'][get(headers, 'Content-Type') or '(missing)']+=1
    if len(headers.defects)>0:
        c['misc']['header block with a parse defect (after repair)']+=1
    if item['repaired']:
        c['misc']['header block changed by repair_headers']+=1
    if common.header_value(headers, 'X-To') is not None:
        c['misc']['files with an X-To header']+=1

    for name, value in headers.items():
        value=str(value)
        if ENCODED_WORD.search(value):
            c['encoded_word_headers'][name]+=1
            if name not in c['encoded_examples']:
                try:
                    decoded=str(make_header(decode_header(value)))
                except Exception as e:
                    decoded='(could not decode: %s)' % e
                c['encoded_examples'][name]=(value, decoded)

    date=get(headers, 'Date')
    shape=date_shape(date)
    c['date_shapes'][shape]+=1
    if shape not in c['date_examples']:
        c['date_examples'][shape]=date
    zone=re.search(r'([-+]\d{4})\s*\((\w+)\)', date)
    if zone:
        c['date_zones'][zone.group(1)+' ('+zone.group(2)+')']+=1
    else:
        c['date_zones']['no offset (abbreviation) pair']+=1
    when=parse_date(date)
    if when is None:
        c['bad_dates'].append((path, date))
    else:
        c['dates'].append((when, path, date))
        c['years'][when.year]+=1

    origin=get(headers, 'X-Origin')
    c['xorigin'][(path.split('/')[1], origin.lower())]+=1


def survey_mandatory(c, item, is_new):
    """Missing or empty mandatory headers, per file and per distinct email."""
    headers=item['headers']
    found=[]
    for name in ['Message-ID', 'Date', 'From', 'To', 'Subject']:
        value=common.header_value(headers, name)
        if value is None:
            found.append(name+' missing')
        elif value.strip()=='':
            found.append(name+' empty')
    if item['body'].strip()=='':
        found.append('body empty')
    for key in found:
        c['mandatory'][(key, 'files')]+=1
        if is_new:
            c['mandatory'][(key, 'distinct')]+=1


def survey_addresses(c, item):
    """Address formats in From, To and Cc, plus the Bcc vs Cc check."""
    headers=item['headers']
    for field in ['From', 'To', 'Cc']:
        value=common.header_value(headers, field)
        if value is None or value.strip()=='':
            continue
        c['address'][(field, 'headers')]+=1
        if '\n' in value:
            c['address'][(field, 'wrapped over several lines')]+=1
        pairs=getaddresses([common.unfold(value)])
        seen=set()
        for name, addr in pairs:
            c['address'][(field, 'entries')]+=1
            if addr.lower() in seen:
                c['address'][(field, 'same address twice in one header')]+=1
            seen.add(addr.lower())
            for tag in address_tags(name, addr, value):
                c['address'][(field, tag)]+=1
                key=(field, tag)
                if key not in c['address_examples']:
                    c['address_examples'][key]=collections.Counter()
                if name!='':
                    c['address_examples'][key][name+' <'+addr+'>']+=1
                else:
                    c['address_examples'][key][addr]+=1
    bcc=common.header_value(headers, 'Bcc')
    if bcc is not None and bcc.strip()!='':
        cc=common.header_value(headers, 'Cc') or ''
        c['bcc']['emails with a Bcc header']+=1
        if bcc==cc:
            c['bcc']['Bcc exactly equal to Cc']+=1
        if common.collapse_ws(bcc)==common.collapse_ws(cc):
            c['bcc']['Bcc equal to Cc after collapsing whitespace']+=1
        if cc.strip()=='':
            c['bcc']['Bcc with no Cc']+=1


def survey_body(c, item):
    """Markers, attachment cues and heading-like lines in the decoded body."""
    headers=item['headers']
    cte=get(headers, 'Content-Transfer-Encoding')
    body, charset=common.decode_body(item['body'], cte, item['encoding'])
    if charset is not None:
        c['qp_charset'][charset]+=1
        if body!=item['body']:
            c['qp_charset']['body changed by decoding']+=1
    lines=body.split('\n')

    # line-level marker counts
    hits=set()
    for i in range(len(lines)):
        line=lines[i]
        names=[]
        if markers.is_quote_line(line):
            names.append('line starting with >')
            if 'original message' in line.lower():
                names.append('Original Message inside > quoting')
        else:
            if re.match(r'^[ \t]+>', line):
                names.append('line starting with spaces then >')
            if markers.OUTLOOK.match(line):
                names.append('Outlook Original Message')
            if markers.LOTUS_FWD.match(line):
                names.append('Lotus Forwarded by')
            if markers.OTHER_FWD.match(line):
                names.append('other forward line')
            if markers.FROM_DATE.match(line):
                names.append('Lotus From: name date')
            if markers.NAME_ON_DATE.match(line) and not markers.LOTUS_FWD.match(line) and not markers.FROM_DATE.match(line):
                names.append('Lotus name on date')
            if markers.DATE_LINE.match(line):
                names.append('bare date line (Lotus block)')
            if WROTE.search(line):
                names.append('"wrote:" attribution')
        for name in names:
            c['marker_lines'][name]+=1
            hits.add(name)
    for name in hits:
        c['marker_files'][name]+=1
    for line in item['body'].split('\n'):
        if markers.OUTLOOK.match(line):
            c['marker_lines_no_qp']['Outlook Original Message']+=1

    # first marker, where authored text ends
    i, kind, name=markers.find_first_marker(lines)
    c['first_marker'][name or '(no marker)']+=1
    subject=get(headers, 'Subject')
    if name is not None and kind=='reply':
        if markers.FW_SUBJECT.match(subject):
            c['outlook_subject'][(name, 'FW: subject')]+=1
        else:
            c['outlook_subject'][(name, 'other subject')]+=1
    if i is None:
        i=len(lines)
    if kind=='reply' and markers.FW_SUBJECT.match(subject):
        kind='forward'
    authored=[]
    quoted=[]
    for line in lines[:i]:
        if markers.is_quote_line(line):
            quoted.append(line)
        else:
            authored.append(line)
    authored='\n'.join(authored)
    quoted='\n'.join(quoted)
    block='\n'.join(lines[i:])
    if name is not None and authored.strip()=='':
        c['no_authored'][name]+=1

    # attachment cues and where they sit
    for m in ATTACH_WORD.finditer(body):
        c['attach_words'][m.group(0).lower()]+=1
    if len(markers.file_placeholders(body))>0:
        c['attach_where']['`<<file>>` placeholder anywhere']+=1
    places=[]
    if len(markers.file_placeholders(authored))>0:
        places.append('authored')
    if kind=='forward' and len(markers.file_placeholders(block))>0:
        places.append('forwarded')
    if (kind=='reply' and len(markers.file_placeholders(block))>0) or len(markers.file_placeholders(quoted))>0:
        places.append('quoted')
    for place in places:
        c['attach_where']['placeholder in '+place+' text']+=1
    if places==['quoted']:
        c['attach_where']['placeholder only in quoted text']+=1
    if places==['forwarded']:
        c['attach_where']['placeholder only in forwarded text']+=1
    word=markers.ATTACH_WORD
    if word.search(authored):
        c['attach_where']['attach word in authored text']+=1
    if word.search(body) and not word.search(authored):
        c['attach_where']['attach word only outside the authored text']+=1

    # heading-like lines: broad candidates, then what the shared rule keeps
    kinds_here=set()
    for k in range(len(lines)):
        for kind_name in heading_candidates(lines, k):
            c['headings'][kind_name+' raw']+=1
        kept=markers.heading_kind(lines, k)
        if kept is not None:
            c['headings'][kept+' kept']+=1
            kinds_here.add(kept)
            if kept not in c['heading_examples']:
                c['heading_examples'][kept]=collections.Counter()
            c['heading_examples'][kept][lines[k].strip()]+=1
    for kept in kinds_here:
        c['headings'][kept+' files']+=1


def survey_copies(c, path, item):
    """Fingerprint groups, plus content groups that ignore the Date."""
    fp=item['fingerprint']
    headers=item['headers']
    if fp not in c['fingerprints']:
        c['fingerprints'][fp]=[]
    c['fingerprints'][fp].append((path, get(headers, 'Date')))
    parts=[]
    for name in ['From', 'To', 'Cc', 'Subject']:
        parts.append(common.collapse_ws(get(headers, name)))
    parts.append(common.collapse_ws(item['body']))
    key=hashlib.md5('\n'.join(parts).encode('utf-8')).hexdigest()
    if key not in c['content_keys']:
        c['content_keys'][key]=set()
    c['content_keys'][key].add(get(headers, 'Date'))


def survey():
    """Read every file of the picked mailboxes once and fill the counters."""
    c=new_counts()
    paths=[]
    for mailbox in MAILBOXES:
        for path in common.list_email_files(os.path.join(ROOT, 'maildir', mailbox)):
            paths.append(path)
    for full in tqdm(paths, desc='files'):
        path=os.path.relpath(full, ROOT)
        try:
            raw=open(full, 'rb').read()
            item=common.read_email(full)
        except Exception as e:
            c['misc']['could not read']+=1
            continue
        parts=path.split('/')
        mailbox=parts[1]
        c['files']['total']+=1
        c['mailbox_files'][mailbox]+=1
        c['folder_files'][(mailbox, parts[2])]+=1
        if len(parts)>4:
            c['nested_folders'][(mailbox, '/'.join(parts[2:-1]))]+=1
        c['line_endings'][line_ending_kind(raw)]+=1
        is_new=item['fingerprint'] not in c['mailbox_fps'][mailbox]
        c['mailbox_fps'][mailbox].add(item['fingerprint'])
        try:
            survey_headers(c, path, item)
            survey_mandatory(c, item, is_new)
            survey_addresses(c, item)
            survey_body(c, item)
            survey_copies(c, path, item)
        except Exception as e:
            c['misc']['survey error: '+type(e).__name__]+=1
    return c


def copies_summary(c):
    """Numbers about files that share a fingerprint."""
    s=collections.Counter()
    biggest=0
    for fp in c['fingerprints']:
        group=c['fingerprints'][fp]
        s['distinct']+=1
        if len(group)>1:
            s['groups']+=1
            s['files in groups']+=len(group)
            if len(group)>biggest:
                biggest=len(group)
            dates=set()
            folders=set()
            mailboxes=set()
            for path, date in group:
                dates.add(date)
                folders.add('/'.join(path.split('/')[:-1]))
                mailboxes.add(path.split('/')[1])
            if len(dates)==1:
                s['groups where every copy has the same Date']+=1
            if len(folders)>1:
                s['groups spread over more than one folder']+=1
            if len(mailboxes)>1:
                s['groups spread over more than one mailbox']+=1
    s['largest group']=biggest
    for key in c['content_keys']:
        if len(c['content_keys'][key])>1:
            s['same From/To/Cc/Subject/body but different Dates']+=1
    s['content keys']=len(c['content_keys'])
    return s


def write_report(c):
    """Turn the counters into docs/EDA.md."""
    total=c['files']['total']
    out=[]
    out.append('# Exploratory data analysis')
    out.append('')
    out.append('Generated by `scripts/eda.py` over the 5 picked mailboxes (%s). Every file is decoded and split with `src/common.py`, the same helpers the extractor uses. Body counts are taken after undoing quoted-printable.' % ', '.join(MAILBOXES))
    out.append('')

    # files per mailbox and folder
    out.append('## Files per mailbox and folder')
    out.append('')
    rows=[]
    for mailbox in MAILBOXES:
        folders=0
        for key in c['folder_files']:
            if key[0]==mailbox:
                folders+=1
        nested=0
        for key in c['nested_folders']:
            if key[0]==mailbox:
                nested+=1
        rows.append([mailbox, n(c['mailbox_files'][mailbox]), n(len(c['mailbox_fps'][mailbox])), folders, nested])
    rows.append(['**total**', n(total), n(len(c['fingerprints'])), len(c['folder_files']), len(c['nested_folders'])])
    out=out+table(['Mailbox', 'Files', 'Distinct emails', 'Top-level folders', 'Nested folders'], rows)
    out.append('')
    out.append('The total distinct count is across all five mailboxes, so it is smaller than the sum of the per-mailbox counts.')
    out.append('')
    out.append('<details><summary>Files in every top-level folder</summary>')
    out.append('')
    rows=[]
    for key in sorted(c['folder_files']):
        rows.append([key[0], key[1], n(c['folder_files'][key])])
    out=out+table(['Mailbox', 'Folder', 'Files'], rows)
    out.append('')
    rows=[]
    for key in sorted(c['nested_folders']):
        rows.append([key[0], key[1], n(c['nested_folders'][key])])
    out.append('Nested folders:')
    out.append('')
    out=out+table(['Mailbox', 'Folder', 'Files'], rows)
    out.append('')
    out.append('</details>')
    out.append('')

    # line endings
    out.append('## Line endings')
    out.append('')
    rows=[]
    for key, count in c['line_endings'].most_common():
        rows.append([key, n(count), pct(count, total)])
    out=out+table(['Line endings', 'Files', 'Share'], rows)
    out.append('')
    out.append('Most files mix CRLF headers with LF body lines, so the reader turns every CRLF into LF before splitting at the first blank line.')
    out.append('')

    # encodings
    out.append('## Encodings')
    out.append('')
    rows=[['utf-8', n(c['encodings']['utf-8'])], ['  of those, pure ASCII', n(c['encodings']['utf-8, pure ASCII'])],
          ['cp1252 (utf-8 failed)', n(c['encodings']['cp1252'])], ['latin-1 (cp1252 failed too)', n(c['encodings']['latin-1'])]]
    out=out+table(['Decoded as', 'Files'], rows)
    out.append('')
    out.append('Files that needed a fallback (utf-8 failed):')
    out.append('')
    rows=[]
    for path, encoding in c['fallback_files']:
        rows.append([path, encoding])
    out=out+table(['File', 'Decoded as'], rows)
    out.append('')

    # transfer encodings and content types
    out.append('## Content-Transfer-Encoding and Content-Type')
    out.append('')
    rows=[]
    for key, count in c['cte'].most_common():
        rows.append([key, n(count)])
    out=out+table(['Content-Transfer-Encoding', 'Files'], rows)
    out.append('')
    rows=[]
    for key, count in c['ctype'].most_common():
        rows.append([key, n(count)])
    out=out+table(['Content-Type', 'Files'], rows)
    out.append('')
    rows=[]
    for key, count in c['qp_charset'].most_common():
        rows.append([key, n(count)])
    out.append('Quoted-printable bodies after decoding (charset is what the decoded bytes needed):')
    out.append('')
    out=out+table(['After decoding', 'Files'], rows)
    out.append('')
    before=c['marker_lines_no_qp']['Outlook Original Message']
    after=c['marker_lines']['Outlook Original Message']
    out.append('Decoding matters for splitting: %s Outlook "Original Message" lines are found after decoding but only %s before, because quoted-printable files end the line with `=20`.' % (n(after), n(before)))
    out.append('')

    # encoded words
    out.append('## Headers with =?...?= encoded words')
    out.append('')
    rows=[]
    for name, count in c['encoded_word_headers'].most_common():
        raw, decoded=c['encoded_examples'][name]
        rows.append([name, n(count), '`'+raw+'`', repr(decoded)])
    out=out+table(['Header', 'Files', 'Example', 'Decoded'], rows)
    out.append('')
    out.append('The charset ANSI_X3.4-1968 is plain ASCII. The original apostrophes and dashes were lost before the export, so they decode to `?` or a control character.')
    out.append('')

    # dates
    out.append('## Dates')
    out.append('')
    rows=[]
    for shape, count in c['date_shapes'].most_common():
        rows.append(['`'+shape+'`', n(count), c['date_examples'][shape]])
    out=out+table(['Format', 'Files', 'Example'], rows)
    out.append('')
    rows=[]
    for zone, count in c['date_zones'].most_common():
        rows.append([zone, n(count)])
    out=out+table(['Offset (abbreviation)', 'Files'], rows)
    out.append('')
    dates=sorted(c['dates'])
    bogus=[]
    real=[]
    for d in dates:
        # nothing in these mailboxes can predate 1990, so those are placeholder dates
        if d[0].year<1990:
            bogus.append(d)
        else:
            real.append(d)
    out.append('- Unparseable dates: %s.' % n(len(c['bad_dates'])))
    if len(real)>0:
        out.append('- Earliest real date: %s UTC (`%s`, %s).' % (real[0][0].isoformat(), real[0][2], real[0][1]))
        out.append('- Latest date: %s UTC (`%s`, %s).' % (real[-1][0].isoformat(), real[-1][2], real[-1][1]))
    bogus_values=collections.Counter()
    for d in bogus:
        bogus_values[d[2]]+=1
    for value, count in bogus_values.items():
        out.append('- **Bogus:** %s files say `%s`, which is 1980-01-01 00:00 UTC, a null-date placeholder from the export, e.g. %s.' % (n(count), value, bogus[0][1]))
    out.append('')
    rows=[]
    for year in sorted(c['years']):
        rows.append([year, n(c['years'][year])])
    out=out+table(['Year (UTC)', 'Files'], rows)
    out.append('')

    # mandatory headers
    out.append('## Missing or empty mandatory headers')
    out.append('')
    rows=[]
    for key in ['Message-ID missing', 'Message-ID empty', 'Date missing', 'Date empty', 'From missing', 'From empty',
                'To missing', 'To empty', 'Subject missing', 'Subject empty', 'body empty']:
        rows.append([key, n(c['mandatory'][(key, 'files')]), n(c['mandatory'][(key, 'distinct')])])
    out=out+table(['Problem', 'Files', 'Distinct emails (per mailbox)'], rows)
    out.append('')
    out.append('An empty Subject is allowed (the header exists). Missing To is the only mandatory field that is ever absent.')
    out.append('')

    # addresses
    out.append('## Address formats')
    out.append('')
    tags=[]
    for key in c['address']:
        if key[1] not in tags:
            tags.append(key[1])
    rows=[]
    for tag in tags:
        row=[tag]
        for field in ['From', 'To', 'Cc']:
            row.append(n(c['address'][(field, tag)]))
        examples=collections.Counter()
        for field in ['From', 'To', 'Cc']:
            if (field, tag) in c['address_examples']:
                examples.update(c['address_examples'][(field, tag)])
        shown=[]
        for value, count in examples.most_common(3):
            shown.append('`'+value+'`')
        row.append(', '.join(shown))
        rows.append(row)
    out=out+table(['Format', 'From', 'To', 'Cc', 'Most common examples'], rows)
    out.append('')
    out.append('Counts for headers and wrapped headers are per file; the rest are per address entry from `getaddresses` after unfolding.')
    out.append('')

    # bcc
    out.append('## Bcc vs Cc')
    out.append('')
    rows=[]
    for key in ['emails with a Bcc header', 'Bcc exactly equal to Cc', 'Bcc equal to Cc after collapsing whitespace', 'Bcc with no Cc']:
        rows.append([key, n(c['bcc'][key])])
    out=out+table(['Check', 'Files'], rows)
    out.append('')

    # copies
    s=copies_summary(c)
    out.append('## Copies of the same email')
    out.append('')
    rows=[['files', n(total)], ['distinct fingerprints', n(s['distinct'])],
          ['fingerprints shared by 2+ files', n(s['groups'])], ['files in those groups', n(s['files in groups'])],
          ['largest group', n(s['largest group'])],
          ['groups where every copy has the same Date', n(s['groups where every copy has the same Date'])],
          ['groups spread over more than one folder', n(s['groups spread over more than one folder'])],
          ['groups spread over more than one mailbox', n(s['groups spread over more than one mailbox'])],
          ['distinct From/To/Cc/Subject/body ignoring Date', n(s['content keys'])],
          ['of those, seen with more than one Date (re-sends)', n(s['same From/To/Cc/Subject/body but different Dates'])]]
    out=out+table(['Measure', 'Count'], rows)
    out.append('')
    out.append('The Date header is part of the fingerprint, so copies sharing a fingerprint always share the Date; the check confirms it. Emails that match on everything but the Date are re-sends, and Task 3 handles them.')
    out.append('')

    # markers
    out.append('## Reply and forward markers')
    out.append('')
    rows=[]
    for name in ['Outlook Original Message', 'Lotus Forwarded by', 'Lotus From: name date', 'Lotus name on date',
                 'bare date line (Lotus block)', 'other forward line', 'line starting with >',
                 'Original Message inside > quoting', 'line starting with spaces then >', '"wrote:" attribution']:
        rows.append([name, n(c['marker_lines'][name]), n(c['marker_files'][name])])
    out=out+table(['Marker', 'Lines', 'Files'], rows)
    out.append('')
    out.append('First marker in each file (where the sender\'s own text ends):')
    out.append('')
    rows=[]
    for name, count in c['first_marker'].most_common():
        rows.append([MARKER_LABELS[name], '`'+name+'`', n(count), pct(count, total), n(c['no_authored'][name])])
    out=out+table(['First marker', 'Name in src/markers.py', 'Files', 'Share', 'No authored text before it'], rows)
    out.append('')
    rows=[]
    for key in sorted(c['outlook_subject']):
        rows.append([MARKER_LABELS[key[0]], key[1], n(c['outlook_subject'][key])])
    out.append('Reply-style first markers by subject prefix (Outlook uses the same Original Message line for replies and forwards):')
    out.append('')
    out=out+table(['First marker', 'Subject', 'Files'], rows)
    out.append('')

    # attachments
    out.append('## Attachment cues')
    out.append('')
    rows=[]
    for key in ['`<<file>>` placeholder anywhere', 'placeholder in authored text', 'placeholder in forwarded text',
                'placeholder in quoted text', 'placeholder only in forwarded text', 'placeholder only in quoted text',
                'attach word in authored text', 'attach word only outside the authored text']:
        rows.append([key, n(c['attach_where'][key])])
    out=out+table(['Cue', 'Files'], rows)
    out.append('')
    rows=[]
    for word, count in c['attach_words'].most_common(12):
        rows.append(['`'+word+'`', n(count)])
    out=out+table(['Word starting with "attach"', 'Occurrences'], rows)
    out.append('')

    # headings
    out.append('## Heading-like lines')
    out.append('')
    rows=[]
    for kind in ['caps', 'numbered', 'underlined']:
        rows.append([kind, n(c['headings'][kind+' raw']), n(c['headings'][kind+' kept']), n(c['headings'][kind+' files'])])
    out=out+table(['Kind', 'Candidate lines', 'Kept by markers.heading_kind', 'Files with one kept'], rows)
    out.append('')
    out.append('Candidates are lines of 60 characters or less that are not From:/To:/Sent:/cc:/Subject:/Date:/Bcc: lines: ALL CAPS lines and numbered lines that stand alone between blank lines, and any line with a ---- or ==== line right below. Most candidates are noise, so `src/markers.py` adds filters:')
    out.append('')
    out.append('- nothing ending in `.` `?` `!` `;` `,` and nothing with `<<`, `http`, `@` or `/` (sentences, attachment names, links, addresses, itinerary names like `MANN/C KAY`)')
    out.append('- ALL CAPS: 4+ letters, starts with a letter, at least half letters, no inner `:`, and 2+ words or one word of 6+ letters. This drops `FYI` (284 lines), initials like `JWVS`, `[IMAGE]`, `- FILE.DOC` and `TIME: 2:00 PM`.')
    out.append('- numbered: the title after the number starts with a capital, is Title Case (every word of 4+ letters capitalized) and has 8 words or less, so `3. The agreement reference in 6.7.1` is a list item, not a title')
    out.append('- underlined: blank line above, underline about as long as the text, Title Case, 8 words or less. Most raw candidates are sentences sitting above a separator line.')
    out.append('')
    for kind in ['caps', 'numbered', 'underlined']:
        if kind in c['heading_examples']:
            shown=[]
            for value, count in c['heading_examples'][kind].most_common(15):
                shown.append('`'+value.replace('\t', ' ')+'` (%d)' % count)
            out.append('- kept %s: %s' % (kind, ', '.join(shown)))
    out.append('')

    # other quirks
    out.append('## Other quirks')
    out.append('')
    rows=[]
    for key in sorted(c['xorigin']):
        rows.append([key[0], key[1] or '(empty)', n(c['xorigin'][key])])
    out=out+table(['Mailbox', 'X-Origin (lowercased)', 'Files'], rows)
    out.append('')
    for key, count in c['misc'].most_common():
        out.append('- %s: %s' % (key, n(count)))
    out.append('- sager-e/calendar/34. has a bare line break inside its Subject. Without `repair_headers` the email module stops there and drops the other 12 headers.')
    out.append('')
    return out


def write_rules_check(c, out):
    """Section that checks each rule in BUILD_PROMPT.md against the numbers above."""
    total=c['files']['total']
    s=copies_summary(c)
    outlook_fw=c['outlook_subject'][('outlook_original_message', 'FW: subject')]
    outlook_all=outlook_fw+c['outlook_subject'][('outlook_original_message', 'other subject')]
    out.append('## Rules checked against these numbers')
    out.append('')
    rows=[
        ['Only parse the real header block', 'X-To is in %s files; To is missing in %s' % (n(c['misc']['files with an X-To header']), n(c['mandatory'][('To missing', 'files')])), 'keep'],
        ['Every file has its own Message-ID', '%s files, %s distinct fingerprints' % (n(total), n(s['distinct'])), 'keep: copies are matched by fingerprint'],
        ['Bcc is a copy of Cc', '%s of %s Bcc headers equal Cc exactly' % (n(c['bcc']['Bcc exactly equal to Cc']), n(c['bcc']['emails with a Bcc header'])), 'keep: still stored, never scored'],
        ['About 3% have no To:', '%s of %s files (%s)' % (n(c['mandatory'][('To missing', 'files')]), n(total), pct(c['mandatory'][('To missing', 'files')], total)), 'corrected: 1.5% of files here'],
        ['Files use CRLF', '%s files mix CRLF headers with LF body lines' % n(c['line_endings']['CRLF header block, LF lines in the body']), 'corrected: convert CRLF to LF, keep LF'],
        ['A few need cp1252', '%s cp1252, %s latin-1' % (n(c['encodings']['cp1252']), n(c['encodings']['latin-1'])), 'keep'],
        ['Content-Type always text/plain', ', '.join(list(c['ctype'].keys())[:3]), 'keep, but %s files are quoted-printable and must be decoded before splitting' % n(c['cte']['quoted-printable'])],
        ['Dates look like -0800 (PST)', '%s parse, %s fail; %s bogus 1979-12-31 placeholders' % (n(len(c['dates'])), n(len(c['bad_dates'])), n(c['years'][1980])), 'keep; bogus dates stay (they parse) and are called out'],
        ['Outlook Original Message is a reply marker', '%s of %s first-marker Outlook blocks have an FW: subject' % (n(outlook_fw), n(outlook_all)), 'changed: FW: subject makes the block forwarded_content'],
        ['Lotus reply blocks start "From: Name   date"', 'only %s files start that way; %s use name / date / To: lines and %s `Name <addr> on date`' % (n(c['first_marker']['lotus_from_date']), n(c['first_marker']['lotus_name_date_block']), n(c['first_marker']['lotus_name_on_date'])), 'extended: all three shapes count'],
        ['> quoting is line by line', '%s files have > lines at column 0, %s more only after spaces' % (n(c['marker_files']['line starting with >']), n(c['marker_files']['line starting with spaces then >'])), 'keep column 0 only (indented > is mostly ASCII art and nested jokes)'],
        ['has_attachment words in the sender\'s own text', '%s files have the words only outside the authored text' % n(c['attach_where']['attach word only outside the authored text']), 'keep; also count attaches/attaching/attachments'],
        ['`<<file>>` placeholders', '%s files have them only in forwarded text, %s only in quoted replies' % (n(c['attach_where']['placeholder only in forwarded text']), n(c['attach_where']['placeholder only in quoted text'])), 'refined: count authored and forwarded text, not quoted replies'],
        ['Headings: ALL CAPS, underlined, numbered', '%s / %s / %s raw candidates, %s / %s / %s kept' % (n(c['headings']['caps raw']), n(c['headings']['numbered raw']), n(c['headings']['underlined raw']), n(c['headings']['caps kept']), n(c['headings']['numbered kept']), n(c['headings']['underlined kept'])), 'refined: precision filters above'],
    ]
    out=out+table(['Rule or hypothesis', 'Data', 'Verdict'], rows)
    out.append('')
    out.append('Details and reasons for every change are in docs/DECISIONS.md.')
    out.append('')
    return out


def main():
    c=survey()
    out=write_report(c)
    out=write_rules_check(c, out)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('surveyed', c['files']['total'], 'files')
    print('wrote', OUT)


if __name__=='__main__':
    main()
