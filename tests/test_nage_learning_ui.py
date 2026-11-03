from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_desktop_learning_surface_is_wired_to_local_learning_routes() -> None:
    html = (ROOT / "desktop_static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "desktop_static" / "app.js").read_text(encoding="utf-8")
    service_worker = (ROOT / "desktop_static" / "sw.js").read_text(encoding="utf-8")
    for marker in ('data-view="learning"', 'id="view-learning"', 'id="themeSelect"', 'Réviser VC'):
        assert marker in html
    for marker in (
        '"/career/manifest"', '"/career/chapters"', '"/career/tutor/ask"',
        '"/career/quiz/next"', '"/career/quiz/answer"', '/career/search?q=',
        'summary/${encodeURIComponent(l.selectedChapter)}',
        'localStorage.setItem("nage-theme"', 'event.altKey',
    ):
        assert marker in javascript
    assert "url.pathname.startsWith('/career/summary/')" in service_worker
