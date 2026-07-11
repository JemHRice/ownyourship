import time


def _scan_and_wait(client, timeout=5.0):
    """Trigger a scan and poll /api/status until it completes."""
    assert client.post("/api/scan").json()["status"] in ("scanning", "already_scanning")
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/status").json()
        if status["scan_complete"]:
            return status
        if status["scan_error"]:
            raise AssertionError(f"scan failed: {status['scan_error']}")
        time.sleep(0.02)
    raise AssertionError("scan did not complete in time")


def test_status_before_scan(server_client):
    status = server_client.get("/api/status").json()
    assert status["scan_complete"] is False
    assert status["total_blocks"] == 0


def test_scan_completes_and_finds_blocks(server_client):
    status = _scan_and_wait(server_client)
    assert status["scan_complete"] is True
    assert status["total_blocks"] >= 1  # the `foo` function in mod.py


def test_session_start_rejects_invalid_mode(server_client):
    resp = server_client.post("/api/session/start", json={"mode": "bogus"})
    assert resp.status_code == 400


def test_session_start_accepts_valid_mode(server_client):
    resp = server_client.post("/api/session/start", json={"mode": "easy"})
    assert resp.status_code == 200
    assert "session_id" in resp.json()


def test_question_requires_completed_scan(server_client):
    resp = server_client.get("/api/question", params={"session_id": 1, "mode": "easy"})
    assert resp.status_code == 400


def test_question_returns_generated_payload(server_client, monkeypatch):
    from ownyourship import quiz

    async def fake_generate(block, *args, **kwargs):
        qdata = {
            "question": "what does foo do?",
            "type": "multiple_choice",
            "options": ["A: a", "B: b", "C: c", "D: d"],
            "correct_answer": "A",
            "explanation": "because",
            "block_id": block["id"],
        }
        return qdata, 12, 34

    monkeypatch.setattr(quiz, "generate_question", fake_generate)

    _scan_and_wait(server_client)
    sid = server_client.post("/api/session/start", json={"mode": "easy"}).json()["session_id"]
    resp = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["question"] == "what does foo do?"
    assert "code_snippet" in body
    assert body["total_blocks"] >= 1


