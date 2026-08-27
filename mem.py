"""mem - memory management for the structured-memory database.

Read before deriving. Write when you learn something durable. Review
periodically so the store stays trustworthy rather than merely large.

    python mem.py status                       what is in here
    python mem.py recall trap                  all traps
    python mem.py recall trap vram             traps matching "vram"
    python mem.py search cublas                across every table
    python mem.py remember trap foo "bar"      upsert a fact
    python mem.py log error "what broke"       append an event
    python mem.py dep dr-companion Ruby4Lich5 --location C:\\Ruby4Lich5 --why "..."
    python mem.py project ghost-front --status published
    python mem.py review                       maintenance report
    python mem.py forget trap foo              delete a fact

Every write prints what changed. Nothing is silent.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent / "memory.db"

CATEGORIES = ("user", "project", "reference", "feedback", "trap", "tool")
KINDS = ("decision", "error", "milestone", "removal", "install")
CONFIDENCE = ("verified", "reported", "inferred")


# Six sessions write to this file with no coordination. Python's default is
# 5.0s, and a hold longer than that raises OperationalError and DROPS the
# write. Measured: an 8s hold against the 5s default lost the row after 5.6s;
# the same hold with 30s wrote it at 8.1s, and a 2s control wrote it either
# way, so the failure was real and not the harness.
#
# This is the mechanism CLAUDE.md's "write immediately, a fact learned and not
# written is a fact lost" depends on, and it was failing under exactly the
# condition that makes that rule necessary. A >5s write is not exotic here:
# `mem guard` and `mem export` write files inside a transaction, and the GPU
# has sat at 100% all day.
BUSY_TIMEOUT = 30.0


def connect() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"no database at {DB} - run: python -c \"import sqlite3,pathlib; "
                 f"sqlite3.connect('memory.db').executescript(pathlib.Path('schema.sql').read_text())\"")
    conn = sqlite3.connect(DB, timeout=BUSY_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT * 1000)}")
    return conn


def lost_write(exc: Exception, what: str) -> int:
    """Report a dropped write so loudly it cannot be skimmed past.

    A raw traceback is loud enough for someone watching, and invisible to a
    session that ran `mem remember` as step four of a nine-step turn. The
    failure mode that matters is not the crash: it is that a fact which was
    never recorded looks exactly like one that was.
    """
    bar = "!" * 68
    print(f"\n{bar}", file=sys.stderr)
    print("  THE WRITE DID NOT HAPPEN. NOTHING WAS SAVED.", file=sys.stderr)
    print(f"  {what}", file=sys.stderr)
    print(f"  reason: {exc}", file=sys.stderr)
    print(f"  waited {BUSY_TIMEOUT:.0f}s for another session to release the store.", file=sys.stderr)
    print("  RUN THE COMMAND AGAIN. Do not treat this turn as recorded.", file=sys.stderr)
    print(f"{bar}\n", file=sys.stderr)
    return 3


def wrap(text: str, width: int = 76, indent: str = "      ") -> str:
    """Wrap long values so recall output stays readable."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return f"\n{indent}".join(lines)


# --------------------------------------------------------------------------


def cmd_status(conn, args) -> int:
    print(f"  {DB}\n")
    for table in ("facts", "events", "projects", "dependencies"):
        n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<14} {n:>5}")
    print("\n  facts by category")
    for r in conn.execute(
        "SELECT category, count(*) n FROM facts GROUP BY category ORDER BY n DESC"
    ):
        print(f"    {r['category']:<12} {r['n']:>4}")
    last = conn.execute("SELECT ts, kind, summary FROM events ORDER BY ts DESC LIMIT 3").fetchall()
    if last:
        print("\n  recent events")
        for r in last:
            print(f"    {r['ts'][:16]}  {r['kind']:<10} {r['summary'][:44]}")
    return 0


