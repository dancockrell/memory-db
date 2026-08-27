"""Do the stored check commands actually run?

    python test_checks.py            report only
    python test_checks.py --run      actually execute them

Every row in this store can carry a check_cmd: the command that establishes
the fact, so a reader can re-derive it instead of believing it. That is the
whole design. But a check command nobody has ever executed is a claim about
a claim -- the exact failure the column exists to prevent, one level up.

This runs them and reports what happens. Three outcomes, not two:

    ok         the command ran and exited 0
    failed     the command ran and exited non-zero (may be a REAL finding --
               the fact may have gone stale, which is the column working)
    unchecked  the command could not be run at all: a placeholder, a shell
               this script cannot drive, or something the safety filter
               refused. Never counted as a pass.

A failure here is ambiguous by nature and that is fine. What matters is that
"I could not run this" never hides inside "nothing went wrong".

SAFETY. These strings were written by several sessions over hours. Anything
that could mutate state is refused rather than run -- this is a verification
pass, and a verifier that changes the machine is not one.
"""

import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "memory.db"
TIMEOUT = 30

PLACEHOLDER = re.compile(r"<[a-z_ ]+>|\.\.\.")

# Refused outright. Deliberately blunt: a false refusal costs one "unchecked"
# line, a false permit could delete something.
DANGEROUS = re.compile(
    r"\b(rm|del|rmdir|Remove-Item|mv|Move-Item|kill|taskkill|Stop-Process|"
    r"shutdown|format|mkfs|dd|DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|"
    r"git\s+(push|reset|clean|checkout|rebase|commit)|npm\s+(install|i)\b|"
    r"pip\s+install|winget|choco|Set-ExecutionPolicy|Set-ItemProperty|"
    r"New-Item|Out-File|Set-Content|Add-Content)\b",
    re.I,
)
REDIRECT = re.compile(r"(?<![0-9])>(?!=)|>>")


def classify(cmd: str):
    """Return (runnable, reason). Never raises."""
    if not cmd or not cmd.strip():
        return False, "empty"
    if PLACEHOLDER.search(cmd):
        return False, "placeholder - not runnable as written"
    if DANGEROUS.search(cmd):
        return False, "refused: could mutate state"
    if REDIRECT.search(cmd) and "2>&1" not in cmd and "/dev/null" not in cmd:
        return False, "refused: writes to a file"
    return True, ""


# Prepended rather than relying on a login shell. The first version used
# `bash -lc`, whose profile errors on this machine -- 29 of 70 checks came
# back "failed" with an identical /etc/profile.d/git-prompt.sh line and exit
# 127, which is "command not found" from the broken PATH that followed. A
# checker built to test checks, reporting its own breakage as 29 findings.
PATH_PREFIX = (
    'export PATH="/c/Program Files/nodejs:'
    '/c/Program Files/Git/bin:'
    '/c/Program Files/GitHub CLI:'
    '/c/Users/Admin/AppData/Local/Programs/Python/Python313:'
    '/c/Users/Admin/AppData/Roaming/npm:'
    '/c/Users/Admin/bin:$PATH"; '
)


def run(cmd: str):
    """Run through bash. Returns (exit_code, first_output_line)."""
    try:
        p = subprocess.run(
            ["C:/Program Files/Git/bin/bash.exe", "--noprofile", "--norc", "-c",
             PATH_PREFIX + cmd],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        out = (p.stdout or p.stderr or "").strip().splitlines()
        return p.returncode, (out[0][:70] if out else "")
    except subprocess.TimeoutExpired:
        return None, f"timed out after {TIMEOUT}s"
    except Exception as e:
        return None, f"could not launch: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually execute the commands")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [
        (f"{r['category']}/{r['key']}", r["check_cmd"])
        for r in conn.execute(
            "SELECT category,key,check_cmd FROM facts "
            "WHERE check_cmd IS NOT NULL AND check_cmd<>'' ORDER BY category,key"
        )
    ] + [
        (f"dep:{r['project']}/{r['name']}", r["check_cmd"])
        for r in conn.execute(
            "SELECT project,name,check_cmd FROM dependencies "
            "WHERE check_cmd IS NOT NULL AND check_cmd<>'' ORDER BY project,name"
        )
    ]

    print(f"  rows carrying a check command: {len(rows)}")
    if len(rows) < 10:
        print("  !! implausibly few -- the query is broken, not the store")
        return 2

    if not args.run:
        print("  (report only; pass --run to execute)")
        return 0

    ok = failed = unchecked = 0
    problems = []
    for label, cmd in rows:
        runnable, reason = classify(cmd)
        if not runnable:
            unchecked += 1
            problems.append(("UNCHECKED", label, reason))
            continue
        code, first = run(cmd)
        if code == 0:
            ok += 1
        elif code is None:
            unchecked += 1
            problems.append(("UNCHECKED", label, first))
        else:
            failed += 1
            problems.append((f"EXIT {code}", label, first))

    for state, label, detail in problems:
        print(f"  {state:<10} {label}")
        if detail:
            print(f"             {detail}")

    total = ok + failed + unchecked
    print()
    print(f"  ok        {ok:>3}")
    print(f"  failed    {failed:>3}   (may be real staleness, not tool error)")
    print(f"  unchecked {unchecked:>3}   (never counted as a pass)")
    print(f"  total     {total:>3}")
    if total != len(rows):
        print("  !! total does not match the row count -- this report is wrong")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
