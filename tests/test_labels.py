import asyncio
import json

from ownyourship import labels
from conftest import FakeAnthropic


def _diagram(fingerprint="F1"):
    return {
        "components": [{
            "id": "a.py",
            "name": "a.py",
            "fingerprint": fingerprint,
            "functions": [{"id": "a.py::foo", "name": "foo", "type": "function", "parent_class": None}],
        }],
        "function_edges": [],
        "component_edges": [],
    }


def test_labels_generated_and_attached(tmp_path):
    client = FakeAnthropic(text="Handles the As")
    d = _diagram()
    asyncio.run(labels.attach_component_labels(d, tmp_path / "cache.json", client))
    assert d["components"][0]["label"] == "Handles the As"


def test_labels_cached_by_fingerprint(tmp_path):
    client = FakeAnthropic(text="Handles the As")
    cache = tmp_path / "cache.json"
    asyncio.run(labels.attach_component_labels(_diagram("F1"), cache, client))
    asyncio.run(labels.attach_component_labels(_diagram("F1"), cache, client))
    assert len(client.calls) == 1  # second run hit the cache, no new API call


def test_label_regenerates_on_fingerprint_change(tmp_path):
    client = FakeAnthropic(text="x")
    cache = tmp_path / "cache.json"
    asyncio.run(labels.attach_component_labels(_diagram("F1"), cache, client))
    asyncio.run(labels.attach_component_labels(_diagram("F2"), cache, client))
    assert len(client.calls) == 2  # changed code → regenerated


def _write_cache(path, label, fingerprint="F1"):
    path.write_text(
        json.dumps({"a.py": {"fingerprint": fingerprint, "label": label}}),
        encoding="utf-8",
    )


def test_poisoned_cached_label_regenerates(tmp_path):
    # A refusal cached before the #18 prompt fix must not be served forever:
    # the fingerprint still matches (the file didn't change), so the cache has
    # to re-validate the label itself, not just the fingerprint.
    cache = tmp_path / "cache.json"
    _write_cache(cache, "I don't see the contents. Could you share the source code?")
    client = FakeAnthropic(text="Grades answers.")
    d = _diagram("F1")
    asyncio.run(labels.attach_component_labels(d, cache, client))
    assert d["components"][0]["label"] == "Grades answers."
    assert len(client.calls) == 1


def test_empty_cached_label_regenerates(tmp_path):
    cache = tmp_path / "cache.json"
    _write_cache(cache, "")
    client = FakeAnthropic(text="Grades answers.")
    d = _diagram("F1")
    asyncio.run(labels.attach_component_labels(d, cache, client))
    assert d["components"][0]["label"] == "Grades answers."
    assert len(client.calls) == 1


def test_failed_generation_is_not_cached(tmp_path):
    # A rejected/empty label must not be written with the current fingerprint,
    # or the failure becomes permanent; the next run should retry.
    cache = tmp_path / "cache.json"
    bad = FakeAnthropic(text="Could you share the source code?")
    asyncio.run(labels.attach_component_labels(_diagram("F1"), cache, bad))
    good = FakeAnthropic(text="Grades answers.")
    d = _diagram("F1")
    asyncio.run(labels.attach_component_labels(d, cache, good))
    assert len(good.calls) == 1
    assert d["components"][0]["label"] == "Grades answers."


def _component_with_sig():
    return {
        "id": "grader.py", "name": "grader.py", "fingerprint": "F1",
        "functions": [{
            "id": "grader.py::grade", "name": "grade",
            "signature": "def grade(user, correct) -> bool",
            "docstring": "Grade one answer.", "type": "function", "parent_class": None,
        }],
    }


def test_label_prompt_includes_signatures():
    # Sparse files broke because the prompt sent only names; give the model the
    # actual signatures so it can infer instead of asking for the source.
    client = FakeAnthropic(text="Grades multiple-choice answers.")
    asyncio.run(labels.generate_component_label(_component_with_sig(), client))
    prompt = client.calls[0]["messages"][0]["content"]
    assert "def grade(user, correct) -> bool" in prompt


def test_label_drops_question_response():
    # If the model still asks for input, don't surface that as the description.
    client = FakeAnthropic(text="I don't see the contents. Could you share the source code?")
    label = asyncio.run(labels.generate_component_label(_component_with_sig(), client))
    assert label == ""


# ── Function-level labels (#21) ───────────────────────────────────────────────

def _fn(fid, name, sig, doc="", chash="H1"):
    return {"id": fid, "name": name, "signature": sig, "docstring": doc,
            "type": "function", "parent_class": None, "content_hash": chash}


