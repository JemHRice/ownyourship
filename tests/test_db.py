import sqlite3

import pytest

from ownyourship import db


def _setup(project):
    db.init_db(project)


def _id_of(project, name):
    rows = db.get_all_blocks(project)
    return next(r["id"] for r in rows if r["block_name"] == name)


def test_init_db_is_idempotent(project):
    db.init_db(project)
    db.init_db(project)  # second call must not raise
    assert db.get_all_blocks(project) == []


def test_upsert_preserves_ids_and_answer_history(project, block_factory):
    """The fatal-bug regression: rescans must keep block IDs stable so past
    answers (and coverage) survive."""
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="foo"),
                                    block_factory(block_name="bar")])
    foo_id = _id_of(project, "foo")

    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, foo_id, "easy", "q?", "multiple_choice",
                     "A", "A", True, 1.0, "Correct!", "exp")

    # Rescan with a moved foo (new line numbers) — same identity key.
    db.upsert_code_blocks(project, [block_factory(block_name="foo", line_start=5, line_end=9),
                                    block_factory(block_name="bar")])

    assert _id_of(project, "foo") == foo_id  # id preserved
    foo_row = next(r for r in db.get_all_blocks(project) if r["block_name"] == "foo")
    assert foo_row["line_start"] == 5  # in-place update

    stats = db.get_stats(project)
    assert stats["correct_blocks"] == 1  # answer still joins


def test_upsert_inserts_new_and_deletes_removed(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="x")])
    db.upsert_code_blocks(project, [block_factory(block_name="x"),
                                    block_factory(block_name="y")])
    assert {r["block_name"] for r in db.get_all_blocks(project)} == {"x", "y"}

    db.upsert_code_blocks(project, [block_factory(block_name="y")])
    assert {r["block_name"] for r in db.get_all_blocks(project)} == {"y"}


def test_upsert_handles_duplicate_names(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="f", line_start=1),
                                    block_factory(block_name="f", line_start=10)])
    rows = [r for r in db.get_all_blocks(project) if r["block_name"] == "f"]
    assert len(rows) == 2
    assert len({r["id"] for r in rows}) == 2


def test_session_correct_block_ids_distinct_and_correct_only(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="a"),
                                    block_factory(block_name="b")])
    a_id, b_id = _id_of(project, "a"), _id_of(project, "b")
    sid = db.create_session(project, "easy")

    db.record_answer(project, sid, a_id, "easy", "q", "multiple_choice", "A", "A", True, 1.0, "", "")
    db.record_answer(project, sid, a_id, "easy", "q", "multiple_choice", "A", "A", True, 1.0, "", "")
    db.record_answer(project, sid, b_id, "easy", "q", "multiple_choice", "B", "A", False, 0.0, "", "")

    assert db.get_session_correct_block_ids(project, sid) == {a_id}


def test_stats_coverage_math_excludes_constants(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_type="function", block_name="f"),
                                    block_factory(block_type="constant", block_name="K")])
    f_id = _id_of(project, "f")
    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, f_id, "easy", "q", "multiple_choice", "A", "A", True, 1.0, "", "")

    stats = db.get_stats(project)
    assert stats["total_blocks"] == 1          # constant not counted
    assert stats["correct_blocks"] == 1
    assert stats["coverage_pct"] == 100.0
    assert stats["has_95_achievement"] is True


def test_stats_partial_coverage(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="a"),
                                    block_factory(block_name="b")])
    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, _id_of(project, "a"), "easy", "q",
                     "multiple_choice", "A", "A", True, 1.0, "", "")

    stats = db.get_stats(project)
    assert stats["coverage_pct"] == 50.0
    assert stats["has_95_achievement"] is False


