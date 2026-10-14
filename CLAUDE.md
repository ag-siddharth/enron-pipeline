# Enron pipeline: rules for every session

The plan is in BUILD_PROMPT.md, progress is in docs/PROGRESS.md. ASSIGNMENT.md is the spec and the final authority.

## Stop and ask first if
- Gmail credentials are needed. The user creates .env; never ask for a password in chat.
- anything would send a real email. Never run `main.py --send-live`.
- the data contradicts the spec (for example fewer than 10,000 valid emails).
- anything in maildir/ or outside this repo would change.

Never `git push`. Never edit maildir/.

## Decisions
Measure first, then decide. Every rule or threshold gets a one-line reason in a comment where it lives and a full entry in docs/DECISIONS.md (what, why, what else was considered, how it was checked).

## After each phase
Run it, check the numbers, update docs/PROGRESS.md (phase, status, key numbers, commit hash), add real problems and fixes to scratch_notes.md, commit.

## Code style
- Simple student Python: small functions, plain for loops, plain dicts and lists. No classes unless really needed, no clever one-liners, no nested comprehensions, no heavy type hints.
- No spaces around = or comparisons: `total=0`, `total+=1`, `if score>=90:`, `if a==b:`. Keep a space after commas and around and, or, not, in.
- Short casual comments that say what a block does and why.
- At most a one-line docstring per function; one or two comment lines at the top of each file.
- `except Exception as e`, never a bare except. Never crash on a bad file: catch, log, skip.
- Plain print() for progress and stats. Don't run code formatters.
- Standard library first. Only third-party packages: tqdm, rapidfuzz, mcp, pytest.

## Python
Always use `.venv/bin/python` and `.venv/bin/pip`, never the system Python.