def _fn_diagram():
    return {
        "components": [
            {"id": "a.py", "name": "a.py", "fingerprint": "FA", "functions": [
                _fn("a.py::foo", "foo", "def foo(x) -> int", "Do the foo.", "H-foo"),
                _fn("a.py::bar", "bar", "def bar() -> None", "", "H-bar"),
            ]},
            {"id": "b.py", "name": "b.py", "fingerprint": "FB", "functions": [
                _fn("b.py::baz", "baz", "def baz()", "", "H-baz"),
            ]},
        ],
        "function_edges": [], "component_edges": [],
    }


def _fn_client(mapping):
    return FakeAnthropic(text=json.dumps(mapping))


def test_function_labels_generated_batched_per_file(tmp_path):
    client = _fn_client({"a.py::foo": "Foos things.", "a.py::bar": "Bars things."})
    out = asyncio.run(labels.attach_function_labels(
        _fn_diagram(), ["a.py::foo", "a.py::bar"], tmp_path / "cache.json", client))
    assert out == {"a.py::foo": "Foos things.", "a.py::bar": "Bars things."}
    assert len(client.calls) == 1  # one batched call for the whole file
    prompt = client.calls[0]["messages"][0]["content"]
    assert "def foo(x) -> int" in prompt and "Do the foo." in prompt


def test_function_labels_grouped_one_call_per_file(tmp_path):
    client = _fn_client({"a.py::foo": "Foos.", "b.py::baz": "Bazzes."})
    asyncio.run(labels.attach_function_labels(
        _fn_diagram(), ["a.py::foo", "b.py::baz"], tmp_path / "cache.json", client))
    assert len(client.calls) == 2  # two files → two calls


def test_function_labels_cached_by_content_hash(tmp_path):
    cache = tmp_path / "cache.json"
    first = _fn_client({"a.py::foo": "Foos things."})
    asyncio.run(labels.attach_function_labels(_fn_diagram(), ["a.py::foo"], cache, first))
    second = _fn_client({"a.py::foo": "SHOULD NOT BE ASKED"})
    out = asyncio.run(labels.attach_function_labels(_fn_diagram(), ["a.py::foo"], cache, second))
    assert out == {"a.py::foo": "Foos things."}
    assert second.calls == []


def test_function_label_regenerates_on_hash_change(tmp_path):
    cache = tmp_path / "cache.json"
    asyncio.run(labels.attach_function_labels(
        _fn_diagram(), ["a.py::foo"], cache, _fn_client({"a.py::foo": "Old."})))
    d = _fn_diagram()
    d["components"][0]["functions"][0]["content_hash"] = "H-foo-2"
    client = _fn_client({"a.py::foo": "New."})
    out = asyncio.run(labels.attach_function_labels(d, ["a.py::foo"], cache, client))
    assert out == {"a.py::foo": "New."}
    assert len(client.calls) == 1


def test_function_label_question_dropped_and_not_cached(tmp_path):
    cache = tmp_path / "cache.json"
    bad = _fn_client({"a.py::foo": "Could you share the source code?"})
    out = asyncio.run(labels.attach_function_labels(_fn_diagram(), ["a.py::foo"], cache, bad))
    assert out == {}
    good = _fn_client({"a.py::foo": "Foos things."})
    out = asyncio.run(labels.attach_function_labels(_fn_diagram(), ["a.py::foo"], cache, good))
    assert out == {"a.py::foo": "Foos things."}
    assert len(good.calls) == 1  # the failure was not cached; retried


def test_function_labels_unknown_ids_ignored(tmp_path):
    client = _fn_client({})
    out = asyncio.run(labels.attach_function_labels(
        _fn_diagram(), ["nope.py::ghost"], tmp_path / "cache.json", client))
    assert out == {}
    assert client.calls == []


def test_function_labels_chunked_for_large_files(tmp_path):
    # One giant call for a big file truncates the JSON response at max_tokens
    # and every label is lost (app.js: 64 functions → 0 labels). Generation
    # must be chunked into bounded calls.
    fns = [_fn(f"a.py::f{i:02d}", f"f{i:02d}", f"def f{i:02d}()", "", f"H{i}") for i in range(40)]
    d = {"components": [{"id": "a.py", "name": "a.py", "fingerprint": "FA", "functions": fns}],
         "function_edges": [], "component_edges": []}
    client = _fn_client({f["id"]: f"Does {f['name']}." for f in fns})
    out = asyncio.run(labels.attach_function_labels(
        d, [f["id"] for f in fns], tmp_path / "cache.json", client))
    assert len(out) == 40                       # nothing lost
    assert len(client.calls) >= 3               # 40 fns → several bounded calls
    assert all(c["max_tokens"] <= 2000 for c in client.calls)


def test_function_labels_parse_fenced_json(tmp_path):
    fenced = "```json\n" + json.dumps({"a.py::foo": "Foos things."}) + "\n```"
    client = FakeAnthropic(text=fenced)
    out = asyncio.run(labels.attach_function_labels(
        _fn_diagram(), ["a.py::foo"], tmp_path / "cache.json", client))
    assert out == {"a.py::foo": "Foos things."}
