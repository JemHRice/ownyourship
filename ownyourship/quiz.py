import json
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import anthropic

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Haiku 3.5 pricing used as estimate; actual Haiku 4.5 pricing may differ.
_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN


# ── Code context fetcher ─────────────────────────────────────────────────────

def get_code_context(file_path: Path, line_start: int, line_end: int, ctx: int = 4) -> str:
    """Return a numbered excerpt around the target block."""
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""

    start = max(0, line_start - 1 - ctx)
    end = min(len(lines), line_end + ctx)
    result = []
    for i, line in enumerate(lines[start:end], start=start + 1):
        marker = ">" if line_start <= i <= line_end else " "
        result.append(f"{marker} {i:4d} | {line}")
    return "\n".join(result)


# ── Prompt builders ──────────────────────────────────────────────────────────

_MODE_INSTRUCTIONS = {
    "easy": (
        "Generate a STRAIGHTFORWARD question. "
        "Someone who understands basic programming should be able to answer it "
        "if they have read this code."
    ),
    "intermediate": (
        "Generate a question requiring SOLID understanding. "
        "Focus on how this block interacts with the rest of the code, "
        "what it returns/modifies, or non-obvious behaviors."
    ),
    "hard": (
        "Generate a CHALLENGING question. "
        "Focus on edge cases, subtle behaviors, error conditions, "
        "or this block's precise role in the system."
    ),
    "tailored": (
        "Generate a question calibrated to the current difficulty level."
    ),
}

_MC_RULES = """
MULTIPLE CHOICE RULES (strictly enforced):
- Provide exactly 4 options labelled A, B, C, D
- ALL 4 options must be plausible given the codebase — a developer who does NOT know
  the answer must NOT be able to eliminate wrong answers through logic alone
- Options should be similar in length and specificity
- The correct answer must require actual knowledge of what this code does
"""


def _build_prompt(block: Dict, code_context: str, mode: str, q_type: str) -> str:
    block_desc = f"{block['block_type']} `{block['block_name']}`"
    if block.get("parent_class"):
        block_desc = f"method `{block['block_name']}` in class `{block['parent_class']}`"

    docstring_line = f"\nDOCSTRING: {block['docstring']}" if block.get("docstring") else ""
    mode_instr = _MODE_INSTRUCTIONS.get(mode, _MODE_INSTRUCTIONS["intermediate"])

    if q_type == "multiple_choice":
        format_block = f"""
{_MC_RULES}
Return ONLY valid JSON — no prose, no markdown fences:
{{
  "question": "...",
  "type": "multiple_choice",
  "options": ["A: ...", "B: ...", "C: ...", "D: ..."],
  "correct_answer": "A",
  "explanation": "Brief explanation of the correct answer"
}}
"""
    else:
        format_block = """
Return ONLY valid JSON — no prose, no markdown fences:
{
  "question": "Explain in plain English: ...",
  "type": "free_text",
  "correct_answer": "Model answer covering the key points",
  "explanation": "The key concepts a correct answer must include"
}
"""

    return f"""You are generating a quiz question to test whether a developer understands their own code.

FILE: {block['file_path']}
BLOCK: {block_desc}
SIGNATURE: {block.get('signature', 'N/A')}{docstring_line}

CODE (lines marked > are the target block):
```
{code_context}
```

TASK: {mode_instr}
QUESTION TYPE: {q_type.replace('_', ' ')}

RULES:
- Test understanding of WHAT this code does and WHY — not syntax knowledge
- The question must include enough context to be answerable without seeing the code
- Do NOT make the answer obvious from the snippet alone
- Do NOT ask "what is the purpose of the `def` keyword" type questions
- Do NOT ask questions that require calculating exact numeric values or doing arithmetic
- Do NOT reference option letters (A, B, C, D) in the explanation — explain the concept only
- The explanation must be a single confident statement — do NOT reconsider, recalculate, hedge, or use phrases like "however" or "actually" to change your answer mid-explanation
- Decide on the correct answer BEFORE writing the explanation, then write the explanation to match it

{format_block}"""


