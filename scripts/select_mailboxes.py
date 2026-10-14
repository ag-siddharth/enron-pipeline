# scans all 150 mailboxes, scores each one on how well it exercises the parser, and picks the subset
# writes output/selection_manifest.csv with every mailbox, its numbers and why it was or wasn't picked

import csv
import os
import re
import sys

from tqdm import tqdm

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src import common

MAILDIR=os.path.join(ROOT, 'maildir')
MANIFEST=os.path.join(ROOT, 'output', 'selection_manifest.csv')

# rule 1: most emails must parse, and tiny mailboxes don't show enough variety
MIN_MANDATORY_PCT=90
MIN_DISTINCT=500
# rule 2: every parser feature needs real data to prove it works
MIN_FEATURE_PCT=5
# rule 5: the spec wants 10,000 emails, 12,000 leaves headroom for failed parses, the cap keeps runs fast
MIN_MAILBOXES=5
MIN_TOTAL=12000
MAX_TOTAL=20000

FEATURES=['cc', 'forwarded', 'quoted', 'attachment']
MANDATORY_CHECKS=['no_message_id', 'no_date', 'no_from', 'no_to', 'no_subject_header', 'empty_body']
LOW_PRIORITY=['X-From', 'X-To', 'X-Folder', 'X-Origin', 'Content-Type']

QUOTE_LINE=re.compile(r'^>', re.M)
PLACEHOLDER=re.compile(r'<<[^<>\n]+>>')


def filled(headers, name):
    """True if the header is there and not just whitespace."""
    value=common.header_value(headers, name)
    return value is not None and value.strip()!=''


def mandatory_problems(headers, body):
    """List which mandatory checks fail for one email."""
    problems=[]
    if not filled(headers, 'Message-ID'):
        problems.append('no_message_id')
    if not filled(headers, 'Date'):
        problems.append('no_date')
    if not filled(headers, 'From'):
        problems.append('no_from')
    if not filled(headers, 'To'):
        problems.append('no_to')
    # the subject may be empty, it just has to exist
    if common.header_value(headers, 'Subject') is None:
        problems.append('no_subject_header')
    if body.strip()=='':
        problems.append('empty_body')
    return problems


def feature_flags(headers, body):
    """Which of the four parser features one email has."""
    lower=body.lower()
    flags={}
    flags['cc']=filled(headers, 'Cc')
    flags['forwarded']='forwarded by' in lower or 'forwarded message' in lower
    flags['quoted']='original message' in lower or QUOTE_LINE.search(body) is not None
    flags['attachment']='attach' in lower or PLACEHOLDER.search(body) is not None
    return flags


def new_stats():
    """Empty counters for one mailbox."""
    stats={'files': 0, 'read_errors': 0, 'distinct': 0, 'mandatory_ok': 0, 'low_priority_ok': 0,
           'bcc_filled': 0, 'bcc_same_as_cc': 0, 'bcc_without_cc': 0}
    for name in MANDATORY_CHECKS:
        stats[name]=0
    for name in FEATURES:
        stats[name]=0
    return stats


def scan_mailbox(folder):
    """Count files, distinct emails and feature coverage for one mailbox."""
    stats=new_stats()
    seen=set()
    for path in common.list_email_files(folder):
        try:
            item=common.read_email(path)
        except Exception as e:
            print('  could not read', path, e)
            stats['read_errors']+=1
            continue
        stats['files']+=1
        # copies of the same email in other folders only count once
        if item['fingerprint'] in seen:
            continue
        seen.add(item['fingerprint'])
        stats['distinct']+=1
        headers=item['headers']
        body=item['body']

        problems=mandatory_problems(headers, body)
        for name in problems:
            stats[name]+=1
        if len(problems)==0:
            stats['mandatory_ok']+=1

        flags=feature_flags(headers, body)
        for name in FEATURES:
            if flags[name]:
                stats[name]+=1

        all_there=True
        for name in LOW_PRIORITY:
            if not filled(headers, name):
                all_there=False
        if all_there:
            stats['low_priority_ok']+=1

        # bcc: is it ever more than a copy of cc?
        if filled(headers, 'Bcc'):
            stats['bcc_filled']+=1
            bcc=common.collapse_ws(common.header_value(headers, 'Bcc'))
            cc=common.collapse_ws(common.header_value(headers, 'Cc') or '')
            if bcc==cc:
                stats['bcc_same_as_cc']+=1
            if cc=='':
                stats['bcc_without_cc']+=1
    return stats, seen


def pct(count, total):
    """Percent as a float, 0 when there's nothing to divide by."""
    if total==0:
        return 0.0
    return 100.0*count/total


def first_filter(stats):
    """Rules 1 and 2: return the reason a mailbox is dropped, or None if it stays."""
    distinct=stats['distinct']
    if distinct<MIN_DISTINCT:
        return 'fewer than %d distinct emails' % MIN_DISTINCT
    # integer math so 90.0% exactly isn't lost to float rounding
    if stats['mandatory_ok']*100<MIN_MANDATORY_PCT*distinct:
        return 'mandatory coverage below %d%%' % MIN_MANDATORY_PCT
    low=[]
    for name in FEATURES:
        if stats[name]*100<MIN_FEATURE_PCT*distinct:
            low.append('%s %.1f%%' % (name, pct(stats[name], distinct)))
    if len(low)>0:
        return 'feature below %d%%: %s' % (MIN_FEATURE_PCT, ', '.join(low))
    return None


