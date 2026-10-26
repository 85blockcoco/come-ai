"""Local workshop integration with fictitious configuration and no remote calls."""
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from come_ai_web import create_app


def test_evolution_backlog_settings_persist_and_offline_forces_local_provider(tmp_path):
    (tmp_path / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    app = create_app(tmp_path)
    try:
        with TestClient(app) as client:
            status = client.get("/api/devkit/status", headers={"Origin": "http://testserver"}).json()
            assert status["workshop_token"], "jeton attendu pour le navigateur local"
            headers = {"X-Workshop-Token": status["workshop_token"]}
            assert client.get("/api/devkit/evolution").status_code == 403
            initial = client.get("/api/devkit/evolution", headers=headers)
            assert initial.status_code == 200
            assert initial.json()["settings"]["model"] == "auto"
            assert initial.json()["provider"]["configured"] is False
            assert client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto"}).status_code == 403
            settings = client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto", "mode": "offline", "allow_remote": True}, headers=headers)
            assert settings.status_code == 200
            assert settings.json()["provider"] == "ollama"
            assert settings.json()["allow_remote"] is False
            task = client.post("/api/devkit/evolution/tasks", json={"title": "Fixture", "description": "Corriger valeur", "selected_files": ["core.py"]}, headers=headers)
            assert task.status_code == 200
            second = client.get("/api/devkit/evolution", headers=headers).json()
            assert second["tasks"][0]["task_id"] == task.json()["task_id"]
            assert second["mode"] == "offline"
            assert second["automatic_deployment"] is False
            assert second["scheduling"] is False
            assert str(tmp_path) not in client.get("/api/devkit/evolution", headers=headers).text
            performance = client.post("/api/devkit/evolution/settings", json={"provider": "gemini", "model": "auto", "mode": "performance"}, headers=headers).json()
            assert performance["max_output_tokens"] == 6000
            assert performance["timeout_seconds"] == 60
    finally:
        app.state.runtime.task_runner.stop(wait=True, timeout=1)


def test_evolution_candidate_result_has_direct_review_handoff() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    evolution = (root / "v5_static/evolution.js").read_text(encoding="utf-8")
    devkit = (root / "v5_static/devkit.js").read_text(encoding="utf-8")
    html = (root / "v5_static/index.html").read_text(encoding="utf-8")
    assert 'id="evolutionCandidateReview"' in html
    assert 'button.textContent = "Examiner le correctif proposé"' in evolution
    assert 'detail: {candidateId}' in evolution
    assert 'renderRunResult(result); } catch (error) { show(error.message); } }); n("evolutionHistory").append(button);' in evolution
    assert 'addEventListener("devkit:open-candidate"' in devkit
    assert 'request(`/candidates/${encodeURIComponent(requestedId)}`)' in devkit
    assert "ui.diff.textContent = preview.diff" in devkit
    assert 'id="developerApplyConfirmYes"' in html
    assert 'id="developerRollbackConfirmYes"' in html
    assert 'ui.applyConfirm.hidden = false' in devkit
    assert 'ui.rollbackConfirm.hidden = false' in devkit
    assert 'window.confirm(' not in devkit


def test_evolution_ui_resumes_the_active_job_after_page_reload() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node absent: impossible d’exécuter le contrôleur UI du Dev Kit")
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert = require("assert");
const fs = require("fs");
const listeners = {};
const elements = new Map();
function makeElement(id = "") {
  return {
    id, listeners: {}, selectedOptions: [], value: "", textContent: "", hidden: false,
    disabled: false, checked: false, children: [],
    addEventListener(name, callback) { this.listeners[name] = callback; },
    replaceChildren(...children) { this.children = children; },
    append(child) { this.children.push(child); },
    click() { return this.listeners.click?.(); },
  };
}
const developerTab = makeElement("developer-tab");
global.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  },
  querySelector(selector) {
    assert.strictEqual(selector, '[data-view-target="developerView"]');
    return developerTab;
  },
  createElement(tag) { return makeElement(tag); },
};
const timers = new Map();
let nextTimer = 0;
global.setTimeout = (callback) => { const id = ++nextTimer; timers.set(id, callback); return id; };
global.clearTimeout = (id) => timers.delete(id);
global.window = {
  location: {hash:"#v5/developerView"},
  addEventListener(name, callback) { listeners[name] = callback; },
  dispatchEvent() {},
};
global.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail; } };
let statusCalls = 0;
let jobCalls = 0;
const active = [
  {kind:"diagnostics", job_id:"diagnostic-1", status:"running", message:"Diagnostic actif"},
  {kind:"evolution", job_id:"evolution-1", status:"running", message:"Cycle à reprendre"},
];
global.fetch = async (url) => {
  let payload;
  if (url === "/api/devkit/status") {
    statusCalls += 1;
    payload = {workshop_token:"synthetic-token", source_files:[], active_jobs: statusCalls < 3 ? active : []};
  } else if (url === "/api/devkit/evolution") {
    payload = {settings:{provider:"ollama", model:"local", allow_remote:false, gemini_free_project_confirmed:false}, provider:{provider_id:"ollama", model_id:"local", configured:true}, dashboard:{metrics:{}, tasks_by_status:{}}, mode:"offline", usage:{}, tasks:[], runs:[], catalogue:{}};
  } else if (url === "/api/devkit/jobs/evolution-1") {
    jobCalls += 1;
    payload = jobCalls === 1
      ? {job_id:"evolution-1", kind:"evolution", status:"running", message:"Cycle à reprendre"}
      : {job_id:"evolution-1", kind:"evolution", status:"completed", message:"Cycle terminé", report:{candidate_id:"candidate-1", status:"needs_review"}};
  } else {
    throw new Error(`Unexpected request: ${url}`);
  }
  return {ok:true, json:async () => payload};
};
eval(fs.readFileSync(SCRIPT_PATH, "utf8"));
const idle = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  // A direct page reload to this view does not generate a tab click.
  await idle();
  assert.strictEqual(jobCalls, 1, "the active evolution job is polled after page load");
  assert.strictEqual(document.getElementById("evolutionRun").disabled, true);
  assert.strictEqual(document.getElementById("evolutionState").textContent, "Cycle en cours");
  assert.strictEqual(document.getElementById("evolutionMessage").textContent, "Cycle à reprendre");

  window.location.hash = "#v5/assistantView";
  await listeners.hashchange();
  assert.strictEqual(jobCalls, 1, "leaving the view does not stop its active job poll");
  window.location.hash = "#v5/developerView";
  await listeners.hashchange();
  await idle();
  assert.strictEqual(jobCalls, 1, "returning to the view does not create duplicate poll loops");
  assert.strictEqual(document.getElementById("evolutionRun").disabled, true);

  const timerId = [...timers.keys()][0];
  assert.ok(timerId, "the running job has a scheduled follow-up poll");
  await timers.get(timerId)();
  assert.strictEqual(jobCalls, 2);
  assert.strictEqual(document.getElementById("evolutionRun").disabled, false);
  assert.match(document.getElementById("evolutionDetails").textContent, /candidate-1/);
  console.log("active evolution job resumed and completed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
'''.replace("SCRIPT_PATH", repr(str(root / "v5_static" / "evolution.js")))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr
    assert "active evolution job resumed and completed" in result.stdout
