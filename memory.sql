BEGIN TRANSACTION;
CREATE TABLE dependencies (
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
INSERT INTO "dependencies" VALUES(1,'dr-companion','Ruby4Lich5','C:/Ruby4Lich5','https://github.com/elanthia-online/lich-5/releases','Lich runs on Ruby; dr-companion automates Lich. Captured in no manifest.',1);
INSERT INTO "dependencies" VALUES(2,'dr-companion','Genie4','C:/Genie4',NULL,'Simutronics client dr-companion works alongside.',1);
CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    ts          TEXT NOT NULL DEFAULT (datetime('now')),
    session     TEXT,
    kind        TEXT NOT NULL CHECK (kind IN
                  ('decision','error','milestone','removal','install')),
    summary     TEXT NOT NULL,
    detail      TEXT
);
INSERT INTO "events" VALUES(1,'2026-08-26 15:32:10','a9593032','milestone','Structured memory database created and hourly backup registered','SQLite 3.50.4 via Python. Dump-and-hash backup to private repo dancockrell/memory-db. Scheduled task ClaudeMemoryBackup, hourly.');
CREATE TABLE facts (
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
INSERT INTO "facts" VALUES(1,'trap','vram-wmi','Win32_VideoController.AdapterRAM reports the RTX 4070 as 4 GB (32-bit overflow). Use nvidia-smi.','verified','2026-08-23','2026-08-26 15:29:46','2026-08-26 15:29:46');
INSERT INTO "facts" VALUES(2,'trap','crlf-scripts','Heredocs write LF; cmd.exe mis-parses LF-only scripts with misleading errors. Fix with sed then verify with cat -A.','verified','2026-08-24','2026-08-26 15:29:46','2026-08-26 15:29:46');
INSERT INTO "facts" VALUES(3,'trap','temp-wipe','Never clear TEMP wholesale on a running system. Broke a Chrome update mid-flight, removing chrome.exe while 268 files stayed intact.','verified','2026-08-26','2026-08-26 15:29:46','2026-08-26 15:29:46');
INSERT INTO "facts" VALUES(4,'trap','git-noreply','Commits must use the GitHub noreply email or pushes are rejected, and the error does not say so.','verified','2026-08-24','2026-08-26 15:29:46','2026-08-26 15:29:46');
INSERT INTO "facts" VALUES(5,'trap','exec-policy','LocalMachine execution policy is AllSigned, blocking npm.ps1. npm works in Git Bash and cmd.','verified','2026-08-24','2026-08-26 15:29:46','2026-08-26 15:29:46');
INSERT INTO "facts" VALUES(6,'tool','gpu','RTX 4070, 12012 MB VRAM. Models above ~12 GB spill to shared memory.','verified','2026-08-23','2026-08-26 15:29:46','2026-08-26 15:29:46');
CREATE TABLE projects (
    name        TEXT PRIMARY KEY,
    path        TEXT,
    repo        TEXT,
    stack       TEXT,
    status      TEXT DEFAULT 'active' CHECK (status IN
                  ('active','paused','archived','published')),
    notes       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO "projects" VALUES('dr-companion','C:/Users/Admin/dev/dr-companion','dancockrell/dr-companion','Tauri (Rust + web)','active','Automates Lich. Needs Ruby4Lich5.','2026-08-26 15:29:46');
INSERT INTO "projects" VALUES('ghost-front','C:/Users/Admin/dev/ghost-front','dancockrell/ghost-front','single-file HTML','published','WW2 horror platformer','2026-08-26 15:29:46');
INSERT INTO "projects" VALUES('raven-classroom','C:/Users/Admin/dev/raven-classroom','dancockrell/raven-classroom','HTML + Apps Script','published','Reader engine behind Raven/Magi/Long Night','2026-08-26 15:29:46');
INSERT INTO "projects" VALUES('quickgrade','C:/Users/Admin/Downloads/testgrader','dancockrell/quickgrade','PWA','published','Offline paper grader; student data never leaves device','2026-08-26 15:29:46');
INSERT INTO "projects" VALUES('world-aflame','C:/Users/Admin/dev/world-aflame','dancockrell/world-aflame','HTML + WebRTC','published','Three-faction card game','2026-08-26 15:29:46');
INSERT INTO "projects" VALUES('longnight','C:/Users/Admin/dev/longnight','dancockrell/longnight','canvas RPG','active','Synthesised orchestra, no audio downloads','2026-08-26 15:29:46');
CREATE INDEX idx_facts_category ON facts(category);
CREATE INDEX idx_events_ts   ON events(ts);
CREATE INDEX idx_events_kind ON events(kind);
CREATE TRIGGER facts_touch
AFTER UPDATE ON facts FOR EACH ROW
BEGIN
    UPDATE facts SET updated_at = datetime('now') WHERE id = OLD.id;
END;
CREATE TRIGGER projects_touch
AFTER UPDATE ON projects FOR EACH ROW
BEGIN
    UPDATE projects SET updated_at = datetime('now') WHERE name = OLD.name;
END;
COMMIT;