def test_history_pagination_and_nesting(project, block_factory):
    _setup(project)
    db.upsert_code_blocks(project, [block_factory(block_name="a")])
    a_id = _id_of(project, "a")

    for _ in range(3):
        sid = db.create_session(project, "easy")
        db.record_answer(project, sid, a_id, "easy", "what?", "multiple_choice",
                         "A", "A", True, 1.0, "Correct!", "exp")

    page1 = db.get_history(project, session_limit=2, offset=0)
    page2 = db.get_history(project, session_limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert page1[0]["questions"][0]["question_text"] == "what?"
    assert page1[0]["total_questions"] == 1


# ── Foreign-key enforcement (RED — implementation pending) ────────────────────

def test_record_answer_rejects_orphan_block(project):
    """An answer referencing a non-existent block must be rejected, not stored."""
    db.init_db(project)
    sid = db.create_session(project, "easy")
    with pytest.raises(sqlite3.IntegrityError):
        db.record_answer(project, sid, 99999, "easy", "q", "multiple_choice",
                         "A", "A", True, 1.0, "", "")


def test_record_answer_rejects_orphan_session(project, block_factory):
    """An answer referencing a non-existent session must be rejected, not stored."""
    db.init_db(project)
    db.upsert_code_blocks(project, [block_factory(block_name="a")])
    block_id = _id_of(project, "a")
    with pytest.raises(sqlite3.IntegrityError):
        db.record_answer(project, 99999, block_id, "easy", "q", "multiple_choice",
                         "A", "A", True, 1.0, "", "")


def test_rescan_removing_answered_block_does_not_crash(project, block_factory):
    """With FKs enforced, dropping an answered block on rescan must still work:
    its answer history is removed alongside it, not left dangling."""
    db.init_db(project)
    db.upsert_code_blocks(project, [block_factory(block_name="gone"),
                                    block_factory(block_name="stays")])
    gone_id = _id_of(project, "gone")
    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, gone_id, "easy", "q", "multiple_choice",
                     "A", "A", True, 1.0, "", "")

    db.upsert_code_blocks(project, [block_factory(block_name="stays")])  # "gone" removed

    assert {r["block_name"] for r in db.get_all_blocks(project)} == {"stays"}
    assert db.count_session_answers(project, sid) == 0  # orphaned answer cleared


def test_end_session_persists_cost_and_ended_at(project):
    db.init_db(project)
    sid = db.create_session(project, "easy")
    db.end_session(project, sid, tokens_used=300, cost_usd=0.0123)

    sess = next(s for s in db.get_history(project, session_limit=5, offset=0) if s["id"] == sid)
    assert sess["cost_usd"] == 0.0123
    assert sess["ended_at"] is not None


# ── Content-hash identity preserves history across rename/move (RED) ──────────

def test_rename_preserves_answer_history(project, block_factory):
    """A block renamed but with an unchanged body (same content hash) keeps its id,
    so its answer history survives."""
    db.init_db(project)
    db.upsert_code_blocks(project, [block_factory(block_name="foo", content_hash="H1")])
    foo_id = _id_of(project, "foo")
    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, foo_id, "easy", "q", "multiple_choice", "A", "A", True, 1.0, "", "")

    db.upsert_code_blocks(project, [block_factory(block_name="bar", content_hash="H1")])  # renamed

    assert {r["block_name"] for r in db.get_all_blocks(project)} == {"bar"}
    assert _id_of(project, "bar") == foo_id
    assert db.count_session_answers(project, sid) == 1


def test_move_to_new_file_preserves_history(project, block_factory):
    db.init_db(project)
    db.upsert_code_blocks(project, [block_factory(file_path="a.py", block_name="foo", content_hash="H1")])
    old_id = _id_of(project, "foo")
    sid = db.create_session(project, "easy")
    db.record_answer(project, sid, old_id, "easy", "q", "multiple_choice", "A", "A", True, 1.0, "", "")

    db.upsert_code_blocks(project, [block_factory(file_path="b.py", block_name="foo", content_hash="H1")])  # moved

    rows = db.get_all_blocks(project)
    assert len(rows) == 1
    assert rows[0]["file_path"] == "b.py"
    assert rows[0]["id"] == old_id
    assert db.count_session_answers(project, sid) == 1
