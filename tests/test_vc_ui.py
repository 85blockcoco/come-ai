from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_vc_view_exposes_complete_revision_flow() -> None:
    html = (ROOT / "v5_static" / "index.html").read_text(encoding="utf-8")
    for marker in ("vcView", "vcCardForm", "vcSessionForm", "vcFocusTopic", "vcReveal", "vcRadar", "vcExamStart", "vcExamSubmit", "vcExamHistory", "vcProgress", "vcReadiness", "vcQuickFocus"):
        assert marker in html
    assert 'data-view-target="vcView"' in html
    assert 'aria-live="polite"' in html
    assert 'role="list"' in html


def test_vc_frontend_uses_local_routes_and_keeps_answer_out_of_session_payload() -> None:
    script = (ROOT / "v5_static" / "v5.js").read_text(encoding="utf-8")
    for route in (
        "/api/academics/vc/status",
        "/api/academics/vc/cards",
        "/api/academics/vc/session",
        "/api/academics/vc/review",
        "/api/academics/vc/radar",
        "/api/academics/vc/exam",
        "/api/academics/vc/exam/grade",
        "/api/academics/vc/exams",
        "/api/academics/vc/session/summary",
    ):
        assert route in script
    assert "correction.back" in script
    assert "VC_EXAM_DRAFT_KEY" in script
    assert "restoreVCExamDraft" in script
    assert "local" in script


def test_vc_frontend_has_no_automatic_external_submission() -> None:
    script = (ROOT / "v5_static" / "v5.js").read_text(encoding="utf-8")
    assert "fetch(\"http" not in script
    assert "window.open" not in script