# ── Response parser ──────────────────────────────────────────────────────────

def _shuffle_mc_options(qdata: Dict) -> Dict:
    """Randomly redistribute which letter holds the correct answer."""
    if qdata.get("type") != "multiple_choice":
        return qdata

    options = qdata.get("options", [])
    if len(options) != 4:
        return qdata

    letters = ["A", "B", "C", "D"]
    correct_letter = qdata.get("correct_answer", "A").strip().upper()[:1]
    if correct_letter not in letters:
        return qdata

    def _strip(opt: str) -> str:
        return re.sub(r"^[A-D][:.]\s*", "", str(opt)).strip()

    texts = [_strip(o) for o in options]
    correct_idx = letters.index(correct_letter)

    # Shuffle by index so duplicate-text options are handled safely
    indexed = list(enumerate(texts))
    random.shuffle(indexed)

    new_correct_pos = next(
        i for i, (orig_idx, _) in enumerate(indexed) if orig_idx == correct_idx
    )

    qdata = dict(qdata)
    qdata["options"] = [f"{letters[i]}: {text}" for i, (_, text) in enumerate(indexed)]
    qdata["correct_answer"] = letters[new_correct_pos]
    return qdata


def _parse_response(text: str) -> Optional[Dict]:
    text = text.strip()
    for attempt in (
        lambda: json.loads(text),
        lambda: json.loads(re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL).group(1)),
        lambda: json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0)),
    ):
        try:
            return attempt()
        except Exception:
            continue
    return None


# ── Block selector ───────────────────────────────────────────────────────────

def select_next_block(
    all_blocks: List[Dict],
    answered_ids: set,
    mode: str,
    session_perf: Dict,  # {block_id: {"correct": int, "total": int}}
    all_time_perf: Dict,
) -> Optional[Dict]:
    candidates = [b for b in all_blocks if b["id"] not in answered_ids]
    if not candidates:
        return None

    if mode != "tailored":
        return random.choice(candidates)

    def _score(block: Dict) -> float:
        perf = session_perf.get(block["id"], {"correct": 0, "total": 0})
        total = perf["total"]
        correct = perf["correct"]
        if total == 0:
            return 0.5 + random.uniform(-0.1, 0.1)
        accuracy = correct / total
        if accuracy < 0.4:
            return 0.1 + random.uniform(-0.05, 0.05)  # struggling → highest priority
        if accuracy > 0.8:
            return 0.8 + random.uniform(-0.1, 0.1)    # mastered → lowest priority
        return 0.5 + random.uniform(-0.1, 0.1)

    candidates.sort(key=_score)
    return candidates[0]


# ── Question generator ───────────────────────────────────────────────────────

async def generate_question(
    block: Dict,
    project_path: Path,
    mode: str,
    client: anthropic.AsyncAnthropic,
    session_perf: Dict,
) -> Tuple[Optional[Dict], int, int]:
    """
    Returns (question_dict, input_tokens, output_tokens).
    question_dict is None on failure.
    """
    file_abs = project_path / block["file_path"]
    code_context = get_code_context(file_abs, block["line_start"], block["line_end"])
    if not code_context:
        return None, 0, 0

    q_type = "multiple_choice"

    prompt = _build_prompt(block, code_context, mode, q_type)

    try:
        response = await client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"API error during question generation: {type(exc).__name__}") from None

    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens

    data = _parse_response(response.content[0].text)
    if data:
        data = _shuffle_mc_options(data)
        data["block_id"] = block["id"]
        data["file_path"] = block["file_path"]
        data["block_name"] = block["block_name"]
        data["block_type"] = block["block_type"]
        data["parent_class"] = block.get("parent_class")

    return data, in_tok, out_tok