def cmd_recall(conn, args) -> int:
    sql = "SELECT * FROM facts"
    params, where = [], []
    if args.category:
        where.append("category = ?")
        params.append(args.category)
    if args.pattern:
        where.append("(key LIKE ? OR value LIKE ?)")
        params += [f"%{args.pattern}%"] * 2
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY category, key"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("  nothing matched")
        return 1
    for r in rows:
        flag = "" if r["confidence"] == "verified" else f"  [{r['confidence']}]"
        print(f"\n  {r['category']}/{r['key']}{flag}")
        print(f"      {wrap(r['value'])}")
        if r["source"]:
            print(f"      source: {r['source']}  updated: {r['updated_at'][:10]}")
    print()
    return 0


def cmd_search(conn, args) -> int:
    t = f"%{args.term}%"
    hits = 0
    rows = conn.execute(
        "SELECT category, key, value FROM facts WHERE key LIKE ? OR value LIKE ?", (t, t)
    ).fetchall()
    if rows:
        print("  facts")
        for r in rows:
            print(f"    {r['category']}/{r['key']}: {r['value'][:64]}")
            hits += 1
    rows = conn.execute(
        "SELECT ts, kind, summary FROM events WHERE summary LIKE ? OR detail LIKE ? "
        "ORDER BY ts DESC LIMIT 10", (t, t)
    ).fetchall()
    if rows:
        print("\n  events")
        for r in rows:
            print(f"    {r['ts'][:16]} {r['kind']}: {r['summary'][:60]}")
            hits += 1
    rows = conn.execute(
        "SELECT project, name, location, why FROM dependencies "
        "WHERE name LIKE ? OR why LIKE ? OR location LIKE ?", (t, t, t)
    ).fetchall()
    if rows:
        print("\n  dependencies")
        for r in rows:
            print(f"    {r['project']} -> {r['name']} ({r['location']})")
            hits += 1
    rows = conn.execute(
        "SELECT name, path, repo, notes FROM projects WHERE name LIKE ? OR notes LIKE ?", (t, t)
    ).fetchall()
    if rows:
        print("\n  projects")
        for r in rows:
            print(f"    {r['name']}: {r['notes'] or ''}")
            hits += 1
    print(f"\n  {hits} hit(s)")
    return 0 if hits else 1


def cmd_remember(conn, args) -> int:
    existing = conn.execute(
        "SELECT value, check_cmd FROM facts WHERE category = ? AND key = ?",
        (args.category, args.key),
    ).fetchone()
    check = getattr(args, "check", None)
    # COALESCE below protects a check from being erased by an unrelated edit,
    # which left no way to remove a WRONG one -- three rows held prose that a
    # runner then tried to execute as a command. --clear-check is the explicit
    # escape hatch; the sentinel survives COALESCE and is normalised to NULL.
    if getattr(args, "clear_check", False):
        check = ""
    # COALESCE, not excluded.check_cmd: updating a fact's wording without
    # passing --check must not silently delete the command that verifies it.
    # Erasing a check while editing prose is exactly how a row goes back to
    # being a claim nobody can re-derive.
    conn.execute(
        "INSERT INTO facts (category,key,value,confidence,source,check_cmd) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(category,key) DO UPDATE SET value=excluded.value, "
        "confidence=excluded.confidence, source=excluded.source, "
        "check_cmd=CASE WHEN excluded.check_cmd = '' THEN NULL "
        "ELSE COALESCE(excluded.check_cmd, facts.check_cmd) END, "
        "updated_at=datetime('now')",
        (args.category, args.key, args.value, args.confidence, args.source, check),
    )
    conn.commit()
    if existing and existing["value"] != args.value:
        print(f"  updated {args.category}/{args.key}")
        print(f"    was: {existing['value'][:70]}")
        print(f"    now: {args.value[:70]}")
    elif existing:
        print(f"  unchanged {args.category}/{args.key}")
    else:
        print(f"  added {args.category}/{args.key}  [{args.confidence}]")

    if getattr(args, "clear_check", False):
        # Report the erasure, not the value that was erased. `check or
        # existing` printed the OLD command here, so a successful clear
        # announced the thing it had just removed.
        print("    check command CLEARED")
        return 0

    kept = check or (existing["check_cmd"] if existing else None)
    if kept:
        print(f"    verify: {kept}")
    elif args.category in ("trap", "tool", "reference"):
        print("    no --check: a reader can only believe this row, not test it")
    return 0