def rank_key(stats):
    """Rule 3: weakest feature first, then the average, then low-priority coverage."""
    values=[]
    for name in FEATURES:
        values.append(pct(stats[name], stats['distinct']))
    weakest=min(values)
    average=sum(values)/len(values)
    low=pct(stats['low_priority_ok'], stats['distinct'])
    return (weakest, average, low)


def pick(ranked, fingerprints):
    """Rule 5: take mailboxes in rank order under the cap until the targets are met."""
    picked=[]
    union=set()
    reasons={}
    for name in ranked:
        if len(picked)>=MIN_MAILBOXES and len(union)>=MIN_TOTAL:
            reasons[name]='not needed, targets already met'
            continue
        together=union | fingerprints[name]
        if len(together)>MAX_TOTAL:
            reasons[name]='would push the total to %d distinct (cap %d)' % (len(together), MAX_TOTAL)
            continue
        picked.append(name)
        union=together
        reasons[name]='picked'
    return picked, union, reasons


def write_manifest(names, all_stats, ranks, reasons):
    """One row per mailbox with its numbers and the result."""
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    columns=['mailbox', 'files', 'distinct', 'copies_pct', 'mandatory_pct'] + MANDATORY_CHECKS
    columns=columns + ['cc_pct', 'forwarded_pct', 'quoted_pct', 'attachment_pct', 'weakest_pct',
                       'average_pct', 'low_priority_pct', 'bcc_filled', 'bcc_same_as_cc', 'rank', 'result']
    with open(MANIFEST, 'w', newline='', encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(columns)
        for name in names:
            s=all_stats[name]
            d=s['distinct']
            weakest, average, low=rank_key(s)
            row=[name, s['files'], d, '%.1f' % pct(s['files']-d, s['files']), '%.1f' % pct(s['mandatory_ok'], d)]
            for check in MANDATORY_CHECKS:
                row.append(s[check])
            for feature in FEATURES:
                row.append('%.1f' % pct(s[feature], d))
            row=row + ['%.1f' % weakest, '%.1f' % average, '%.1f' % low, s['bcc_filled'], s['bcc_same_as_cc']]
            row.append(ranks.get(name, ''))
            row.append(reasons[name])
            writer.writerow(row)


def main():
    names=[]
    for name in sorted(os.listdir(MAILDIR)):
        if not name.startswith('.') and os.path.isdir(os.path.join(MAILDIR, name)):
            names.append(name)
    print('scanning', len(names), 'mailboxes in', MAILDIR)

    all_stats={}
    fingerprints={}
    for name in tqdm(names, desc='mailboxes'):
        stats, seen=scan_mailbox(os.path.join(MAILDIR, name))
        all_stats[name]=stats
        fingerprints[name]=seen

    # rules 1 and 2
    reasons={}
    eligible=[]
    for name in names:
        reason=first_filter(all_stats[name])
        if reason is None:
            eligible.append(name)
        else:
            reasons[name]=reason

    # rule 3, ties go to the mailbox name so the order never changes between runs
    def sort_key(name):
        weakest, average, low=rank_key(all_stats[name])
        return (-weakest, -average, -low, name)
    ranked=sorted(eligible, key=sort_key)
    ranks={}
    for i, name in enumerate(ranked):
        ranks[name]=i+1

    picked, union, pick_reasons=pick(ranked, fingerprints)
    for name in pick_reasons:
        reasons[name]=pick_reasons[name]
    write_manifest(names, all_stats, ranks, reasons)

    # totals
    total_files=0
    total_distinct=0
    bcc_filled=0
    bcc_same=0
    bcc_without_cc=0
    read_errors=0
    for name in names:
        s=all_stats[name]
        total_files+=s['files']
        total_distinct+=s['distinct']
        bcc_filled+=s['bcc_filled']
        bcc_same+=s['bcc_same_as_cc']
        bcc_without_cc+=s['bcc_without_cc']
        read_errors+=s['read_errors']
    print()
    print('files read:', total_files, ' read errors:', read_errors)
    print('distinct within each mailbox, summed:', total_distinct)
    print('bcc filled:', bcc_filled, ' bcc same as cc:', bcc_same, ' bcc without cc:', bcc_without_cc)
    print('dropped by rules 1-2:', len(names)-len(eligible), ' eligible:', len(eligible))
    print()
    print('rank  mailbox          files  distinct  weakest  average  low_prio  result')
    for name in ranked:
        s=all_stats[name]
        weakest, average, low=rank_key(s)
        print('%4d  %-15s %6d  %8d  %6.1f%%  %6.1f%%  %7.1f%%  %s' % (
            ranks[name], name, s['files'], s['distinct'], weakest, average, low, reasons[name]))
    print()
    picked_files=0
    for name in picked:
        picked_files+=all_stats[name]['files']
    print('picked:', ', '.join(picked))
    print('picked files:', picked_files, ' distinct across picked:', len(union))
    if len(picked)<MIN_MAILBOXES or len(union)<MIN_TOTAL:
        print('WARNING: targets not met, check the rules')
    print('wrote', MANIFEST)


if __name__=='__main__':
    main()
