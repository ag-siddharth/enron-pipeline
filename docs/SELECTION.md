# Mailbox selection

The spec (section 2) asks for at least 5 mailboxes and at least 10,000 emails, and for the choice to be documented.
`scripts/select_mailboxes.py` scans all 150 mailboxes and writes `output/selection_manifest.csv`, which has one row per mailbox with its numbers and either `picked` or the reason it wasn't.

**This is a purposive subset, not a random sample.** The mailboxes were chosen because they exercise every part of the parser (Cc lists, forwards, quoted replies, attachments). Any rate measured on them, such as the duplicate rate or how often forwards appear, says nothing about the whole Enron corpus.

## Method

- Every file in every mailbox is read with the same helpers the extractor uses (`src/common.py`): decode, CRLF to LF, split at the first blank line, parse only the header block.
- Copies count once. Every file has its own Message-ID even when it's a copy of the same email in another folder, so copies are matched by a fingerprint: md5 of the raw From, To, Cc, Date and Subject headers plus the body with whitespace collapsed. A file whose fingerprint was already seen in that mailbox is skipped.
- Over the distinct emails of each mailbox it measures:

| Measure | Counts an email when |
|---|---|
| mandatory coverage | Message-ID, Date, From and To are non-empty, a Subject header exists (it may be empty), and the body is non-empty |
| cc % | the real Cc header is non-empty |
| forwarded % | the body contains "forwarded by" or "forwarded message" (any case) |
| quoted % | the body contains "original message" or a line starting with `>` |
| attachment % | the body contains "attach" (any case) or a `<<...>>` placeholder |
| low-priority coverage | X-From, X-To, X-Folder, X-Origin and Content-Type are all non-empty |

## Rules

1. Keep mailboxes with at least 90% mandatory coverage and at least 500 distinct emails. Most emails must parse, and tiny mailboxes don't show enough variety.
2. Keep only mailboxes where cc, forwarded, quoted and attachment are each at least 5%. Every parser feature needs real data to prove it works.
3. Rank by the weakest of those four, then their average, then low-priority coverage. An average hides a feature at 0%, and one missing feature should sink a mailbox.
4. Bcc is left out of the scoring because it's an exact copy of Cc: all 68,456 distinct emails with a Bcc header have Bcc equal to Cc, and none has Bcc without Cc.
5. Pick in rank order, skipping any mailbox that would push the total above 20,000 distinct emails, until there are at least 5 mailboxes and at least 12,000 distinct emails. The total counts distinct fingerprints across the picked mailboxes. 12,000 is the spec's 10,000 plus headroom for failed parses, and the cap keeps runs fast.

## Results

All 517,401 files read without errors, giving 289,112 distinct emails when copies are counted once per mailbox.

| Step | Mailboxes |
|---|---|
| scanned | 150 |
| dropped: fewer than 500 distinct emails | 18 |
| dropped: mandatory coverage below 90% (always because of missing To headers) | 33 |
| dropped: a feature below 5% (forwarded 44, attachment 6, quoted 6, cc 5; some miss more than one) | 47 |
| eligible and ranked | 52 |
| skipped by the 20,000 cap (kaminski-v, dasovich-j, taylor-m) | 3 |
| picked | 5 |
| not needed once the targets were met | 44 |

| Rank | Mailbox | Files | Distinct | Copies | Mandatory | Cc | Forwarded | Quoted | Attachment | Weakest | Average | Low-priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | sanders-r | 7,329 | 4,336 | 40.8% | 95.3% | 29.5% | 27.2% | 26.5% | 32.0% | 26.5% | 28.8% | 98.1% |
| 2 | mann-k | 23,381 | 7,609 | 67.5% | 99.3% | 27.0% | 29.5% | 23.4% | 34.1% | 23.4% | 28.5% | 99.8% |
| 3 | sager-e | 5,200 | 3,256 | 37.4% | 96.3% | 26.0% | 23.0% | 23.6% | 31.4% | 23.0% | 26.0% | 98.5% |
| 7 | shankman-j | 3,856 | 2,202 | 42.9% | 96.2% | 17.1% | 20.4% | 25.2% | 18.7% | 17.1% | 20.4% | 98.4% |
| 8 | fischer-m | 1,498 | 711 | 52.5% | 93.1% | 43.0% | 21.7% | 16.9% | 25.7% | 16.9% | 26.8% | 100.0% |

- **Picked: sanders-r, mann-k, sager-e, shankman-j, fischer-m.**
- 41,264 files and 17,903 distinct emails across the five (18,114 when each mailbox is counted on its own, so 211 emails appear in more than one of the picked mailboxes).
- This matches the earlier run exactly (same five mailboxes, 41,264 files, 17,903 distinct).
- Ranks 4 to 6 (kaminski-v with 11,538 distinct, dasovich-j with 15,882, taylor-m with 7,713) would each have pushed the total past 20,000, so the cap skipped them.

## How the picked set differs from the corpus

Medians over all 150 mailboxes compared with the five picked ones:

| Measure | Corpus median | Picked median | Picked range |
|---|---|---|---|
| copies | 27.4% | 42.9% | 37.4% to 67.5% |
| mandatory coverage | 93.8% | 96.2% | 93.1% to 99.3% |
| cc | 17.6% | 27.0% | 17.1% to 43.0% |
| forwarded | 4.8% | 23.0% | 20.4% to 29.5% |
| quoted | 23.6% | 23.6% | 16.9% to 26.5% |
| attachment | 18.6% | 31.4% | 18.7% to 34.1% |

The picked mailboxes have about five times the median forward rate and more folder copies than typical. That's the point of the selection, but it means duplicate counts from this subset are higher than a random sample would give.
