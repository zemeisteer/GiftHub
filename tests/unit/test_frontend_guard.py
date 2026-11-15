import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "code",
    [
        "el.setAttribute('onclick', x)",
        'el.setAttribute( "srcdoc", x)',
        "el.setHTMLUnsafe(x)",
        "range.createContextualFragment(x)",
        "new DOMParser().parseFromString(x, 'text/html')",
        "setTimeout('alert(1)', 1)",
        "setInterval(`x()`, 1)",
        "const f = Function('return 1')",
        "const u = 'javascript:alert(1)'",
    ],
)
def test_guard_new_js_rules(tmp_path, code):
    (tmp_path / "a.js").write_text(code)
    assert len(find_violations(tmp_path)) == 1


def test_guard_allows_function_callbacks(tmp_path):
    (tmp_path / "a.js").write_text("setTimeout(() => 1, 5); el.setAttribute('title', 'x')")
    assert find_violations(tmp_path) == []


def test_guard_multiline_html(tmp_path):
    (tmp_path / "a.html").write_text('<p>\n<button\n  class="x"\n  onclick="x()">\n')
    v = find_violations(tmp_path)
    assert v == ["a.html:2: inline event handler attribute is forbidden"]


def test_guard_script_src_on_later_line_is_ok(tmp_path):
    (tmp_path / "a.html").write_text('<script\n  type="module"\n  src="/a.js"></script>')
    assert find_violations(tmp_path) == []
    (tmp_path / "b.html").write_text('<script\n  type="module">\nx()</script>')
    assert len(find_violations(tmp_path)) == 1


def test_guard_skips_tests_and_node_modules(tmp_path):
    (tmp_path / "a.test.mjs").write_text("el.innerHTML = x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("el.innerHTML = x")
    assert find_violations(tmp_path) == []


def test_new_frontend_is_clean():
    assert find_violations(ROOT / "web" / "shared") == []