def test_answer_records_and_grades(server_client, monkeypatch):
    _mock_question_generation(monkeypatch)  # serves a question with correct answer "A"
    _scan_and_wait(server_client)
    sid = server_client.post("/api/session/start", json={"mode": "easy"}).json()["session_id"]
    q = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"}).json()

    resp = server_client.post("/api/answer", json={
        "session_id": sid, "block_id": q["block_id"], "mode": "easy",
        "question_text": "q?", "question_type": "multiple_choice",
        "user_answer": "A", "correct_answer": "A", "explanation": "exp",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_correct"] is True
    assert body["score"] == 1.0


def test_history_clamps_limit(server_client):
    _scan_and_wait(server_client)
    resp = server_client.get("/api/history", params={"limit": 999})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_config_strips_disclaimer_fields(server_client):
    body = server_client.get("/api/config").json()
    assert "disclaimer_acknowledged" not in body
    assert "disclaimer_acknowledged_at" not in body
    assert "included_extensions" in body


def test_diagram_requires_scan(server_client):
    assert server_client.get("/api/diagram").status_code == 400


def test_diagram_endpoint_returns_components(server_client):
    _scan_and_wait(server_client)
    body = server_client.get("/api/diagram").json()
    assert {"components", "function_edges", "component_edges"} <= set(body)
    assert any(c["functions"] for c in body["components"])  # mod.py / foo


def test_diagram_labels_endpoint(server_client, monkeypatch):
    from ownyourship import labels

    async def fake_label(component, client):
        return "a label"

    monkeypatch.setattr(labels, "generate_component_label", fake_label)
    _scan_and_wait(server_client)
    body = server_client.get("/api/diagram/labels").json()
    assert body and all(v == "a label" for v in body.values())


def test_function_labels_requires_scan(server_client):
    resp = server_client.post("/api/diagram/labels/functions", json={"function_ids": ["x"]})
    assert resp.status_code == 400


def test_function_labels_endpoint(server_client, monkeypatch):
    from ownyourship import labels

    async def fake_labels(file_name, functions, client):
        return {f["id"]: "a fn label" for f in functions}

    monkeypatch.setattr(labels, "generate_function_labels", fake_labels)
    _scan_and_wait(server_client)
    d = server_client.get("/api/diagram").json()
    fid = next(f["id"] for c in d["components"] for f in c["functions"])
    resp = server_client.post("/api/diagram/labels/functions", json={"function_ids": [fid]})
    assert resp.status_code == 200
    assert resp.json() == {fid: "a fn label"}


def test_function_labels_unknown_id_returns_empty(server_client):
    _scan_and_wait(server_client)
    resp = server_client.post("/api/diagram/labels/functions",
                              json={"function_ids": ["nope.py::ghost"]})
    assert resp.status_code == 200
    assert resp.json() == {}


# ── 20-question session cap (RED — implementation pending) ────────────────────

SESSION_QUESTION_CAP = 20


def _mock_question_generation(monkeypatch):
    """Make /api/question return a canned MC question without touching the API."""
    from ownyourship import quiz

    async def fake_generate(block, *args, **kwargs):
        qdata = {
            "question": "what does foo do?",
            "type": "multiple_choice",
            "options": ["A: a", "B: b", "C: c", "D: d"],
            "correct_answer": "A",
            "explanation": "because",
            "block_id": block["id"],
        }
        return qdata, 5, 7

    monkeypatch.setattr(quiz, "generate_question", fake_generate)


def _answer_wrong(client, question_body, session_id):
    """Submit a deliberately wrong answer.

    Only correctly-answered blocks leave the pool, so answering wrong keeps the
    block pool full — the session can then only end because of the cap, never
    because we ran out of blocks.
    """
    return client.post("/api/answer", json={
        "session_id": session_id,
        "block_id": question_body["block_id"],
        "mode": "easy",
        "question_text": question_body.get("question", "q"),
        "question_type": "multiple_choice",
        "user_answer": "B",                                   # mock's correct is "A"
        "correct_answer": question_body["correct_answer"],
        "explanation": "",
    })


def _start_session(client):
    return client.post("/api/session/start", json={"mode": "easy"}).json()["session_id"]


def test_session_caps_at_20_questions(server_client, monkeypatch):
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)

    for n in range(SESSION_QUESTION_CAP):
        body = server_client.get(
            "/api/question", params={"session_id": sid, "mode": "easy"}
        ).json()
        assert not body.get("finished"), f"session ended early at question {n + 1}"
        _answer_wrong(server_client, body, sid)

    # The 21st request must report the session complete, not serve another question.
    body = server_client.get(
        "/api/question", params={"session_id": sid, "mode": "easy"}
    ).json()
    assert body.get("finished") is True


def test_question_cap_is_per_session(server_client, monkeypatch):
    """The cap counts this session's questions only — a fresh session starts over."""
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)

    sid1 = _start_session(server_client)
    for _ in range(SESSION_QUESTION_CAP):
        body = server_client.get(
            "/api/question", params={"session_id": sid1, "mode": "easy"}
        ).json()
        _answer_wrong(server_client, body, sid1)

    sid2 = _start_session(server_client)
    body = server_client.get(
        "/api/question", params={"session_id": sid2, "mode": "easy"}
    ).json()
    assert not body.get("finished")
    assert "question" in body


# ── Session validation (RED — implementation pending) ─────────────────────────

UNKNOWN_SESSION_ID = 99999


def test_question_rejects_unknown_session(server_client, monkeypatch):
    """Requesting a question for a session that was never started must 404."""
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    resp = server_client.get(
        "/api/question", params={"session_id": UNKNOWN_SESSION_ID, "mode": "easy"}
    )
    assert resp.status_code == 404


def test_answer_rejects_unknown_session(server_client):
    """Submitting an answer against a session that was never started must 404,
    before anything is recorded."""
    _scan_and_wait(server_client)
    resp = server_client.post("/api/answer", json={
        "session_id": UNKNOWN_SESSION_ID, "block_id": 1, "mode": "easy",
        "question_text": "q?", "question_type": "multiple_choice",
        "user_answer": "A", "correct_answer": "A", "explanation": "exp",
    })
    assert resp.status_code == 404


# ── Stats, session end, and the block-exhaustion finish ───────────────────────

def _answer_correct(client, question_body, session_id):
    return client.post("/api/answer", json={
        "session_id": session_id,
        "block_id": question_body["block_id"],
        "mode": "easy",
        "question_text": question_body.get("question", "q"),
        "question_type": "multiple_choice",
        "user_answer": "A",                                   # mock's correct is "A"
        "correct_answer": question_body["correct_answer"],
        "explanation": "",
    })


def test_stats_endpoint_before_scan(server_client):
    body = server_client.get("/api/stats").json()
    assert "error" in body


