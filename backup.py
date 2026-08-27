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

    # mode=ro, and DO NOT ADD immutable=1.
    #
    # The comment here used to claim immutable=1 was what stopped a concurrent
    # WAL write from tearing the read. It says the opposite of the truth, and
    # the code never had the flag. immutable=1 promises SQLite the file cannot
    # change, so it SKIPS THE WAL -- every committed-but-uncheckpointed row is
    # silently absent from the dump, and the hash gate would cheerfully commit
    # the smaller file. Measured on a WAL database with two committed rows:
    #
    #     mode=ro      sees 2 rows
    #     immutable=1  sees 1 row
    #
    # So the flag would cause precisely the data loss the old comment claimed
    # it prevented, and anyone "fixing" the mismatch between comment and code
    # by adding it would be walking into that.
    #
    # What actually makes this safe is WAL snapshot isolation, which needs no
    # flag: a reader sees a consistent snapshot as of when it started and does
    # not block writers. Verified by dumping against a transaction holding 200
    # uncommitted rows -- the dump returned the pre-transaction state in 0.01s
    # rather than a mix, and 201 rows after the commit.
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

    rows = sum(1 for line in sql.splitlines() if line.startswith("INSERT"))

    # Count the fragile thing before overwriting the only other copy.
    # The hash check answers "did anything change", which a wiped database
    # satisfies enthusiastically. Nothing here refused a collapse: the store
    # could lose most of its rows and this would dutifully snapshot the loss
    # and push it. Git history would still hold the good version, so the data
    # is recoverable -- but nobody would know to go looking, which is the part
    # that matters.
    #
    # Deletions are legitimate (mem forget, consolidating near-duplicates), so
    # this is not a no-drop rule. It refuses a collapse, not a trim.
    previous_rows = 0
    if DUMP.exists():
        previous_rows = sum(
            1 for line in DUMP.read_text(encoding="utf-8").splitlines()
            if line.startswith("INSERT")
        )

    delta = rows - previous_rows
    log(f"changed -> {digest[:12]}  ({rows} rows, {delta:+d}, {len(sql):,} bytes)")

    forced = "--force" in sys.argv
    if forced and previous_rows >= 20 and rows < previous_rows // 2:
        log(f"--force: accepting a collapse {previous_rows} -> {rows}")

    if not forced and previous_rows >= 20 and rows < previous_rows // 2:
        log(f"REFUSING: row count collapsed {previous_rows} -> {rows}")
        log("  Nothing has been written. If this shrink is real, run:")
        log("    python backup.py --force")
        log("  Otherwise the live database may be damaged; the last good")
        log("  snapshot is still in memory.sql and in git history.")
        return 1

    DUMP.write_text(sql, encoding="utf-8", newline="\n")
    HASHFILE.write_text(digest + "\n", encoding="utf-8", newline="\n")

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
