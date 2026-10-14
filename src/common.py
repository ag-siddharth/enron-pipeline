# shared helpers: find email files, decode them, split headers from body, fingerprint them
# the selection script, the EDA script and the extractor all use these so their counts match

import base64
import hashlib
import os
import quopri
import re
from email.parser import HeaderParser

# a header line starts with a field name (printable ascii, no spaces or colon) and a colon
HEADER_LINE=re.compile(r'^[!-9;-~]+:')
# re: 16,740, fw: 2,005 and fwd: 242 are the only reply/forward prefixes in the picked mailboxes
SUBJECT_PREFIX=re.compile(r'^\s*(re|fw|fwd)\s*:', re.I)


def list_email_files(folder):
    """Return every non-hidden file under folder, in sorted order."""
    found=[]
    for root, dirs, files in os.walk(folder):
        # skip hidden folders and files like .DS_Store, and walk in a fixed order
        keep=[]
        for d in sorted(dirs):
            if not d.startswith('.'):
                keep.append(d)
        dirs[:]=keep
        for name in sorted(files):
            if not name.startswith('.'):
                found.append(os.path.join(root, name))
    return found


def decode_bytes(raw):
    """Decode file bytes with utf-8, then cp1252, then latin-1, never dropping characters."""
    # strict decoding so nothing gets replaced or dropped; latin-1 maps every byte so it can't fail
    for encoding in ['utf-8', 'cp1252']:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return raw.decode('latin-1'), 'latin-1'


def to_lf(text):
    """Turn CRLF line endings into LF."""
    return text.replace('\r\n', '\n')


def split_message(text):
    """Split LF text into (header block, body) at the first blank line."""
    if text.startswith('\n'):
        # blank first line means there are no headers at all
        return '', text[1:]
    pos=text.find('\n\n')
    if pos==-1:
        # no blank line, so the whole file is the header block
        return text, ''
    return text[:pos+1], text[pos+2:]


def is_stray_line(lines, i):
    """True if line i of a header block is neither a header nor a folded continuation."""
    line=lines[i]
    if line=='':
        return False
    if i>0 and (line[0]==' ' or line[0]=='\t'):
        return False
    return HEADER_LINE.match(line) is None


def more_headers_below(lines, i):
    """True if any line after line i looks like a header."""
    for later in lines[i+1:]:
        if HEADER_LINE.match(later):
            return True
    return False


def repair_headers(header_text, body):
    """Fix stray lines in the header block so the email module doesn't stop early."""
    # sager-e/calendar/34 has a bare line break inside its Subject, and the email module
    # then drops every header after it. a stray line with more headers below it is a broken
    # value, so fold it in. with no headers below it (or on the very first line) the blank
    # line is missing and the body starts there
    if header_text=='':
        return header_text, body
    lines=header_text.split('\n')
    if header_text.endswith('\n'):
        lines=lines[:-1]
    fixed=[]
    for i in range(len(lines)):
        if not is_stray_line(lines, i):
            fixed.append(lines[i])
            continue
        if i>0 and more_headers_below(lines, i):
            fixed.append(' '+lines[i])
            continue
        rest='\n'.join(lines[i:])
        if body=='':
            body=rest
        else:
            body=rest+'\n\n'+body
        break
    new_header_text=''
    if len(fixed)>0:
        new_header_text='\n'.join(fixed)+'\n'
    return new_header_text, body


def parse_headers(header_text):
    """Parse only the header block with the email module."""
    return HeaderParser().parsestr(header_text)


def header_value(headers, name):
    """Return a header as a plain string, or None if the header isn't there."""
    value=headers.get(name)
    if value is None:
        return None
    return str(value)


def unfold(value):
    """Join a folded header value back into one line."""
    # the continuation lines keep their leading space or tab, so dropping the line break is enough
    return value.replace('\n', '')


def decode_body(body, transfer_encoding, file_encoding):
    """Undo quoted-printable or base64 on a body, returns (text, charset used or None)."""
    name=(transfer_encoding or '').strip().lower()
    if name!='quoted-printable' and name!='base64':
        return body, None
    # strict decoding means encoding with the same codec gives back the exact file bytes
    raw=body.encode(file_encoding)
    if name=='quoted-printable':
        decoded=quopri.decodestring(raw)
    else:
        decoded=base64.b64decode(raw)
    text, charset=decode_bytes(decoded)
    return to_lf(text), charset


def collapse_ws(text):
    """Collapse every run of whitespace into one space and trim the ends."""
    return ' '.join(text.split())


def normalize_subject(subject):
    """Strip leading Re:/Fw:/Fwd: over and over (any case or spacing), collapse whitespace, lowercase."""
    text=subject
    while True:
        stripped=SUBJECT_PREFIX.sub('', text, count=1)
        if stripped==text:
            break
        text=stripped
    return collapse_ws(text).lower()


def fingerprint(headers, body):
    """md5 of the raw From, To, Cc, Date and Subject plus the body with whitespace collapsed."""
    # every file has its own Message-ID, so copies of one email can only be matched by content
    parts=[]
    for name in ['From', 'To', 'Cc', 'Date', 'Subject']:
        value=header_value(headers, name)
        if value is None:
            value=''
        parts.append(value)
    parts.append(collapse_ws(body))
    joined='\n'.join(parts)
    return hashlib.md5(joined.encode('utf-8')).hexdigest()


def read_email(path):
    """Read one file and return a dict with its text, headers, body and fingerprint."""
    with open(path, 'rb') as f:
        raw=f.read()
    text, encoding=decode_bytes(raw)
    text=to_lf(text)
    plain_header, plain_body=split_message(text)
    header_text, body=repair_headers(plain_header, plain_body)
    headers=parse_headers(header_text)
    item={}
    item['raw']=raw
    item['encoding']=encoding
    item['text']=text
    item['header_text']=header_text
    item['headers']=headers
    item['body']=body
    item['repaired']=header_text!=plain_header
    item['fingerprint']=fingerprint(headers, body)
    return item