def test_stats_endpoint_reports_coverage_and_breakdowns(server_client, monkeypatch):
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)
    q = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"}).json()
    _answer_correct(server_client, q, sid)

    stats = server_client.get("/api/stats").json()
    assert stats["total_blocks"] >= 1
    assert stats["correct_blocks"] >= 1
    assert 0 <= stats["coverage_pct"] <= 100
    assert "has_95_achievement" in stats

    assert stats["file_stats"]
    assert {"file_path", "total_blocks", "correct_blocks", "attempts", "avg_score"} <= set(stats["file_stats"][0])
    assert stats["concept_stats"]
    assert {"block_type", "total_blocks", "correct_blocks", "attempts", "avg_score"} <= set(stats["concept_stats"][0])


def test_session_end_persists_cost(server_client, monkeypatch):
    from ownyourship import quiz

    async def fake_generate(block, *args, **kwargs):
        qdata = {
            "question": "q", "type": "multiple_choice",
            "options": ["A: a", "B: b", "C: c", "D: d"],
            "correct_answer": "A", "explanation": "e", "block_id": block["id"],
        }
        return qdata, 1_000_000, 1_000_000  # $1 input + $5 output = $6

    monkeypatch.setattr(quiz, "generate_question", fake_generate)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)
    server_client.get("/api/question", params={"session_id": sid, "mode": "easy"})

    resp = server_client.post("/api/session/end", json={"session_id": sid})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ended"
    assert resp.json()["cost_usd"] == 6.0

    sess = next(s for s in server_client.get("/api/stats").json()["sessions"] if s["id"] == sid)
    assert sess["ended_at"] is not None
    assert sess["cost_usd"] == 6.0


def test_question_finished_when_all_blocks_covered(server_client, monkeypatch):
    """Distinct from the cap: once every block is answered correctly, the pool
    is empty and /api/question reports the all-covered finish."""
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)

    q = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"}).json()
    _answer_correct(server_client, q, sid)  # the only block (foo) leaves the pool

    body = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"}).json()
    assert body.get("finished") is True
    assert "covered" in body.get("message", "").lower()


# ── Reject ended sessions (RED — implementation pending) ──────────────────────

def test_question_rejects_ended_session(server_client, monkeypatch):
    """Once a session is ended, no more questions may be served for it."""
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)
    server_client.post("/api/session/end", json={"session_id": sid})

    resp = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"})
    assert resp.status_code == 409


def test_answer_rejects_ended_session(server_client):
    """Once a session is ended, no more answers may be recorded against it."""
    _scan_and_wait(server_client)
    sid = _start_session(server_client)
    server_client.post("/api/session/end", json={"session_id": sid})

    resp = server_client.post("/api/answer", json={
        "session_id": sid, "block_id": 1, "mode": "easy",
        "question_text": "q?", "question_type": "multiple_choice",
        "user_answer": "A", "correct_answer": "A", "explanation": "exp",
    })
    assert resp.status_code == 409


# ── Server-side answer integrity (RED — implementation pending) ───────────────

def test_answer_graded_by_server_not_client(server_client, monkeypatch):
    """The client can't mark a wrong answer correct by lying about correct_answer.

    The mock's correct answer is "A". The user picks "B" (wrong) but the client
    claims correct_answer is "B" to force a pass. The server must grade against
    its own stored answer and record this as incorrect.
    """
    _mock_question_generation(monkeypatch)
    _scan_and_wait(server_client)
    sid = _start_session(server_client)
    q = server_client.get("/api/question", params={"session_id": sid, "mode": "easy"}).json()

    resp = server_client.post("/api/answer", json={
        "session_id": sid, "block_id": q["block_id"], "mode": "easy",
        "question_text": "q", "question_type": "multiple_choice",
        "user_answer": "B", "correct_answer": "B", "explanation": "",
    })
    assert resp.status_code == 200
    assert resp.json()["is_correct"] is False


def test_answer_without_served_question_rejected(server_client):
    """Grades only come from server-issued questions: answering a block that was
    never served in this session is rejected, since there's nothing to grade against."""
    _scan_and_wait(server_client)
    sid = _start_session(server_client)

    resp = server_client.post("/api/answer", json={
        "session_id": sid, "block_id": 1, "mode": "easy",
        "question_text": "q", "question_type": "multiple_choice",
        "user_answer": "A", "correct_answer": "A", "explanation": "",
    })
    assert resp.status_code == 409
