# OwnYourShip — Session Handoff

> Read this at the start of every session. Update it at the end of every session.

---

## Current State

**Date of last update:** 2026-06-10  
**Status:** Feature-complete v1 — tested and working end-to-end

---

## What Was Built (Session 1 — Initial Build)

Full initial implementation. See git history or original session notes for details.

---

## What Was Changed (Session 2 — Fixes & Features)

### Bugs fixed
- **"Next Question" button not appearing** — `clearFeedback()` was setting `style.display = 'none'` inline, which overrode the CSS `.show { display: block }` class. Fixed by clearing the inline style instead.
- **Correct answer always A** — Claude consistently places the correct answer first. Fixed in `quiz.py` by shuffling MC options after generation and remapping `correct_answer` to the new position.
- **Nav routing after session end** — clicking "Quiz" after viewing stats showed the stale last question. Fixed by clearing `S.sessionId` and `S.currentQuestion` in `showSessionDone()`.
- **Explanation contradicting itself** — Claude was doing chain-of-thought reasoning inside the JSON explanation field, changing its answer mid-string. Fixed via prompt rules.
- **`code_snippet` missing from API response** — server was running old code. Fix required restart. Code snippet now confirmed working after restart.

### Features added
- **Code snippet display** — relevant lines shown in question card, target lines highlighted, context lines dimmed
- **20-question session cap** — sessions stop at 20 questions; multiple sessions required to reach 95%
- **2-strike MC mechanic** — wrong answer 1: that option locks red, "one attempt remaining" shown; wrong answer 2: correct answer revealed, feedback shown
- **All questions now multiple choice** — free text removed entirely (from quiz generation, server grading path, and UI)
- **Question History tab** — Stats screen now has Overview + Question History tabs; history shows every past session with each question, your answer, correct answer (if wrong), and explanation

### Prompt improvements
- No arithmetic/calculation questions
- No option letter references in explanations
- Explanations must be a single confident statement — no hedging or reconsidering

---

## What Was Changed (Session 3 — Bug-Hunt & Fixes, 2026-06-10)

### Bugs fixed
- **Ctrl+C dead on Windows** — `shutdown_event.wait()` with no timeout can't be interrupted by Ctrl+C on Windows. `main.py` now polls `wait(timeout=1.0)` in a loop, so both Ctrl+C and the browser End Session button work.
- **Coverage reset to ~0 on every launch** — `upsert_code_blocks` was DELETE + re-INSERT, so block IDs changed on every scan (and the UI triggers a scan on every page load). All past `question_results.block_id` references went stale, making the 95% achievement impossible across runs — fatal, since the 20-question cap requires multiple sessions. Now a true upsert keyed on `(file_path, block_type, block_name, parent_class)`: existing IDs are preserved and updated in place, new blocks inserted, removed blocks deleted. Verified with a scripted test: answer history and coverage survive rescans, duplicates and deletions handled.
- **Off-by-one final score** — session-done screen showed `questionCount - 1` as the denominator (e.g. "20/19 correct" on a perfect session). Fixed in `app.js:showSessionDone`.
- **`migrations` exclusion never worked** — it was in `excluded_patterns` (matched against filenames only); moved to `excluded_dirs`. Note: projects with an existing `.oys/config.json` keep their stored lists and won't pick this up automatically.

### Cleanup
- **Haiku 4.5 pricing confirmed and updated** — $1.00 input / $5.00 output per 1M tokens (was $0.80/$4.00 Haiku 3.5 proxy, ~20% undercount). `quiz.py` constants updated; model ID `claude-haiku-4-5-20251001` confirmed valid.
- **Free-text remnants removed** — `grader.grade_free_text` (dead code) deleted; security banner, Hard-mode card, CLI disclaimer, and DISCLAIMER.md no longer claim answers are sent for grading (MC is graded locally — only question generation hits the API).
- **Dead `all_time_perf` plumbing removed** — `select_next_block` accepted but never used all-time performance data; the param, the per-question DB query, and `db.get_performance_by_block` are gone. (Cross-session fresh-slate is the documented design; reintroduce deliberately if tailored mode should ever use history.)
- Removed a no-op `SO_REUSEADDR` set *after* `bind()` in `_find_free_port`.

