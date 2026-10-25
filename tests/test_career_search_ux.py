"""Guards for the Stage Hunter information hierarchy and honest loading UI.

The fixtures are synthetic.  These tests inspect and execute the shipped
browser helpers without making any network request.
"""

from __future__ import annotations

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


def test_progress_copy_explicitly_says_that_progress_is_estimated() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Progression estimée" in source
    assert "Le nombre exact de sources sera affiché à la fin" in source


def test_detail_view_keeps_full_loaded_offer_when_prep_payload_is_bounded() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    detail = source.split("async function loadStageDetail(jobId) {", 1)[1].split(
        "\nfunction renderStagePrepSelect", 1
    )[0]
    assert "selectedMatch = state.stageMatches.find" in detail
    assert "{...(selectedMatch.job || {}), ...(prep.job || {})}" in detail
    assert "...(selectedMatch.qualification || {})" in detail


def test_progress_reaches_complete_state_with_real_result_counts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = "let stageHunterResultMode" + source.split("let stageHunterResultMode", 1)[1].split(
        "\nfunction renderStageExploration", 1
    )[0]
    script = r'''
const assert = require("assert");
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
const realSetInterval = setInterval;
const realClearInterval = clearInterval;
global.setInterval = () => 99;
global.clearInterval = () => {};
HELPERS
startStageHunterProgress();
assert.strictEqual(elements["#stagehunter-progress"].hidden, false);
assert.strictEqual(elements["#stagehunter-progress-bar"].attrs["aria-valuenow"], "6");
finishStageHunterProgress(true, {summary:{sources_attempted:12,retained_count:34}});
assert.strictEqual(elements["#stagehunter-progress-bar"].attrs["aria-valuenow"], "100");
assert.match(elements["#stagehunter-progress-detail"].textContent, /12 sources consultées/);
assert.match(elements["#stagehunter-progress-detail"].textContent, /34 offres retenues/);
assert(classes.has("is-complete"));
global.setInterval = realSetInterval;
global.clearInterval = realClearInterval;
'''.replace("HELPERS", helpers)
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=8)
    assert completed.returncode == 0, completed.stderr

