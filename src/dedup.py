# task 3: flag duplicates (same sender, same normalized subject, body at least 90% similar)
# recomputes the flags on every run and writes duplicates_report.csv; the notifications ledger is never touched

import argparse
import csv
import os
import random
import time

from rapidfuzz.distance import Indel

from src import common
from src import database

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REPORT_COLUMNS=['duplicate_message_id', 'original_message_id', 'subject', 'from_address', 'duplicate_date',
                'original_date', 'similarity_score']
# the spec's threshold
MIN_SCORE=90
# bodies this short are easy to call similar by accident, so the stats count them
SHORT_BODY=50


def compare_text(body):
    """The text two emails are compared on: the body with whitespace collapsed."""
    return common.collapse_ws(body or '')


def score_from_distance(m, n, distance):
    """fuzz.ratio's formula from the whole-number Indel distance."""
    return round(100.0*(m+n-distance)/(m+n), 2)


def similarity(a, b):
    """Score 90-100 if a and b are similar enough, else None (the fast version)."""
    # never call two empty texts similar
    if a=='' or b=='':
        return None
    # identical texts are 100 without any fuzzy matching (the folder copies)
    if a==b:
        return 100.0
    m=len(a)
    n=len(b)
    # fuzz.ratio is at most 200*min/(m+n), so it can't reach 90 when 20*min < 9*(m+n)
    if 20*min(m, n)<9*(m+n):
        return None
    # ratio>=90 means 10*distance<=m+n, decided on whole numbers so no float rounding sneaks in
    limit=(m+n)//10
    distance=Indel.distance(a, b, score_cutoff=limit)
    if distance>limit:
        return None
    return score_from_distance(m, n, distance)


def plain_similarity(a, b):
    """The same decision with no shortcuts: the full Indel distance for every pair."""
    if a=='' or b=='':
        return None
    m=len(a)
    n=len(b)
    distance=Indel.distance(a, b)
    if 10*distance<=m+n:
        return score_from_distance(m, n, distance)
    return None


def match_group(emails, compare):
    """Walk one group in date order; returns (duplicate, original, score) for every flagged email."""
    originals=[]
    flags=[]
    for email in emails:
        text=compare_text(email['body'])
        found=None
        # attach to the earliest original it scores 90+ against
        for original, original_text in originals:
            score=compare(text, original_text)
            if score is not None:
                found=(original, score)
                break
        if found is None:
            originals.append((email, text))
        else:
            flags.append((email, found[0], found[1]))
    return flags


def plain_match_group(emails):
    """Compare every pair first, then apply the same earliest-original rule."""
    texts=[]
    for email in emails:
        texts.append(compare_text(email['body']))
    scores={}
    for i in range(len(emails)):
        for j in range(i+1, len(emails)):
            scores[(i, j)]=plain_similarity(texts[i], texts[j])
    original_index=[]
    flags=[]
    for j in range(len(emails)):
        found=None
        for i in original_index:
            if scores[(i, j)] is not None:
                found=(emails[i], scores[(i, j)])
                break
        if found is None:
            original_index.append(j)
        else:
            flags.append((emails[j], found[0], found[1]))
    return flags


def load_groups(conn):
    """Emails grouped by (from_address, normalized_subject), each group in date order then message_id."""
    groups=[]
    current=[]
    current_key=None
    sql='''SELECT id, message_id, date, from_address, normalized_subject, subject, body
           FROM emails ORDER BY from_address, normalized_subject, date, message_id'''
    for row in conn.execute(sql):
        key=(row['from_address'], row['normalized_subject'])
        if key!=current_key:
            # only groups of 2 or more can hold a duplicate
            if len(current)>=2:
                groups.append(current)
            current=[]
            current_key=key
        current.append(dict(row))
    if len(current)>=2:
        groups.append(current)
    return groups


def find_duplicates(groups):
    """Run the fast matcher over every group; returns all the flags."""
    flags=[]
    for group in groups:
        flags.extend(match_group(group, similarity))
    return flags


def save_flags(conn, flags):
    """Reset and rewrite is_duplicate, duplicate_of and similarity_score in one transaction."""
    conn.execute('BEGIN')
    conn.execute('UPDATE emails SET is_duplicate=0, duplicate_of=NULL, similarity_score=NULL')
    for duplicate, original, score in flags:
        conn.execute('UPDATE emails SET is_duplicate=1, duplicate_of=?, similarity_score=? WHERE id=?',
                     (original['message_id'], score, duplicate['id']))
    conn.commit()