def cmd_forget(conn, args) -> int:
    cur = conn.execute(
        "DELETE FROM facts WHERE category = ? AND key = ?", (args.category, args.key)
    )
    conn.commit()
    print(f"  {'deleted' if cur.rowcount else 'no such fact'}: {args.category}/{args.key}")
    return 0 if cur.rowcount else 1


def cmd_log(conn, args) -> int:
    conn.execute(
        "INSERT INTO events (session,kind,summary,detail) VALUES (?,?,?,?)",
        (args.session, args.kind, args.summary, args.detail),
    )
    conn.commit()
    print(f"  logged {args.kind}: {args.summary}")
    return 0


def cmd_dep(conn, args) -> int:
    conn.execute(
        "INSERT INTO dependencies (project,name,location,source_url,why,critical,check_cmd) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(project,name) DO UPDATE SET "
        "location=excluded.location, source_url=excluded.source_url, why=excluded.why, "
        "check_cmd=coalesce(excluded.check_cmd, dependencies.check_cmd)",
        (args.project, args.name, args.location, args.url, args.why,
         0 if args.optional else 1, args.check),
    )
    conn.commit()
    print(f"  {args.project} -> {args.name}  ({args.location or 'no path'})")
    if not args.check:
        existing = conn.execute(
            "SELECT check_cmd FROM dependencies WHERE project=? AND name=?",
            (args.project, args.name),
        ).fetchone()
        if not (existing and existing["check_cmd"]):
            # A claim about what exists rots the moment the world moves and
            # looks equally authoritative afterwards. A command does not.
            print("  NOTE: no --check recorded. A reader cannot verify this row,")
            print("        only believe it. Add the command that establishes it.")
    return 0


def cmd_project(conn, args) -> int:
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (args.name,)).fetchone()
    if not any([args.path, args.repo, args.stack, args.status, args.notes]):
        if not row:
            print(f"  no project '{args.name}'")
            return 1
        for k in row.keys():
            if row[k]:
                print(f"  {k:<12} {row[k]}")
        deps = conn.execute(
            "SELECT name, location, why, critical FROM dependencies WHERE project = ?", (args.name,)
        ).fetchall()
        if deps:
            print("\n  dependencies")
            for d in deps:
                mark = "!" if d["critical"] else " "
                print(f"   {mark} {d['name']:<16} {d['location'] or ''}")
                print(f"      {wrap(d['why'])}")
        return 0

    fields = {"path": args.path, "repo": args.repo, "stack": args.stack,
              "status": args.status, "notes": args.notes}
    if row:
        sets = {k: v for k, v in fields.items() if v is not None}
        conn.execute(
            f"UPDATE projects SET {', '.join(f'{k}=?' for k in sets)} WHERE name=?",
            (*sets.values(), args.name),
        )
        print(f"  updated {args.name}: {', '.join(sets)}")
    else:
        conn.execute(
            "INSERT INTO projects (name,path,repo,stack,status,notes) VALUES (?,?,?,?,?,?)",
            (args.name, args.path, args.repo, args.stack, args.status or "active", args.notes),
        )
        print(f"  added project {args.name}")
    conn.commit()
    return 0


