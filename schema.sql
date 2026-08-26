-- Structured memory for Claude sessions on this machine.
-- Complements the markdown files in .claude/projects/*/memory/ — those are
-- loaded automatically at session start; this is for anything queryable,
-- accumulating, or too granular to belong in a file that gets read every time.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Durable facts. One row per fact, unique on (category, key).
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY,
    category    TEXT NOT NULL CHECK (category IN
                  ('user','project','reference','feedback','trap','tool')),
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    confidence  TEXT DEFAULT 'verified' CHECK (confidence IN
                  ('verified','reported','inferred')),
    source      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (category, key)
);

CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);

-- Things that happened. Append-only.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL DEFAULT (datetime('now')),
    session     TEXT,
    kind        TEXT NOT NULL CHECK (kind IN
                  ('decision','error','milestone','removal','install')),
    summary     TEXT NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

-- Project state. Cheaper than walking the filesystem every session.
CREATE TABLE IF NOT EXISTS projects (
    name        TEXT PRIMARY KEY,
    path        TEXT,
    repo        TEXT,
    stack       TEXT,
    status      TEXT DEFAULT 'active' CHECK (status IN
                  ('active','paused','archived','published')),
    notes       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- External dependencies that no manifest captures.
-- Exists because Ruby4Lich5 was removed as apparent clutter; it is a hard
-- dependency of dr-companion and nothing on the machine said so.
CREATE TABLE IF NOT EXISTS dependencies (
    id          INTEGER PRIMARY KEY,
    project     TEXT NOT NULL,
    name        TEXT NOT NULL,
    location    TEXT,
    source_url  TEXT,
    why         TEXT NOT NULL,
    critical    INTEGER NOT NULL DEFAULT 1,
    UNIQUE (project, name),
    FOREIGN KEY (project) REFERENCES projects(name) ON DELETE CASCADE
);

-- Keep updated_at honest.
CREATE TRIGGER IF NOT EXISTS facts_touch
AFTER UPDATE ON facts FOR EACH ROW
BEGIN
    UPDATE facts SET updated_at = datetime('now') WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS projects_touch
AFTER UPDATE ON projects FOR EACH ROW
BEGIN
    UPDATE projects SET updated_at = datetime('now') WHERE name = OLD.name;
END;
