"""UX guards for the precise CV plan: filters, deterministic order, navigation.

All plan items are synthetic (no profile, no real CV, no real offer).
JavaScript tests execute the actual cv_plan.js module and the actual
career.js Studio preselection helpers in Node with controlled DOM/storage
stubs — never a simulated claim of browser coverage.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from career.application_prep import reconcile_cv_plan_with_requirements_fit

ROOT = Path(__file__).resolve().parents[1]
CV_PLAN_JS = ROOT / "career_static" / "cv_plan.js"
CV_PLAN_CSS = ROOT / "career_static" / "cv_plan.css"
CAREER_JS = ROOT / "career_static" / "career.js"
INDEX_HTML = ROOT / "career_static" / "index.html"


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: JavaScript behavioural guards not executable on this host")


def test_exact_cross_source_repeats_share_one_cv_action_and_coverage_count() -> None:
    preparation = {
        "offer_intelligence": {
            "requirements_by_id": {
                "req-1": {"id": "req-1", "source_field": "requirements", "locator": "line:1", "text": "Excel required."},
                "req-2": {"id": "req-2", "source_field": "description_original", "locator": "line:4", "text": "Excel required."},
                "req-3": {"id": "req-3", "source_field": "description_original", "locator": "line:5", "text": "Fluent English required."},
            }
        },
        "cv_action_plan": [
            {"id": "action-1", "requirement_id": "req-1", "requirement": "Excel required."},
            {"id": "action-2", "requirement_id": "req-2", "requirement": "Excel required."},
            {"id": "action-3", "requirement_id": "req-3", "requirement": "Fluent English required."},
        ],
        "cv_coverage": {},
    }
    fits = {
        "fits": [
            {"requirement_id": "req-1", "requirement_text": "Excel required.", "modality": "mandatory", "category": "tech", "verdict": "supported"},
            {"requirement_id": "req-2", "requirement_text": "Excel required.", "modality": "mandatory", "category": "tech", "verdict": "supported"},
            {"requirement_id": "req-3", "requirement_text": "Fluent English required.", "modality": "mandatory", "category": "langues", "verdict": "to_verify"},
        ]
    }

    reconcile_cv_plan_with_requirements_fit(preparation, fits)

    assert len(preparation["cv_action_plan"]) == 2
    repeated = preparation["cv_action_plan"][0]
    assert repeated["requirement_ids"] == ["req-1", "req-2"]
    assert [ref["source_field"] for ref in repeated["source_references"]] == [
        "requirements",
        "description_original",
    ]
    assert preparation["cv_coverage"]["requirements_total"] == 2
    assert preparation["cv_coverage"]["supported"] == 1
    assert preparation["cv_coverage"]["to_verify"] == 1


def _run_node_script(script: str) -> None:
    handle = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
    handle.write(script)
    handle.close()
    try:
        completed = subprocess.run([_node(), handle.name], text=True, capture_output=True, timeout=15)
        assert completed.returncode == 0, completed.stderr
    finally:
        os.unlink(handle.name)


def _module_source() -> str:
    return CV_PLAN_JS.read_text(encoding="utf-8")


def fixture_prep() -> str:
    """Synthetic preparation payload covering one item of each rank."""
    prep = {
        "cv_coverage": {
            "requirements_total": 5,
            "supported": 2,
            "to_verify": 3,
            "coverage_percent": 40,
            "target_language": "en",
            "label": "Couverture documentaire du CV",
            "disclaimer": "depuis ton profil",
        },
        "cv_action_plan": [
            {
                "id": "supported-excel",
                "status": "supported",
                "priority": "medium",
                "action_type": "move_up",
                "action_label": "Mettre en avant",
                "section": "Compétences",
                "offer_reference": "Exigence détectée n°1",
                "profile_reference": "Profil local · Compétences",
                "requirement": "Advanced Excel is required.",
                "profile_evidence": "Tools: Advanced Excel.",
                "evidence_quality": "documented",
            },
            {
                "id": "needs-bloomberg",
                "status": "needs_evidence",
                "priority": "high",
                "action_type": "verify_before_adding",
                "action_label": "Ne pas ajouter sans preuve",
                "section": "À déterminer",
                "offer_reference": "Exigence détectée non étayée n°1",
                "requirement": "Bloomberg Terminal proficiency is required.",
                "profile_evidence": "",
                "missing_keywords": ["bloomberg", "terminal"],
                "evidence_quality": "missing",
            },
            {
                "id": "supported-english",
                "status": "supported",
                "priority": "high",
                "action_type": "move_up",
                "action_label": "Mettre en avant",
                "section": "Langues",
                "offer_reference": "Exigence détectée n°2",
                "profile_reference": "Profil local · Langues",
                "requirement": "Fluent English is required.",
                "profile_evidence": "English C1.",
                "evidence_quality": "documented",
            },
            {
                "id": "improve-quantify",
                "status": "supported",
                "priority": "medium",
                "action_type": "rephrase",
                "action_label": "Reformuler fidèlement",
                "section": "Expériences",
                "offer_reference": "Exigence détectée n°3",
                "profile_reference": "Profil local · Expériences",
                "requirement": "Construction d’un modèle financier connue.",
                "profile_evidence": "Projet académique : modèle financier.",
                "evidence_quality": "needs_quantification",
            },
            {
                "id": "pref-sql",
                "status": "needs_evidence",
                "priority": "medium",
                "modality": "preferred",
                "action_label": "Ne pas ajouter sans preuve",
                "section": "À déterminer",
                "requirement": "SQL is a nice to have.",
                "profile_evidence": "",
                "missing_keywords": ["sql"],
                "evidence_quality": "missing",
            },
        ],
    }
    return json.dumps(prep, ensure_ascii=False)


_SHARED_PRELUDE = r'''
const assert = require("assert");
class Element {}
const focusLog = [];
function matchesClass(node, cls) { return (" " + String(node.className || "") + " ").includes(" " + cls + " "); }
function selectorMatches(node, part) { return part.startsWith(".") ? matchesClass(node, part.slice(1)) : node.tag === part; }
function stubText(node) {
  let text = node._ownText || "";
  (node.children || []).forEach((child) => { text += " " + stubText(child); });
  return text.trim();
}
function findDescendant(node, chain, index) {
  for (const child of node.children || []) {
    if (selectorMatches(child, chain[index])) {
      if (index === chain.length - 1) return child;
      const deeper = findDescendant(child, chain, index + 1);
      if (deeper) return deeper;
    }
    const elsewhere = findDescendant(child, chain, 0);
    if (elsewhere) return elsewhere;
  }
  return null;
}
function domStub(tag, text = "", className = "") {
  const node = {
    tag, tagName: tag, className,
    type: "", hidden: false, href: "", dataset: {}, attributes: {}, listeners: {},
    children: [], id: "", focused: false,
    focus() { this.focused = true; focusLog.push(this); },
    append(...items) {
      items.forEach((item) => {
        if (!item) return;
        this.children.push(item);
        item.parentElementStub = this;
        if (this.options) this.options = this.children.slice();
      });
    },
    remove() {
      const parent = this.parentElementStub;
      if (parent) parent.children = parent.children.filter((child) => child !== this);
      if (parent && parent.options) parent.options = parent.children.slice();
      this.removed = true;
    },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key]; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    click(event = { preventDefault() {}, key: "" }) { (this.listeners.click || []).forEach((fn) => fn(event)); },
    querySelector(selector) {
      const parts = selector.split(",").map((part) => part.trim()).filter(Boolean);
      for (const part of parts) {
        const found = findDescendant(this, part.split(/\s+/), 0);
        if (found) return found;
      }
      return null;
    },
    closest(selector) {
      let current = this;
      const chain = selector.trim().split(/\s+/);
      while (current) {
        if (selectorMatches(current, chain[0])) {
          if (chain.length === 1) return current;
          return findDescendant(current, chain, 1);
        }
        current = current.parentElementStub;
      }
      return null;
    },
    replaceChildren(...items) {
      this.children = items.filter(Boolean);
      if (this.options) this.options = this.children.slice();
      this.value = this.children[0] ? this.children[0].value : "";
    },
  };
  node.classList = {
    add(cls) { if (!matchesClass(node, cls)) node.className = (node.className + " " + cls).trim(); },
    remove(cls) { node.className = node.className.split(/\s+/).filter((c) => c && c !== cls).join(" "); },
    contains(cls) { return matchesClass(node, cls); },
    toggle(cls, force) {
      const target = force === undefined ? !matchesClass(node, cls) : Boolean(force);
      if (target) node.classList.add(cls);
      else node.classList.remove(cls);
      return target;
    },
  };
  node._ownText = text;
  Object.defineProperty(node, "textContent", {
    get() { return stubText(node); },
    set(value) { node._ownText = String(value); },
  });
  Object.setPrototypeOf(node, Element.prototype);
  return node;
}
class OptionStub {
  constructor(text = "", value = "") { this.textContent = text; this.value = value; }
}
const Option = OptionStub;
const registry = {};
const storage = new Map();
const timeoutQueue = [];
globalThis.window = {
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => { storage.set(key, String(value)); },
    removeItem: (key) => { storage.delete(key); },
  },
  setTimeout(fn) { timeoutQueue.push(fn); return timeoutQueue.length; },
  location: { hash: "" },
};
globalThis.Element = Element;
const document = {
  getElementById: (id) => registry[id] || null,
  createElement: (tag) => domStub(tag),
};
globalThis.document = document;
const $ = (selector) => registry[selector] || null;
globalThis.$ = $;
const views = [];
let revealedElement = null;
let revealedBlock = null;
function showView(viewName, options = {}) { views.push({ viewName, options }); }
function reveal(element, block = "nearest") { revealedElement = element; revealedBlock = block; }
const studioCalls = [];
function openStudioForJob(job, language = "") { studioCalls.push({ job, language }); }
const networkRequests = [];
async function api(url, options) { networkRequests.push({ url, options }); return {}; }
function flushTimeouts() { timeoutQueue.splice(0).forEach((fn) => fn()); }
// Le module est rendu avec le même `make` raccordable que career.js.
function make(tag, text = "", className = "") { return domStub(tag, text, className); }
'''


def _prelude_with_module() -> str:
    return _SHARED_PRELUDE + "\n" + _module_source() + "\n"


def test_deterministic_order_blocking_required_improvement_preference() -> None:
    script = _prelude_with_module() + r'''
const prep = PREP;
const entries = cvPlanPrepareItems(prep);
assert.deepStrictEqual(
  entries.map((entry) => entry.item.id),
  ["needs-bloomberg", "supported-english", "supported-excel", "improve-quantify", "pref-sql"],
  "ordre : blocage factuel, exigence obligatoire, amélioration, préférence",
);
assert.deepStrictEqual(entries.map((entry) => entry.rankKey), ["blocking", "required", "required", "improvement", "preference"]);
assert.strictEqual(cvPlanRank({ status: "needs_evidence", evidence_quality: "missing" }), 0);
assert.strictEqual(cvPlanRank({ status: "supported" }), 1);
assert.strictEqual(cvPlanRank({ status: "supported", evidence_quality: "needs_quantification" }), 2);
assert.strictEqual(cvPlanRank({ status: "needs_evidence", modality: "preferred" }), 3);
assert.strictEqual(cvPlanRank({ blocking: true }), 0);
assert.strictEqual(cvPlanRank({ source: "cv_structure", status: "supported" }), 2);
assert.strictEqual(
  cvPlanItemFilterKey({ status: "needs_evidence", filter: "verify", evidence_quality: "partial" }),
  "blocking",
  "un élément classé comme blocage factuel reste visible dans le filtre Bloquants",
);
const counts = cvPlanCountByFilter(entries);
assert.deepStrictEqual(counts, { all: 5, highlight: 2, verify: 2, blocking: 1 });
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def _render_fixture_section_script_suffix() -> str:
    return r'''
const prep = PREP;
const target = domStub("div");
const section = renderCvPlanSection(target, prep, { id: "synthetic-job", title: "M&A Intern", company: "Fixture Bank" });
assert(section, "la section du plan doit être rendue");
const nodes = [...section.children, ...section.children.flatMap((child) => child.children)] ;
const filterButtons = nodes.filter((node) => matchesClass(node, "cv-plan-filter"));
const list = nodes.find((node) => matchesClass(node, "cv-plan-list"));
const status = nodes.find((node) => matchesClass(node, "cv-plan-live"));
const empty = nodes.find((node) => matchesClass(node, "cv-plan-empty"));
'''.replace("PREP", fixture_prep())


def test_filters_counters_and_visibility_are_accessible() -> None:
    script = _prelude_with_module() + _render_fixture_section_script_suffix() + r'''
assert.deepStrictEqual(filterButtons.map((button) => button.textContent), [
  "Tous · 5", "À mettre en avant · 2", "À vérifier · 2", "Bloquants · 1",
]);
const group = nodes.find((node) => matchesClass(node, "cv-plan-filters"));
assert.strictEqual(group.getAttribute("role"), "group");
assert.strictEqual(group.getAttribute("aria-label"), "Filtres du plan CV");
assert.strictEqual(status.getAttribute("aria-live"), "polite");
assert.strictEqual(status.getAttribute("role"), "status");
// Filtre « Bloquants » : un seul conseil reste visible, les autres sont masqués.
const blockingButton = filterButtons.find((button) => button.dataset.filter === "blocking");
assert.strictEqual(blockingButton.getAttribute("aria-pressed"), "false");
blockingButton.click();
assert.strictEqual(blockingButton.getAttribute("aria-pressed"), "true");
assert.deepStrictEqual(list.children.map((row) => !row.hidden), [true, false, false, false, false]);
assert.match(status.textContent, /Filtre « Bloquants » : 1 conseil affiché sur 5/);
// Retour à « Tous » : tout redevient visible et annoncé.
filterButtons.find((button) => button.dataset.filter === "all").click();
assert.deepStrictEqual(list.children.map((row) => !row.hidden), [true, true, true, true, true]);
assert.match(status.textContent, /Filtre « Tous » : 5 conseils affichés sur 5/);
assert.strictEqual(empty.hidden, true);
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def test_item_text_shows_requirement_provenance_and_never_copies_claims() -> None:
    script = _prelude_with_module() + _render_fixture_section_script_suffix() + r'''
const blockedRow = list.children[0];
assert.match(blockedRow.textContent, /Blocage factuel/);
assert.match(blockedRow.textContent, /Exigence de l’offre : Bloomberg Terminal proficiency is required\./);
assert.match(blockedRow.textContent, /Mots-clés non étayés à vérifier : bloomberg, terminal/);
assert.match(blockedRow.textContent, /Aucune preuve trouvée dans le profil local/);
const requiredRow = list.children[1];
assert.match(requiredRow.textContent, /Preuve déjà présente : « English C1\. »/);
assert.match(requiredRow.textContent, /Exigence obligatoire/);
const improvementRow = list.children[3];
assert.match(improvementRow.textContent, /Amélioration/);
assert.match(improvementRow.textContent, /ajoute un résultat chiffré uniquement si tu peux le prouver/);
// La ligne de couverture explique la mesure documentaire et exclut la probabilité.
const summaryMatch = nodes.find((node) => matchesClass(node, "cv-plan-summary"));
assert.match(summaryMatch.textContent, /2\/5 exigences appuyées par des preuves suffisantes/);
assert.match(summaryMatch.textContent, /40 % confirmées/);
assert.match(summaryMatch.textContent, /langue cible en/);
const disclaimer = nodes.find((node) => node.textContent === "Ce n’est pas une probabilité d’embauche : c’est un contrôle des preuves actuellement présentes dans ton profil.");
assert(disclaimer, "l’avertissement non-probabiliste est affiché");
// Explication dépliable de la couverture documentaire.
const help = nodes.find((node) => node.tag === "details");
assert(help, "l’aide à la couverture est repliable");
assert.match(help.textContent, /preuve approuvée/);
assert.match(help.textContent, /ne compte jamais comme une exigence satisfaite/);
assert.strictEqual(networkRequests.length, 0);
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def test_empty_filter_state_announces_nothing_hidden() -> None:
    script = _prelude_with_module() + r'''
const prep = {
  cv_coverage: { requirements_total: 1, supported: 1, coverage_percent: 100, target_language: "fr" },
  cv_action_plan: [
    { id: "only-supported", status: "supported", priority: "high", section: "Compétences",
      action_label: "Mettre en avant", requirement: "Excel requis.", profile_evidence: "Excel avancé.",
      evidence_quality: "documented" },
  ],
};
const target = domStub("div");
const section = renderCvPlanSection(target, prep, { id: "fixture-job" });
const nodes = [...section.children, ...section.children.flatMap((child) => child.children)];
const filterButtons = nodes.filter((node) => matchesClass(node, "cv-plan-filter"));
assert.deepStrictEqual(filterButtons.map((button) => button.textContent), [
  "Tous · 1", "À mettre en avant · 1", "À vérifier · 0", "Bloquants · 0",
]);
const list = nodes.find((node) => matchesClass(node, "cv-plan-list"));
const status = nodes.find((node) => matchesClass(node, "cv-plan-live"));
const empty = nodes.find((node) => matchesClass(node, "cv-plan-empty"));
filterButtons.find((button) => button.dataset.filter === "blocking").click();
assert.deepStrictEqual(list.children.map((row) => !row.hidden), [false]);
assert.strictEqual(empty.hidden, false);
assert.match(empty.textContent, /Aucun conseil dans « Bloquants »/);
assert.match(status.textContent, /0 conseil affiché sur 1/);
'''
    _run_node_script(script)


def test_studio_button_preselects_offer_and_language_without_any_network() -> None:
    script = _prelude_with_module() + _render_fixture_section_script_suffix() + r'''
const job = { id: "synthetic-job", title: "M&A Intern", company: "Fixture Bank" };
// Rang 0 (blocage factuel) : passer par le profil puis le Studio.
const blockedRow = list.children[0];
const blockedStudioButton = blockedRow.querySelector(".cv-plan-actions button");
assert.strictEqual(blockedStudioButton.textContent, "Compléter puis préparer");
blockedStudioButton.click();
assert.strictEqual(studioCalls.length, 1);
assert.deepStrictEqual(studioCalls[0].job, job);
assert.strictEqual(studioCalls[0].language, "en");
// Rang 1 (exigence obligatoire étayée) : Studio direct, pas de raccourci profil.
const requiredRow = list.children[1];
const requiredStudioButton = requiredRow.querySelector(".cv-plan-actions button");
assert.strictEqual(requiredStudioButton.textContent, "Préparer dans le Studio");
assert.strictEqual(requiredRow.querySelector(".cv-plan-action-profile"), null, "aucun raccourci profil pour une exigence déjà étayée");
requiredStudioButton.click();
assert.strictEqual(studioCalls[1].language, "en");
// Aucune requête réseau ne part du plan CV (ni cloud, ni consentement).
assert.strictEqual(networkRequests.length, 0, "aucune requête réseau déclenchée par le plan");
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def test_complete_profile_targets_the_right_rubric() -> None:
    script = _prelude_with_module() + r'''
const cases = [
  [{ section: "Compétences" }, "profile-skills"],
  [{ section: "Expériences" }, "profile-experience"],
  [{ section: "Formation" }, "profile-education"],
  [{ section: "Langues" }, "profile-languages"],
  [{ section: "Informations complémentaires" }, "profile-eligibility"],
  [{ category: "Langue" }, "profile-languages"],
];
cases.forEach(([item, expectedField]) => {
  const target = cvPlanProfileTarget(item);
  assert.strictEqual(target.view, "profile", JSON.stringify(item));
  assert.strictEqual(target.field, expectedField, JSON.stringify(item));
});
assert.deepStrictEqual(cvPlanProfileTarget({ category: "Disponibilité" }), { view: "settings", field: "availability-start" });
assert.deepStrictEqual(cvPlanProfileTarget({ category: "Mobilité" }), { view: "stagehunter", field: "stagehunter-cities" });
const fallback = cvPlanProfileTarget({ section: "À déterminer" });
assert.deepStrictEqual(fallback, { view: "profile", field: "" });
// Rubrique connue : focus direct sur le champ.
const experienceField = domStub("input");
registry["profile-experience"] = experienceField;
openCvPlanProfileTarget({ view: "profile", field: "profile-experience" });
assert.strictEqual(views.length, 1);
flushTimeouts();
assert.strictEqual(views[0].viewName, "profile");
assert.strictEqual(revealedElement, experienceField);
assert.strictEqual(experienceField.focused, true, "le champ de la bonne rubrique reçoit le focus");
// Cible inconnue : premier champ du formulaire de profil, jamais un champ de CV source.
const form = domStub("form", "", "form-stack");
const firstField = domStub("input");
form.append(firstField);
registry["#profile-form"] = form;
openCvPlanProfileTarget({ view: "profile", field: "" });
flushTimeouts();
assert.strictEqual(revealedElement, firstField);
assert.strictEqual(firstField.focused, true);
assert.strictEqual(networkRequests.length, 0, "aucun appel réseau : le raccourci est purement navigateur");
assert.strictEqual(studioCalls.length, 0, "aucune ouverture de Studio déguisée en complétion de profil");
'''
    _run_node_script(script)


def test_reviewed_marking_is_local_only_and_survives_a_re_render() -> None:
    script = _prelude_with_module() + r'''
const prep = PREP;
const render = () => {
  const target = domStub("div");
  const section = renderCvPlanSection(target, prep, { id: "synthetic-job", title: "M&A Intern" });
  const nodes = [...section.children, ...section.children.flatMap((child) => child.children)];
  return {
    list: nodes.find((node) => matchesClass(node, "cv-plan-list")),
    status: nodes.find((node) => matchesClass(node, "cv-plan-live")),
  };
};
const first = render();
const row = first.list.children[0]; // blocage factuel (Bloomberg)
const reviewedButton = row.querySelector(".cv-plan-action-reviewed");
assert.strictEqual(reviewedButton.textContent, "Marquer comme revu");
assert.strictEqual(reviewedButton.getAttribute("aria-pressed"), "false");
assert.strictEqual(row.querySelector(".cv-plan-reviewed-badge"), null);
reviewedButton.click();
assert.strictEqual(reviewedButton.textContent, "Marquer comme non revu");
assert.strictEqual(reviewedButton.getAttribute("aria-pressed"), "true");
assert.strictEqual(row.querySelector(".cv-plan-reviewed-badge").textContent, "Revu localement");
assert.match(first.status.textContent, /marqué comme revu localement/);
assert.match(first.status.textContent, /CV source/);
assert.match(first.status.textContent, /modifiés/);
assert.strictEqual(networkRequests.length, 0, "aucun appel API : la marque reste dans le navigateur");
const stored = JSON.parse(storage.get("career_cv_plan_reviewed_synthetic-job"));
assert.deepStrictEqual(Object.keys(stored), ["needs-bloomberg"]);
// Re-rendu (nouvelle analyse) : la marque réapparaît depuis le stockage local.
const second = render();
const secondRow = second.list.children[0];
const secondBadge = secondRow.querySelector(".cv-plan-reviewed-badge");
assert(secondBadge, "la marque « revu » doit survivre au re-rendu");
assert.strictEqual(secondBadge.textContent, "Revu localement");
assert.strictEqual(secondRow.querySelector(".cv-plan-action-reviewed").textContent, "Marquer comme non revu");
// Dé-marquage explicite.
secondRow.querySelector(".cv-plan-action-reviewed").click();
assert.strictEqual(secondRow.querySelector(".cv-plan-action-reviewed").textContent, "Marquer comme revu");
assert.strictEqual(secondRow.querySelector(".cv-plan-reviewed-badge"), null);
assert.match(second.status.textContent, /de nouveau marqué à revoir/);
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def test_keyboard_navigation_moves_between_visible_items() -> None:
    script = _prelude_with_module() + _render_fixture_section_script_suffix() + r'''
const rows = list.children;
const firstActionOf = (row) => row.querySelector(".cv-plan-actions button");
function press(key, from) {
  const before = focusLog.length;
  const event = { prevented: false, preventDefault() { this.prevented = true; }, key, target: from };
  list.listeners.keydown[0](event);
  return { prevented: event.prevented, focused: focusLog.at(-1) || null, focusChanged: focusLog.length > before };
}
// ArrowDown depuis le premier conseil → action du deuxième ; ArrowUp inverse.
let result = press("ArrowDown", firstActionOf(rows[0]));
assert.strictEqual(result.prevented, true);
assert.strictEqual(result.focused, firstActionOf(rows[1]), "ArrowDown atteint le conseil suivant");
result = press("ArrowUp", firstActionOf(rows[1]));
assert.strictEqual(result.focused, firstActionOf(rows[0]), "ArrowUp revient au conseil précédent");
result = press("Home", firstActionOf(rows[2]));
assert.strictEqual(result.focused, firstActionOf(rows[0]), "Home atteint le début de la liste");
result = press("End", firstActionOf(rows[0]));
assert.strictEqual(result.focused, firstActionOf(rows[4]), "End atteint la fin de la liste");
// Une touche étrangère au déplacement n'intercepte rien.
const before = focusLog.length;
const tabEvent = { prevented: false, preventDefault() { this.prevented = true; }, key: "Tab", target: firstActionOf(rows[0]) };
list.listeners.keydown[0](tabEvent);
assert.strictEqual(tabEvent.prevented, false, "Tab garde son comportement natif (parcours bouton par bouton)");
assert.strictEqual(focusLog.length, before);
// Après filtrage « À vérifier », les flèches sautent les conseils masqués.
filterButtons.find((button) => button.dataset.filter === "verify").click();
assert.deepStrictEqual(rows.map((row) => !row.hidden), [false, false, false, true, true]);
result = press("ArrowDown", firstActionOf(rows[2])); // ligne cachée : le focus part du premier visible
assert.strictEqual(result.focused, firstActionOf(rows[3]), "la navigation clavier ignore les conseils masqués");
'''.replace("PREP", fixture_prep())
    _run_node_script(script)


def test_no_cloud_or_native_dialogs_in_the_module() -> None:
    source = _module_source()
    for forbidden in (
        "window.prompt",
        "window.confirm",
        "window.alert",
        "navigator.clipboard",
        "fetch(",
        "api(",
        "XMLHttpRequest",
    ):
        assert forbidden not in source, forbidden
    css = CV_PLAN_CSS.read_text(encoding="utf-8")
    assert "var(--" in css, "les styles du plan réutilisent les tokens existants"
    assert "@media (max-width: 760px)" in css, "viewport étroit géré"
    index = INDEX_HTML.read_text(encoding="utf-8")
    cv_css = re.search(r'href="/career-static/cv_plan\.css\?v=([^"]+)"', index)
    cv_script = re.search(r'<script src="/career-static/cv_plan\.js\?v=([^"]+)" defer></script>', index)
    career_script = re.search(r'<script src="/career-static/career\.js\?v=([^"]+)" defer></script>', index)
    assert cv_css and cv_script and career_script
    assert cv_css.group(1) == cv_script.group(1) == career_script.group(1)
    # Régression : en mode local, la ligne de consentement cloud ne doit pas être
    # rendue (la règle .studio-consent a plus de poids que [hidden] sans ce correctif).
    assert ".studio-consent[hidden]" in (ROOT / "career_static" / "career.css").read_text(encoding="utf-8")
    script_position = index.index(cv_script.group(0))
    career_position = index.index(career_script.group(0))
    assert script_position < career_position, "cv_plan.js s'exécute avant l'accroche career.js"
    # Navigation inchangée : les sept onglets existants, aucun ajout ni retrait.
    for view in ("dashboard", "discover", "stagehunter", "applications", "interviews", "profile", "settings"):
        assert f'id="tab-{view}"' in index


def _career_slice(start: str, end: str) -> str:
    source = CAREER_JS.read_text(encoding="utf-8")
    return source.split(start, 1)[1].split(end, 1)[0]


def test_studio_prefill_survives_a_reload_and_stays_cloudless() -> None:
    open_fn = _career_slice('function openStudioForJob(job, language = "") {', "\nfunction renderDraftHistory")
    render_fn = _career_slice("function renderStudioJobOptions(jobs) {", "\nfunction openStudioForJob")
    script = _prelude_with_module() + r'''
const jobs = [
  { id: "j1", company: "Fixture Bank", title: "M&A Intern", city: "Paris", country: "France" },
  { id: "j2", company: "Second Fixture", title: "Analyste crédit", city: "", country: "" },
];
const makeSelect = () => {
  const node = domStub("select");
  node.options = [];
  return node;
};
let draftModeUiUpdates = 0;
function updateDraftModeUI() { draftModeUiUpdates += 1; }
// ——— Session 1 : arrivée depuis le plan CV ———
const sessionOne = { pendingStudioJob: null, pendingStudioLanguage: "", studioJobs: jobs };
const selectsOne = { applicationDraftJob: makeSelect(), applicationDraftLanguage: makeSelect(), applicationDraftMode: makeSelect(), applicationDraftConsent: { checked: false } };
const shownViews = [];
const globalShowView = showView;
showView = (viewName, options = {}) => { shownViews.push(viewName); return globalShowView(viewName, options); };
OPEN_FUNCTION
sessionOneFn({ id: "j1", company: "Fixture Bank", title: "M&A Intern" }, "en");
assert.strictEqual(selectsOne.applicationDraftMode.value, "local");
assert.strictEqual(selectsOne.applicationDraftConsent.checked, false);
assert.deepStrictEqual(shownViews.at(-1), "studio");
assert.deepStrictEqual(JSON.parse(storage.get("career_studio_prefill")), { job_id: "j1", language: "en", mode: "local" });
// ——— Session 2 : rechargement de l'interface (mémoire vide, stockage conservé) ———
const sessionTwo = { pendingStudioJob: null, pendingStudioLanguage: "", studioJobs: jobs };
const selectsTwo = { applicationDraftJob: makeSelect(), applicationDraftLanguage: makeSelect(), applicationDraftMode: makeSelect(), applicationDraftConsent: { checked: false } };
SESSION_TWO
assert.strictEqual(selectsTwo.applicationDraftJob.value, "j1", "l'offre sélectionnée reste sélectionnée après rechargement");
assert.strictEqual(selectsTwo.applicationDraftLanguage.value, "en", "la langue choisie est réappliquée");
assert.strictEqual(selectsTwo.applicationDraftMode.value, "local", "le mode restauré reste le gabarit local");
assert.strictEqual(selectsTwo.applicationDraftConsent.checked, false, "jamais de consentement cloud activé au rechargement");
assert(draftModeUiUpdates >= 1, "la ligne de consentement reste masquée en mode local");
// ——— Session 3 : un mode IA falsifié dans le stockage n'est jamais restauré ———
storage.set("career_studio_prefill", JSON.stringify({ job_id: "j1", language: "fr", mode: "ai" }));
const sessionThree = { pendingStudioJob: null, pendingStudioLanguage: "", studioJobs: jobs };
const selectsThree = { applicationDraftJob: makeSelect(), applicationDraftLanguage: makeSelect(), applicationDraftMode: makeSelect(), applicationDraftConsent: { checked: false } };
SESSION_THREE
assert.strictEqual(selectsThree.applicationDraftMode.value, "local", "le mode IA synchronifié n'est jamais restauré, retour au gabarit local");
assert.strictEqual(selectsThree.applicationDraftConsent.checked, false);
// Aucune requête réseau n'a été tentée pendant les trois sessions.
assert.strictEqual(networkRequests.length, 0);
'''.replace(
        "OPEN_FUNCTION",
        'const elements = selectsOne;\nconst state = sessionOne;\nconst sessionOneFn = function openStudioForJob(job, language = "") {' + open_fn,
    ).replace(
        "SESSION_TWO",
        "(function () {\n"
        "  const elements = { applicationDraftJob: selectsTwo.applicationDraftJob, applicationDraftLanguage: selectsTwo.applicationDraftLanguage, applicationDraftMode: selectsTwo.applicationDraftMode, applicationDraftConsent: selectsTwo.applicationDraftConsent };\n"
        "  const state = sessionTwo;\n"
        "  function renderStudioJobOptions(jobs) {" + render_fn + "\n"
        "  renderStudioJobOptions(jobs);\n"
        "})();",
    ).replace(
        "SESSION_THREE",
        "(function () {\n"
        "  const elements = { applicationDraftJob: selectsThree.applicationDraftJob, applicationDraftLanguage: selectsThree.applicationDraftLanguage, applicationDraftMode: selectsThree.applicationDraftMode, applicationDraftConsent: selectsThree.applicationDraftConsent };\n"
        "  const state = sessionThree;\n"
        "  function renderStudioJobOptions(jobs) {" + render_fn + "\n"
        "  renderStudioJobOptions(jobs);\n"
        "})();",
    )
    _run_node_script(script)


def test_studio_selection_changes_are_persisted_through_listeners() -> None:
    source = CAREER_JS.read_text(encoding="utf-8")
    assert "elements.applicationDraftJob.addEventListener" in source
    assert "elements.applicationDraftLanguage.addEventListener" in source
    assert 'saveStudioPrefill(selectedJob, elements.applicationDraftLanguage.value, "local")' in source
    open_fn = _career_slice('function openStudioForJob(job, language = "") {', "\nfunction renderDraftHistory")
    assert 'saveStudioPrefill(job, state.pendingStudioLanguage, "local")' in open_fn
    assert "loadStudioPrefill().job_id" in source
