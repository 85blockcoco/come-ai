from pathlib import Path


def test_v5_exposes_a_complete_vc_review_surface() -> None:
    html = (Path(__file__).parents[1] / "v5_static" / "index.html").read_text(encoding="utf-8")
    javascript = (Path(__file__).parents[1] / "v5_static" / "v5.js").read_text(encoding="utf-8")
    for marker in (
        'data-view-target="vcView"',
        'id="vcStartForm"',
        'id="vcReveal"',
        'data-vc-grade="again"',
        'id="vcRadar"',
        'id="vcExamStartForm"',
        'id="vcExamSubmit"',
    ):
        assert marker in html
    for marker in (
        "/api/academics/vc/status",
        "/api/academics/vc/session",
        "/reveal",
        "/grade",
        "/api/academics/vc/exam",
        "submitVcExam",
        "renderVcRadar",
    ):
        assert marker in javascript