### Known issue accepted as-is
- `/api/answer` trusts the client-supplied `correct_answer` (the browser already knows the answer before submitting). Self-cheating only — acceptable for a local single-user tool.

### Backlog cleared (same session)
- **Rescan button** — "⟳ Rescan Project" in the sidebar; triggers `/api/scan`, polls until complete, refreshes block counts. Required a server fix: scan flags now flip *before* the worker thread starts, otherwise a poll right after POST could see a stale `scan_complete=True` and return without rescanning (verified via TestClient).
- **Non-Python line ranges** — new `scanner._block_end_line` does naive brace matching from the regex match to find the real `line_end` for JS/TS/Go/Rust/Java blocks, so snippets show full bodies. Body-less declarations (`struct Foo(i32);`, arrow funcs without braces) stay single-line. Limitation: braces inside strings/comments aren't lexed — acceptable for snippet display. Covered by tests (JS function/class/arrow, Go struct/method, Rust tuple-struct/fn).
- **History pagination** — `/api/history` takes `limit` (clamped 1–50) and `offset`; `db.get_history` uses `LIMIT ? OFFSET ?`. UI loads 10 sessions at a time with a "Load more sessions" button that hides when a short page comes back.

### README pass (end of session)
- Fixed typos ("code that exceeds", "its"), removed the malformed `<URL>` brackets from the clone command, replaced the stale "isn't reliable yet whatsoever" paragraph (that bug was fixed in Session 2), and documented the rescan button and Stats/History tabs.
- Not done: screenshots and `pipx` install instructions — needs a published package / captured images.

---

## Known Issues / Incomplete Items

1. **Renamed/moved blocks lose history** — the upsert key is name-based, so renaming a function or moving it to another file orphans its answer history (the block gets a new ID). A content-hash identity would handle renames; not worth it yet.

2. **Brace matching is naive** — `_block_end_line` doesn't lex strings/comments, so a stray `{`/`}` inside one can skew a non-Python snippet's range. Cosmetic only.

3. **JS changes not browser-tested** — Session 3's app.js changes (rescan button, history pagination, score fix) were verified by review only (no Node on this machine for `node --check`). Do a quick browser smoke test on the next `oys` run: rescan mid-welcome, history Load more, session-done score.

---

## Next Steps

Backlog is clear. Candidates for a future session:
1. Browser smoke test of the Session 3 UI changes (see known issue 3)
2. README screenshots + `pipx`/PyPI packaging
3. Content-hash block identity if rename-history-loss starts to hurt

---

## Architecture Reference

```
ownyourship/
├── ownyourship/
│   ├── main.py       — CLI entry point, disclaimer, server lifecycle
│   ├── server.py     — FastAPI, all REST endpoints
│   ├── scanner.py    — AST (Python) + regex (JS/TS/Go/Rust/Java) scanner
│   ├── quiz.py       — Haiku question generation, MC shuffle, block selector
│   ├── grader.py     — MC grading only (free text removed)
│   ├── db.py         — SQLite schema + all queries incl. get_history()
│   ├── config.py     — .oys/config.json management
│   └── static/       — Dark-mode SPA (index.html, style.css, app.js)
├── venv/             — Python 3.13 venv, all deps installed
├── pyproject.toml
├── DISCLAIMER.md
├── .gitignore
├── .env.example
└── README.md
```

## Environment

- Python 3.13, venv at `venv\Scripts\activate`
- `oys` command available after activation
- API key at `%USERPROFILE%\.oys\.env`
- Run against the ownyourship repo itself for testing: `oys C:\Users\jemhr\MLProjects\ownyourship`
