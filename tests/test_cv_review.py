"""SPEC-004 — Evidence-backed CV review workspace.

Every test here is local: no network call, no model, no personal data. The
fixtures are synthetic (tests/fixtures/cv_review).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from career.cv_fit import CoverageResult, FitGap
from career.cv_review import (
    CRITICAL_SECTIONS,
    PLACEHOLDER_TEXT,
    ReviewBlock,
    ReviewError,
    ReviewWorkspace,
    apply_decision,
    build_review_markdown,
    build_workspace,
    can_export,
    diff_segments,
    merge_decisions,
    profile_lines,
    resolve_block_text,
    workspace_to_dict,
)
from career.cv_review_store import ReviewStore, ReviewStoreError, safe_application_id
from career.cv_variants import MA_VARIANT, MARKETS_VARIANT
from career.service import CareerService


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cv_review"
CV_REVIEW_JS = ROOT / "career_static" / "js" / "cv-review.js"
INDEX_HTML = ROOT / "career_static" / "index.html"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _service(tmp_path: Path) -> CareerService:
    service = CareerService(tmp_path, curated_sources=())
    profile = _fixture("profile.json")
    service.update_profile(
        {
            key: profile[key]
            for key in (
                "display_name",
                "contact_email",
                "contact_phone",
                "linkedin_url",
                "education",
                "experience",
                "skills",
                "projects",
                "languages",
                "eligibility",
            )
        }
    )
    offer = _fixture("offer.json")
    service.import_job(
        {
            key: offer[key]
            for key in (
                "company",
                "title",
                "official_url",
                "job_family",
                "requirements",
                "source_status",
                "city",
                "country",
                "description_original",
            )
        }
    )
    return service


def _application(service: CareerService, variant: str = "m_a") -> str:
    jobs = service.list_jobs()
    job_id = jobs[0]["id"]
    kit = service.create_application_kit(job_id, "en", variant)
    return str(kit["application"]["id"])


def _coverage(*requirements: str) -> CoverageResult:
    """A local coverage result with uncovered mandatory requirements."""

    gaps = [
        FitGap(
            requirement=requirement,
            requirement_type="mandatory",
            current_state="missing",
            adapted_state=f"Add '{requirement}' with quantified evidence: {PLACEHOLDER_TEXT}",
            provenance=None,
            variant_specific=True,
        )
        for requirement in requirements
    ]
    return CoverageResult(
        mandatory_total=len(gaps),
        mandatory_covered=0,
        preferred_total=0,
        preferred_covered=0,
        mandatory_pct=0.0,
        preferred_pct=0.0,
        gaps=gaps,
        recommended_variant=MA_VARIANT,
        variant_rationale="Fixture de test local.",
    )


# ----------------------------------------------------------------------
# Core: construction, diff, statuses
# ----------------------------------------------------------------------
def test_workspace_lists_every_reviewed_section_with_exact_evidence() -> None:
    profile = _fixture("profile.json")
    offer = _fixture("offer.json")

    workspace = build_workspace(
        "app-fixture-1",
        job=offer,
        profile=profile,
        variant=MA_VARIANT,
        language="en",
        created_at="2026-10-22T10:00:00Z",
    )

    assert workspace.application_id == "app-fixture-1"
    assert workspace.variant_id == "m_a"
    assert list(workspace.section_headings) == [
        "experiences",
        "skills",
        "education",
        "projects",
        "languages",
    ]
    experiences = [item for item in workspace.blocks if item.section == "experiences"]
    assert [item.block_id for item in experiences] == ["experiences:0", "experiences:1"]
    first = experiences[0]
    assert first.status == "verified"
    assert first.proposed_text == first.source_text
    assert first.evidence is not None
    evidence = first.evidence[0]
    assert evidence.source == "profile.experience"
    assert evidence.quote == first.source_text
    # The offsets point at the very same characters inside the profile field.
    raw = profile["experience"]
    assert raw[evidence.start_offset : evidence.end_offset] == evidence.quote


def test_build_workspace_is_pure_and_deterministic() -> None:
    profile = _fixture("profile.json")
    offer = _fixture("offer.json")
    snapshot = json.dumps(profile, ensure_ascii=False, sort_keys=True)

    first = build_workspace("app-1", job=offer, profile=profile, variant=MA_VARIANT)
    second = build_workspace("app-1", job=offer, profile=profile, variant=MA_VARIANT)

    assert workspace_to_dict(first) == workspace_to_dict(second)
    assert json.dumps(profile, ensure_ascii=False, sort_keys=True) == snapshot


def test_variant_adaptation_is_reviewed_as_a_pending_change() -> None:
    profile = _fixture("profile.json")
    offer = _fixture("offer.json")

    workspace = build_workspace(
        "app-1", job=offer, profile=profile, variant=MARKETS_VARIANT, language="en"
    )
    skills = next(item for item in workspace.blocks if item.block_id == "skills:0")

    assert skills.source_text == "Excel, financial modelling, valuation, Bloomberg"
    assert skills.proposed_text == "Excel, financial modeling, valuation, Bloomberg"
    assert skills.status == "pending"
    assert skills.evidence is not None


def test_diff_segments_show_only_the_changed_words() -> None:
    segments = diff_segments("financial modelling", "financial modeling")

    assert [segment.op for segment in segments] == ["equal", "delete", "insert"]
    assert "".join(item.text for item in segments if item.op != "insert") == "financial modelling"
    assert "".join(item.text for item in segments if item.op != "delete") == "financial modeling"
    assert diff_segments("same text", "same text") == [
        type(segments[0])(op="equal", text="same text")
    ]


def test_profile_lines_keep_exact_offsets() -> None:
    raw = "First line\n• Second line\n\nThird"
    lines = profile_lines(raw)

    assert [item[0] for item in lines] == ["First line", "Second line", "Third"]
    assert raw[lines[1][1] : lines[1][2]] == "Second line"


# ----------------------------------------------------------------------
# Core: decisions and export blocking
# ----------------------------------------------------------------------
def _workspace_with_placeholder() -> tuple[ReviewWorkspace, list]:
    profile = _fixture("profile.json")
    workspace = build_workspace(
        "app-1",
        job=_fixture("offer.json"),
        profile=profile,
        variant=MA_VARIANT,
        coverage=_coverage("Bloomberg Terminal"),
    )
    placeholders = [
        item for item in workspace.blocks if item.placeholder_reason and item.section in CRITICAL_SECTIONS
    ]
    return workspace, placeholders


def test_critical_placeholder_blocks_the_export_until_it_is_decided() -> None:
    workspace, placeholders = _workspace_with_placeholder()
    assert placeholders, "the fixture must expose an unproven requirement"

    allowed, reasons = can_export(workspace)
    assert allowed is False
    assert reasons
    assert any("Placeholder critique" in reason for reason in reasons)

    updated = apply_decision(workspace, placeholders[0].block_id, "modified", user_text="Bloomberg Terminal, level 2")
    allowed, reasons = can_export(updated)
    assert allowed is True
    assert reasons == []


def test_apply_decision_returns_a_new_workspace_and_validates_its_input() -> None:
    workspace, placeholders = _workspace_with_placeholder()
    target = placeholders[0].block_id

    updated = apply_decision(
        workspace,
        target,
        "modified",
        user_text="Bloomberg Terminal, level 2",
        decided_at="2026-10-22T10:05:00Z",
    )

    assert updated is not workspace
    assert workspace.block(target).status == "pending"
    assert updated.block(target).status == "modified"
    assert updated.block(target).user_text == "Bloomberg Terminal, level 2"
    assert updated.block(target).decided_at == "2026-10-22T10:05:00Z"

    with pytest.raises(ReviewError):
        apply_decision(workspace, target, "modified")
    with pytest.raises(ReviewError):
        apply_decision(workspace, target, "unknown-status")
    with pytest.raises(ReviewError):
        apply_decision(workspace, "does-not-exist", "accepted")


def test_resolved_text_follows_the_decision() -> None:
    source = "Excel, valuation"
    block = ReviewBlock(
        block_id="skills:0",
        section="skills",
        source_text=source,
        proposed_text="Excel, valuation, Bloomberg",
        status="verified",
        evidence=None,
    )
    workspace = ReviewWorkspace(application_id="app-1", blocks=[block])

    assert resolve_block_text(block) == "Excel, valuation, Bloomberg"

    rejected = apply_decision(workspace, "skills:0", "rejected")
    assert resolve_block_text(rejected.blocks[0]) == source

    modified = apply_decision(workspace, "skills:0", "modified", user_text="Excel, valuation, Bloomberg Terminal")
    assert resolve_block_text(modified.blocks[0]) == "Excel, valuation, Bloomberg Terminal"


def test_merge_keeps_decisions_and_drops_the_stale_ones() -> None:
    profile = _fixture("profile.json")
    offer = _fixture("offer.json")
    # The US variant rewords the source line: the block waits for a decision.
    workspace = build_workspace("app-1", job=offer, profile=profile, variant=MARKETS_VARIANT)
    target = "skills:0"
    assert workspace.block(target).status == "pending"
    decided = apply_decision(workspace, target, "rejected", decided_at="2026-10-22T10:06:00Z")

    merged = merge_decisions(workspace, decided)
    assert merged.block(target).status == "rejected"

    # The wording moved (profile edited): the old decision no longer applies.
    moved = build_workspace(
        "app-1",
        job=offer,
        profile={**profile, "skills": "Excel, financial modelling, valuation, Bloomberg, SQL"},
        variant=MARKETS_VARIANT,
    )
    refreshed = merge_decisions(moved, decided)
    assert refreshed.block(target).status == "pending"
    assert refreshed.block(target).user_text is None


def test_review_markdown_drops_unconfirmed_placeholders() -> None:
    workspace, placeholders = _workspace_with_placeholder()
    markdown = build_review_markdown(workspace, _fixture("profile.json"))

    assert PLACEHOLDER_TEXT not in markdown
    assert "## Professional Experience" in markdown
    assert "- Excel, financial modelling, valuation, Bloomberg" in markdown

    decided = apply_decision(workspace, placeholders[0].block_id, "rejected")
    assert PLACEHOLDER_TEXT not in build_review_markdown(decided, _fixture("profile.json"))


# ----------------------------------------------------------------------
# Store: persistence and immutable history
# ----------------------------------------------------------------------
def test_store_round_trips_the_workspace_and_keeps_the_history_append_only(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path)
    workspace = build_workspace(
        "app-store-1",
        job=_fixture("offer.json"),
        profile=_fixture("profile.json"),
        variant=MA_VARIANT,
        created_at="2026-10-22T10:00:00Z",
    )
    store.save_workspace(workspace)
    loaded = store.load_workspace("app-store-1")

    assert loaded is not None
    assert loaded.application_id == workspace.application_id
    assert [item.block_id for item in loaded.blocks] == [item.block_id for item in workspace.blocks]
    assert loaded.blocks[0].evidence[0].quote == workspace.blocks[0].evidence[0].quote

    history_path = store.history_path("app-store-1")
    first = store.new_event(
        application_id="app-store-1",
        block_id="skills:0",
        section="skills",
        from_status="verified",
        to_status="rejected",
        decided_at="2026-10-22T10:01:00Z",
    )
    store.append_event(first)
    prefix = history_path.read_text(encoding="utf-8")

    second = store.new_event(
        application_id="app-store-1",
        block_id="skills:0",
        section="skills",
        from_status="rejected",
        to_status="accepted",
        decided_at="2026-10-22T10:02:00Z",
    )
    store.append_event(second)
    content = history_path.read_text(encoding="utf-8")

    # The log is only appended to: the earlier bytes never change.
    assert content.startswith(prefix)
    history = store.load_history("app-store-1")
    assert [event.sequence for event in history.events] == [1, 2]
    assert [event.to_status for event in history.events] == ["rejected", "accepted"]
    assert history.events[0].user_text is None


def test_store_refuses_an_unsafe_application_id(tmp_path: Path) -> None:
    ReviewStore(tmp_path)

    for unsafe in ("../escape", "app/../../etc", "", "a" * 200, ".hidden"):
        with pytest.raises(ReviewStoreError):
            safe_application_id(unsafe)

    assert safe_application_id("app_0123456789") == "app_0123456789"


# ----------------------------------------------------------------------
# Service: decisions, persistence and export
# ----------------------------------------------------------------------
def test_service_persists_the_decisions_and_exports_the_reviewed_cv(tmp_path: Path) -> None:
    service = _service(tmp_path)
    application_id = _application(service)

    workspace = service.get_cv_review(application_id)
    assert workspace["blocks"]
    assert workspace["progress"]["critical_total"] > 0
    assert workspace["can_export"] is False
    assert workspace["export_blockers"]

    placeholders = [
        block
        for block in workspace["blocks"]
        if block["badge"]["key"] == "placeholder" and block["section"] in CRITICAL_SECTIONS
    ]
    assert placeholders

    with pytest.raises(Exception) as refusal:
        service.export_cv_review(application_id)
    assert "Export bloqué" in str(refusal.value)

    for block in placeholders:
        service.decide_cv_review(
            application_id, block["block_id"], "rejected"
        )

    updated = service.get_cv_review(application_id)
    assert updated["can_export"] is True
    assert updated["export_blockers"] == []

    path = service.export_cv_review(application_id)
    assert path.is_file()
    assert path.suffix == ".docx"

    # The decisions survive a restart of the local service.
    restarted = CareerService(tmp_path, curated_sources=())
    reloaded = restarted.get_cv_review(application_id)
    assert reloaded["can_export"] is True
    history = restarted.get_cv_review_history(application_id)
    assert history["count"] == len(placeholders)
    assert history["immutable"] is True


def test_service_records_a_manual_wording_in_the_exported_document(tmp_path: Path) -> None:
    service = _service(tmp_path)
    application_id = _application(service)
    workspace = service.get_cv_review(application_id)
    placeholders = [
        block
        for block in workspace["blocks"]
        if block["badge"]["key"] == "placeholder" and block["section"] in CRITICAL_SECTIONS
    ]
    assert placeholders
    target = placeholders[0]
    service.decide_cv_review(
        application_id, target["block_id"], "modified", user_text="Bloomberg Terminal, level 2"
    )
    for block in placeholders[1:]:
        service.decide_cv_review(application_id, block["block_id"], "rejected")

    path = service.export_cv_review(application_id)
    from career.cv_quality.parser import extract_text_from_file

    document = extract_text_from_file(path)
    assert "Bloomberg Terminal, level 2" in document.text
    assert PLACEHOLDER_TEXT not in document.text


def test_service_refuses_an_unknown_block_or_status(tmp_path: Path) -> None:
    service = _service(tmp_path)
    application_id = _application(service)

    with pytest.raises(Exception):
        service.decide_cv_review(application_id, "skills:does-not-exist", "accepted")
    with pytest.raises(Exception):
        service.decide_cv_review(application_id, "skills:0", "unknown")


# ----------------------------------------------------------------------
# HTTP: the four review endpoints
# ----------------------------------------------------------------------
def test_http_review_endpoints_expose_the_workspace_history_and_export(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    service = _service(tmp_path)
    application_id = _application(service)

    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get(f"/api/career/cv-review/{application_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["application_id"] == application_id
        assert payload["blocks"]
        assert payload["progress"]["label"]
        assert payload["can_export"] is False

        blocked = client.get(f"/api/career/cv-review/{application_id}/export")
        assert blocked.status_code == 400

        placeholders = [
            block
            for block in payload["blocks"]
            if block["badge"]["key"] == "placeholder" and block["section"] in CRITICAL_SECTIONS
        ]
        assert placeholders
        for block in placeholders:
            decision = client.post(
                f"/api/career/cv-review/{application_id}/decide",
                json={"block_id": block["block_id"], "status": "rejected"},
            )
            assert decision.status_code == 200
            assert decision.json()["decision"]["to_status"] == "rejected"

        history = client.get(f"/api/career/cv-review/{application_id}/history")
        assert history.status_code == 200
        assert history.json()["count"] == len(placeholders)

        exported = client.get(f"/api/career/cv-review/{application_id}/export")
        assert exported.status_code == 200
        assert exported.content[:2] == b"PK"

        invalid = client.post(
            f"/api/career/cv-review/{application_id}/decide",
            json={"block_id": placeholders[0]["block_id"], "status": "invented"},
        )
        assert invalid.status_code == 422


def test_http_review_is_not_available_for_an_unknown_application(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from come_ai_web import create_app

    service = _service(tmp_path)
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.get("/api/career/cv-review/app-does-not-exist")

    assert response.status_code == 400


# ----------------------------------------------------------------------
# Interface: the local review module
# ----------------------------------------------------------------------
def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : les garde-fous JavaScript ne sont pas exécutables sur cette machine")


def _run_node_script(script: str) -> None:
    handle = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
    handle.write(script)
    handle.close()
    try:
        completed = subprocess.run([_node(), handle.name], text=True, capture_output=True, timeout=20)
        assert completed.returncode == 0, completed.stderr
    finally:
        os.unlink(handle.name)


_DOM_PRELUDE = r'''
const assert = require("assert");
class Element {}
function matchesClass(node, cls) { return (" " + String(node.className || "") + " ").includes(" " + cls + " "); }
function stubText(node) {
  let text = node._ownText || "";
  (node.children || []).forEach((child) => { text += " " + stubText(child); });
  return text.trim();
}
function domStub(tag, text = "", className = "") {
  const node = {
    tag, tagName: tag, className, type: "", hidden: false, href: "", dataset: {}, attributes: {},
    listeners: {}, children: [], id: "", value: "", focused: false, style: {},
    focus() { this.focused = true; },
    append(...items) { items.forEach((item) => { if (item) this.children.push(item); }); },
    replaceChildren(...items) { this.children = items.filter(Boolean); },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, key: "" })); },
    querySelector(selector) { return null; },
  };
  node.classList = {
    add(cls) { if (!matchesClass(node, cls)) node.className = (node.className + " " + cls).trim(); },
    remove(cls) { node.className = node.className.split(/\s+/).filter((c) => c && c !== cls).join(" "); },
    contains(cls) { return matchesClass(node, cls); },
  };
  node._ownText = text;
  Object.defineProperty(node, "textContent", {
    get() { return stubText(node); },
    set(value) { node._ownText = String(value); },
  });
  Object.setPrototypeOf(node, Element.prototype);
  return node;
}
globalThis.Element = Element;
globalThis.document = { createElement: (tag) => domStub(tag) };
function make(tag, text = "", className = "") { return domStub(tag, text, className); }
const networkCalls = [];
async function api(url, options) { networkCalls.push({ url, options }); return {}; }
'''


def test_review_module_renders_the_split_diff_the_badges_and_the_decisions() -> None:
    module_source = CV_REVIEW_JS.read_text(encoding="utf-8")
    script = _DOM_PRELUDE + "\n" + module_source + "\n" + r'''
const workspace = {
  progress: { critical_total: 4, critical_validated: 2, label: "2/4 blocs critiques validés" },
  can_export: false,
  export_blockers: ["Placeholder critique non confirmé : Exigence non étayée."],
  blocks: [
    {
      block_id: "skills:0",
      section: "skills",
      source_text: "financial modelling",
      proposed_text: "financial modeling",
      status: "pending",
      user_text: null,
      placeholder_reason: null,
      badge: { key: "to_verify", tone: "warning", label: "À vérifier" },
      diff: [
        { op: "equal", text: "financial " },
        { op: "delete", text: "modelling" },
        { op: "insert", text: "modeling" },
      ],
      evidence: [{ source: "profile.skills", quote: "financial modelling" }],
    },
    {
      block_id: "skills:1",
      section: "skills",
      source_text: "",
      proposed_text: "[AJOUTER PREUVE CHIFFRÉE]",
      status: "pending",
      user_text: null,
      placeholder_reason: "Exigence de l’offre non étayée par le profil local : Bloomberg.",
      badge: { key: "placeholder", tone: "danger", label: "Placeholder" },
      diff: [{ op: "insert", text: "[AJOUTER PREUVE CHIFFRÉE]" }],
      evidence: null,
    },
  ],
};
assert.strictEqual(cvReviewBadge(workspace.blocks[0]).text, "🟡 À vérifier");
assert.strictEqual(cvReviewBadge(workspace.blocks[1]).text, "🔴 Placeholder");
const progress = cvReviewProgress(workspace);
assert.strictEqual(progress.total, 4);
assert.strictEqual(progress.validated, 2);
assert.strictEqual(progress.percent, 50);
assert.strictEqual(progress.label, "2/4 blocs critiques validés");
assert.strictEqual(cvReviewExportEnabled(workspace), false);
assert.match(cvReviewExportTooltip(workspace), /Export bloqué/);

const container = domStub("div");
const decisions = [];
renderCvReview(container, workspace, { onDecide: (block, status, text) => decisions.push({ block: block.block_id, status, text }) });
const blocks = container.children[container.children.length - 1].children;
assert.strictEqual(blocks.length, 2);
// Vue split : source à gauche, proposition à droite.
const split = blocks[0].children.find((node) => matchesClass(node, "cv-review-split"));
assert(split.children.length === 2);
assert(matchesClass(split.children[0], "cv-review-source"));
assert(matchesClass(split.children[1], "cv-review-proposed"));
// Diff coloré : le changement est visible dans la proposition.
const diffNodes = split.children[1].children[1].children;
assert.deepStrictEqual(diffNodes.map((node) => node.className), ["cv-review-diff cv-review-diff-equal", "cv-review-diff cv-review-diff-delete", "cv-review-diff cv-review-diff-insert"]);
// Badge de preuve.
assert.strictEqual(blocks[0].children[0].children[1].textContent, "🟡 À vérifier");
assert.strictEqual(blocks[1].children[0].children[1].textContent, "🔴 Placeholder");
// La raison du placeholder est affichée.
assert(blocks[1].children[2].textContent.includes("Bloomberg"));
// Les quatre boutons de décision par bloc.
const actions = blocks[0].children[blocks[0].children.length - 1];
const labels = actions.children.filter((node) => matchesClass(node, "cv-review-action")).map((node) => node.textContent);
assert.deepStrictEqual(labels, ["Enregistrer la modification", "✅ Accepter", "✏️ Modifier", "❌ Refuser", "↩️ Source"].filter((label) => label !== "Enregistrer la modification"));
// Un clic sur « Refuser » remonte la décision sans appel réseau.
const reject = actions.children.find((node) => node.textContent === "❌ Refuser");
reject.click();
assert.deepStrictEqual(decisions, [{ block: "skills:0", status: "rejected", text: "" }]);
assert.strictEqual(networkCalls.length, 0);
'''
    _run_node_script(script)


def test_review_module_only_calls_the_local_career_api() -> None:
    source = CV_REVIEW_JS.read_text(encoding="utf-8")

    assert "http://" not in source
    assert "https://" not in source
    assert "XMLHttpRequest" not in source
    assert "navigator.sendBeacon" not in source
    assert "/api/career/cv-review/" in source
    # Aucun dialogue natif : la modification se fait dans un champ de la page.
    for forbidden in ("window.prompt", "window.confirm", "window.alert"):
        assert forbidden not in source


def test_index_html_exposes_the_review_view_and_the_local_module() -> None:
    index = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="view-review"' in index
    assert 'id="cv-review-container"' in index
    assert 'id="cv-review-export"' in index
    assert '<script src="/career-static/js/cv-review.js" defer></script>' in index
    assert index.index('<script src="/career-static/js/cv-review.js" defer></script>') < index.index(
        '<script src="/career-static/career.js" defer></script>'
    )
