import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_frontend import find_violations  # noqa: E402


def test_guard_flags_innerhtml(tmp_path):
    (tmp_path / "a.js").write_text("el.innerHTML = x")
    (tmp_path / "b.html").write_text('<button onclick="x()">')
    assert len(find_violations(tmp_path)) == 2


def test_guard_flags_other_patterns(tmp_path):
    (tmp_path / "a.js").write_text(
        "a.outerHTML=1\nb.insertAdjacentHTML('x')\ndocument.write(1)\neval(x)\nnew Function('a')"
    )
    (tmp_path / "b.html").write_text(
        "<script>x()</script>\n<style>a{}</style>\n<script src=\"/a.js\"></script>"
    )
    v = find_violations(tmp_path)
    assert len(v) == 7
    assert v[0].startswith("a.js:1: ")


def test_guard_skips_tests_and_node_modules(tmp_path):
    (tmp_path / "a.test.mjs").write_text("el.innerHTML = x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("el.innerHTML = x")
    assert find_violations(tmp_path) == []


def test_new_frontend_is_clean():
    assert find_violations(ROOT / "web" / "shared") == []