def cmd_export(conn, args) -> int:
    """Write DEPENDENCIES.md into each project directory.

    A database only defends a session that thinks to query it. A file in the
    directory reaches whoever is standing there deciding what to delete --
    which is the person who actually causes the damage. Generated from the
    database so the two cannot drift.
    """
    rows = conn.execute(
        "SELECT p.name, p.path, p.repo FROM projects p "
        "WHERE EXISTS (SELECT 1 FROM dependencies d WHERE d.project = p.name)"
        + (" AND p.name = ?" if args.project else "")
        + " ORDER BY p.name",
        (args.project,) if args.project else (),
    ).fetchall()

    if not rows:
        print("  no projects with recorded dependencies" +
              (f" matching '{args.project}'" if args.project else ""))
        return 1

    written = skipped = 0
    for proj in rows:
        if not proj["path"]:
            print(f"  {proj['name']}: no path recorded, skipped")
            skipped += 1
            continue
        target = Path(proj["path"])
        if not target.exists():
            print(f"  {proj['name']}: path missing on disk, skipped ({target})")
            skipped += 1
            continue

        deps = conn.execute(
            "SELECT name, location, source_url, why, critical, check_cmd FROM dependencies "
            "WHERE project = ? ORDER BY critical DESC, name", (proj["name"],)
        ).fetchall()

        lines = [
            f"# {proj['name']} — external dependencies",
            "",
            "**None of this is declared in `package.json`, `Cargo.toml`, or any",
            "other manifest in this repository.** If you are cleaning up this",
            "machine, these look like unrelated clutter and are not.",
            "",
            "Generated from the shared memory database. Edit there, not here:",
            "`python C:\\Users\\Admin\\dev\\memory-db\\mem.py dep " + proj["name"] + " NAME --why \"...\"`",
            "",
        ]
        crit = [d for d in deps if d["critical"]]
        opt = [d for d in deps if not d["critical"]]

        if crit:
            lines += ["## Required", ""]
            for d in crit:
                lines.append(f"### {d['name']}")
                lines.append("")
                if d["location"]:
                    lines.append(f"- Location: `{d['location']}`")
                if d["source_url"]:
                    lines.append(f"- Source: {d['source_url']}")
                lines.append(f"- Why: {d['why']}")
                if d["check_cmd"]:
                    lines.append(f"- Verify: `{d['check_cmd']}`")
                lines.append("")
        if opt:
            lines += ["## Optional", ""]
            for d in opt:
                loc = f" (`{d['location']}`)" if d["location"] else ""
                lines.append(f"- **{d['name']}**{loc} — {d['why']}")
            lines.append("")

        out = target / "DEPENDENCIES.md"
        text = "\n".join(lines)
        if out.exists() and out.read_text(encoding="utf-8") == text:
            # Content is current; only the timestamp lies. Touch it so the
            # staleness check in `review` can actually be cleared -- a check
            # that stays lit after the fix is as useless as one that never fires.
            out.touch()
            print(f"  {proj['name']}: unchanged (timestamp refreshed)")
            continue
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"  {proj['name']}: wrote {out}  ({len(crit)} required, {len(opt)} optional)")
        written += 1

    print(f"\n  {written} written, {skipped} skipped")
    return 0


