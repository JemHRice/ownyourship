from typing import Tuple


def grade_multiple_choice(
    user_answer: str, correct_answer: str
) -> Tuple[bool, float, str]:
    user = user_answer.strip().upper()[:1]
    correct = correct_answer.strip().upper()[:1]
    is_correct = user == correct
    feedback = "Correct!" if is_correct else f"Incorrect — the right answer was {correct}."
    return is_correct, 1.0 if is_correct else 0.0, feedback
