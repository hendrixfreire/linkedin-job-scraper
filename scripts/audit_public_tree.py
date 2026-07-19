#!/usr/bin/env python3
"""Block accidental publication of local runtime data and identifiers."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

FORBIDDEN_PATHS = (
    re.compile(r"(^|/)config\.json$"),
    re.compile(r"(^|/)data/profile\.json$"),
    re.compile(r"(^|/)\.env(?:\..*)?$"),
    re.compile(r"\.(?:db|sqlite|sqlite3|pdf|png|jpe?g|webp)$", re.I),
    re.compile(r"(^|/)(?:reports/(?:screenshots|evidence)|cookies|sessions|data/browser-profile(?:-|/|$))"),
)
FORBIDDEN_CONTENT = (
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"(?<!github\.com/)\bhendrixfreire\b", re.I),
    re.compile(r"\b(?:discord|telegram):-?\d{8,}\b", re.I),
    re.compile(r"\b(?:ghp|github_pat|sk-[A-Za-z0-9])[-A-Za-z0-9_]{12,}\b"),
    re.compile(r"\b(?:api[_-]?key|authorization)\s*[:=]\s*['\"]?(?!\$\{|<)[^\s'\"]+", re.I),
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.STDOUT)


def main() -> int:
    violations: list[str] = []
    for path in filter(None, git("ls-files").splitlines()):
        normalized = PurePosixPath(path).as_posix()
        if any(pattern.search(normalized) for pattern in FORBIDDEN_PATHS):
            violations.append(f"private runtime file tracked: {normalized}")
            continue
        content = git("show", f":{normalized}")
        if any(pattern.search(content) for pattern in FORBIDDEN_CONTENT):
            violations.append(f"personal or sensitive content in: {normalized}")
    if violations:
        print("PUBLIC PRIVACY AUDIT FAILED:", *[f"- {item}" for item in violations], sep="\n", file=sys.stderr)
        return 1
    print("Public privacy audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