def cmd_guard(conn, args) -> int:
    """Write WHAT-USES-THIS.md into each dependency's own directory.

    `export` puts the list in the project, which reaches someone reading the
    project. It does not reach someone standing in C:\\Ruby4Lich5 deciding
    whether that folder is game clutter -- which is where the deletion
    actually happened. The warning belongs where the destructive action
    occurs, not where the dependency is declared and not where the reader is
    already being careful.
    """
    # Denominator first. "No problems found" and "nothing was checked" print
    # identically unless you make them different -- and the second is the more
    # dangerous state, because it looks like success.
    total_deps = conn.execute("SELECT count(*) FROM dependencies").fetchone()[0]
    with_loc = conn.execute(
        "SELECT count(*) FROM dependencies WHERE location IS NOT NULL"
    ).fetchone()[0]

    if total_deps == 0:
        print("  NOTHING TO CHECK - the dependencies table is empty.")
        print("  This is not a pass. Either nothing has been recorded yet, or the")
        print("  table was lost. Verify before treating this as clean.")
        return 1

    print(f"  checking {with_loc} of {total_deps} dependencies (those with a location)\n")

    rows = conn.execute(
        "SELECT location, group_concat(project, '|') AS projects FROM dependencies "
        "WHERE location IS NOT NULL GROUP BY location ORDER BY location"
    ).fetchall()

    written = 0
    unprotected: list[tuple[str, str, str]] = []   # (location, projects, reason)
    thin: list[tuple[str, str, int]] = []          # (project, name, why length)

    # A dependency whose why is a single short sentence produces a warning
    # nobody stops for. Generating from a database moves the accuracy problem
    # to the row; it does not remove it. Treat a thin row as a defect.
    THIN_WHY = 80

    for row in rows:
        loc = row["location"]
        projects = ", ".join(sorted(set(row["projects"].split("|"))))

        # A URL has no directory to warn in -- expected, but still means this
        # dependency has no colocated protection.
        if "://" in loc:
            unprotected.append((loc, projects, "network endpoint, no directory exists"))
            continue

        # Anything else that is not a directory is a RECORDING defect, not
        # housekeeping. A bare filename means guard silently protects nothing.
        if not Path(loc).is_dir():
            parent = Path(loc).parent
            hint = (f"not a directory - did you mean {parent}?"
                    if str(parent) not in (".", "") and parent.is_dir()
                    else "not a directory on disk")
            unprotected.append((loc, projects, hint))
            continue

        target = Path(loc)
        projects = sorted(set(row["projects"].split("|")))
        deps = conn.execute(
            "SELECT project, name, why, critical, source_url, check_cmd FROM dependencies "
            "WHERE location = ? ORDER BY critical DESC, project", (loc,)
        ).fetchall()

        lines = [
            "# Do not delete this directory",
            "",
            f"`{loc}` is a dependency of "
            + ", ".join(f"**{p}**" for p in projects) + ".",
            "",
            "It looks like unrelated software from outside. It is not.",
            "",
        ]
        for d in deps:
            lines.append(f"## {d['project']} needs it")
            lines.append("")
            lines.append(d["why"])
            lines.append("")
            # Write the check, not the claim. A statement about what exists
            # rots silently; a command tells the truth every time it is run.
            if d["check_cmd"]:
                lines += ["Verify for yourself:", "", "```", d["check_cmd"], "```", ""]
            if d["source_url"]:
                lines += [f"Reinstall from: {d['source_url']}", ""]

        lines += [
            "---",
            "",
            "Generated from the shared memory database at",
            "`C:\\Users\\Admin\\dev\\memory-db`. To change what this says, edit there",
            "and re-run `python mem.py guard` -- editing this file directly will be",
            "overwritten.",
            "",
        ]

        for d in deps:
            if len(d["why"] or "") < THIN_WHY:
                thin.append((d["project"], d["name"], len(d["why"] or "")))

        out = target / "WHAT-USES-THIS.md"
        text = "\n".join(lines)
        try:
            if out.exists() and out.read_text(encoding="utf-8") == text:
                out.touch()
                print(f"  ok       {loc}  (unchanged, timestamp refreshed)")
                continue
            out.write_text(text, encoding="utf-8", newline="\n")
            print(f"  wrote    {loc}  (needed by {', '.join(projects)})")
            written += 1
        except OSError as exc:
            unprotected.append((loc, ", ".join(projects), f"write failed: {exc.strerror}"))

    print(f"\n  {written} written")

    # A silent skip reads as housekeeping. It means a dependency has no
    # colocated protection at all -- which is how the FLUX licence warning,
    # the one with an actual legal consequence, ended up existing nowhere.
    if unprotected:
        print(f"\n  UNPROTECTED - {len(unprotected)} dependency location(s) have no warning file:")
        for loc, projects, reason in unprotected:
            print(f"    {loc}")
            print(f"      needed by {projects}")
            print(f"      {reason}")
        print("\n    Fix by pointing location at the containing directory:")
        print("      python mem.py dep PROJECT NAME --location <dir> --why \"...\"")

    if thin:
        print(f"\n  THIN - {len(thin)} row(s) produce a warning too short to stop anyone:")
        for project, name, n in sorted(set(thin)):
            print(f"    {project} -> {name}  ({n} chars of 'why')")
        print("\n    Generating from a database moves the accuracy problem to the row,")
        print("    it does not remove it. A one-line why is the same defect as an")
        print("    empty warning, just harder to see.")

    return 1 if (unprotected or thin) else 0



