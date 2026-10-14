-- sample queries for enron.db (task 2). run them all with: sqlite3 enron.db < sample_queries.sql
-- every query has an "Expected" note, and the "Output" comment under it is the real result from the
-- last pipeline run, refreshed by: .venv/bin/python scripts/run_sample_queries.py

-- 1. Emails per sender, top 10
-- Expected: the five mailbox owners near the top, since their sent folders are in the subset. "emails"
-- counts every file (folder copies are separate rows), "contents" counts distinct fingerprints.
SELECT from_address, COUNT(*) AS emails, COUNT(DISTINCT fingerprint) AS contents
FROM emails
GROUP BY from_address
ORDER BY emails DESC, from_address
LIMIT 10;
-- Output (10 rows):
-- from_address | emails | contents
-- kay.mann@enron.com | 16668 | 4847
-- richard.sanders@enron.com | 3119 | 1609
-- jeffrey.shankman@enron.com | 2538 | 1025
-- elizabeth.sager@enron.com | 2535 | 1472
-- ben.jacoby@enron.com | 503 | 201
-- b..sanders@enron.com | 337 | 337
-- a..shankman@enron.com | 312 | 309
-- reagan.rorschach@enron.com | 300 | 122
-- suzanne.adams@enron.com | 281 | 112
-- gfergus@brobeck.com | 275 | 141

-- 2a. Emails in a date range: everything sent on 2 December 2001 (UTC), the day Enron filed for bankruptcy
-- Expected: a handful of rows in time order; dates are ISO 8601 UTC text, so a plain text range works
SELECT date, from_address, subject
FROM emails
WHERE date>='2001-12-02T00:00:00+00:00' AND date<'2001-12-03T00:00:00+00:00'
ORDER BY date, message_id
LIMIT 10;
-- Output (10 rows):
-- date | from_address | subject
-- 2001-12-02T15:08:38+00:00 | kathleen.carnahan@enron.com | RE: East/West Power Development entities not wholly owned subs of E...
-- 2001-12-02T18:52:53+00:00 | b..sanders@enron.com | 
-- 2001-12-02T19:21:57+00:00 | ben.jacoby@enron.com | RE: Site List Rev 4 - Onondaga GSA BKR provisons
-- 2001-12-02T19:41:53+00:00 | kay.mann@enron.com | 
-- 2001-12-02T19:42:57+00:00 | jbq@quinnemanuel.com | i saw in the new york times that
-- 2001-12-02T19:43:23+00:00 | kay.mann@enron.com | RE: Check this one out
-- 2001-12-02T21:30:54+00:00 | kay.mann@enron.com | info re bank
-- 2001-12-02T22:39:54+00:00 | kay.mann@enron.com | Enron Metals & Commodity Corp
-- 2001-12-02T22:40:36+00:00 | lori.pinder@enron.com | RE: Enron Metals & Commodity Corp
-- 2001-12-02T22:40:52+00:00 | kay.mann@enron.com | FW: Enron Metals & Commodity Corp

-- 2b. Emails per month in the last quarter of 2001
-- Expected: three rows, October to December 2001
SELECT substr(date, 1, 7) AS month, COUNT(*) AS emails
FROM emails
WHERE date>='2001-10-01T00:00:00+00:00' AND date<'2002-01-01T00:00:00+00:00'
GROUP BY month
ORDER BY month;
-- Output (3 rows):
-- month | emails
-- 2001-10 | 1388
-- 2001-11 | 1278
-- 2001-12 | 568

-- 2c. The date range query uses the index on date
-- Expected: a SEARCH using idx_emails_date, not a full SCAN of emails
EXPLAIN QUERY PLAN
SELECT date, from_address, subject
FROM emails
WHERE date>='2001-12-02T00:00:00+00:00' AND date<'2001-12-03T00:00:00+00:00';
-- Output (1 row):
-- id | parent | notused | detail
-- 3 | 0 | 163 | SEARCH emails USING INDEX idx_emails_date (date>? AND date<?)

-- 3a. How many emails have CC recipients
-- Expected: about a quarter of all emails (the extractor reports 26.4% coverage for cc)
SELECT COUNT(DISTINCT email_id) AS emails_with_cc,
       (SELECT COUNT(*) FROM emails) AS all_emails
FROM email_recipients
WHERE type='cc';
-- Output (1 row):
-- emails_with_cc | all_emails
-- 10737 | 40651