def write_report(flags, path):
    """duplicates_report.csv: one row per flagged email, grouped by original."""
    rows=[]
    for duplicate, original, score in flags:
        rows.append([duplicate['message_id'], original['message_id'], duplicate['subject'], duplicate['from_address'],
                     duplicate['date'], original['date'], score])
    # originals in time order, and each original's duplicates in time order under it
    rows.sort(key=lambda r: (r[5], r[1], r[4], r[0]))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer=csv.writer(f)
        writer.writerow(REPORT_COLUMNS)
        for row in rows:
            writer.writerow(row)
    return len(rows)


def stats_lines(groups, flags):
    """The numbers the spec and the build prompt ask for."""
    members={}
    same_date=0
    identical=0
    short=0
    for duplicate, original, score in flags:
        key=original['message_id']
        members[key]=members.get(key, 1)+1
        if duplicate['date']==original['date']:
            same_date+=1
        if score==100.0:
            identical+=1
        if len(compare_text(duplicate['body']))<SHORT_BODY:
            short+=1
    group_count=len(members)
    in_groups=sum(members.values())
    average=0.0
    if group_count>0:
        average=in_groups/group_count
    biggest=0
    for key in members:
        if members[key]>biggest:
            biggest=members[key]
    lines=[]
    candidates=0
    for group in groups:
        candidates+=len(group)
    lines.append('sender+subject groups with 2+ emails: %d (%d emails)' % (len(groups), candidates))
    lines.append('duplicate groups found (an original plus 1+ duplicates): %d' % group_count)
    lines.append('emails flagged as duplicates: %d' % len(flags))
    lines.append('average duplicate group size: %.2f (largest %d)' % (average, biggest))
    lines.append('flagged with the same Date as their original (folder copies): %d' % same_date)
    lines.append('flagged with a later Date (real re-sends): %d' % (len(flags)-same_date))
    lines.append('flagged with identical text (score 100): %d, fuzzy 90-99.99: %d' % (identical, len(flags)-identical))
    lines.append('flagged with a body under %d characters: %d' % (SHORT_BODY, short))
    return lines


def check_against_plain(groups, sample_size, max_group, seed):
    """Run the fast and the plain matcher on a sample of groups; returns (groups, emails, mismatches)."""
    small=[]
    for group in groups:
        if len(group)<=max_group:
            small.append(group)
    picker=random.Random(seed)
    sample=small
    if len(small)>sample_size:
        sample=picker.sample(small, sample_size)
    emails=0
    mismatches=[]
    for group in sample:
        emails+=len(group)
        fast=[]
        for duplicate, original, score in match_group(group, similarity):
            fast.append((duplicate['message_id'], original['message_id'], score))
        plain=[]
        for duplicate, original, score in plain_match_group(group):
            plain.append((duplicate['message_id'], original['message_id'], score))
        if fast!=plain:
            mismatches.append(group[0]['from_address']+' / '+group[0]['normalized_subject'])
    return len(sample), emails, mismatches


def run(conn, report_path):
    """Find duplicates, save the flags, write the report; returns (flags, stat lines)."""
    groups=load_groups(conn)
    flags=find_duplicates(groups)
    save_flags(conn, flags)
    write_report(flags, report_path)
    return flags, stats_lines(groups, flags)


def main():
    parser=argparse.ArgumentParser(description='flag duplicates in the database and write the report')
    parser.add_argument('--db', default=os.path.join(ROOT, 'enron.db'))
    parser.add_argument('--report', default=os.path.join(ROOT, 'duplicates_report.csv'))
    parser.add_argument('--stats', default=os.path.join(ROOT, 'output', 'dedup_stats.txt'))
    parser.add_argument('--check', action='store_true', help='also check the fast matcher against the plain one')
    args=parser.parse_args()
    conn=database.connect(args.db)
    started=time.time()
    flags, lines=run(conn, args.report)
    for line in lines:
        print(line)
    with open(args.stats, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n')
    print('took %.1fs, wrote %s and %s' % (time.time()-started, args.report, args.stats))
    if args.check:
        # every-pair matching is slow, so check a fixed random sample of the smaller groups
        groups=load_groups(conn)
        checked, emails, mismatches=check_against_plain(groups, 500, 40, 7)
        print('plain check: %d groups, %d emails, %d mismatches' % (checked, emails, len(mismatches)))
        for name in mismatches:
            print('  mismatch:', name)


if __name__=='__main__':
    main()

