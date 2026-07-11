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
