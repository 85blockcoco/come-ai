from academics.vc.glossary import decode_clause, lookup_term
from academics.vc.report import progress_report


def test_glossary_explains_documented_and_unknown_terms():
    assert lookup_term("pre-money")["fr"] == "valorisation avant investissement"
    assert decode_clause("1x liquidation preference")["status"] == "documenté"
    assert decode_clause("clause inconnue")["status"] == "à vérifier"


def test_report_keeps_untested_topics_honest_and_counts_events():
    report = progress_report(
        radar=[{"topic": "valuation", "status": "solide"}, {"topic": "returns", "status": "non testé"}],
        sessions=[{"answered": 3}], exams=[{"score": 8}],
    )
    assert report["topics"] == {"total": 2, "tested": 1, "mastered": 1, "untested": 1}
    assert report["sessions"]["answered"] == 3
    assert report["honesty"] == "non testé reste non testé"
