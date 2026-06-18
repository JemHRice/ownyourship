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
                answered_at   TEXT    NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (block_id)   REFERENCES code_blocks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_qr_session ON question_results(session_id);
            CREATE INDEX IF NOT EXISTS idx_qr_block   ON question_results(block_id);
            CREATE INDEX IF NOT EXISTS idx_cb_file    ON code_blocks(file_path);
        """)


@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_code_blocks(project_path: Path, blocks: List[Dict]) -> None:
    """True upsert keyed on (file_path, block_type, block_name, parent_class).

    Block IDs must survive rescans — question_results.block_id references them,
    and the all-time coverage stats join on those IDs. A delete-and-reinsert
    would orphan every past answer and reset coverage to zero on each launch.
    """
    db_path = get_db_path(project_path)
    now = _utcnow_iso()
    with _connect(db_path) as conn:
        existing_by_key: Dict[tuple, List[int]] = {}
        for row in conn.execute(
            "SELECT id, file_path, block_type, block_name, parent_class"
            " FROM code_blocks ORDER BY id"
        ):
            key = (row["file_path"], row["block_type"], row["block_name"], row["parent_class"])
            existing_by_key.setdefault(key, []).append(row["id"])

        scanned_by_key: Dict[tuple, List[Dict]] = {}
        for b in blocks:
            key = (b["file_path"], b["block_type"], b["block_name"], b.get("parent_class"))
            scanned_by_key.setdefault(key, []).append(b)

        for key, scanned in scanned_by_key.items():
            ids = existing_by_key.get(key, [])
            # Duplicate names within a file pair up in order; extras are inserted.
            for block_id, b in zip(ids, scanned):
                conn.execute(
                    """UPDATE code_blocks
                       SET signature=?, docstring=?, decorators=?,
                           line_start=?, line_end=?, scanned_at=?
                       WHERE id=?""",
                    (
                        b.get("signature"), b.get("docstring"),
                        json.dumps(b.get("decorators", [])),
                        b["line_start"], b["line_end"], now, block_id,
                    ),
                )
            for b in scanned[len(ids):]:
                conn.execute(
                    """INSERT INTO code_blocks
                       (file_path, block_type, block_name, parent_class, signature,
                        docstring, decorators, line_start, line_end, scanned_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        b["file_path"], b["block_type"], b["block_name"],
                        b.get("parent_class"), b.get("signature"), b.get("docstring"),
                        json.dumps(b.get("decorators", [])),
                        b["line_start"], b["line_end"], now,
                    ),
                )

        stale_ids = [
            block_id
            for key, ids in existing_by_key.items()
            for block_id in ids[len(scanned_by_key.get(key, [])):]
        ]
        if stale_ids:
            conn.executemany(
                "DELETE FROM code_blocks WHERE id=?", [(i,) for i in stale_ids]
            )


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
                explanation, answered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id, block_id, mode, question_text, question_type,
                user_answer, correct_answer, int(is_correct), score,
                feedback, explanation, now,
            ),
        )
        return cur.lastrowid


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

        correct_blocks = conn.execute("""
            SELECT COUNT(DISTINCT qr.block_id)
            FROM question_results qr
            JOIN code_blocks cb ON cb.id = qr.block_id
            WHERE qr.is_correct = 1
              AND cb.block_type IN ('function','method','class')
        """).fetchone()[0]

        file_stats = conn.execute("""
            SELECT
                cb.file_path,
                COUNT(DISTINCT cb.id)  AS total_blocks,
                COUNT(DISTINCT CASE WHEN qr.is_correct=1 THEN qr.block_id END) AS correct_blocks,
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
                COUNT(DISTINCT CASE WHEN qr.is_correct=1 THEN qr.block_id END) AS correct_blocks,
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
