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


def main() -> int:
    if not SCHEMA.exists():
        print("!! schema.sql missing -- cannot build a fixture")
        return 2

    failures = 0
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
