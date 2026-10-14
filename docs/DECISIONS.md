# Decisions

Every rule and threshold in the code has a one-line reason next to it and a full entry here: what we decided, why (a spec section or a number from the data), what else we considered, and how we checked it.

## Phase 0: setup

### D0.1 Extra .gitignore lines for SQLite side files
- **Decision:** besides the list in BUILD_PROMPT.md, ignore `*.db-journal`, `*.db-wal` and `*.db-shm`.
- **Why:** if a load crashes mid-transaction, SQLite leaves `enron.db-journal` next to the database. Committing that half-written state would be as bad as committing `enron.db` itself, which the list already ignores with `*.db`.
- **Considered:** using the list exactly as given. The extra lines can only stop a database side file from being committed, so nothing else changes.
- **Checked:** `git check-ignore -v` confirms maildir, ASSIGNMENT.md, .venv and enron.db are all ignored.

### D0.2 Pin every package from pip freeze
- **Decision:** requirements.txt is the full `.venv/bin/pip freeze` (35 lines), not just the four direct packages.
- **Why:** BUILD_PROMPT.md phase 0 asks for every tested version to be pinned. mcp 2.3.0 pulls in pydantic, anyio, starlette and httpx2, and their versions affect the MCP server.
- **Considered:** listing only tqdm, rapidfuzz, mcp and pytest. That's shorter, but a fresh install could then pull different transitive versions from the ones that were tested.
- **Checked:** phase 9 installs requirements.txt into a fresh venv and runs the pipeline and the tests.
