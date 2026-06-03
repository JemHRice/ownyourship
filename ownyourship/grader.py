import json
import re
from typing import Tuple

import anthropic

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_FREE_TEXT_CHARS = 500


def grade_multiple_choice(
    user_answer: str, correct_answer: str
) -> Tuple[bool, float, str]:
    user = user_answer.strip().upper()[:1]
    correct = correct_answer.strip().upper()[:1]
    is_correct = user == correct
    feedback = "Correct!" if is_correct else f"Incorrect — the right answer was {correct}."
    return is_correct, 1.0 if is_correct else 0.0, feedback


async def grade_free_text(
    question: str,
    user_answer: str,
    model_answer: str,
    code_context: str,
    client: anthropic.AsyncAnthropic,
) -> Tuple[bool, float, str, int, int]:
    """
    Returns (is_correct, score 0-1, feedback, input_tokens, output_tokens).
    """
    user_answer = user_answer[:MAX_FREE_TEXT_CHARS]

    prompt = f"""You are grading a developer's explanation of their own code.

QUESTION:
{question}

CODE BEING DISCUSSED:
{code_context}

MODEL ANSWER (key points to look for):
{model_answer}

DEVELOPER'S ANSWER:
{user_answer}

Grade fairly:
- Core concept must be present, but informal language is fine
- Partial correct understanding earns partial score
- Do not penalise for extra correct observations
- A blank or completely off-topic answer scores 0

Return ONLY valid JSON:
{{
  "is_correct": true or false,
  "score": 0.0 to 1.0,
  "feedback": "Brief encouraging feedback — what was right, what was missing"
}}"""

    try:
        response = await client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise RuntimeError(f"API error during grading: {type(exc).__name__}") from None

    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    text = response.content[0].text.strip()

    result = None
    for attempt in (
        lambda: json.loads(text),
        lambda: json.loads(re.search(r"\{.*\}", text, re.DOTALL).group(0)),
    ):
        try:
            result = attempt()
            break
        except Exception:
            continue

    if not result:
        return False, 0.0, "Could not grade automatically — try again.", in_tok, out_tok

    is_correct = bool(result.get("is_correct", False))
    score = float(result.get("score", 1.0 if is_correct else 0.0))
    score = max(0.0, min(1.0, score))
    feedback = str(result.get("feedback", ""))

    return is_correct, score, feedback, in_tok, out_tok
