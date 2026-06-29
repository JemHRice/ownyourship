import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _utcnow_iso() -> str:
    """Current UTC time as a naive ISO string.

    Non-deprecated replacement for datetime.utcnow() that keeps the same
    on-disk format as previously stored timestamps, so ordering stays
    consistent across rows written before and after this change.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def get_db_path(project_path: Path) -> Path:
    return project_path / ".oys" / "progress.db"


def init_db(project_path: Path) -> None:
    db_path = get_db_path(project_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS code_blocks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path   TEXT    NOT NULL,
                block_type  TEXT    NOT NULL,
                block_name  TEXT    NOT NULL,
                parent_class TEXT,
                signature   TEXT,
                docstring   TEXT,
                decorators  TEXT,
                line_start  INTEGER,
                line_end    INTEGER,
                content_hash TEXT,
                scanned_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                mode         TEXT    NOT NULL,
                started_at   TEXT    NOT NULL,
                ended_at     TEXT,
                tokens_used  INTEGER DEFAULT 0,
                cost_usd     REAL    DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS question_results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    INTEGER NOT NULL,
                block_id      INTEGER NOT NULL,
                mode          TEXT    NOT NULL,
                question_text TEXT    NOT NULL,
                question_type TEXT    NOT NULL,
                user_answer   TEXT,
                correct_answer TEXT,
                is_correct    INTEGER,
                score         REAL    DEFAULT 0.0,
                feedback      TEXT,
                explanation   TEXT,
                content_hash  TEXT,
                answered_at   TEXT    NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (block_id)   REFERENCES code_blocks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_qr_session ON question_results(session_id);
            CREATE INDEX IF NOT EXISTS idx_qr_block   ON question_results(block_id);
            CREATE INDEX IF NOT EXISTS idx_cb_file    ON code_blocks(file_path);
        """)

        # Migrate pre-existing DBs that predate the content_hash columns.
        cb_cols = {r["name"] for r in conn.execute("PRAGMA table_info(code_blocks)")}
        if "content_hash" not in cb_cols:
            conn.execute("ALTER TABLE code_blocks ADD COLUMN content_hash TEXT")
        qr_cols = {r["name"] for r in conn.execute("PRAGMA table_info(question_results)")}
        if "content_hash" not in qr_cols:
            conn.execute("ALTER TABLE question_results ADD COLUMN content_hash TEXT")


@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FKs unless asked
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _update_block(conn, block_id: int, b: Dict, now: str) -> None:
    conn.execute(
        """UPDATE code_blocks
           SET file_path=?, block_type=?, block_name=?, parent_class=?,
               signature=?, docstring=?, decorators=?, line_start=?, line_end=?,
               content_hash=?, scanned_at=?
           WHERE id=?""",
        (
            b["file_path"], b["block_type"], b["block_name"], b.get("parent_class"),
            b.get("signature"), b.get("docstring"), json.dumps(b.get("decorators", [])),
            b["line_start"], b["line_end"], b.get("content_hash"), now, block_id,
        ),
    )


