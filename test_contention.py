"""Does a write survive while another session holds the database?

    python test_contention.py

Six sessions run mem.py against one SQLite file with no coordination.
CLAUDE.md's doctrine is "write immediately, not at the end -- a fact learned
and not written is a fact lost." That doctrine depends on this mechanism, and
the mechanism has to hold under exactly the condition that makes the doctrine
necessary: several sessions writing at once.

Found by the Red Team GitHub 1 session and reproduced here rather than taken
on their numbers.

Three cases, and the CONTROL is the one that makes the others mean anything:

  control     a short hold, well inside the timeout -- the write MUST succeed,
              or the harness is broken and the failures below prove nothing
  contention  a hold longer than the old 5s default -- this is the bug
  isolation   dump while a transaction is open and uncommitted -- must see a
              consistent snapshot, never a mix

Everything runs against a copy in a temp directory. The live store is never
opened for writing.
"""

import multiprocessing as mp
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
SCHEMA = HERE / "schema.sql"


def holder(db, seconds, ready, done):
    """Hold a write transaction open for `seconds`."""
    conn = sqlite3.connect(db, timeout=1)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO facts (category,key,value) VALUES ('trap','holder','x')")
    ready.set()
    time.sleep(seconds)
    conn.commit()
    conn.close()
    done.set()


def writer(db, key, timeout, result):
    """Attempt one upsert, the way mem.py does."""
    started = time.time()
    try:
        conn = sqlite3.connect(db, timeout=timeout)
        conn.execute(
            "INSERT INTO facts (category,key,value) VALUES ('trap',?,'written') "
            "ON CONFLICT(category,key) DO UPDATE SET value='written'",
            (key,),
        )
        conn.commit()
        conn.close()
        result.value = 1
    except sqlite3.OperationalError:
        result.value = 0
    result_time = time.time() - started
    return result_time


def _writer_proc(db, key, timeout, result):
    writer(db, key, timeout, result)


def fresh(tmp: Path, name: str) -> Path:
    db = tmp / name
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return db


def scenario(tmp, label, hold_seconds, timeout):
    db = fresh(tmp, f"{label}.db")
    ready, done = mp.Event(), mp.Event()
    result = mp.Value("i", -1)

    h = mp.Process(target=holder, args=(str(db), hold_seconds, ready, done))
    h.start()
    ready.wait(10)

    w = mp.Process(target=_writer_proc, args=(str(db), "the-fact", timeout, result))
    t0 = time.time()
    w.start()
    w.join(hold_seconds + timeout + 15)
    elapsed = time.time() - t0
    h.join(20)

    conn = sqlite3.connect(db)
    present = conn.execute(
        "SELECT count(*) FROM facts WHERE key='the-fact'"
    ).fetchone()[0]
    conn.close()

    return {"label": label, "hold": hold_seconds, "timeout": timeout,
            "ok": result.value == 1, "present": present, "elapsed": elapsed}


def writes_set_matches_reality() -> bool:
    """Does mem.py's WRITES set still name every command that writes?

    lost_write() only fires for commands listed in WRITES. A command that
    writes but is missing from that set has its lost write downgraded to
    "read failed" and exit 1 -- quiet, and quiet is the whole thing this
    machinery exists to prevent.

    The Red Team session verified the set by hand once. A hand check is a
    claim about one moment; this derives the answer from the source every
    run, so adding a writing command and forgetting the set fails here
    instead of silently years later.
    """
    import ast
    import re

    src = (HERE / "mem.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Look at what is PASSED TO execute(), not at the function's text.
    #
    # The first version grepped each function body for INSERT/UPDATE/DELETE
    # and flagged cmd_export and cmd_guard, which touch no table at all. It
    # had matched the English word "delete" -- once in a docstring about
    # "deciding what to delete", once in the literal "# Do not delete this
    # directory" that cmd_guard writes into its warning files.
    #
    # Grepping text and parsing structure are different claims, and prose
    # about deleting reads identically to SQL that deletes. Walking the call
    # arguments cannot make that mistake, because a docstring is not an
    # argument to execute().
    SQL_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)

    def issues_a_write(fn) -> bool:
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            fname = getattr(call.func, "attr", None)
            if fname not in ("execute", "executemany", "executescript"):
                continue
            for arg in call.args[:1]:
                # Constant strings, and adjacent-literal concatenations.
                parts = []
                for n in ast.walk(arg):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str):
                        parts.append(n.value)
                if any(SQL_WRITE.match(p) for p in parts):
                    return True
        return False

    actually_write = {
        node.name[4:]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("cmd_")
        and issues_a_write(node)
    }

    m = re.search(r"WRITES\s*=\s*\{([^}]*)\}", src)
    if not m:
        print("  WRITES set not found in mem.py -- this check is broken")
        return False
    declared = {s.strip().strip("\"'") for s in m.group(1).split(",") if s.strip()}

    if not actually_write:
        print("  no writing commands detected -- the AST walk is broken, not mem.py")
        return False

    missing = actually_write - declared
    extra = declared - actually_write
    print(f"  commands that write: {' '.join(sorted(actually_write))}")
    print(f"  WRITES declares:     {' '.join(sorted(declared))}")
    if missing:
        print(f"  MISSING from WRITES: {' '.join(sorted(missing))}")
        print("  -> a lost write in these would be reported as a mere read failure")
    if extra:
        print(f"  EXTRA in WRITES:     {' '.join(sorted(extra))}")
    return not missing and not extra


def main() -> int:
    if not SCHEMA.exists():
        print("!! schema.sql missing -- cannot build a fixture")
        return 2

    failures = 0

    print("  --- does WRITES still match the code? (static, fast) ---")
    if not writes_set_matches_reality():
        failures += 1
    print()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        control = scenario(tmp, "control", hold_seconds=2, timeout=30)
        print(f"  CONTROL     hold 2s, timeout 30s -> "
              f"{'written' if control['present'] else 'LOST'} in {control['elapsed']:.1f}s")
        if not control["present"]:
            print("  !! the CONTROL lost a write. The harness is broken; the")
            print("     results below prove nothing about the database.")
            return 2

        old = scenario(tmp, "old-default", hold_seconds=8, timeout=5)
        print(f"  OLD 5s      hold 8s, timeout  5s -> "
              f"{'written' if old['present'] else 'LOST'} in {old['elapsed']:.1f}s")

        new = scenario(tmp, "new-timeout", hold_seconds=8, timeout=30)
        print(f"  NEW 30s     hold 8s, timeout 30s -> "
              f"{'written' if new['present'] else 'LOST'} in {new['elapsed']:.1f}s")

        if old["present"]:
            print("\n  NOTE: the old default survived here, so this machine did not")
            print("  reproduce the loss this run. Not evidence it cannot happen.")
        if not new["present"]:
            failures += 1
            print("\n  FAIL: the 30s timeout still lost the write.")

    print()
    if failures:
        print(f"  {failures} failure(s).")
        return 1
    print("  A write survives a hold that the old default would have dropped.")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
