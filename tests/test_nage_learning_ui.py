from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_desktop_learning_surface_is_wired_to_local_learning_routes() -> None:
    html = (ROOT / "desktop_static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")
    service_worker = (ROOT / "desktop_static" / "sw.js").read_text(encoding="utf-8")
    css = (ROOT / "desktop_static" / "app.css").read_text(encoding="utf-8")
    for marker in ('data-view="learning"', 'id="view-learning"', 'id="themeSelect"', 'id="styleSelect"', 'Style général', 'Révision', 'id="workModeToggle"', 'Work Mode'):
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
        'Matière active : Venture Capital', 'learning-subject-nav', 'Venture Capital', 'setWorkMode', 'aria-pressed',
        'practiceError', 'Les cas guidés Q16–Q21 ne sont pas disponibles sur cette instance',
        'Choisir la suite après cette leçon', 'Ajouter à À revoir',
        'Annale(s) à pratiquer dans le sujet', '67 questions des packs 2023, 2024 et 2025',
        'Saisis une réponse avant d’afficher le corrigé', 'course_scope === "related"',
    ):
        assert marker in javascript
    assert "url.pathname.startsWith('/career/summary/')" in service_worker
    assert "app.css?v=20261103-vc-course-lessons-5" in html and "app.js?v=20261103-vc-course-lessons-5" in html
    assert "app.css?v=20261103-vc-course-lessons-5" in service_worker and "app.js?v=20261103-vc-course-lessons-5" in service_worker
    assert ':root[data-style="study"]' in css
    assert ".learning-step-grid" in css
    assert ".case-practice" in css
    assert ".practice-control" in css
    assert ".work-mode-toggle:focus-visible" in css
    assert ".learning-subject-tab[aria-current=\"page\"]" in css


def test_guided_course_and_past_paper_practice_are_connected_without_answer_leaks() -> None:
    javascript = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")
    router = (ROOT / "career" / "learning_router.py").read_text(encoding="utf-8")
    lessons = (ROOT / "career" / "course_lessons.py").read_text(encoding="utf-8")
    for marker in (
        '"understood"', '"practice"', '"review"', 'review_queue',
        'attempted_item_count', 'Saisis au moins une réponse avant d’afficher le corrigé',
        'unclassified_count', '"unclassified"',
    ):
        assert marker in router or marker in lessons
    assert 'currentPastPaperQuestions' in javascript
    assert 'study-past-papers' in javascript
    assert 'key === "value" && "value" in node) node.value = value' in javascript
