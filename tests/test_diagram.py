from ownyourship import diagram

CONFIG = {
    "included_extensions": [".py"],
    "excluded_dirs": [],
    "excluded_patterns": [],
}


def _write(tmp_path, name, src):
    (tmp_path / name).write_text(src, encoding="utf-8")


def _component(d, comp_id):
    return next(c for c in d["components"] if c["id"] == comp_id)


def test_components_group_functions_by_file(tmp_path):
    _write(tmp_path, "a.py", "def foo():\n    pass\n\ndef bar():\n    pass\n")
    _write(tmp_path, "b.py", "def baz():\n    pass\n")
    d = diagram.build_diagram(tmp_path, CONFIG)

    assert {c["id"] for c in d["components"]} == {"a.py", "b.py"}
    assert {f["name"] for f in _component(d, "a.py")["functions"]} == {"foo", "bar"}


def test_function_edges_present(tmp_path):
    _write(tmp_path, "a.py", "def bar():\n    pass\n\ndef foo():\n    return bar()\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    assert {"source": "a.py::foo", "target": "a.py::bar"} in d["function_edges"]


def test_component_edges_aggregate_cross_file(tmp_path):
    _write(tmp_path, "a.py", "def baz():\n    pass\n")
    _write(tmp_path, "b.py", "from a import baz\n\ndef foo():\n    return baz()\n\ndef qux():\n    return baz()\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    edge = next(e for e in d["component_edges"] if e["source"] == "b.py" and e["target"] == "a.py")
    assert edge["count"] == 2


def test_component_edges_exclude_intra_file(tmp_path):
    _write(tmp_path, "a.py", "def bar():\n    pass\n\ndef foo():\n    return bar()\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    assert d["component_edges"] == []


def test_methods_included_with_class(tmp_path):
    _write(tmp_path, "a.py", "class C:\n    def run(self):\n        pass\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    fns = _component(d, "a.py")["functions"]
    run = next(f for f in fns if f["name"] == "run")
    assert run["id"] == "a.py::C.run"
    assert run["parent_class"] == "C"


def test_component_has_content_fingerprint(tmp_path):
    _write(tmp_path, "a.py", "def foo():\n    pass\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    assert _component(d, "a.py")["fingerprint"]  # for label caching


def test_functions_include_signature(tmp_path):
    # Labels need real signatures to describe sparse files (issue #18).
    _write(tmp_path, "a.py", "def foo(x):\n    return x\n")
    d = diagram.build_diagram(tmp_path, CONFIG)
    fn = _component(d, "a.py")["functions"][0]
    assert fn.get("signature")