def classify_location(loc: str):
    """Decide what a dependency's `location` actually is before judging it.

    Returns (state, detail); state is one of:
      ok         -- resolves on this machine
      gone       -- a path shape that does not resolve
      unchecked  -- not a single filesystem path; cannot be judged from here

    Two bugs shaped this, in order.

    First, `Path(loc).exists()` was called on every row, so a URL, a prose
    note, a wildcard and a relative path all reported "GONE" identically --
    six rows, six false positives. A warning list where everything is a
    false positive teaches the reader to skim it, which is how the one real
    GONE row gets missed.

    Then the fix over-corrected: a prose heuristic looking for " and "
    matched a real directory named "Legacy builds and Assets...", quietly
    demoting a checkable path to unchecked. So the filesystem is asked
    first and the prose heuristics are only a fallback for strings that
    have already failed to resolve. Guess last, look first.
    """
    loc = (loc or "").strip()
    if not loc:
        return "unchecked", "empty"

    if "://" in loc:
        return "unchecked", "URL, not a path"

    # Wildcards need globbing; Path.exists() compares the literal asterisk.
    if any(ch in loc for ch in "*?["):
        pat = Path(loc)
        try:
            if pat.parent.is_dir():
                return ("ok", loc) if any(pat.parent.glob(pat.name))                        else ("gone", f"no match for {loc}")
        except OSError:
            return "unchecked", "cannot glob"
        return "gone", f"containing directory absent: {pat.parent}"

    p = Path(loc)
    try:
        if p.exists():
            return "ok", loc
    except OSError:
        return "unchecked", "invalid path syntax"

    # A relative path was written relative to something. Try the obvious
    # anchors before declaring a live file dead.
    if not p.is_absolute():
        for anchor in (Path.home(), Path("C:/")):
            try:
                if (anchor / p).exists():
                    return "ok", str(anchor / p)
            except OSError:
                pass

    # Only now, having failed to resolve it, ask whether it was ever a path.
    if " and " in loc or loc.lower().startswith("hardcoded"):
        return "unchecked", "prose, or several locations in one field"
    if not p.is_absolute():
        return "unchecked", f"relative path, no anchor found: {loc}"

    return "gone", loc

