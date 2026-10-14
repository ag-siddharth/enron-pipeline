# shared helpers: find email files, decode them, split headers from body, fingerprint them
# the selection script, the EDA script and the extractor all use these so their counts match

import hashlib
import os
from email.parser import HeaderParser


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


def parse_headers(header_text):
    """Parse only the header block with the email module."""
    return HeaderParser().parsestr(header_text)


def header_value(headers, name):
    """Return a header as a plain string, or None if the header isn't there."""
    value=headers.get(name)
    if value is None:
        return None
    return str(value)


def collapse_ws(text):
    """Collapse every run of whitespace into one space and trim the ends."""
    return ' '.join(text.split())


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
    header_text, body=split_message(text)
    headers=parse_headers(header_text)
    item={}
    item['raw']=raw
    item['encoding']=encoding
    item['text']=text
    item['header_text']=header_text
    item['headers']=headers
    item['body']=body
    item['fingerprint']=fingerprint(headers, body)
    return item
