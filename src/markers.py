# patterns for reply and forward markers, attachment cues and headings
# shared by scripts/eda.py and src/extractor.py so the EDA numbers describe the real rules

import re

# lines starting with > are quoted line by line, so a marker never counts after a >
OUTLOOK=re.compile(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', re.I)
LOTUS_FWD=re.compile(r'^\s*-{3,}\s*Forwarded by\b', re.I)
# rare forward lines from other mail clients (14 files in the EDA)
OTHER_FWD=re.compile(r'^\s*(-{2,}\s*(Begin )?Forwarded message\s*-{2,}|Begin forwarded message:|-{2,}\s*Inline attachment follows\s*-{2,})', re.I)
# lotus reply headers come in three shapes (see docs/EDA.md)
FROM_DATE=re.compile(r'^\s*From:\s.*\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}', re.I)
NAME_ON_DATE=re.compile(r'^\s*\S.*\son \d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2}(:\d{2})?\s*[AP]M\s*$', re.I)
DATE_LINE=re.compile(r'^\s*\d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2}( ?[AP]M)?\s*$', re.I)
TO_LINE=re.compile(r'^\s*To:', re.I)
# outlook header block that lost its Original Message line
FROM_LINE=re.compile(r'^\s*From:\s', re.I)
SENT_LINE=re.compile(r'^\s*(Sent|Date):\s', re.I)
# outlook uses the same Original Message line for forwards, the subject tells them apart
FW_SUBJECT=re.compile(r'^\s*(fw|fwd)\s*:', re.I)

PLACEHOLDER=re.compile(r'<<[^<>\n]+>>')
# 41 of 7,015 placeholders are links (<< File: mailto:x@y.com >>, <<http://...>>), not files
LINK_PLACEHOLDER=re.compile(r'mailto:|https?:|www\.', re.I)
# attach, attached, attaches, attaching, attachment, attachments (EDA: all six are common enough)
ATTACH_WORD=re.compile(r'\battach(?:ed|es|ing|ment|ments)?\b', re.I)

HEADER_LIKE=re.compile(r'^\s*(from|to|sent|cc|bcc|subject|date)\s*:', re.I)
UNDERLINE=re.compile(r'^\s*(-{3,}|={3,})\s*$')
NUMBERED=re.compile(r'^\s*\d{1,2}(\.\d{1,2})*[.)]\s+')


def file_placeholders(text):
    """Every <<file>> placeholder in the text that names a file rather than a link."""
    found=[]
    for match in PLACEHOLDER.finditer(text):
        if LINK_PLACEHOLDER.search(match.group(0)) is None:
            found.append(match.group(0))
    return found


def is_quote_line(line):
    """True for a > quoted line (column 0 only, indented > is mostly ascii art)."""
    return line.startswith('>')


def lotus_block_start(lines, i):
    """If line i is the date line of a lotus name / date / To: block, return where the block starts."""
    if not DATE_LINE.match(lines[i]):
        return None
    if i==0 or lines[i-1].strip()=='':
        return None
    # the To: line comes 1 to 4 lines below the date (15,789 of 15,978 date lines in the EDA)
    for j in range(1, 5):
        if i+j<len(lines) and TO_LINE.match(lines[i+j]):
            return i-1
    return None


def outlook_block_without_separator(lines, i):
    """True if line i starts a From: / Sent: header pair with no Original Message line."""
    if not FROM_LINE.match(lines[i]):
        return False
    for j in range(1, 3):
        if i+j<len(lines) and SENT_LINE.match(lines[i+j]):
            return True
    return False


def find_first_marker(lines):
    """Find the first reply or forward marker; returns (line index, 'reply' or 'forward', name)."""
    for i in range(len(lines)):
        line=lines[i]
        if is_quote_line(line):
            continue
        if LOTUS_FWD.match(line):
            return i, 'forward', 'lotus_forwarded_by'
        if OTHER_FWD.match(line):
            return i, 'forward', 'other_forward'
        if OUTLOOK.match(line):
            return i, 'reply', 'outlook_original_message'
        if FROM_DATE.match(line):
            return i, 'reply', 'lotus_from_date'
        if NAME_ON_DATE.match(line):
            return i, 'reply', 'lotus_name_on_date'
        start=lotus_block_start(lines, i)
        if start is not None:
            return start, 'reply', 'lotus_name_date_block'
        if outlook_block_without_separator(lines, i):
            return i, 'reply', 'outlook_header_block'
    return None, None, None


def title_case(text):
    """True if every word with 4+ letters starts with a capital."""
    count=0
    for word in text.split():
        letters=re.sub(r'[^A-Za-z]', '', word)
        if len(letters)>=4:
            count+=1
            if not letters[0].isupper():
                return False
    return count>0


def heading_kind(lines, i):
    """Return 'caps', 'numbered' or 'underlined' if line i is a heading, else None."""
    s=lines[i].strip()
    # 60 characters is the limit from the build prompt; header-like lines are quoted email headers
    if s=='' or len(s)>60 or HEADER_LIKE.match(s) or is_quote_line(s):
        return None
    # sentences, attachment names, links and addresses aren't headings
    if s[-1] in '.?!;,' or '<<' in s or 'http' in s.lower() or '@' in s or '/' in s:
        return None
    prev=''
    if i>0:
        prev=lines[i-1].strip()
    nxt=''
    if i+1<len(lines):
        nxt=lines[i+1].strip()
    letters=re.sub(r'[^A-Za-z]', '', s)

    # underlined: blank line above, ---- or ==== right below and about as long as the text
    if prev=='' and UNDERLINE.match(nxt) and len(letters)>=3:
        if abs(len(nxt)-len(s))<=max(3, len(s)//4) and title_case(s) and len(s.split())<=8:
            return 'underlined'

    # the other two kinds must stand alone between blank lines
    above_ok=prev=='' or UNDERLINE.match(prev)
    below_ok=nxt=='' or UNDERLINE.match(nxt)
    if not above_ok or not below_ok:
        return None

    # numbered title like "1. Overview": short and Title Case, unlike a numbered sentence
    if NUMBERED.match(s):
        title=NUMBERED.sub('', s)
        if title[:1].isupper() and title_case(title) and len(title.split())<=8:
            return 'numbered'
        return None

    # all caps: 4+ letters, mostly letters, starts with one, no "label: value", and not
    # a lone short word (FYI and initials like JWVS are the most common all-caps lines)
    nonspace=re.sub(r'\s', '', s)
    if len(letters)>=4 and letters==letters.upper() and s[0].isalpha() and ':' not in s[:-1]:
        if 2*len(letters)>=len(nonspace) and (len(s.split())>=2 or len(letters)>=6):
            return 'caps'
    return None
