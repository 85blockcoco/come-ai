"""Guards for the Stage Hunter information hierarchy and honest loading UI.

The fixtures are synthetic.  These tests inspect and execute the shipped
browser helpers without making any network request.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "career_static" / "index.html"
SCRIPT = ROOT / "career_static" / "career.js"


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: impossible d'exécuter les gardes JavaScript")


def test_stage_search_exposes_accessible_progress_and_result_summary() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="stagehunter-progress"' in html
    assert 'id="stagehunter-progress-bar"' in html
    assert 'role="progressbar"' in html
    assert 'aria-live="polite"' in html
    assert 'id="stagehunter-result-summary"' in html


def test_stage_results_make_education_priority_and_rank_visible() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Accessible BBA / Bac+4" in source
    assert "Ambitieux M2 / MBA" in source
    assert "Niveau à vérifier" in source
    assert "Choix #" in source
    assert "accessibles maintenant" in source
    assert "ambitieuses M2 / MBA" in source


def test_stagehunter_keeps_first_run_criteria_visible_and_advanced_filters_collapsible() -> None:
    html = HTML.read_text(encoding="utf-8")
    core_criteria = html.index('id="stagehunter-start-date"')
    advanced = html.index('<details class="stagehunter-advanced">')
    finance_domains = html.index('id="stagehunter-domains"')
    save_button = html.index("Enregistrer mes critères")
    assert core_criteria < advanced < finance_domains < save_button
    assert 'id="stagehunter-min-stage-duration"' in html
    assert 'offres à partir du 1<sup>er</sup> janvier 2027' in html
    assert "stages de six mois minimum" in html
    # The default branch is closed so the first screen emphasizes start date,
    # minimum duration and contract before optional matching refinements.
    assert '<details class="stagehunter-advanced" open' not in html


def test_stagehunter_cycle_summary_follows_the_five_user_steps() -> None:
    html = HTML.read_text(encoding="utf-8")
    last_step = html.index('<p class="eyebrow">Étape E</p>')
    overview = html.index("stagehunter-pipeline-panel")
    assert last_step < overview


def test_offer_fact_helpers_never_replace_missing_information_with_an_invention() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = source.split("function formatStageDate(", 1)[1].split(
        "\nfunction stageMatchBlock", 1
    )[0]
    script = r'''
const assert = require("assert");
function formatStageDate(HELPERS
const empty = {job:{}, qualification:{}};
assert.strictEqual(stageOfferFactValue(empty.job, empty.qualification, "start"), "À vérifier");
assert.strictEqual(stageOfferFactValue(empty.job, empty.qualification, "duration"), "À vérifier");
assert.strictEqual(stageOfferFactValue(empty.job, empty.qualification, "location"), "À vérifier");
const known = {
  job: {city:"Milan", country:"Italy", start_date:"2027-02-01", end_date:"2027-07-31", duration_months:6},
  qualification: {},
};
assert.match(stageOfferFactValue(known.job, known.qualification, "location"), /Milan/);
assert.match(stageOfferFactValue(known.job, known.qualification, "start"), /févr|2027/);
assert.strictEqual(stageOfferFactValue(known.job, known.qualification, "duration"), "6 mois");
const evidencedYear = {job:{qualification_facts:{temporal_facts:[{fact_type:"start", value:{month:1, year:2027}, contradictions:[]}]}}, qualification:{start_month:1}};
assert.strictEqual(stageOfferFactValue(evidencedYear.job, evidencedYear.qualification, "start"), "janvier 2027");
const conflictedYear = {job:{}, qualification:{start_month:1, temporal_facts:[{fact_type:"start", value:{month:1, year:2027}, contradictions:["date contradictoire"]}]}};
assert.strictEqual(stageOfferFactValue(conflictedYear.job, conflictedYear.qualification, "start"), "janvier · année à vérifier");
'''.replace("HELPERS", helpers)
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=8)
    assert completed.returncode == 0, completed.stderr

def test_offer_cards_surface_all_decision_facts_and_source_reliability() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for label in (
        "Contrat",
        "Localisation",
        "Publication",
        "Début",
        "Fin",
        "Durée",
        "Candidater avant",
        "Langue",
    ):
        assert f'"{label}"' in source
    assert "Informations manquantes" in source
    assert "official_source_trust_label" in source
    assert "Origine du lien" in source
    assert "Prérequis repérés dans l’offre" in source


def test_progress_copy_says_the_steps_come_from_the_server() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    module = (ROOT / "career_static" / "js" / "exploration-progress.js").read_text(encoding="utf-8")
    # Une progression estimée ne doit plus être promise à la personne : les
    # étapes affichées sont celles que le serveur a réellement terminées.
    assert "Progression estimée" not in source
    assert "progression estimée" not in module.lower()
    assert "étape réellement terminée" in source
    assert "étape réellement terminée" in HTML.read_text(encoding="utf-8")
    assert "/api/career/stage-search/explorations" in module


def test_detail_view_keeps_full_loaded_offer_when_prep_payload_is_bounded() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    detail = source.split("async function loadStageDetail(jobId) {", 1)[1].split(
        "\nfunction renderStagePrepSelect", 1
    )[0]
    assert "selectedMatch = state.stageMatches.find" in detail
    assert "{...(selectedMatch.job || {}), ...(prep.job || {})}" in detail
    assert "...(selectedMatch.qualification || {})" in detail


def test_progress_reaches_complete_state_with_real_result_counts(tmp_path: Path) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = "let stageHunterResultMode" + source.split("let stageHunterResultMode", 1)[1].split(
        "\nfunction renderStageExploration", 1
    )[0]
    module_path = tmp_path / "exploration-progress.js"
    module_path.write_text(
        (ROOT / "career_static" / "js" / "exploration-progress.js").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    script = r'''
const assert = require("assert");
const fs = require("fs");
const fill = {style:{}};
const classes = new Set();
const elements = {
  "#stagehunter-progress": {hidden:true,classList:{remove(...names){names.forEach(n=>classes.delete(n));},toggle(name,on){on?classes.add(name):classes.delete(name);}}},
  "#stagehunter-progress-bar": {attrs:{},setAttribute(k,v){this.attrs[k]=v;},querySelector(){return fill;}},
  "#stagehunter-progress-percent": {textContent:""},
  "#stagehunter-progress-label": {textContent:""},
  "#stagehunter-progress-detail": {textContent:""},
};
const $ = (selector) => elements[selector] || null;
global.window = globalThis;
global.document = {getElementById(id){ return elements["#" + id] || null; }};
(0, eval)(fs.readFileSync(MODULE_PATH, "utf8"));
HELPERS
const state = {
  run_id: "explore_run_synthetic", status: "running", phase: "qualifying",
  phase_order: ["preparing","consulting","normalizing","qualifying","deduplicating","ranking","persisting","completed"],
  phases_completed: 3, sources_total: 21, sources_completed: 8, sources_succeeded: 7,
  sources_failed: 1, offers_read: 340, offers_qualified: 57, cancel_requested: false,
};
renderExplorationProgress(state);
assert.strictEqual(elements["#stagehunter-progress"].hidden, false);
assert.strictEqual(elements["#stagehunter-progress-bar"].attrs["aria-valuenow"], "43");
assert.match(elements["#stagehunter-progress-detail"].textContent, /8\/21 sources terminées/);
assert.match(elements["#stagehunter-progress-detail"].textContent, /7 réussies/);
assert.match(elements["#stagehunter-progress-detail"].textContent, /1 en erreur/);
assert.match(elements["#stagehunter-progress-detail"].textContent, /340 annonces lues/);
assert.match(elements["#stagehunter-progress-detail"].textContent, /57 offres qualifiées/);
'''.replace("HELPERS", helpers).replace("MODULE_PATH", json.dumps(str(module_path)))
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=8)
    assert completed.returncode == 0, completed.stderr


def test_stale_exploration_returns_user_to_saved_offers_with_refresh_notice() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    function = source.split("async function loadStageHunter() {", 1)[1].split(
        '\n$("#stagehunter-brief-form")', 1
    )[0]
    script = r'''
const assert = require("assert");
let stageHunterResultMode = "auto";
const state = {applications:[]};
const calls = [];
const status = {textContent:""};
const elements = {"#stagehunter-result-mode":status,"#stagehunter-matches-empty":{textContent:""}};
const $ = selector => elements[selector] || null;
const savedOffers = {offers:[{id:"synthetic-saved-offer"}]};
const api = async path => {
  calls.push(path);
  if (path === "/api/career/stage-search") return {configured:true};
  if (path === "/api/career/stage-search/explore") return {
    outcomes:[{source:"old-run"}], criteria_changed:true, requires_refresh:true, matches:[]
  };
  if (path === "/api/career/stage-search/matches") return savedOffers;
  if (path === "/api/career/applications") return {applications:[]};
  if (path === "/api/career/application-pipeline") return {pipeline:[]};
  throw new Error("Unexpected API " + path);
};
let renderedSaved = null, renderedStale = false;
const renderStageBrief = () => {};
const renderStageTerms = () => {};
const renderStageExploration = () => {};
const renderExplorationMatches = () => {renderedStale=true;};
const renderStageMatches = value => {renderedSaved=value;};
const renderStagePrepSelect = () => {};
const renderStageApplications = () => {};
const loadApplicationPipeline = async () => {};
LOAD_STAGE_HUNTER
(async () => {
  await loadStageHunter();
  assert.strictEqual(stageHunterResultMode,"saved");
  assert.strictEqual(renderedSaved,savedOffers);
  assert.strictEqual(renderedStale,false,"stale matches must never be presented as current");
  assert.match(status.textContent,/périmée.*relancée/i);
  assert.ok(calls.includes("/api/career/stage-search/matches"));
})().catch(error => {console.error(error);process.exitCode=1;});
'''.replace("LOAD_STAGE_HUNTER", "async function loadStageHunter() {" + function)
    # Execute the shipped function with controlled synthetic API/UI boundaries.
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=8)
    assert completed.returncode == 0, completed.stderr