-- 3b. Emails with the most CC recipients, joined through the normalized recipients table
-- Expected: big distribution lists, each cc counted once per address
SELECT e.date, e.from_address, e.subject, COUNT(*) AS cc_count
FROM emails e
JOIN email_recipients r ON r.email_id=e.id
WHERE r.type='cc'
GROUP BY e.id
ORDER BY cc_count DESC, e.date
LIMIT 10;
-- Output (10 rows):
-- date | from_address | subject | cc_count
-- 2001-10-17T21:04:22+00:00 | becky.spencer@enron.com | New Temp IDs | 95
-- 2000-12-05T11:00:00+00:00 | taffy.milligan@enron.com | URGENT APB - Darren Inoff, Andrews & Kurth | 91
-- 2000-12-05T11:00:00+00:00 | taffy.milligan@enron.com | URGENT APB - Darren Inoff, Andrews & Kurth | 91
-- 2001-06-08T15:19:00+00:00 | deb.korkmas@enron.com | Letter of Credit Seminar - CLE CREDIT | 91
-- 2001-06-08T15:19:00+00:00 | deb.korkmas@enron.com | Letter of Credit Seminar - CLE CREDIT | 91
-- 2000-12-05T11:19:00+00:00 | taffy.milligan@enron.com | Re: URGENT APB - Darren Inoff, Andrews & Kurth | 90
-- 2000-12-05T11:19:00+00:00 | taffy.milligan@enron.com | Re: URGENT APB - Darren Inoff, Andrews & Kurth | 90
-- 2001-10-18T18:52:23+00:00 | joannie.williamson@enron.com | Quarterly Managing Director Meeting - Monday, October 22 | 79
-- 2001-12-03T15:45:52+00:00 | michelle.robichaux@enron.com | RE: | 76
-- 2001-02-03T19:19:00+00:00 | alan.comnes@enron.com | Re: Challenge to exercise of Eminent Domain - Confidential Attorney... | 73

-- 3c. Addresses that are cc'd most often
-- Expected: the mailbox owners and their assistants
SELECT a.address, COUNT(*) AS times_cc
FROM email_recipients r
JOIN addresses a ON a.id=r.address_id
WHERE r.type='cc'
GROUP BY a.address
ORDER BY times_cc DESC, a.address
LIMIT 10;
-- Output (10 rows):
-- address | times_cc
-- kay.mann@enron.com | 1569
-- ben.jacoby@enron.com | 784
-- elizabeth.sager@enron.com | 657
-- sheila.tweed@enron.com | 587
-- jkeffer@kslaw.com | 518
-- roseann.engeldorf@enron.com | 516
-- richard.sanders@enron.com | 421
-- mark.fisher@enron.com | 363
-- chris.booth@enron.com | 350
-- lisa.bills@enron.com | 303

-- 4a. Flagged duplicates, split into folder copies (same Date as the original) and re-sends
-- Expected: most flags are folder copies with a score of 100; re-sends are a small part
SELECT CASE WHEN d.date=o.date THEN 'same Date (folder copy)' ELSE 'different Date (re-send)' END AS kind,
       COUNT(*) AS flagged, ROUND(AVG(d.similarity_score), 2) AS avg_score
FROM emails d
JOIN emails o ON o.message_id=d.duplicate_of
WHERE d.is_duplicate=1
GROUP BY kind
ORDER BY kind DESC;
-- Output (0 rows):
-- kind | flagged | avg_score

-- 4b. Duplicates joined to their originals, the least similar ones first
-- Expected: scores between 90 and 100, every duplicate dated on or after its original
SELECT d.date AS duplicate_date, o.date AS original_date, d.similarity_score, d.from_address, d.subject
FROM emails d
JOIN emails o ON o.message_id=d.duplicate_of
WHERE d.is_duplicate=1
ORDER BY d.similarity_score, d.date, d.message_id
LIMIT 10;
-- Output (0 rows):
-- duplicate_date | original_date | similarity_score | from_address | subject

-- 5a. Contents (fingerprints) that appear in more than one folder
-- Expected: thousands, because Outlook and Notes keep the same email in several folders
SELECT COUNT(*) AS contents_in_several_folders
FROM (SELECT fingerprint FROM emails GROUP BY fingerprint HAVING COUNT(DISTINCT x_folder)>1);
-- Output (1 row):
-- contents_in_several_folders
-- 12910

-- 5b. The contents copied into the most folders
-- Expected: up to 8 copies of one email, spread over folders like all_documents, discussion_threads and sent
SELECT COUNT(*) AS files, COUNT(DISTINCT x_folder) AS folders, MIN(subject) AS subject, MIN(from_address) AS sender
FROM emails
GROUP BY fingerprint
HAVING COUNT(DISTINCT x_folder)>1
ORDER BY files DESC, folders DESC, subject
LIMIT 10;
-- Output (10 rows):
-- files | folders | subject | sender
-- 8 | 8 | Enron Wholesale Services Legal Department | enron.announcements@enron.com
-- 7 | 7 | 1-URGENT - Outlook Email Notification (new) | outlook.team@enron.com
-- 7 | 7 | 2- SURVEY/INFORMATION EMAIL | outlook.team@enron.com
-- 7 | 7 | 3 - URGENT - TO PREVENT LOSS OF INFORMATION | outlook.team@enron.com
-- 7 | 7 | 4-URGENT - OWA Please print this now. | outlook.team@enron.com
-- 7 | 7 | Foreign & Domestic Counsel Database | becky.spencer@enron.com
-- 7 | 7 | Managers Training | enron.announcements@enron.com
-- 7 | 7 | Messaging Administration Group | taffy.milligan@enron.com
-- 7 | 7 | Outlook Migration - EWS Legal | janette.elbertson@enron.com
-- 7 | 7 | PG&E BANKRUPTCY CASE-- IMPORTANT | enron.announcements@enron.com
