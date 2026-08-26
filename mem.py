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


def connect() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"no database at {DB} - run: python -c \"import sqlite3,pathlib; "
                 f"sqlite3.connect('memory.db').executescript(pathlib.Path('schema.sql').read_text())\"")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        "SELECT value FROM facts WHERE category = ? AND key = ?", (args.category, args.key)
    ).fetchone()
    conn.execute(
        "INSERT INTO facts (category,key,value,confidence,source) VALUES (?,?,?,?,?) "
        "ON CONFLICT(category,key) DO UPDATE SET value=excluded.value, "
        "confidence=excluded.confidence, source=excluded.source, updated_at=datetime('now')",
        (args.category, args.key, args.value, args.confidence, args.source),
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
        "INSERT INTO dependencies (project,name,location,source_url,why,critical) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(project,name) DO UPDATE SET "
        "location=excluded.location, source_url=excluded.source_url, why=excluded.why",
        (args.project, args.name, args.location, args.url, args.why, 0 if args.optional else 1),
    )
    conn.commit()
    print(f"  {args.project} -> {args.name}  ({args.location or 'no path'})")
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
            "SELECT name, location, source_url, why, critical FROM dependencies "
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
                lines += [f"- Why: {d['why']}", ""]
        if opt:
            lines += ["## Optional", ""]
            for d in opt:
                loc = f" (`{d['location']}`)" if d["location"] else ""
                lines.append(f"- **{d['name']}**{loc} — {d['why']}")
            lines.append("")

        out = target / "DEPENDENCIES.md"
        text = "\n".join(lines)
        if out.exists() and out.read_text(encoding="utf-8") == text:
            print(f"  {proj['name']}: unchanged")
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
    rows = conn.execute(
        "SELECT location, group_concat(project, '|') AS projects FROM dependencies "
        "WHERE location IS NOT NULL GROUP BY location ORDER BY location"
    ).fetchall()

    written = skipped = 0
    for row in rows:
        loc = row["location"]
        # Skip anything that isn't a real directory on disk: URLs, ports,
        # bare filenames that name a model rather than a path.
        if "://" in loc or not Path(loc).is_dir():
            skipped += 1
            continue

        target = Path(loc)
        projects = sorted(set(row["projects"].split("|")))
        deps = conn.execute(
            "SELECT project, name, why, critical, source_url FROM dependencies "
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

        out = target / "WHAT-USES-THIS.md"
        text = "\n".join(lines)
        try:
            if out.exists() and out.read_text(encoding="utf-8") == text:
                print(f"  {loc}: unchanged")
                continue
            out.write_text(text, encoding="utf-8", newline="\n")
            print(f"  {loc}: wrote WHAT-USES-THIS.md  (needed by {', '.join(projects)})")
            written += 1
        except OSError as exc:
            print(f"  {loc}: FAILED - {exc}")
            skipped += 1

    print(f"\n  {written} written, {skipped} skipped (URLs and non-directories)")
    return 0


def cmd_review(conn, args) -> int:
    """Maintenance. A memory store that is never pruned becomes untrustworthy."""
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

    print("\n=== dependencies whose location is missing on disk ===")
    rows = conn.execute(
        "SELECT project,name,location FROM dependencies WHERE location IS NOT NULL"
    ).fetchall()
    missing = 0
    for r in rows:
        if not Path(r["location"]).exists():
            print(f"  {r['project']} -> {r['name']}  GONE: {r['location']}")
            missing += 1
            issues += 1
    if not missing:
        print("  all present")

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
    conn = connect()
    try:
        return globals()[f"cmd_{args.cmd}"](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
