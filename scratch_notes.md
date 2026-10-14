# Scratch notes (for AI_USAGE.md)

## Mailbox selection (exploration in Claude chat, review and fixes in Claude Code)
- First script searched the whole file as text. "To:" also matched "X-To:", so every mailbox showed 100% mandatory. Fixed by reading headers with the email module: real coverage was ~96-99%, the gap was missing To: lines.
- A bare `except: pass` also swallowed Ctrl+C, so I couldn't stop the script. Fixed with `except Exception`.
- Ranking by the average of the optional fields picked mailboxes with 0% forwarded/quoted. I pushed back; switched to ranking by the weakest field.
- Claude Code's review found every file has its own Message-ID, so "unique" counted files. Over half were copies of the same email in different folders. Switched to a content fingerprint, re-picked 5 mailboxes (17,903 distinct), decided to merge copies at ingestion.
- Claude Code used a different Python than my terminal and stubbed out tqdm. Fixed with .venv and a CLAUDE.md rule to always use .venv/bin/python.
- Shell commands with # comments broke in zsh (comments aren't skipped by default) and created junk folders.