def _insert_block(conn, b: Dict, now: str) -> None:
    conn.execute(
        """INSERT INTO code_blocks
           (file_path, block_type, block_name, parent_class, signature,
            docstring, decorators, line_start, line_end, content_hash, scanned_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            b["file_path"], b["block_type"], b["block_name"], b.get("parent_class"),
            b.get("signature"), b.get("docstring"), json.dumps(b.get("decorators", [])),
            b["line_start"], b["line_end"], b.get("content_hash"), now,
        ),
    )


def upsert_code_blocks(project_path: Path, blocks: List[Dict]) -> None:
    """Upsert that preserves block IDs (and thus answer history) across rescans.

    Block IDs must survive rescans — question_results.block_id references them,
    and coverage stats join on those IDs. Matching is two-phase:

    1. Exact key match on (file_path, block_type, block_name, parent_class).
    2. For anything left over, recover identity by content_hash when the match
       is unique — so a renamed or moved block keeps its history, while
       boilerplate that hashes identically (e.g. duplicate __init__s) is not
       falsely merged.
    """
    db_path = get_db_path(project_path)
    now = _utcnow_iso()
    with _connect(db_path) as conn:
        existing_rows = list(conn.execute(
            "SELECT id, file_path, block_type, block_name, parent_class, content_hash"
            " FROM code_blocks ORDER BY id"
        ))
        existing_by_key: Dict[tuple, List[int]] = {}
        for row in existing_rows:
            key = (row["file_path"], row["block_type"], row["block_name"], row["parent_class"])
            existing_by_key.setdefault(key, []).append(row["id"])

        scanned_by_key: Dict[tuple, List[Dict]] = {}
        for b in blocks:
            key = (b["file_path"], b["block_type"], b["block_name"], b.get("parent_class"))
            scanned_by_key.setdefault(key, []).append(b)

        matched_ids: set = set()
        unmatched_scanned: List[Dict] = []

        # Phase 1 — exact key match. Duplicate names within a key pair up in order.
        for key, scanned in scanned_by_key.items():
            ids = existing_by_key.get(key, [])
            for block_id, b in zip(ids, scanned):
                _update_block(conn, block_id, b, now)
                matched_ids.add(block_id)
            unmatched_scanned.extend(scanned[len(ids):])

        # Phase 2 — content-hash recovery for leftovers, unique matches only.
        leftover_existing = [r for r in existing_rows if r["id"] not in matched_ids]
        existing_by_hash: Dict[str, List[int]] = {}
        for r in leftover_existing:
            if r["content_hash"]:
                existing_by_hash.setdefault(r["content_hash"], []).append(r["id"])
        scanned_by_hash: Dict[str, List[Dict]] = {}
        for b in unmatched_scanned:
            if b.get("content_hash"):
                scanned_by_hash.setdefault(b["content_hash"], []).append(b)

        for b in unmatched_scanned:
            h = b.get("content_hash")
            ex_ids = existing_by_hash.get(h, []) if h else []
            if h and len(ex_ids) == 1 and len(scanned_by_hash.get(h, [])) == 1:
                _update_block(conn, ex_ids[0], b, now)
                matched_ids.add(ex_ids[0])
            else:
                _insert_block(conn, b, now)

        stale_ids = [r["id"] for r in existing_rows if r["id"] not in matched_ids]
        if stale_ids:
            params = [(i,) for i in stale_ids]
            # Drop dependent answer rows first, or the foreign key blocks the
            # delete when a removed block has answer history.
            conn.executemany("DELETE FROM question_results WHERE block_id=?", params)
            conn.executemany("DELETE FROM code_blocks WHERE id=?", params)


def get_all_blocks(project_path: Path) -> List[Dict]:
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM code_blocks ORDER BY file_path, line_start"
        ).fetchall()
    return [dict(r) for r in rows]


def create_session(project_path: Path, mode: str) -> int:
    db_path = get_db_path(project_path)
    now = _utcnow_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO sessions (mode, started_at) VALUES (?, ?)", (mode, now)
        )
        return cur.lastrowid


def end_session(
    project_path: Path, session_id: int, tokens_used: int, cost_usd: float
) -> None:
    db_path = get_db_path(project_path)
    now = _utcnow_iso()
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE sessions SET ended_at=?, tokens_used=?, cost_usd=? WHERE id=?",
            (now, tokens_used, cost_usd, session_id),
        )


def record_answer(
    project_path: Path,
    session_id: int,
    block_id: int,
    mode: str,
    question_text: str,
    question_type: str,
    user_answer: str,
    correct_answer: str,
    is_correct: bool,
    score: float,
    feedback: str,
    explanation: str,
) -> int:
    db_path = get_db_path(project_path)
    now = _utcnow_iso()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO question_results
               (session_id, block_id, mode, question_text, question_type,
                user_answer, correct_answer, is_correct, score, feedback,
                explanation, content_hash, answered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,
                       (SELECT content_hash FROM code_blocks WHERE id=?), ?)""",
            (
                session_id, block_id, mode, question_text, question_type,
                user_answer, correct_answer, int(is_correct), score,
                feedback, explanation, block_id, now,
            ),
        )
        return cur.lastrowid


def session_exists(project_path: Path, session_id: int) -> bool:
    """True if a session with this id was created."""
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
    return row is not None


def session_is_active(project_path: Path, session_id: int) -> bool:
    """True if the session exists and has not been ended."""
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id=? AND ended_at IS NULL", (session_id,)
        ).fetchone()
    return row is not None


def count_session_answers(project_path: Path, session_id: int) -> int:
    """Number of questions answered in a session (one row per answered question).

    Used to enforce the per-session question cap. `submitAnswer` fires once per
    question, so this equals the number of questions served in the session.
    """
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM question_results WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return row[0]


def get_session_correct_block_ids(project_path: Path, session_id: int) -> set:
    """Block IDs answered correctly at least once in this session — never repeated."""
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT block_id FROM question_results WHERE session_id=? AND is_correct=1",
            (session_id,),
        ).fetchall()
    return {r["block_id"] for r in rows}