def cmd_review(conn, args) -> int:
    """Maintenance. A memory store that is never pruned becomes untrustworthy."""
    counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("facts", "events", "projects", "dependencies")}

    if counts["facts"] == 0 and counts["projects"] == 0:
        print("  NOTHING TO REVIEW - facts and projects are both empty.")
        print("  Every check below would report clean against an empty store, which")
        print("  is indistinguishable from a healthy one. Verify the database first.")
        return 1

    print("  reviewing " + ", ".join(f"{n} {t}" for t, n in counts.items()) + "\n")
    issues = 0

    print("=== unverified facts (confirm or downgrade) ===")
    rows = conn.execute(
        "SELECT category,key,confidence,source FROM facts WHERE confidence <> 'verified' "
        "ORDER BY category, key"
    ).fetchall()
    for r in rows:
        print(f"  [{r['confidence']}] {r['category']}/{r['key']}  ({r['source'] or 'no source'})")
        issues += 1
    if not rows:
        print("  none")

    print("\n=== facts not touched in 90 days ===")
    rows = conn.execute(
        "SELECT category,key,updated_at FROM facts "
        "WHERE updated_at < datetime('now','-90 days') ORDER BY updated_at"
    ).fetchall()
    for r in rows:
        print(f"  {r['updated_at'][:10]}  {r['category']}/{r['key']}")
        issues += 1
    if not rows:
        print("  none")

    print("\n=== near-duplicate keys within a category ===")
    rows = conn.execute("SELECT category, key FROM facts ORDER BY category, key").fetchall()
    seen, dupes = {}, 0
    for r in rows:
        norm = r["key"].replace("-", "").replace("_", "").lower()
        prior = seen.get((r["category"], norm))
        if prior:
            print(f"  {r['category']}: '{prior}' vs '{r['key']}'")
            dupes += 1
            issues += 1
        seen[(r["category"], norm)] = r["key"]
    if not dupes:
        print("  none")

    # Write the check, not the claim. A row with no verification command can
    # only be believed, never re-derived, and it stays authoritative long
    # after it stops being true.
    print("\n=== dependencies with no verification command ===")
    rows = conn.execute(
        "SELECT project, name FROM dependencies "
        "WHERE check_cmd IS NULL OR check_cmd = '' ORDER BY project, name"
    ).fetchall()
    for r in rows:
        print(f"  {r['project']} -> {r['name']}")
        issues += 1
    if not rows:
        print("  all verifiable")
    else:
        print('\n    A reader can only believe these. Add the command that')
        print('    establishes it:  mem dep PROJECT NAME --check "..."')

    print("\n=== dependencies whose location is missing on disk ===")
    rows = conn.execute(
        "SELECT project,name,location FROM dependencies WHERE location IS NOT NULL"
    ).fetchall()
    missing = unverifiable = 0
    for r in rows:
        state, detail = classify_location(r["location"])
        if state == "gone":
            print(f"  {r['project']} -> {r['name']}  GONE: {detail}")
            missing += 1
            issues += 1
        elif state == "unchecked":
            unverifiable += 1
            print(f"  {r['project']} -> {r['name']}  NOT CHECKED: {detail}")
    if not missing:
        print("  none confirmed missing")
    if unverifiable:
        print("")
        print(f"    {unverifiable} location(s) above are not filesystem paths.")
        print("    They were not checked. Absence of a warning is not evidence")
        print("    they are present -- give those rows a --check command.")

    # Generating from a source does not help if nothing re-runs it. A file
    # cannot drift from its row while it is being written, and drifts for as
    # long as it is not. Caught after a generated DEPENDENCIES.md landed in
    # another repo carrying a claim the database had already corrected.
    print("\n=== generated files older than the rows they came from ===")
    import datetime as _dt

    stale = 0
    for proj in conn.execute(
        "SELECT p.name, p.path, max(d.updated_at) AS newest FROM projects p "
        "JOIN dependencies d ON d.project = p.name "
        "WHERE p.path IS NOT NULL GROUP BY p.name"
    ):
        f = Path(proj["path"]) / "DEPENDENCIES.md"
        if not f.exists() or not proj["newest"]:
            continue
        row_time = _dt.datetime.fromisoformat(proj["newest"]).replace(tzinfo=_dt.timezone.utc)
        file_time = _dt.datetime.fromtimestamp(f.stat().st_mtime, _dt.timezone.utc)
        if file_time < row_time:
            print(f"  {proj['name']}: DEPENDENCIES.md is older than its rows")
            print(f"      file {file_time:%Y-%m-%d %H:%M}  rows {row_time:%Y-%m-%d %H:%M}")
            stale += 1
            issues += 1

    for dep in conn.execute(
        "SELECT location, max(updated_at) AS newest FROM dependencies "
        "WHERE location IS NOT NULL GROUP BY location"
    ):
        loc = dep["location"]
        if "://" in loc or not Path(loc).is_dir():
            continue
        f = Path(loc) / "WHAT-USES-THIS.md"
        if not f.exists() or not dep["newest"]:
            continue
        row_time = _dt.datetime.fromisoformat(dep["newest"]).replace(tzinfo=_dt.timezone.utc)
        file_time = _dt.datetime.fromtimestamp(f.stat().st_mtime, _dt.timezone.utc)
        if file_time < row_time:
            print(f"  {loc}: WHAT-USES-THIS.md is older than its rows")
            stale += 1
            issues += 1

    if not stale:
        print("  all current")
    else:
        print("\n    Fix: python mem.py export && python mem.py guard")

    print("\n=== projects whose path is missing on disk ===")
    rows = conn.execute("SELECT name, path FROM projects WHERE path IS NOT NULL").fetchall()
    gone = 0
    for r in rows:
        if not Path(r["path"]).exists():
            print(f"  {r['name']}  GONE: {r['path']}")
            gone += 1
            issues += 1
    if not gone:
        print("  all present")

    print(f"\n  {issues} item(s) needing attention")
    return 0


