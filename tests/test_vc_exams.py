from academics.vc.exams import build_mock_exam, grade_mock_exam


def test_mock_exam_is_deterministic_and_bounded():
    exam = build_mock_exam(limit=20)
    assert len(exam.questions) == 20
    assert exam.duration_minutes == 30
    assert [item.id for item in exam.questions[:5]] == ["q-pm", "q-moic", "q-dilution", "q-term", "q-unknown"]


def test_exam_preserves_partial_answers_when_time_expires():
    exam = build_mock_exam(limit=5)
    result = grade_mock_exam(exam, {"q-pm": "10", "q-moic": "3"}, elapsed_minutes=30)
    assert result.timed_out
    assert result.answered == 2
    assert result.score == 4
    assert all(detail["revealed"] is False for detail in result.details)


def test_exam_reports_weak_topics_without_calling_them_mastered():
    exam = build_mock_exam(limit=5)
    result = grade_mock_exam(exam, {"q-pm": "10"})
    assert "cap-table" in result.weak_topics
    assert "method" in result.weak_topics
    assert result.max_score == 10


def test_exam_question_ids_are_unique_for_long_exam():
    exam = build_mock_exam(limit=10)
    assert len({question.id for question in exam.questions}) == 10
