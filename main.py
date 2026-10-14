# runs the whole pipeline: extract, load, find duplicates, write the draft notices
# it never sends email unless --send-live is given. see README.md for every flag and output

import argparse
import os
import sys
import time

from src import database
from src import dedup
from src import extractor
from src import notifier

ROOT=os.path.dirname(os.path.abspath(__file__))
MAILDIR=os.path.join(ROOT, 'maildir')


def output_paths(only):
    """Where everything goes; --only uses dev.db and output_dev/ so it can't touch the real outputs."""
    paths={}
    if only is None:
        paths['db']=os.path.join(ROOT, 'enron.db')
        paths['out']=os.path.join(ROOT, 'output')
        paths['error_log']=os.path.join(ROOT, 'error_log.txt')
        paths['report']=os.path.join(ROOT, 'duplicates_report.csv')
    else:
        paths['db']=os.path.join(ROOT, 'dev.db')
        paths['out']=os.path.join(ROOT, 'output_dev')
        paths['error_log']=os.path.join(paths['out'], 'error_log.txt')
        paths['report']=os.path.join(paths['out'], 'duplicates_report.csv')
    return paths


def show(title, lines, path):
    """Print a stage's stats and keep a copy in a text file."""
    print()
    print('== '+title)
    for line in lines:
        print(line)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines)+'\n')


def check_args(args):
    """Return an error message for flag combinations that would be unsafe, else None."""
    if args.fresh and args.only is None:
        return '--fresh only rebuilds dev.db, so use it with --only. enron.db also holds the send ledger; delete it yourself if you really want to rebuild it.'
    if args.send_live and args.only is not None:
        return '--send-live uses the send ledger in enron.db, so run it without --only.'
    if args.limit<1:
        return '--limit must be 1 or more.'
    if not os.path.isdir(MAILDIR):
        return 'no maildir/ folder here; download and extract the dataset first (see README.md).'
    if args.only is not None and not os.path.isdir(os.path.join(MAILDIR, args.only)):
        return 'no mailbox called %s in maildir/' % args.only
    return None


def main():
    parser=argparse.ArgumentParser(description='Enron email pipeline: extract, load, dedup, draft notices.')
    parser.add_argument('--send-live', action='store_true', help='also send notices through the MCP server, to NOTIFY_TO')
    parser.add_argument('--limit', type=int, default=3, help='most notices to send with --send-live (default 3)')
    parser.add_argument('--only', metavar='MAILBOX', help='run on one mailbox into dev.db and output_dev/')
    parser.add_argument('--fresh', action='store_true', help='delete dev.db first (only with --only)')
    args=parser.parse_args()
    problem=check_args(args)
    if problem is not None:
        print(problem)
        sys.exit(2)

    paths=output_paths(args.only)
    mailboxes=extractor.MAILBOXES
    if args.only is not None:
        mailboxes=[args.only]
    os.makedirs(paths['out'], exist_ok=True)
    if args.fresh and os.path.exists(paths['db']):
        os.remove(paths['db'])
        print('removed', paths['db'])
    print('mailboxes:', ', '.join(mailboxes))
    print('database:', paths['db'])

    conn=database.connect(paths['db'])
    database.create_schema(conn)

    # tasks 1 and 2: the extractor streams records straight into the loader
    started=time.time()
    before=database.table_counts(conn)
    stats=extractor.new_stats()
    records=extractor.extract(MAILDIR, mailboxes, paths['error_log'], stats)
    load_stats=database.load(conn, records, os.path.join(paths['out'], 'load_log.txt'))
    after=database.table_counts(conn)
    show('extract (%.1fs)' % (time.time()-started), extractor.stats_lines(stats),
         os.path.join(paths['out'], 'extraction_stats.txt'))
    print('failed files are listed in', paths['error_log'])
    show('load', database.load_lines(load_stats, before, after), os.path.join(paths['out'], 'load_stats.txt'))

    # task 3
    started=time.time()
    flags, lines=dedup.run(conn, paths['report'])
    show('duplicates (%.1fs)' % (time.time()-started), lines, os.path.join(paths['out'], 'dedup_stats.txt'))
    print('report:', paths['report'])

    # task 4, dry run: always
    started=time.time()
    drafts=notifier.write_drafts(conn, paths['out'])
    print()
    print('== drafts (%.1fs)' % (time.time()-started))
    print('wrote %d .eml drafts to %s' % (drafts, os.path.join(paths['out'], 'replies')))

    # task 4, live: only when asked
    if args.send_live:
        print()
        print('== send live (at most %d)' % args.limit)
        notifier.send_live(conn, paths['out'], args.limit)
    else:
        print('no email sent (dry run). add --send-live to send notices through the MCP server.')
    conn.close()


if __name__=='__main__':
    main()
