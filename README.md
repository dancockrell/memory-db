# Structured Memory Database

A small SQLite-backed memory store for development work that needs durable facts, decisions, dependencies and project state across sessions.

Markdown notes are useful for narrative context. They are poor at answering questions such as “which projects depend on Ruby?”, “what failed last week?”, or “which fact is verified versus merely reported?”. This repository keeps that information structured and queryable.

The live `memory.db` is intentionally **not committed**. Git tracks a deterministic SQL dump (`memory.sql`) plus `memory.sha256`; `backup.py` writes and pushes a new dump only when the database has actually changed.

## Schema

| Table | Purpose |
|---|---|
| `facts` | Durable keyed facts, with category, confidence and source |
| `events` | Append-only decisions, errors, installs, removals and milestones |
| `projects` | Project path, repository, state and notes |
| `dependencies` | External dependencies that normal package manifests do not capture |

The dependency table is the reason this exists. A machine cleanup once removed Ruby4Lich5 as apparent game clutter while DR Companion still depended on it. A dependency that exists only in somebody's memory is not documented.

## Command-line use

`mem.py` is the normal interface:

```bash
python mem.py status
python mem.py recall trap
python mem.py search cublas
python mem.py remember trap example "what was learned"
python mem.py log error "what broke"
python mem.py dep dr-companion Ruby4Lich5 --location C:\Ruby4Lich5 --why "Lich runtime"
python mem.py project dr-companion --status active
python mem.py review
```

Writes are explicit and loud. The database uses a 30-second SQLite busy timeout because several sessions may write concurrently. If a write still cannot acquire the database, `mem.py` exits loudly rather than allowing a missing fact to look like a saved one.

## Backup

```bash
python backup.py
```

The backup process:

1. dump SQLite deterministically to SQL text;
2. hash the dump;
3. compare it with `memory.sha256`;
4. commit only if the content changed;
5. push;
6. verify that local `HEAD` matches `origin/main`.

Text is committed instead of the binary database so changes remain diffable and Git does not accumulate complete binary copies of a growing `.db` on every backup.

## Restore

```bash
git clone https://github.com/dancockrell/memory-db
cd memory-db
python -c "import sqlite3,pathlib; sqlite3.connect('memory.db').executescript(pathlib.Path('memory.sql').read_text(encoding='utf-8'))"
```

Then run:

```bash
python mem.py status
```

## Tests

The repository includes checks for round trips, classification, concurrent access and failure behavior:

```bash
python -m unittest discover -p "test_*.py"
```

## Privacy

This repository is private because the database accumulates working context, machine information and project state. Treat a published commit as permanent; do not place secrets in the store merely because the repository is private.
