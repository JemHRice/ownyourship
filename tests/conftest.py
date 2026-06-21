"""Shared test fixtures and helpers.

No test ever hits the Anthropic API or the network: the quiz code takes an
injected client, so we pass a FakeAnthropic whose `.messages.create` returns a
canned response (or raises a canned error).
"""
import threading
from types import SimpleNamespace

import pytest


# ── Fake Anthropic client ──────────────────────────────────────────────────

def make_response(text: str, in_tok: int, out_tok: int):
    """Mimic the shape quiz.generate_question reads: content[0].text + usage."""
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


class FakeAnthropic:
    """Stand-in for anthropic.AsyncAnthropic.

    `messages.create` is async (the real one is awaited). It records every
    call in `self.calls` and either returns a canned response or raises the
    canned error.
    """

    def __init__(self, text: str = "{}", in_tok: int = 10, out_tok: int = 20, error=None):
        self._text = text
        self._in = in_tok
        self._out = out_tok
        self._error = error
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return make_response(self._text, self._in, self._out)


@pytest.fixture
def fake_anthropic():
    return FakeAnthropic


# ── Code-block builder (matches scanner output: no `id`) ────────────────────

def make_block(
    file_path="mod.py",
    block_type="function",
    block_name="foo",
    parent_class=None,
    signature="def foo()",
    docstring=None,
    decorators=None,
    line_start=1,
    line_end=2,
):
    return {
        "file_path": file_path,
        "block_type": block_type,
        "block_name": block_name,
        "parent_class": parent_class,
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators or [],
        "line_start": line_start,
        "line_end": line_end,
    }


@pytest.fixture
def block_factory():
    return make_block


# ── Project dir ─────────────────────────────────────────────────────────────

@pytest.fixture
def project(tmp_path):
    """An empty project directory (a real, isolated path per test)."""
    return tmp_path


# ── Server client (resets the module-level _state singleton per test) ───────

@pytest.fixture
def server_app(tmp_path):
    """Build a fresh FastAPI app over a tiny project and reset _state.

    server.py keeps a module-level _state singleton, so without this reset
    tests would leak scan flags into one another. Returns (project_path, app).
    """
    from ownyourship import db
    from ownyourship.server import create_app, _state

    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    db.init_db(tmp_path)  # main.py always does this before serving

    app = create_app(tmp_path, "test-key", threading.Event())

    _state.scan_complete = False
    _state.scan_in_progress = False
    _state.scan_error = None
    _state.current_session_id = None
    _state.session_tokens_in = 0
    _state.session_tokens_out = 0
    _state.session_perf = {}
    _state.pending_answers = {}

    return tmp_path, app


@pytest.fixture
def server_client(server_app):
    from fastapi.testclient import TestClient

    _proj, app = server_app
    with TestClient(app) as client:
        yield client
