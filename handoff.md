# OwnYourShip — Session Handoff

> Read this at the start of every session. Update it at the end of every session.

---

## Current State

**Date of last update:** 2026-07-09
**Status:** v1 + architecture diagram feature. **116 passing tests**, CI on Python
3.10/3.13. `master` is branch-protected (PR + green CI required) — branch per change,
Conventional Commits, TDD red/green, squash-merge. Packaging publish-ready, not on PyPI.

**Open right now:**
- **PR #28 (`feat/diagram-ux`) — OPEN, awaiting owner browser smoke test.** The diagram
  UX batch: legible drill-down grid (#22), function-description side panel (#21 frontend),
  language accent colors (#25), titled exports (#24). Merging closes those four issues.
- No other open issues or PRs.

---

## What Was Built (Sessions 1–5)

Sessions 1–2: full initial build (scanner, quiz, SPA, SQLite) + bug fixes.
Session 3 (2026-06-10): Windows Ctrl+C, rescan-survives-coverage upsert, rescan button,
non-Python line ranges, history pagination. Session 4 (2026-06-18): pytest suite, dead-code
removal, `utcnow` deprecation, default-extension trim. Session 5 (2026-06-22, PRs #1–8):
CI + CONTRIBUTING + branch protection; server-side trust boundary (20-question cap, session
validation, FK enforcement, ended-session 409s, server-side answer grading); packaging.
Details in git history and closed PRs.

---

## What Was Changed (Session 6 — Diagram feature, 2026-06-22 → 2026-07-01)

- **Reset-on-change coverage** (PR #13): a block counts as covered only when answered
  against its current `content_hash`; editing a body re-queues it, renames/moves keep
  history (content-hash identity, PR #10).
- **Architecture diagram backend** (PRs #14–16, all TDD): `callgraph.py` (Python AST call
  edges), `diagram.py` + `GET /api/diagram` (components/function_edges/component_edges),
  `labels.py` + `GET /api/diagram/labels` (Claude one-sentence component labels, cached in
  `.oys/label_cache.json` by content fingerprint).
- **Diagram frontend** (PR #17, merged 2026-07-09): Cytoscape.js (CDN) Diagram tab —
  overview of component boxes + aggregated call arrows; click a file to drill into its
  functions + 1-hop cross-file boundary; focus/pan/zoom; opt-in ✨ Describe (Claude);
  PNG/SVG export.
- **Label prompt hardening** (PR #20, fixes #18): labels are inferred from signatures +
  first docstring lines, never ask for source; question-shaped responses are dropped.

## What Was Changed (Session 7 — Smoke test & diagram UX batch, 2026-07-09)

Owner smoke-tested the Diagram tab; findings filed as issues #21–#25, then fixed:

- **PR #17 merged** (drill-down confirmed working; closed #19).
- **PR #26 (fixes #23)**: `Describe` was serving a pre-#20 refusal for `grader.py` from
  the label cache forever — a fingerprint match alone no longer suffices; cached labels are
  re-validated on read and failures are never cached (they retry). Poisoned caches self-heal
  on the next Describe. Verified live: the real poisoned entry regenerated correctly.
- **PR #27 (backend of #21)**: `POST /api/diagram/labels/functions` — one-line Claude
  descriptions per function, **one batched call per file** (signatures + docstrings only),
  cached by each function's `content_hash` under `fn:` keys in `label_cache.json`. Takes an
  explicit id list so boundary functions from other files ride along; unknown ids ignored.
  Verified live end-to-end (generation, caching, unknown-id handling).
- **PR #28 (OPEN — closes #21 #22 #24 #25)**, one commit per issue:
  - **#22 layout**: `cose` scattered disconnected nodes (non-Python files have *zero* call
    edges — the call graph is Python-AST-only), giving huge empty boxes with confetti edges
    on app.js/server.py/conftest. Drill-down now uses fixed positions: alphabetical compact
    grid of the file's functions, callers stacked left, callees right; fonts 13/15.
  - **#21 panel**: 320px side panel in drill-down listing functions + called-from/calls-out
    sections; Describe fills one-liners (auto-describes on later drill-downs once opted in);
    panel row click ↔ node focus sync.
  - **#25 colors**: component border/title tinted by language (extension-mapped), legend
    chips for languages present; CVD-validated dark palette; bright/faded state channel
    untouched.
  - **#24 exports**: PNG/SVG get a title band + view-specific filename —
    `<project>_architecture` / `<file>_architecture` / `<file> - <fn>_breakdown`.

---

## Known Issues / Incomplete Items

1. **Brace matching is naive** — `_block_end_line` doesn't lex strings/comments, so a stray
   brace inside one can skew a non-Python snippet's range. Cosmetic only.
2. **Call graph is Python-only** — JS/TS/Go/etc. files appear as components with functions
   but no edges. The #22 grid layout makes them legible anyway; real cross-language call
   extraction is roadmap.
3. **Frontend JS is review-verified only** (no Node/browser in the dev environment) — the
   owner browser-tests each frontend PR before merge. PR #28 is the one awaiting that now.
4. `/api/answer` self-cheating remains acceptable-by-design for a local single-user tool
   (server-side grading shipped in Session 5; "B-full" withholding of `correct_answer`
   from the client would need frontend rework).

---

## Next Steps

1. **Owner smoke test → merge PR #28** (checklist is in the PR body): drill into app.js and
   server.py, Describe, panel interactions, legend, PNG/SVG exports from all three views.
2. README screenshots (browser + key needed) and a PyPI publish-on-tag workflow.
3. Refactor `server._state` off the module-level singleton (DI).
4. Low-priority coverage: `/api/shutdown`, scanner signature edges, `get_code_context`
   out-of-range lines; proper (non-regex) parsers for non-Python languages; more quiz modes.

---

## Architecture Reference

```
ownyourship/
├── ownyourship/
│   ├── main.py       — CLI entry point, disclaimer, server lifecycle
│   ├── server.py     — FastAPI, all REST endpoints (incl. /api/diagram*)
│   ├── scanner.py    — AST (Python) + regex (JS/TS/Go/Rust/Java/Kotlin) scanner
│   ├── callgraph.py  — Python AST call-edge extraction
│   ├── diagram.py    — assembles components + edges for /api/diagram
│   ├── labels.py     — Claude component/function labels + .oys/label_cache.json
│   ├── quiz.py       — Haiku question generation, MC shuffle, block selector
│   ├── grader.py     — MC grading (local only)
│   ├── db.py         — SQLite schema + all queries
│   ├── config.py     — .oys/config.json management
│   └── static/       — Dark-mode SPA (index.html, style.css, app.js, Cytoscape via CDN)
├── tests/            — pytest suite (116 tests; FakeAnthropic, no network)
├── .github/          — CI (3.10/3.13), PR template
├── venv/             — Python 3.13 venv
├── pyproject.toml    — publish-ready, optional dep group [test]
└── README.md / DISCLAIMER.md / CONTRIBUTING.md
```

## Environment

- Python 3.13, venv at `venv\Scripts\activate`; `oys` command after activation
- API key at `%USERPROFILE%\.oys\.env`
- Run against this repo itself: `oys C:\Users\jemhr\MLProjects\ownyourship`
- No Node/browser for JS verification — frontend PRs get owner browser smoke tests
