"""Hourly hashed backup of the structured-memory database.

Dumps SQLite to SQL text, hashes the dump, and commits only when the hash
changes. Text dump rather than the binary .db because git stores a full copy
of a binary blob per commit -- 24 commits a day would bloat the repo
permanently, and a .sql dump diffs, compresses, and stays reviewable.

Run manually:   python backup.py
Hourly:         registered as the scheduled task "ClaudeMemoryBackup"
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "memory.db"
DUMP = HERE / "memory.sql"
HASHFILE = HERE / "memory.sha256"
LOG = HERE / "backup.log"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}  {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(HERE), *args],
        capture_output=True,
        text=True,
    )


def dump_database() -> str:
    """Serialise the database to deterministic SQL text."""
    if not DB.exists():
        log(f"no database at {DB}")
        sys.exit(1)

    # immutable=1 so a WAL-mode write in progress can't block or tear the read
    uri = f"file:{DB.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        return "\n".join(conn.iterdump())


def main() -> int:
    sql = dump_database()
    digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()

    previous = HASHFILE.read_text(encoding="utf-8").strip() if HASHFILE.exists() else ""
    if digest == previous:
        log(f"unchanged ({digest[:12]}) - nothing to do")
        return 0

    DUMP.write_text(sql, encoding="utf-8", newline="\n")
    HASHFILE.write_text(digest + "\n", encoding="utf-8", newline="\n")

    rows = sum(1 for line in sql.splitlines() if line.startswith("INSERT"))
    log(f"changed -> {digest[:12]}  ({rows} rows, {len(sql):,} bytes)")

    git("add", "memory.sql", "memory.sha256")

    status = git("status", "--porcelain", "--", "memory.sql", "memory.sha256")
    if not status.stdout.strip():
        log("git reports nothing staged - skipping commit")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = git("commit", "-m", f"Memory snapshot {stamp} ({digest[:12]})")
    if commit.returncode != 0:
        log(f"commit failed: {commit.stderr.strip()[:200]}")
        return 1

    push = git("push", "origin", "main")
    if push.returncode != 0:
        log(f"push failed: {push.stderr.strip()[:200]}")
        return 1

    # Verify the outcome, not the exit code.
    local = git("rev-parse", "HEAD").stdout.strip()
    remote = git("rev-parse", "origin/main").stdout.strip()
    if local != remote:
        log(f"MISMATCH after push: local {local[:8]} != remote {remote[:8]}")
        return 1

    log(f"pushed {local[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
