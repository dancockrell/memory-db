"""Does the backup actually restore what was put in it?

    python test_roundtrip.py

A backup nobody has restored from is not a backup. This restores one and
compares byte for byte.

Why it exists in this shape. The first round-trip check on this store
compared the live database against a restore of memory.sql and reported
clean -- but every fact value in the store happened to be a single line, so
the check could not have revealed a line-ending bug even if one had been
present. That is the same trap that hid an autocrlf defect in a sibling
repo, where the one file anybody thought to spot-check was the only file
incapable of showing it: the sample you reach for is correlated with the
property that hides the fault.

So this does not test the live data. It builds a store full of the content
most likely to break a SQL text dump -- embedded newlines of both kinds,
quotes, backslashes, unicode, tabs, significant whitespace -- and proves
those survive. Real data passing tells you little; this tells you something.

The suite refuses to pass unless the corruption cases are actually detected,
so a comparison that has quietly stopped comparing reports itself rather
than reporting a clean backup.
"""

import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA = HERE / "schema.sql"

# Content chosen to break a naive dump/restore. Each entry is (key, value).
HOSTILE = [
    ("plain", "an ordinary single-line value"),
    ("lf-newlines", "first line\nsecond line\nthird line"),
    ("crlf-newlines", "first line\r\nsecond line\r\n"),
    ("bare-cr", "before\rafter"),
    ("single-quotes", "it's a 'quoted' value, isn't it"),
    ("double-quotes", 'he said "yes" twice'),
    ("backslashes", "C:\\Users\\Admin\\dev  and  a\\\\double  and a trailing\\"),
    ("sql-shaped", "'); DROP TABLE facts; --"),
    ("unicode-dashes", "an em dash \u2014 an en dash \u2013 an ellipsis \u2026"),
    ("unicode-wide", "\ud55c\uad6d\uc5b4 \u4e2d\u6587 \u0631\u0628\u064a\u0639"),
    ("tabs", "col1\tcol2\tcol3"),
    ("edge-whitespace", "   leading and trailing   "),
    ("empty-ish", " "),
    ("long-line", "x" * 4000),
    ("mixed", "line one\r\n\ttabbed 'quoted' \u2014 C:\\path\\here\nline three  "),
]

MIN_CASES = 12


def build(db_path: Path, rows) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO facts (category, key, value) VALUES ('trap', ?, ?)", rows
    )
    conn.commit()
    conn.close()


def dump(db_path: Path) -> str:
    """Same read-only dump the real backup performs.

    Closed explicitly: sqlite3's context manager commits, it does not close,
    so `with sqlite3.connect(...)` leaves the file locked. On Windows that
    surfaces later as a PermissionError deleting the temp directory, which
    reads like a test-harness problem rather than the leaked handle it is.
    """
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def restore(sql: str, db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    return conn


def read_back(conn) -> dict:
    return {k: v for k, v in conn.execute("SELECT key, value FROM facts")}


def compare(original: dict, restored: dict):
    """Return a list of (key, why) for everything that did not survive."""
    problems = []
    for key, want in original.items():
        if key not in restored:
            problems.append((key, "missing after restore"))
        elif restored[key] != want:
            problems.append((key, f"{want!r} -> {restored[key]!r}"))
    for key in restored:
        if key not in original:
            problems.append((key, "appeared from nowhere"))
    return problems


def main(tmp: Path) -> int:
    if len(HOSTILE) < MIN_CASES:
        print(f"!! only {len(HOSTILE)} cases defined, expected at least {MIN_CASES}")
        print("   The suite has been gutted; it cannot prove anything.")
        return 2

    original = dict(HOSTILE)
    src = tmp / "source.db"
    build(src, HOSTILE)

    sql = dump(src)
    print(f"  dumped {len(sql):,} bytes covering {len(original)} hostile values")
    if len(sql) < 500:
        print("!! dump is implausibly small -- the dump failed, the data did not")
        return 2

    # --- the real question -------------------------------------------------
    conn = restore(sql, tmp / "restored.db")
    problems = compare(original, read_back(conn))
    conn.close()

    for key, why in problems:
        print(f"  LOST  {key}: {why}")
    print(f"  {len(original) - len(problems)}/{len(original)} values survived intact")

    # --- can this comparison still fail? -----------------------------------
    # Two deliberate corruptions. If either slips through, the comparison has
    # stopped comparing and every result above is worthless.
    print()
    checks_that_must_fail = 0

    # Real newlines, not the two-character escape. SQLite's iterdump writes
    # embedded newlines literally inside quoted strings, so there is no "\n"
    # sequence to substitute -- the first version of this line replaced one
    # that never occurs, corrupted nothing, and the suite correctly accused
    # itself of being broken. This is what core.autocrlf=true does to a
    # checked-out .sql file.
    crlf_sql = sql.replace("\n", "\r\n")
    conn = restore(crlf_sql, tmp / "corrupt1.db")
    if compare(original, read_back(conn)):
        checks_that_must_fail += 1
        print("  PASS  line-ending corruption is detected")
    else:
        print("  FAIL  line-ending corruption slipped through -- comparison is broken")
    conn.close()

    conn = restore(sql, tmp / "corrupt2.db")
    conn.execute("UPDATE facts SET value = value || ' ' WHERE key = 'plain'")
    if compare(original, read_back(conn)):
        checks_that_must_fail += 1
        print("  PASS  a single trailing space is detected")
    else:
        print("  FAIL  a one-character change slipped through -- comparison is broken")
    conn.close()

    if checks_that_must_fail < 2:
        print("\n  SUITE IS BROKEN: the comparison cannot detect corruption.")
        return 2

    print()
    if problems:
        print(f"  {len(problems)} value(s) DID NOT SURVIVE the backup round trip.")
        return 1
    print("  Backup round trip is faithful for every hostile case.")
    return 0


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        raise SystemExit(main(Path(td)))
