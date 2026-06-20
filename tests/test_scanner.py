from pathlib import Path

from ownyourship import scanner


# ── Python AST scanner ──────────────────────────────────────────────────────

def _scan_py(tmp_path: Path, source: str):
    f = tmp_path / "sample.py"
    f.write_text(source, encoding="utf-8")
    return scanner.scan_python_file(f, tmp_path)


def test_python_extracts_functions_classes_methods(tmp_path):
    src = (
        "import os\n"
        "\n"
        "MAX = 10\n"
        "name: str = 'x'\n"
        "\n"
        "def top(a, b=2):\n"
        "    return a + b\n"
        "\n"
        "async def fetch(url):\n"
        "    return url\n"
        "\n"
        "@decorator\n"
        "class Widget(Base):\n"
        "    def method(self, x):\n"
        "        return x\n"
    )
    blocks = _scan_py(tmp_path, src)
    by_name = {(b["block_name"], b["block_type"]): b for b in blocks}

    assert ("top", "function") in by_name
    assert ("fetch", "function") in by_name
    assert ("Widget", "class") in by_name
    assert ("method", "method") in by_name
    assert ("MAX", "constant") in by_name
    assert ("name", "constant") in by_name

    # method is linked to its class
    assert by_name[("method", "method")]["parent_class"] == "Widget"
    # default value captured in signature
    assert "b=2" in by_name[("top", "function")]["signature"].replace(" ", "")
    # async prefix and decorators captured
    assert by_name[("fetch", "function")]["signature"].startswith("async def")
    assert by_name[("Widget", "class")]["decorators"] == ["decorator"]


def test_python_captures_docstring(tmp_path):
    blocks = _scan_py(tmp_path, 'def f():\n    """hello"""\n    pass\n')
    assert blocks[0]["docstring"] == "hello"


def test_python_syntax_error_returns_empty(tmp_path):
    assert _scan_py(tmp_path, "def broken(:\n") == []


# ── Generic regex scanner ─────────────────────────────────────────────────────

def _scan_generic(tmp_path: Path, name: str, source: str):
    f = tmp_path / name
    f.write_text(source, encoding="utf-8")
    return scanner.scan_generic_file(f, tmp_path)


def test_javascript_patterns(tmp_path):
    src = (
        "export function alpha() {}\n"
        "class Beta {}\n"
        "const gamma = () => {}\n"
        "const delta = async function () {}\n"
    )
    names = {(b["block_name"], b["block_type"]) for b in _scan_generic(tmp_path, "a.js", src)}
    assert ("alpha", "function") in names
    assert ("Beta", "class") in names
    assert ("gamma", "function") in names
    assert ("delta", "function") in names


def test_go_patterns(tmp_path):
    src = (
        "func Plain() {}\n"
        "func (r *Repo) Method() {}\n"
        "type User struct {}\n"
        "type Store interface {}\n"
    )
    names = {(b["block_name"], b["block_type"]) for b in _scan_generic(tmp_path, "a.go", src)}
    assert ("Plain", "function") in names
    assert ("Method", "function") in names
    assert ("User", "class") in names
    assert ("Store", "class") in names


def test_rust_patterns(tmp_path):
    src = (
        "pub fn run() {}\n"
        "struct Point {}\n"
        "enum Color {}\n"
        "pub trait Draw {}\n"
    )
    names = {(b["block_name"], b["block_type"]) for b in _scan_generic(tmp_path, "a.rs", src)}
    assert ("run", "function") in names
    assert ("Point", "class") in names
    assert ("Color", "class") in names
    assert ("Draw", "class") in names


def test_generic_dedupes_repeated_names(tmp_path):
    src = "function dup() {}\nfunction dup() {}\n"
    blocks = _scan_generic(tmp_path, "a.js", src)
    assert sum(b["block_name"] == "dup" for b in blocks) == 1


def test_unsupported_extension_scans_empty(tmp_path):
    # Regression guard: extensions without scanner patterns yield nothing.
    assert _scan_generic(tmp_path, "a.rb", "def foo\nend\n") == []


def test_block_end_line_brace_matching(tmp_path):
    src = "fn outer() {\n    inner();\n}\n"
    end = scanner._block_end_line(src, 0)
    assert end == 3


def test_block_end_line_bodyless_returns_none():
    # Semicolon before any brace → declaration has no body.
    assert scanner._block_end_line("struct Foo(i32);\n", 0) is None


# ── Exclusion logic ───────────────────────────────────────────────────────────

def test_should_exclude_dir_and_pattern(tmp_path):
    config = {"excluded_dirs": ["venv"], "excluded_patterns": ["*.lock"]}
    assert scanner.should_exclude(tmp_path / "venv" / "x.py", tmp_path, config) is True
    assert scanner.should_exclude(tmp_path / "yarn.lock", tmp_path, config) is True
    assert scanner.should_exclude(tmp_path / "src" / "main.py", tmp_path, config) is False


def test_should_exclude_outside_project(tmp_path):
    other = tmp_path.parent / "elsewhere" / "x.py"
    assert scanner.should_exclude(other, tmp_path, {}) is True


# ── Project-level scan + meaningful filter ────────────────────────────────────

def test_scan_project_respects_extensions_and_exclusions(tmp_path):
    (tmp_path / "a.py").write_text("def fa():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.js").write_text("function fb() {}\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "c.py").write_text("def fc():\n    pass\n", encoding="utf-8")

    config = {
        "included_extensions": [".py", ".js"],
        "excluded_dirs": ["venv"],
        "excluded_patterns": [],
    }
    names = {b["block_name"] for b in scanner.scan_project(tmp_path, config)}
    assert names == {"fa", "fb"}


def test_get_meaningful_blocks_drops_constants(block_factory):
    blocks = [
        block_factory(block_type="function", block_name="f"),
        block_factory(block_type="class", block_name="C"),
        block_factory(block_type="constant", block_name="K"),
    ]
    kept = {b["block_name"] for b in scanner.get_meaningful_blocks(blocks)}
    assert kept == {"f", "C"}


# ── Java / Kotlin patterns (README claims both as supported) ──────────────────

def test_java_patterns(tmp_path):
    src = (
        "public class Service {\n"
        "    public void run() {}\n"
        "    private int compute(int x) { return x; }\n"
        "}\n"
        "interface Repo {}\n"
    )
    names = {(b["block_name"], b["block_type"]) for b in _scan_generic(tmp_path, "Service.java", src)}
    assert ("Service", "class") in names
    assert ("Repo", "class") in names
    assert ("run", "function") in names
    assert ("compute", "function") in names


def test_kotlin_uses_java_patterns(tmp_path):
    # .kt is dispatched to the same pattern set as .java.
    src = "class Widget {}\ninterface Clickable {}\n"
    names = {(b["block_name"], b["block_type"]) for b in _scan_generic(tmp_path, "Widget.kt", src)}
    assert ("Widget", "class") in names
    assert ("Clickable", "class") in names
