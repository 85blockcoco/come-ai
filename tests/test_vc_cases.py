from academics.vc.cases import grade_case, seed_round_case


def test_seed_case_has_five_guided_questions_and_ten_points():
    case = seed_round_case()
    assert len(case.questions) == 5
    assert sum(question.points for question in case.questions) == 10
    assert "8 M€" in case.statement


def test_case_grade_is_explainable_and_flags_unsupported_claims():
    case = seed_round_case()
    result = grade_case(case, {
        "q1": "Post-money 10 M€, investisseur 20 %.",
        "q2": "Le pool de 10 % crée une dilution.",
        "q3": "La préférence 1x récupère avant le residual.",
        "q4": "Participating peut donner un double bénéfice, non participating choisit.",
        "q5": "Le calendrier et les autres classes sont inconnus.",
    })
    assert result.score == 10
    assert result.max_score == 10
    assert all("missing" in criterion for criterion in result.criteria)
    assert result.unsupported_claims == ()


def test_case_does_not_turn_unanswered_questions_into_mastery():
    result = grade_case(seed_round_case(), {"q1": "Je ne sais pas."})
    assert result.score == 0
    assert result.max_score == 10
