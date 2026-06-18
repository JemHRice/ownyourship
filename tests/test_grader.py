from ownyourship import grader


def test_correct_answer():
    is_correct, score, feedback = grader.grade_multiple_choice("A", "A")
    assert is_correct is True
    assert score == 1.0
    assert feedback == "Correct!"


def test_incorrect_answer_reports_right_letter():
    is_correct, score, feedback = grader.grade_multiple_choice("C", "A")
    assert is_correct is False
    assert score == 0.0
    assert "A" in feedback


def test_case_and_whitespace_insensitive():
    assert grader.grade_multiple_choice("  a ", "A")[0] is True


def test_uses_first_character_only():
    # The UI may submit "A: full option text"; only the letter matters.
    assert grader.grade_multiple_choice("A: some long answer", "A")[0] is True
