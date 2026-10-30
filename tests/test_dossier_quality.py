from career.dossier_quality import analyze_dossier_quality


def test_score_range():
    text = "I am an expert in Excel. We reduced costs by 30%."
    profile = ["Excel basic", "Reduced costs by 30% in 2023"]
    audit = analyze_dossier_quality(text, profile)
    assert 0 <= audit.score <= 100
    assert audit.to_dict()["score"] == audit.score
    assert audit.report


def test_empty_document():
    audit = analyze_dossier_quality("", [])
    assert 0 <= audit.score <= 100