def get_history(
    project_path: Path, session_limit: int = 10, offset: int = 0
) -> List[Dict]:
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        sessions = conn.execute("""
            SELECT s.id, s.mode, s.started_at, s.ended_at,
                   ROUND(s.cost_usd, 4)            AS cost_usd,
                   COUNT(qr.id)                    AS total_questions,
                   COALESCE(SUM(qr.is_correct), 0) AS correct_answers
            FROM sessions s
            LEFT JOIN question_results qr ON s.id = qr.session_id
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
        """, (session_limit, offset)).fetchall()

        result = []
        for session in sessions:
            questions = conn.execute("""
                SELECT
                    qr.question_text, qr.user_answer, qr.correct_answer,
                    qr.is_correct, qr.feedback, qr.explanation, qr.answered_at,
                    COALESCE(cb.file_path,  'unknown') AS file_path,
                    COALESCE(cb.block_name, 'unknown') AS block_name,
                    COALESCE(cb.block_type, 'unknown') AS block_type
                FROM question_results qr
                LEFT JOIN code_blocks cb ON cb.id = qr.block_id
                WHERE qr.session_id = ?
                ORDER BY qr.answered_at
            """, (session["id"],)).fetchall()

            result.append({**dict(session), "questions": [dict(q) for q in questions]})

    return result


def get_stats(project_path: Path) -> Dict:
    db_path = get_db_path(project_path)
    with _connect(db_path) as conn:
        total_blocks = conn.execute(
            "SELECT COUNT(*) FROM code_blocks WHERE block_type IN ('function','method','class')"
        ).fetchone()[0]

        # A correct answer only counts against the body it was given for, so a
        # block whose body changed since drops back to not-covered. `IS` is
        # NULL-safe (matches when both hashes are NULL).
        correct_blocks = conn.execute("""
            SELECT COUNT(DISTINCT qr.block_id)
            FROM question_results qr
            JOIN code_blocks cb ON cb.id = qr.block_id
            WHERE qr.is_correct = 1
              AND qr.content_hash IS cb.content_hash
              AND cb.block_type IN ('function','method','class')
        """).fetchone()[0]

        file_stats = conn.execute("""
            SELECT
                cb.file_path,
                COUNT(DISTINCT cb.id)  AS total_blocks,
                COUNT(DISTINCT CASE WHEN qr.is_correct=1 AND qr.content_hash IS cb.content_hash THEN qr.block_id END) AS correct_blocks,
                COUNT(qr.id)           AS attempts,
                COALESCE(AVG(qr.score), 0) AS avg_score
            FROM code_blocks cb
            LEFT JOIN question_results qr ON cb.id = qr.block_id
            WHERE cb.block_type IN ('function','method','class')
            GROUP BY cb.file_path
            ORDER BY cb.file_path
        """).fetchall()

        concept_stats = conn.execute("""
            SELECT
                cb.block_type,
                COUNT(DISTINCT cb.id)  AS total_blocks,
                COUNT(DISTINCT CASE WHEN qr.is_correct=1 AND qr.content_hash IS cb.content_hash THEN qr.block_id END) AS correct_blocks,
                COUNT(qr.id)           AS attempts,
                COALESCE(AVG(qr.score), 0) AS avg_score
            FROM code_blocks cb
            LEFT JOIN question_results qr ON cb.id = qr.block_id
            WHERE cb.block_type IN ('function','method','class')
            GROUP BY cb.block_type
        """).fetchall()

        sessions = conn.execute("""
            SELECT
                s.id, s.mode, s.started_at, s.ended_at,
                ROUND(s.cost_usd, 4)   AS cost_usd,
                COUNT(qr.id)           AS questions_answered,
                COALESCE(SUM(qr.is_correct), 0) AS correct_answers
            FROM sessions s
            LEFT JOIN question_results qr ON s.id = qr.session_id
            GROUP BY s.id
            ORDER BY s.started_at DESC
            LIMIT 20
        """).fetchall()

    coverage_pct = round(correct_blocks / total_blocks * 100, 1) if total_blocks else 0.0

    return {
        "total_blocks": total_blocks,
        "correct_blocks": correct_blocks,
        "coverage_pct": coverage_pct,
        "has_95_achievement": coverage_pct >= 95.0,
        "file_stats": [dict(r) for r in file_stats],
        "concept_stats": [dict(r) for r in concept_stats],
        "sessions": [dict(r) for r in sessions],
    }
