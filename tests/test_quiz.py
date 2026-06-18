import asyncio
import json
import re

import anthropic
import httpx

from ownyourship import quiz
from conftest import FakeAnthropic


# ── Cost ──────────────────────────────────────────────────────────────────────

def test_estimate_cost():
    assert quiz.estimate_cost(1_000_000, 0) == 1.0
    assert quiz.estimate_cost(0, 1_000_000) == 5.0
    assert quiz.estimate_cost(0, 0) == 0.0


# ── Response parsing ──────────────────────────────────────────────────────────

def test_parse_bare_json():
    assert quiz._parse_response('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert quiz._parse_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_embedded_json():
    assert quiz._parse_response('Here you go: {"a": 1} done') == {"a": 1}


def test_parse_garbage_returns_none():
    assert quiz._parse_response("not json at all") is None


# ── MC shuffle ────────────────────────────────────────────────────────────────

def _option_text(options, letter):
    opt = next(o for o in options if o.startswith(f"{letter}:"))
    return re.sub(r"^[A-D]:\s*", "", opt)


def test_shuffle_keeps_correct_answer_pointing_at_right_text():
    qdata = {
        "type": "multiple_choice",
        "options": ["A: one", "B: two", "C: three", "D: four"],
        "correct_answer": "B",
    }
    for _ in range(20):  # shuffle is random; invariant must hold every time
        out = quiz._shuffle_mc_options(dict(qdata))
        assert _option_text(out["options"], out["correct_answer"]) == "two"


def test_shuffle_passthrough_for_non_mc():
    qdata = {"type": "free_text", "options": []}
    assert quiz._shuffle_mc_options(qdata) == qdata


def test_shuffle_passthrough_for_wrong_option_count():
    qdata = {"type": "multiple_choice", "options": ["A: one"], "correct_answer": "A"}
    assert quiz._shuffle_mc_options(qdata) == qdata


# ── Block selection ───────────────────────────────────────────────────────────

def _blocks(n):
    return [{"id": i, "block_name": f"b{i}"} for i in range(1, n + 1)]


def test_select_excludes_answered():
    blocks = _blocks(3)
    for _ in range(10):
        chosen = quiz.select_next_block(blocks, {1, 2}, "easy", {})
        assert chosen["id"] == 3


def test_select_returns_none_when_all_answered():
    blocks = _blocks(2)
    assert quiz.select_next_block(blocks, {1, 2}, "easy", {}) is None


def test_tailored_prioritises_struggling_block():
    blocks = _blocks(3)
    perf = {
        1: {"correct": 0, "total": 3},   # struggling → highest priority
        2: {"correct": 3, "total": 3},   # mastered → lowest priority
        # block 3 unseen → middle
    }
    for _ in range(10):
        assert quiz.select_next_block(blocks, set(), "tailored", perf)["id"] == 1


# ── Code context ──────────────────────────────────────────────────────────────

def test_get_code_context_marks_target_lines(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    out = quiz.get_code_context(f, line_start=3, line_end=3, ctx=1)
    lines = out.splitlines()
    assert any(ln.startswith(">") and "c" in ln for ln in lines)   # target marked
    assert any(ln.startswith(" ") and "b" in ln for ln in lines)   # context unmarked


def test_get_code_context_missing_file_returns_empty(tmp_path):
    assert quiz.get_code_context(tmp_path / "nope.py", 1, 1) == ""


# ── Question generation (async, fake client) ──────────────────────────────────

def _block(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    return {
        "id": 7, "file_path": "mod.py", "block_name": "foo",
        "block_type": "function", "parent_class": None,
        "line_start": 1, "line_end": 2,
    }


def test_generate_question_parses_and_attaches_metadata(tmp_path):
    payload = json.dumps({
        "question": "what does foo do?",
        "type": "multiple_choice",
        "options": ["A: one", "B: two", "C: three", "D: four"],
        "correct_answer": "C",
        "explanation": "because",
    })
    client = FakeAnthropic(text=payload, in_tok=11, out_tok=22)
    data, in_tok, out_tok = asyncio.run(
        quiz.generate_question(_block(tmp_path), tmp_path, "easy", client, {})
    )
    assert in_tok == 11 and out_tok == 22
    assert data["block_id"] == 7
    assert data["block_name"] == "foo"
    assert _option_text(data["options"], data["correct_answer"]) == "three"


def test_generate_question_unparseable_returns_none(tmp_path):
    client = FakeAnthropic(text="totally not json")
    data, in_tok, out_tok = asyncio.run(
        quiz.generate_question(_block(tmp_path), tmp_path, "easy", client, {})
    )
    assert data is None
    assert (in_tok, out_tok) == (10, 20)  # tokens still counted


def test_generate_question_api_error_raises_runtimeerror(tmp_path):
    err = anthropic.APIError(
        "boom", request=httpx.Request("POST", "http://test"), body=None
    )
    client = FakeAnthropic(error=err)
    try:
        asyncio.run(quiz.generate_question(_block(tmp_path), tmp_path, "easy", client, {}))
    except RuntimeError as exc:
        assert "API error" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_generate_question_missing_file_returns_none(tmp_path):
    block = {"id": 1, "file_path": "gone.py", "block_name": "x",
             "block_type": "function", "parent_class": None,
             "line_start": 1, "line_end": 2}
    client = FakeAnthropic(text="{}")
    data, in_tok, out_tok = asyncio.run(
        quiz.generate_question(block, tmp_path, "easy", client, {})
    )
    assert data is None and (in_tok, out_tok) == (0, 0)
    assert client.calls == []  # never called the API
