from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_desktop_learning_surface_is_wired_to_local_learning_routes() -> None:
    html = (ROOT / "desktop_static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")
    service_worker = (ROOT / "desktop_static" / "sw.js").read_text(encoding="utf-8")
    css = (ROOT / "desktop_static" / "app.css").read_text(encoding="utf-8")
    for marker in ('data-view="learning"', 'id="view-learning"', 'id="themeSelect"', 'id="styleSelect"', 'Style général', 'Réviser VC'):
        assert marker in html
    for marker in (
        '"/career/manifest"', '"/career/chapters"', '"/career/tutor/ask"',
        '"/career/quiz/next"', '"/career/quiz/answer"', '/career/search?q=',
        'summary/${encodeURIComponent(l.selectedChapter)}',
        'localStorage.setItem("nage-theme"', 'event.altKey',
        '"/career/coverage"', '"/career/exam/start"', '"/career/exam/submit"',
        '"/career/srs/review"', 'rating', 'Générer / compléter les cartes',
        'Progression vers la maîtrise', 'Télécharger la fiche PDF', 'plan/pdf',
        'Notions du sujet 2025 vues en quiz', 'questions distinctes', 'exam_objectives',
        '"/career/practice/cases"', '/career/practice/cases/${encodeURIComponent(l.practiceCaseId)}/submit',
        'Calculs au format de l’épreuve', 'Corriger mes calculs', 'points par sous-partie de Q20/Q21 sont indicatifs', 'latest_result',
        'input_type === "choice"', 'practiceScoreCaption', 'Q20/Q21', 'Choisir Alpha ou Mega',
        'examTimer', 'Encore', 'Difficile', 'Facile', '"/career/ingest"',
        'Réessayer l’import local', 'Couverture des supports',
        'Voir l’extrait', 'cite.excerpt', 'const citationLocation', 'onglet ${cite.section}', 'citationLocation(cite)',
        'section: l.selectedChapter', 'Ton parcours jusqu’à l’examen', 'learningProgress',
        'nage-style', 'study-revision', 'study-exercises', 'study-exam',
    ):
        assert marker in javascript
    assert "url.pathname.startsWith('/career/summary/')" in service_worker
    assert ':root[data-style="study"]' in css
    assert ".learning-step-grid" in css
    assert ".case-practice" in css
    assert ".practice-control" in css
