"""Tests for classify_location.

Exists because the function it tests replaced one that reported GONE for
six live rows, and because the first fix then over-corrected and demoted a
real path to "unchecked". Both directions are covered below.

Two cases MUST come back "gone". If this suite ever passes without them,
the classifier has lost the ability to report absence and the GONE list is
decorative again.

Run:  python test_classify.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mem import classify_location as C

HERE = Path(__file__).parent
LEGACY = (r"C:\Users\Admin\Downloads\Legacy builds and Assets"
          r"...if you can't find something, try here")

CASES = [
    # (location, expected state, why this case exists)
    (str(HERE), "ok", "plain absolute directory"),
    (r"C:\Users\Admin\NOPE-does-not-exist-12345", "gone",
     "MUST FAIL: real absence"),
    ("AppData/Local/Programs/Python/Python313/python.exe", "ok",
     "relative to home -- the false GONE that started this"),
    ("AppData/Local/Programs/NOPE-not-real-98765", "unchecked",
     "relative with no anchor: unknown, not dead"),
    ("http://127.0.0.1:8188", "unchecked", "URL is not a path"),
    ("hardcoded in scripts/net/net_manager.gd", "unchecked",
     "prose is not a path"),
    (str(HERE.parent / "*"), "ok", "wildcard that matches"),
    (str(HERE.parent / "zzz-nomatch-*"), "gone",
     "MUST FAIL: wildcard matching nothing"),
    ("", "unchecked", "empty field"),
    (LEGACY + r"\raven-itch-folder*.zip", "ok",
     "real directory whose NAME contains ' and ' -- not prose"),
]


def main() -> int:
    failed = 0
    for loc, want, why in CASES:
        got, detail = C(loc)
        ok = got == want
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  want {want:9} got {got:9}  {why}")
        if not ok:
            print(f"          location={loc!r}")
            print(f"          detail={detail!r}")

    must_fail = sum(1 for _, want, _ in CASES if want == "gone")
    if must_fail < 2:
        print()
        print("  SUITE IS BROKEN: fewer than two cases expect 'gone'.")
        print("  A classifier that cannot report absence is not a check.")
        return 1

    print()
    print(f"  {len(CASES) - failed}/{len(CASES)} passed "
          f"({must_fail} of them assert real absence)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
