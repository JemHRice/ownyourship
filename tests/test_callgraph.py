from ownyourship import callgraph

CONFIG = {"excluded_dirs": [], "excluded_patterns": []}


def _write(tmp_path, name, src):
    (tmp_path / name).write_text(src, encoding="utf-8")


def test_same_file_function_call(tmp_path):
    _write(tmp_path, "a.py", "def bar():\n    return 1\n\ndef foo():\n    return bar()\n")
    edges = callgraph.extract_call_edges(tmp_path, CONFIG)
    assert ("a.py::foo", "a.py::bar") in edges


def test_method_call_resolves(tmp_path):
    src = (
        "class C:\n"
        "    def helper(self):\n"
        "        return 1\n"
        "    def run(self):\n"
        "        return self.helper()\n"
    )
    _write(tmp_path, "a.py", src)
    edges = callgraph.extract_call_edges(tmp_path, CONFIG)
    assert ("a.py::C.run", "a.py::C.helper") in edges


def test_external_and_builtin_calls_ignored(tmp_path):
    _write(tmp_path, "a.py", "def foo():\n    print(len([1]))\n")
    edges = callgraph.extract_call_edges(tmp_path, CONFIG)
    assert edges == set()


def test_cross_file_call(tmp_path):
    _write(tmp_path, "a.py", "def baz():\n    return 1\n")
    _write(tmp_path, "b.py", "from a import baz\n\ndef foo():\n    return baz()\n")
    edges = callgraph.extract_call_edges(tmp_path, CONFIG)
    assert ("b.py::foo", "a.py::baz") in edges


def test_no_self_edges(tmp_path):
    # Recursion shouldn't produce a self-loop.
    _write(tmp_path, "a.py", "def foo(n):\n    return foo(n - 1)\n")
    edges = callgraph.extract_call_edges(tmp_path, CONFIG)
    assert ("a.py::foo", "a.py::foo") not in edges


def test_excluded_dirs_skipped(tmp_path):
    (tmp_path / "venv").mkdir()
    _write(tmp_path, "venv/x.py", "def foo():\n    return 1\n")
    _write(tmp_path, "a.py", "def caller():\n    return foo()\n")
    edges = callgraph.extract_call_edges(
        tmp_path, {"excluded_dirs": ["venv"], "excluded_patterns": []}
    )
    quals = {q for edge in edges for q in edge}
    assert "venv/x.py::foo" not in quals
