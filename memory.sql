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
INSERT INTO "dependencies" VALUES(3,'quickgrade','playwright + chromium browser cache','Downloads/testgrader/tools/node_modules and AppData/Local/ms-playwright','https://playwright.dev','The whole 21-suite harness is Playwright driving headless Chromium. tools/package.json names playwright, but nothing records that the browser binaries live in a separate machine-wide cache that can be stripped independently of node_modules. Both have to be present: npm install, then npx playwright install chromium.',1);
INSERT INTO "dependencies" VALUES(4,'quickgrade','CPython 3.13','AppData/Local/Programs/Python/Python313/python.exe',NULL,'build.py regenerates sw.js and the single-file QuickGrade.html, and the build test fails without it. No manifest names an interpreter, and the obvious names on PATH are Store aliases that do nothing. See trap python-none-on-path.',1);
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
INSERT INTO "events" VALUES(2,'2026-08-26T22:52:38','quickgrade-session','milestone','QuickGrade: answer sheet redesign and a visual inspection rig','Added tools/look.js: it renders a page and reports truncated text, collisions, ink too light or thin to survive a photocopier, content escaping its page, and unreadably small type, with annotated and layer screenshots. It immediately found four real defects, including truncated correct answers and a PAGE label running under the first page bubble on every sheet the app had ever printed. Also: questions now print on the answer sheet beside their own bubbles; corner fiducials are registration brackets rather than solid squares, where the arm width is a robustness number and not a taste one (0.5 of the mark measured 0.71 fill against a 0.70 detector threshold and lost corners to noise, 0.58 measures 0.80); the test code is a ten-mark strip instead of thirty pre-filled bubbles; and pages after the first drop the repeated header.');
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
INSERT INTO "facts" VALUES(7,'trap','file-stripping','Something on this machine strips large files out of untracked dependency trees, and not only in Downloads. 26 Aug 2026: between two runs of the same suite half an hour apart, Downloads/testgrader/tools/node_modules/playwright-core went from a working install to 733 KB with every .js bundle gone and only LICENSE files left, and icudtl.dat disappeared from AppData/Local/ms-playwright/chromium_headless_shell-1234, so Chrome launched and died with ''Invalid file descriptor to ICU data received'' while --version still worked. Git-tracked files were untouched. Recovery: remove node_modules entirely and reinstall (a plain npm install says ''up to date'' from the lockfile without checking file contents, so it does nothing), then npx playwright install chromium --force. Treat an inexplicable module-not-found, or a browser that starts and then dies, as this before suspecting code.','verified','quickgrade-session','2026-08-26T22:52:38','2026-08-26T22:52:38');
INSERT INTO "facts" VALUES(8,'trap','python-none-on-path','There is no working ''python'' on PATH. python and python3 both resolve to the Windows Store aliases in AppData/Local/Microsoft/WindowsApps, which advertise the Store and exit without executing anything. ''py'' is not installed. The conda install at C:/Users/Admin/anaconda3/python.exe starts under a conda shell but NOT from a child process (it fails with ''Could not find platform independent libraries'') because it needs its own directories on PATH for its DLLs. The one that works from anything is C:/Users/Admin/AppData/Local/Programs/Python/Python313/python.exe, 3.13.15. Any script that shells out to Python must probe a candidate with -c print(1) rather than trust a name, or the fact that a file exists on disk.','verified','quickgrade-session','2026-08-26T22:52:38','2026-08-26T22:52:38');
INSERT INTO "facts" VALUES(9,'trap','pip-broken','pip on the Python313 install is itself damaged: ''No module named pip._vendor.rich._emoji_codes''. python -m ensurepip --upgrade does not repair it, because ensurepip reads the recorded version, sees pip present and stops. Same family as the file-stripping trap. Consequence: no pip installs on that interpreter until it is repaired, so plan around it rather than through it. Reading a PDF, for instance, was done by rendering it with pdf.js inside headless Chromium instead of installing pypdf.','verified','quickgrade-session','2026-08-26T22:52:38','2026-08-26T22:52:38');
INSERT INTO "facts" VALUES(10,'trap','heredoc-backslash','Quoted heredocs in the Bash tool still lose backslashes. A JS character class written as [^''BACKSLASH BACKSLASH] arrives with one backslash and the file will not parse; a Python string containing a Windows path loses its escapes and raises a unicodeescape error. Long heredocs are also truncated before their terminator, which surfaces as ''unexpected EOF while looking for matching'' and silently runs nothing in the entire command, including any earlier commands on the same line. Write files in chunks under about 120 lines, prefer forward slashes in paths, and prefer plain string operations to regex escapes in generated scripts.','verified','quickgrade-session','2026-08-26T22:52:38','2026-08-26T22:52:38');
INSERT INTO "facts" VALUES(11,'trap','crlf-breaks-anchors','Repos here are checked out with CRLF endings, so a patch script that matches a multi-line anchor joined with newline finds nothing, makes no change, and reports success. Detect the ending first and build anchors with it, or splice by line number. This wasted several rounds before it was noticed, because every symptom looked like a wrong anchor string.','verified','quickgrade-session','2026-08-26T22:52:38','2026-08-26T22:52:38');
INSERT INTO "facts" VALUES(12,'trap','cuda-dll-path','pip nvidia-* wheels put DLLs in site-packages/nvidia/*/bin. os.add_dll_directory is NOT enough - CTranslate2 resolves cuBLAS via its own LoadLibrary. Prepend those dirs to os.environ PATH before importing faster_whisper. Symptom: Library cublas64_12.dll is not found.','verified','2026-08-23','2026-08-26 15:53:01','2026-08-26 15:53:01');
INSERT INTO "facts" VALUES(13,'trap','uv-python-312','uv venv --python 3.12 fails with a spurious ''missing expected target directory'' error. Pass the interpreter path directly instead.','verified','2026-08-24','2026-08-26 15:53:01','2026-08-26 15:53:01');
INSERT INTO "facts" VALUES(14,'trap','winget-fresh-terminal','winget-installed binaries do not resolve until a NEW terminal opens. They live under AppData/Local/Microsoft/WinGet/Packages/<Publisher.Name>_<hash>/','verified','2026-08-24','2026-08-26 15:53:01','2026-08-26 15:53:01');
INSERT INTO "facts" VALUES(15,'trap','ollama-app-supervises','Killing ''ollama app'' kills the server - the desktop app supervises ''ollama serve'' and port 11434 goes with it.','verified','2026-08-24','2026-08-26 15:53:01','2026-08-26 15:53:01');
INSERT INTO "facts" VALUES(16,'trap','rust-not-on-path','Rust 1.98.0 is installed at %USERPROFILE%/.cargo but is NOT on PATH in Git Bash. Tauri builds need it.','verified','2026-08-26','2026-08-26 15:53:02','2026-08-26 15:53:02');
INSERT INTO "facts" VALUES(17,'trap','transcript-no-speaker','search_session_transcripts returns user messages, assistant messages and tool output undifferentiated. Never attribute a snippet without checking who produced it.','verified','2026-08-25','2026-08-26 15:53:02','2026-08-26 15:53:02');
INSERT INTO "facts" VALUES(18,'trap','verify-outcome-not-output','gh repo create --push prints the repo URL whether or not the push succeeded. Verify state via API, never stdout. Cost: 11 repos reported pushed while empty, 3 times.','verified','2026-08-24','2026-08-26 15:53:02','2026-08-26 15:53:02');
INSERT INTO "facts" VALUES(19,'feedback','publish-voice','Anything Dan publishes under his own name: no em dashes or middle-dot separators, no delve/leverage/robust/seamless, no reflexive three-item lists. His audience (educators) is the most AI-text-fatigued group in the workforce.','verified','2026-08-25','2026-08-26 15:53:02','2026-08-26 15:53:02');
INSERT INTO "facts" VALUES(20,'feedback','claim-standard','Only claim what survives an unannounced test. Dan''s own rule, applied to his languages and skills. Applies to READMEs, commit messages and status reports too.','verified','2026-08-25','2026-08-26 15:53:02','2026-08-26 15:53:02');
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