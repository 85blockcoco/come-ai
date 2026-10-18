"""Offline guards for genuine-board preparation and truthful UI messages.

All jobs/profiles/transports are synthetic. JavaScript tests execute the actual
handler functions in Node with UI/API stubs, not a simulated claim of browser
coverage. The live-browser journey is a separate integration check.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from career.application_prep import MAX_REQUIREMENTS, extract_requirements, prepare_application
from career.discovery import GreenhouseJobBoardConnector
from career.service import CareerService


def test_blank_optional_fields_do_not_invent_empty_requirements() -> None:
    assert extract_requirements({}) == []
    assert extract_requirements({"languages_required": "", "eligibility_requirement": ""}) == []


def test_description_requirements_quote_source_and_stop_at_other_section() -> None:
    description = (
        "Requirements:\nExcel modelling and valuation skills.\n"
        "English fluency required.\nResponsibilities:\nCreate monthly forecasts.\n"
        "Benefits:\nFree coffee."
    )
    items = extract_requirements({"description_original": description})
    assert [item["text"] for item in items] == [
        "Excel modelling and valuation skills.", "English fluency required."
    ]
    assert all(item["text"] in description for item in items)
    assert all(item["source"] == "description_original" for item in items)


def test_description_extraction_is_bounded_and_never_assumes_generic_text_is_requirement() -> None:
    items = extract_requirements({
        "description_original": "Requirements:\n" + "\n".join(f"Synthetic skill {number}." for number in range(100))
    })
    assert len(items) == MAX_REQUIREMENTS
    result = prepare_application({}, {}, {
        "description_original": "A synthetic company builds software and welcomes interns."
    })
    assert result["requirements"] == []
    assert result["matched_elements"] == []
    assert result["source_excerpt"].startswith("A synthetic company")
    assert any("incomplète" in message for message in result["uncertainty"])


def test_structured_requirements_remain_authoritative() -> None:
    items = extract_requirements({
        "requirements": "Excel experience.",
        "description_original": "Requirements: SQL is required.",
    })
    assert items == [{"text": "Excel experience.", "source": "requirements"}]


def test_greenhouse_discovery_to_preparation_uses_source_description(tmp_path: Path) -> None:
    class SyntheticTransport:
        def get_json(self, endpoint: str, timeout_seconds: int) -> dict:
            assert endpoint.startswith("https://boards-api.greenhouse.io/")
            return {"jobs": [{
                "id": 991,
                "title": "Synthetic M&A Intern",
                "absolute_url": "https://careers.example.test/fixture/991",
                "location": {"name": "Paris"},
                "content": "<h3>Requirements</h3><ul><li>Excel modelling and valuation skills.</li>"
                           "<li>English fluency required.</li></ul><h3>Benefits</h3><p>Free coffee.</p>",
            }]}

    service = CareerService(tmp_path, discovery_connector=GreenhouseJobBoardConnector(SyntheticTransport()))
    service.update_profile({"skills": "Excel modelling and valuation", "languages": "English C1"})
    service.create_discovery_source({"company": "Synthetic Bank", "board_token": "synthetic-bank"})
    discovery = service.discover_opportunities()
    assert discovery["outcomes"][0]["status"] == "success"
    jobs = service.list_jobs()
    assert len(jobs) == 1
    prep = service.get_job_prep(jobs[0]["id"])
    assert prep["requirements"]
    assert prep["matched_elements"]
    assert not any(item["text"] in {"Langues requises :", "Éligibilité :"} for item in prep["requirements"])
    for requirement in prep["requirements"]:
        assert requirement["text"] in jobs[0]["description_original"]
    for matched in prep["matched_elements"]:
        assert matched["evidence"] in service.get_profile()[matched["profile_field"]]
    assert prep["job"]["official_url"] == jobs[0]["official_url"]
    assert "Free coffee." not in [item["text"] for item in prep["requirements"]]


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    # Test diagnostics sometimes deliberately use a minimal PATH. Reuse an
    # already installed macOS Node; never install or download anything.
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent: JavaScript behavioural guards not executable on this host")


def test_stage_match_visual_tone_requires_confirmed_qualification() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text()
    function = source.split("function stageMatchBlock(stageMatch) {", 1)[1].split(
        "\nfunction renderStageMatches", 1
    )[0]
    script = r'''
const assert = require("assert");
function make(tag, text="", className="") {
  return {tag, textContent:text, className, children:[], append(...items){this.children.push(...items);}};
}
function chip(text, tone) { return {textContent:text, className:tone}; }
function stageMatchBlock(stageMatch) {FUNCTION
const uncertain = stageMatchBlock({score:100,label:"Pertinence élevée — informations obligatoires à vérifier",
  qualification_status:"to_verify",components:[],warnings:[]});
assert.strictEqual(uncertain.children[0].children[0].textContent, "Pertinence selon tes critères : 100/100");
assert.strictEqual(uncertain.children[0].children[1].className, "warning");
const confirmed = stageMatchBlock({score:100,label:"Correspondance forte",
  qualification_status:"conforming",components:[],warnings:[]});
assert.strictEqual(confirmed.children[0].children[1].className, "good");
'''.replace("FUNCTION", function)
    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr


def test_today_dashboard_profile_shortcut_is_present() -> None:
    html = (Path(__file__).resolve().parents[1] / "career_static/career.html").read_text(encoding="utf-8") if (Path(__file__).resolve().parents[1] / "career_static/career.html").exists() else (Path(__file__).resolve().parents[1] / "career_static/index.html").read_text(encoding="utf-8")
    js = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text(encoding="utf-8")
    assert 'id="today-profile-readiness"' in html
    assert 'data-view-action="profile"' in html
    assert 'api("/api/career/profile")' in js
    assert "renderTodayProfileReadiness" in js


def test_dashboard_quick_tools_expose_only_real_career_views() -> None:
    html = (Path(__file__).resolve().parents[1] / "career_static/index.html").read_text(encoding="utf-8")
    js = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text(encoding="utf-8")
    for view in ("stagehunter", "profile", "studio", "applications", "interviews", "discover"):
        assert f'data-view-action="{view}"' in html
    assert "Tous tes outils Career" in html
    assert 'data-focus-target="profile-document-file"' in html
    assert "focusTarget" in js


@pytest.mark.parametrize("scenario", ["http-error", "source-error", "partial", "success"])
def test_stage_hunter_search_preserves_actual_discovery_result(scenario: str) -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text()
    discovery = source.split("async function runDiscovery(force = false) {", 1)[1].split(
        "\nfunction dashboardActionPriority", 1
    )[0]
    handler = source.split('$("#stagehunter-search")?.addEventListener("click", async () => {', 1)[1].split(
        '\n$("#stagehunter-explore")', 1
    )[0]
    # These are the application's actual functions. Only browser elements,
    # APIs and unrelated refresh loaders are controlled fixtures.
    script = r'''
const assert = require("assert");
const scenario = SCENARIO;
let click, lastMessage;
let stageHunterResultMode = "auto";
const button = {disabled:false, textContent:"Lancer une recherche"};
const trigger = {disabled:false, textContent:"Rechercher"};
const sibling = {disabled:false, textContent:"Actualiser"};
const elements = {discoverySearch:trigger, discoveryForceSearch:sibling};
const $ = () => ({...button, addEventListener:(_, fn) => {click=fn;}});
const setMessage = (text, error=false) => {lastMessage={text,error};};
const api = async () => {
  if (scenario === "http-error") throw new Error("Ajoute d'abord un board synthétique.");
  if (scenario === "source-error") return {outcomes:[{status:"error",company:"Fixture",message:"Source indisponible"}]};
  if (scenario === "partial") return {outcomes:[{status:"success"},{status:"error",company:"Fixture",message:"Source indisponible"}]};
  return {outcomes:[{status:"success"}]};
};
const loadDiscoverySources = async () => {};
const loadJobs = async () => {};
const loadShortlist = async () => {};
const loadDashboard = async () => {};
const loadStudio = async () => {};
const refreshStageHunterIfVisible = async () => {};
const loadStageHunter = async () => {};
DISCOVERY
HANDLER
click().then(() => {
  if (scenario === "http-error") {
    assert.strictEqual(lastMessage.error,true);
    assert.match(lastMessage.text,/board synthétique/);
  } else if (scenario === "source-error") {
    assert.strictEqual(lastMessage.error,true);
    assert.match(lastMessage.text,/Source indisponible/);
  } else if (scenario === "partial") {
    assert.match(lastMessage.text,/1 board vérifié/);
    assert.match(lastMessage.text,/1 source en erreur/);
  } else {
    assert.strictEqual(lastMessage.error,false);
    assert.match(lastMessage.text,/1 board vérifié/);
  }
}).catch(error => {console.error(error);process.exitCode=1;});
'''
    script = script.replace("SCENARIO", json.dumps(scenario))
    script = script.replace("DISCOVERY", "async function runDiscovery(force = false) {" + discovery)
    script = script.replace("HANDLER", '$("#stagehunter-search")?.addEventListener("click", async () => {' + handler)
    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr


def test_tracking_controls_need_explicit_approval_and_real_reference_without_native_prompts() -> None:
    source = (Path(__file__).resolve().parents[1] / "career_static/career.js").read_text()
    functions = source.split("async function approveApplication(", 1)[1].split(
        '\nelements.profileForm.addEventListener', 1
    )[0]
    card = source.split("function applicationCard(", 1)[1].split("\nasync function loadApplications", 1)[0]
    assert "window.prompt" not in card and "window.prompt" not in functions
    assert "window.confirm" not in functions
    assert "approvalCheck.checked" in card and "referenceInput.value" in card
    script = r'''
const assert = require("assert");
let requests = [], messages = [];
const api = async (url, options) => {requests.push({url,...options});return {};};
const setMessage = (text,error=false) => {messages.push({text,error});};
const loadApplications = async () => {};
const loadDashboard = async () => {};
const refreshStageHunterIfVisible = async () => {};
FUNCTIONS
(async () => {
  const app = {id:"synthetic-application"};
  await approveApplication(app);
  assert.strictEqual(requests.length,0);
  assert.strictEqual(messages.at(-1).error,true);
  await approveApplication(app,true);
  assert.strictEqual(requests.length,1);
  assert.strictEqual(JSON.parse(requests[0].body).approved,true);
  await confirmReceipt(app,"");
  await confirmReceipt(app,"x");
  await confirmReceipt(app,"x".repeat(1001));
  assert.strictEqual(requests.length,1);
  await confirmReceipt(app,"fixture-receipt-001");
  assert.strictEqual(requests.length,2);
  assert.strictEqual(JSON.parse(requests[1].body).confirmation_reference,"fixture-receipt-001");
  await markReceiptUnknown(app,"fixture note");
  assert.strictEqual(JSON.parse(requests[2].body).note,"fixture note");
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    script = script.replace("FUNCTIONS", "async function approveApplication(" + functions)
    completed = subprocess.run([_node(), "-e", script], text=True, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr
