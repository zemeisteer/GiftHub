"""Frontend guard: forbids unsafe DOM APIs and inline code in web/ files."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHECK_DIRS = ("web/shared", "web/user", "web/admin")
EXTENSIONS = {".js", ".mjs", ".html", ".css"}
SKIP_DIRS = {"node_modules"}
# Legacy files, removed from this list when replaced (Task 7 and Task 12).
LEGACY_EXCLUDES = ("web/user/index.html", "web/admin/index.html")

JS_RULES = [
    (re.compile(r"\binnerHTML\b"), "innerHTML is forbidden"),
    (re.compile(r"\bouterHTML\b"), "outerHTML is forbidden"),
    (re.compile(r"\binsertAdjacentHTML\b"), "insertAdjacentHTML is forbidden"),
    (re.compile(r"\bdocument\s*\.\s*write(ln)?\b"), "document.write is forbidden"),
    (re.compile(r"\beval\s*\("), "eval() is forbidden"),
    (re.compile(r"\bnew\s+Function\b"), "new Function is forbidden"),
]
HTML_RULES = [
    (re.compile(r"<[^>]*\son[a-z]+\s*=", re.I), "inline event handler attribute is forbidden"),
    (re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", re.I), "inline <script> is forbidden"),
    (re.compile(r"<style\b", re.I), "<style> block is forbidden"),
]


def _is_legacy(path: Path) -> bool:
    posix = path.as_posix()
    return any(posix.endswith(x) for x in LEGACY_EXCLUDES)


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in EXTENSIONS:
            continue
        if p.name.endswith(".test.mjs") or SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        if _is_legacy(p):
            continue
        yield p


def find_violations(root: Path) -> list[str]:
    root = Path(root)
    out: list[str] = []
    for p in _iter_files(root):
        rules = list(JS_RULES) if p.suffix in {".js", ".mjs", ".html"} else []
        if p.suffix == ".html":
            rules += HTML_RULES
        rel = p.relative_to(root).as_posix() if p != root else p.name
        text = p.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for rx, reason in rules:
                if rx.search(line):
                    out.append(f"{rel}:{lineno}: {reason}")
    return out


def main() -> int:
    base = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for d in CHECK_DIRS:
        target = base / d
        if target.is_dir():
            violations += [f"{d}/{v}" for v in find_violations(target)]
    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
