# runs every query in sample_queries.sql and writes its real output as a comment right under it
# usage: .venv/bin/python scripts/run_sample_queries.py [path to db, default enron.db]

import os
import sqlite3
import sys

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUERIES=os.path.join(ROOT, 'sample_queries.sql')
# long subjects get cut so the comments stay readable; 70 fits a full EXPLAIN line
MAX_WIDTH=70


def cell(value):
    """One value as short text."""
    if value is None:
        return 'NULL'
    text=str(value).replace('\n', ' ')
    if len(text)>MAX_WIDTH:
        text=text[:MAX_WIDTH-3]+'...'
    return text


def output_lines(conn, sql):
    """Run one query and return its result as comment lines."""
    try:
        cursor=conn.execute(sql)
        rows=cursor.fetchall()
    except Exception as e:
        return ['-- Output: query failed: %s' % e]
    names=[]
    for column in cursor.description:
        names.append(column[0])
    label='rows'
    if len(rows)==1:
        label='row'
    lines=['-- Output (%d %s):' % (len(rows), label), '-- '+' | '.join(names)]
    for row in rows:
        values=[]
        for value in row:
            values.append(cell(value))
        lines.append('-- '+' | '.join(values))
    return lines


def refresh(conn, lines):
    """Rebuild the file, replacing each old Output block with a fresh one."""
    result=[]
    sql=[]
    i=0
    while i<len(lines):
        line=lines[i]
        if line.startswith('-- Output'):
            # skip the old output block, it ends at the first line that isn't a comment
            i+=1
            while i<len(lines) and lines[i].startswith('--'):
                i+=1
            continue
        result.append(line)
        if not line.startswith('--') and line.strip()!='':
            sql.append(line)
            if line.rstrip().endswith(';'):
                result=result+output_lines(conn, '\n'.join(sql))
                sql=[]
        i+=1
    return result


def main():
    db=os.path.join(ROOT, 'enron.db')
    if len(sys.argv)>1:
        db=sys.argv[1]
    if not os.path.exists(db):
        print('no database at', db, '- run python main.py first')
        return
    conn=sqlite3.connect(db)
    with open(QUERIES, encoding='utf-8') as f:
        lines=f.read().split('\n')
    result=refresh(conn, lines)
    with open(QUERIES, 'w', encoding='utf-8') as f:
        f.write('\n'.join(result))
    print('refreshed the outputs in', QUERIES, 'from', db)


if __name__=='__main__':
    main()
