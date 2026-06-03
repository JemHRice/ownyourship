# OwnYourShip — Session Handoff

> Read this at the start of every session. Update it at the end of every session.

---

## Current State

**Date of last update:** 2026-06-03  
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

## Known Issues / Incomplete Items

1. **Cost pricing estimate** — Uses Haiku 3.5 pricing ($0.80/$4.00 per 1M tokens) as proxy for `claude-haiku-4-5-20251001`. Verify actual Haiku 4.5 pricing at https://anthropic.com/pricing and update `quiz.py:_INPUT_COST_PER_TOKEN` / `_OUTPUT_COST_PER_TOKEN`.

2. **Security banner text** — Still says "for question generation and grading" but free text grading was removed. Should say "for question generation only".

3. **No rescan button in UI** — If the project changes mid-session, the user must restart `oys` to rescan. A "Rescan Project" button in the sidebar would be useful.

4. **Non-Python line range detection** — The regex scanner sets `line_end = line_start` for all non-Python blocks (JS/TS/Go/Rust/Java). This means the code snippet shown for non-Python files only covers one line. Improving line range detection for these languages would make snippets more useful.

5. **History tab has no pagination** — For projects with many sessions, the history list could get very long. Consider limiting to last 10 sessions with a "Load more" button.

6. **Block IDs change on rescan** — `upsert_code_blocks` deletes and re-inserts all blocks on every scan. This means `question_results.block_id` foreign keys go stale after a rescan. The history LEFT JOIN handles this gracefully (shows "unknown"), but coverage stats could be skewed. A content-hash-based identity for blocks would fix this properly.

---

## Next Steps (Priority Order)

1. Fix security banner text (2-minute CSS/HTML change)
2. Verify and update Haiku 4.5 pricing constants
3. Add rescan button to sidebar
4. Improve non-Python snippet line range detection
5. Add history pagination

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
