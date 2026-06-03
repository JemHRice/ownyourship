# OwnYourShip (`oys`)

The answer to a dilemma I faced myself - as a vibe coder/heavy user of LLMs to turn my 
projects from ideas into reality, I find myself with code the exceeds my knowledge. To
me, that is ethically grey - no-one should ship anything they can't stand and defend, or
at the very least explain how the code blocks work together. 

OwnYourShip quizzes you on your own code, at whatever level you want to be tested. It is 
a learning tool for vibe coders to learn what they are coding, without actually slowing
their projects down. It runs locally (using your own Anthropic API key) to create questions
around your own projects, so that you can both ship cool projects AND know how they work.

It is by no means complete yet - in fact, I am using Claude to patch bugs as we go. I
only just caught it changing it's answers mid explanation, so it isn't reliable yet
whatsoever. However, it works to the degree that it will generate non-trivial questions
about your own projects, and keeps a track of your progress across categories. More 
cool features to come, and way more bugs to squish - I am quite excited about this one.

Bottom line: you shouldn't own what you don't know. If you want to OwnYourShip, follow
instructions below!

---

## Security & Cost — Read This First

> **Your code is sent to Anthropic.**  
> Snippets from scanned projects are transmitted to the Anthropic API to generate
> quiz questions. Do **not** use this tool on confidential, classified, or proprietary
> code without your organisation's explicit consent.
> See [DISCLAIMER.md](DISCLAIMER.md) for full terms.

> **You pay for every API call.**  
> This tool uses **your own** Anthropic API key — the author pays nothing and receives
> nothing from your usage. Set a hard monthly spend limit **before** you start:
> https://console.anthropic.com/settings/limits

> **No warranty, no liability.**  
> The author accepts no liability for API costs, data exposure, or any damages.

---

## Requirements

- Python 3.10 or later
- An Anthropic API key — get one at https://console.anthropic.com/keys

---

## Setup (Windows)

### 1. Clone or download the project

```
git clone <https://github.com/JemHRice/ownyourship>
cd ownyourship
```

### 2. Create a virtual environment

```
python -m venv venv
```

### 3. Activate the virtual environment

```
venv\Scripts\activate
```

You should see `(venv)` in your prompt.

### 4. Install dependencies

```
pip install -e .
```

This installs all dependencies and makes the `oys` command available in your venv.

### 5. Set your API key

**Option A — Global (recommended): works across all projects**

Create the file `%USERPROFILE%\.oys\.env` (e.g. `C:\Users\YourName\.oys\.env`):

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

**Option B — Per project**

Create a `.env` file in the project directory you want to quiz on:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

The `.env` file is gitignored — never commit your key.

---

## Usage

```
# Activate venv first
venv\Scripts\activate

# Run from inside the project you want to quiz on
cd C:\path\to\your\project
oys

# Or pass the path explicitly
oys C:\path\to\your\project
```

`oys` will:
1. Show a one-time disclaimer (type `yes` to continue)
2. Add `.oys/` to your project's `.gitignore`
3. Scan the project structure
4. Open the quiz UI in your browser
5. Run until you press Ctrl+C or click "End Session"

---

## Quiz Modes

All modes use multiple choice questions. Each question shows the relevant code snippet and gives you **two attempts** before the correct answer is revealed.

| Mode | Description |
|------|-------------|
| **Easy** | Straightforward questions. Good for a first pass through the codebase. |
| **Intermediate** | Deeper questions — interactions between components, non-obvious behaviours. |
| **Hard** | Challenging questions focused on edge cases, subtle behaviours, and precise roles. |
| **Tailored** | Adapts in real time — focuses on your weak spots, skips what you know. |

Sessions are capped at **20 questions**. Work through multiple sessions to build toward 95% coverage.

### The 95% Goal

When you've demonstrated correct knowledge of 95% of meaningful code blocks
(functions, methods, and classes) the UI celebrates. That's the bar: you can
stand behind this code.

---

## Configuration

On first run, `oys` creates `.oys/config.json` inside your project:

```json
{
  "included_extensions": [".py", ".js", ".ts", ...],
  "excluded_dirs": ["venv", "node_modules", ".git", ...],
  "excluded_patterns": ["*.env", "*.key", "*.pem", "*secret*", ...],
  "cost_warning_threshold_usd": 0.50
}
```

Edit this file to control what gets scanned. Changes take effect on the next `oys` run.

---

## Progress data

All progress is stored in `.oys/progress.db` (SQLite) inside the target project.
Both `.oys/` and `.env` are automatically gitignored — neither will be committed.

To reset progress: delete `.oys/progress.db`.

---

## Cost estimates

`oys` uses **Claude Haiku** for question generation only — all answer grading is done locally.
Haiku is the most cost-efficient Claude model. Typical session costs:

- 20-question session:        ~$0.02–$0.06
- Full project (100 questions): ~$0.10–$0.25

These are rough estimates. The UI shows a running cost counter so you always know
where you stand. A configurable warning triggers at $0.50 by default.

**Set a spend limit** at https://console.anthropic.com/settings/limits.

---

## Supported languages

Python (AST-based, most accurate), JavaScript/TypeScript, Java/Kotlin, Go, Rust.
Additional languages can be added by editing the scanner — PRs welcome.

---

## Security notes

- The server binds to `127.0.0.1` only — it is never accessible from the network.
- Your API key is read from `.env` at runtime and never logged, printed, or committed.
- `.oys/` and `.env` are added to your project's `.gitignore` automatically.
- Default exclusions cover `.env*`, `*.key`, `*.pem`, `*secret*`, `*credential*`,
  `*password*`, `*token*` — these files are never scanned or sent to Anthropic.
- Code snippets are sent to Anthropic as part of API calls. Anthropic's data handling
  is governed by their own privacy policy and terms of service.