# --------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(prog="mem", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="what is in the store")

    s = sub.add_parser("recall", help="query facts")
    s.add_argument("category", nargs="?", choices=CATEGORIES)
    s.add_argument("pattern", nargs="?")

    s = sub.add_parser("search", help="search every table")
    s.add_argument("term")

    s = sub.add_parser("remember", help="upsert a fact")
    s.add_argument("category", choices=CATEGORIES)
    s.add_argument("key")
    s.add_argument("value")
    s.add_argument("--confidence", choices=CONFIDENCE, default="verified")
    s.add_argument("--source")
    s.add_argument("--check", help="command that establishes this fact, so a "
                                   "reader can re-derive it instead of believing it")
    s.add_argument("--clear-check", action="store_true",
                   help="remove a wrong check command (COALESCE otherwise keeps it)")

    s = sub.add_parser("forget", help="delete a fact")
    s.add_argument("category", choices=CATEGORIES)
    s.add_argument("key")

    s = sub.add_parser("log", help="append an event")
    s.add_argument("kind", choices=KINDS)
    s.add_argument("summary")
    s.add_argument("detail", nargs="?")
    s.add_argument("--session")

    s = sub.add_parser("dep", help="record an external dependency")
    s.add_argument("project")
    s.add_argument("name")
    s.add_argument("--location")
    s.add_argument("--url")
    s.add_argument("--why", required=True)
    s.add_argument("--check", help="command that VERIFIES this, not the answer it gave once")
    s.add_argument("--optional", action="store_true")

    s = sub.add_parser("project", help="show or update a project")
    s.add_argument("name")
    s.add_argument("--path")
    s.add_argument("--repo")
    s.add_argument("--stack")
    s.add_argument("--status", choices=("active", "paused", "archived", "published"))
    s.add_argument("--notes")

    s = sub.add_parser("export", help="write DEPENDENCIES.md into project directories")
    s.add_argument("project", nargs="?", help="one project, or omit for all")

    sub.add_parser("guard", help="write WHAT-USES-THIS.md into dependency directories")

    sub.add_parser("review", help="maintenance report")

    args = p.parse_args()
    WRITES = {"remember", "forget", "log", "dep", "project"}
    try:
        conn = connect()
    except sqlite3.OperationalError as e:
        return lost_write(e, f"mem {args.cmd}: could not even open the store")

    try:
        return globals()[f"cmd_{args.cmd}"](conn, args)
    except sqlite3.OperationalError as e:
        # Only a write can lose data. A blocked read is an inconvenience.
        if args.cmd in WRITES:
            detail = " ".join(str(getattr(args, f, "")) for f in ("category", "key", "kind", "summary", "name") if getattr(args, f, None))
            return lost_write(e, f"mem {args.cmd} {detail}".strip())
        print(f"  read failed: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
