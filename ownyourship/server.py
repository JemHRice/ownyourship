import threading
from pathlib import Path
from typing import Dict, Optional

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as cfg
from . import db
from . import grader
from . import quiz as quiz_mod
from . import scanner

STATIC_DIR = Path(__file__).parent / "static"

# A session serves at most this many questions; the frontend caps loads at the
# same number, but the server is the authority (see /api/question).
MAX_QUESTIONS_PER_SESSION = 20


class _State:
    project_path: Optional[Path] = None
    api_key: Optional[str] = None
    client: Optional[anthropic.AsyncAnthropic] = None
    config: dict = {}
    shutdown_event: threading.Event = threading.Event()

    scan_complete: bool = False
    scan_in_progress: bool = False
    scan_error: Optional[str] = None

    current_session_id: Optional[int] = None
    session_tokens_in: int = 0
    session_tokens_out: int = 0
    session_perf: Dict = {}  # {block_id: {"correct": int, "total": int}}


_state = _State()


def create_app(
    project_path: Path, api_key: str, shutdown_event: threading.Event
) -> FastAPI:
    _state.project_path = project_path
    _state.api_key = api_key
    _state.shutdown_event = shutdown_event
    _state.client = anthropic.AsyncAnthropic(api_key=api_key)
    _state.config = cfg.load_config(project_path)

    app = FastAPI(title="OwnYourShip", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Static UI ────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    # ── Status / scan ────────────────────────────────────────────────────────

    @app.get("/api/status")
    async def status():
        blocks = (
            scanner.get_meaningful_blocks(db.get_all_blocks(_state.project_path))
            if _state.scan_complete
            else []
        )
        return {
            "scan_complete": _state.scan_complete,
            "scan_in_progress": _state.scan_in_progress,
            "scan_error": _state.scan_error,
            "total_blocks": len(blocks),
            "project_name": _state.project_path.name,
            "project_path": str(_state.project_path),
        }

    @app.post("/api/scan")
    async def trigger_scan():
        if _state.scan_in_progress:
            return {"status": "already_scanning"}
        # Flip flags before the thread starts, or a client polling /api/status
        # right after this returns can see a stale scan_complete=True.
        _state.scan_in_progress = True
        _state.scan_complete = False
        _state.scan_error = None

        def _do_scan():
            try:
                blocks = scanner.scan_project(_state.project_path, _state.config)
                db.init_db(_state.project_path)
                db.upsert_code_blocks(_state.project_path, blocks)
                _state.scan_complete = True
            except Exception as exc:
                _state.scan_error = str(exc)
            finally:
                _state.scan_in_progress = False

        threading.Thread(target=_do_scan, daemon=True).start()
        return {"status": "scanning"}

    # ── Session ──────────────────────────────────────────────────────────────

    class StartSessionReq(BaseModel):
        mode: str

    @app.post("/api/session/start")
    async def start_session(req: StartSessionReq):
        if req.mode not in ("easy", "intermediate", "hard", "tailored"):
            raise HTTPException(400, "Invalid mode")
        sid = db.create_session(_state.project_path, req.mode)
        _state.current_session_id = sid
        _state.session_tokens_in = 0
        _state.session_tokens_out = 0
        _state.session_perf = {}
        return {"session_id": sid, "mode": req.mode}

    class EndSessionReq(BaseModel):
        session_id: int

    @app.post("/api/session/end")
    async def end_session(req: EndSessionReq):
        cost = quiz_mod.estimate_cost(_state.session_tokens_in, _state.session_tokens_out)
        total_tok = _state.session_tokens_in + _state.session_tokens_out
        db.end_session(_state.project_path, req.session_id, total_tok, cost)
        return {"status": "ended", "cost_usd": round(cost, 4)}

    # ── Question ─────────────────────────────────────────────────────────────

    @app.get("/api/question")
    async def get_question(session_id: int, mode: str):
        if not _state.scan_complete:
            raise HTTPException(400, "Scan not complete")

        if not db.session_exists(_state.project_path, session_id):
            raise HTTPException(404, "Unknown session")

        if not db.session_is_active(_state.project_path, session_id):
            raise HTTPException(409, "Session already ended")

        if db.count_session_answers(_state.project_path, session_id) >= MAX_QUESTIONS_PER_SESSION:
            return {
                "finished": True,
                "message": f"{MAX_QUESTIONS_PER_SESSION}-question session complete!",
            }

        all_blocks = scanner.get_meaningful_blocks(db.get_all_blocks(_state.project_path))
        if not all_blocks:
            raise HTTPException(404, "No quizzable blocks found")

        answered = db.get_session_correct_block_ids(_state.project_path, session_id)

        block = quiz_mod.select_next_block(
            all_blocks, answered, mode, _state.session_perf
        )
        if block is None:
            return {"finished": True, "message": "All blocks covered for this session!"}

        qdata, in_tok, out_tok = await quiz_mod.generate_question(
            block, _state.project_path, mode, _state.client, _state.session_perf
        )
        _state.session_tokens_in += in_tok
        _state.session_tokens_out += out_tok

        cost = quiz_mod.estimate_cost(_state.session_tokens_in, _state.session_tokens_out)
        threshold = _state.config.get("cost_warning_threshold_usd", 0.50)

        if qdata is None:
            raise HTTPException(500, "Failed to generate question — check API key and try again")

        file_abs = _state.project_path / block["file_path"]
        display_snippet = quiz_mod.get_code_context(
            file_abs, block["line_start"], block["line_end"], ctx=2
        )

        return {
            **qdata,
            "code_snippet": display_snippet,
            "session_cost_usd": round(cost, 4),
            "cost_warning": cost >= threshold,
            "answered_count": len(answered),
            "total_blocks": len(all_blocks),
        }

    # ── Answer ───────────────────────────────────────────────────────────────

    class AnswerReq(BaseModel):
        session_id: int
        block_id: int
        mode: str
        question_text: str
        question_type: str
        user_answer: str
        correct_answer: str
        explanation: str

    @app.post("/api/answer")
    async def submit_answer(req: AnswerReq):
        if not db.session_exists(_state.project_path, req.session_id):
            raise HTTPException(404, "Unknown session")

        if not db.session_is_active(_state.project_path, req.session_id):
            raise HTTPException(409, "Session already ended")

        user_answer = req.user_answer[:500]
        is_correct, score, feedback = grader.grade_multiple_choice(
            user_answer, req.correct_answer
        )

        db.record_answer(
            _state.project_path, req.session_id, req.block_id, req.mode,
            req.question_text, req.question_type, user_answer, req.correct_answer,
            is_correct, score, feedback, req.explanation,
        )

        pid = req.block_id
        if pid not in _state.session_perf:
            _state.session_perf[pid] = {"correct": 0, "total": 0}
        _state.session_perf[pid]["total"] += 1
        if is_correct:
            _state.session_perf[pid]["correct"] += 1

        cost = quiz_mod.estimate_cost(_state.session_tokens_in, _state.session_tokens_out)
        threshold = _state.config.get("cost_warning_threshold_usd", 0.50)

        return {
            "is_correct": is_correct,
            "score": score,
            "feedback": feedback,
            "explanation": req.explanation,
            "session_cost_usd": round(cost, 4),
            "cost_warning": cost >= threshold,
        }

    # ── Stats ────────────────────────────────────────────────────────────────

    @app.get("/api/stats")
    async def get_stats():
        if not _state.scan_complete:
            return {"error": "Scan not complete yet"}
        return db.get_stats(_state.project_path)

    # ── Config ───────────────────────────────────────────────────────────────

    @app.get("/api/config")
    async def get_config():
        c = dict(_state.config)
        c.pop("disclaimer_acknowledged", None)
        c.pop("disclaimer_acknowledged_at", None)
        return c

    # ── History ──────────────────────────────────────────────────────────────

    @app.get("/api/history")
    async def get_history(limit: int = 10, offset: int = 0):
        limit = max(1, min(limit, 50))
        offset = max(0, offset)
        return db.get_history(_state.project_path, limit, offset)

    # ── Shutdown ─────────────────────────────────────────────────────────────

    @app.post("/api/shutdown")
    async def shutdown():
        _state.shutdown_event.set()
        return {"status": "shutting_down"}

    return app
