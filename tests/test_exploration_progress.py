"""Server-side exploration progress: real phases, real counters, real cancel.

Every source below is synthetic and served by an offline transport: no test
reads a public board, sends an application or touches a personal document.
The counters asserted here are the ones the server really produced: a run
that stops early never claims more work than it did.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.discovery import GreenhouseJobBoardConnector, PublicSourceError
from career.exploration_run import EXPLORATION_PHASES, ExplorationRun, ExplorationRunStore
from career.exploration_service import CareerExplorationBackend, ExplorationService, _Candidate
from career.service import CareerService
from come_ai_web import create_app
from workspace_core import UserFacingError


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "career_static" / "js" / "exploration-progress.js"


def source(token: str, company: str = "Banque fictive") -> dict:
    return {
        "id": f"registry:greenhouse:{token}",
        "provider": "greenhouse",
        "company": company,
        "board_token": token,
        "public_url": f"https://boards.greenhouse.io/{token}",
        "provenance_url": f"https://careers.example.test/{token}",
        "verified_at": "2026-10-13T22:00:00Z",
    }


def posting(identifier: str, title: str = "Corporate Finance Intern") -> dict:
    return {
        "id": identifier,
        "title": title,
        "absolute_url": f"https://careers.example.test/jobs/{identifier}",
        "location": {"name": "London, United Kingdom"},
        "content": "<p>Stage synthétique en corporate finance.</p>",
    }


class SyntheticTransport:
    """Offline public feed: it records the concurrency and can be paused."""

    def __init__(self, boards, *, failing=(), gate=None, delay=0.0):
        self.boards = boards
        self.failing = set(failing)
        self.gate = gate
        self.delay = delay
        self.calls: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def get_json(self, endpoint, timeout_seconds):
        token = endpoint.split("/boards/", 1)[1].split("/", 1)[0]
        with self._lock:
            self.calls.append(token)
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.gate is not None:
                self.gate.wait(timeout=10)
            if self.delay:
                time.sleep(self.delay)
            if token in self.failing:
                raise PublicSourceError("Source synthétique indisponible.", code="unavailable")
            return {"jobs": self.boards.get(token, [])}
        finally:
            with self._lock:
                self.concurrent -= 1


def service_with(tmp_path: Path, boards, *, failing=(), sources=None, gate=None, delay=0.0):
    transport = SyntheticTransport(boards, failing=failing, gate=gate, delay=delay)
    connector = GreenhouseJobBoardConnector(transport)
    service = CareerService(
        tmp_path,
        discovery_connector=connector,
        curated_sources=tuple(sources or [source(token) for token in boards]),
        exploration_connectors={"greenhouse": connector},
    )
    service.update_stage_search({"domains": ["Corporate Finance"], "cities": ["London"]})
    return service, transport


def test_runtime_dedup_keeps_cross_source_provenance_and_location_conflicts():
    shared_url = "https://boards.greenhouse.io/synthetic-bank/jobs/offer-1"
    candidates = [
        _Candidate(
            job={"company": "Synthetic Bank", "title": "Corporate Finance Intern", "source_name": "greenhouse",
                 "source_id": "gh-1", "official_url": shared_url, "city": "London", "country": "United Kingdom"},
            match={}, classification={}, qualification={}, key=(0,),
        ),
        _Candidate(
            job={"company": "Synthetic Bank", "title": "Corporate Finance Intern", "source_name": "lever",
                 "source_id": "lever-1", "official_url": shared_url, "city": "Manchester", "country": "United Kingdom"},
            match={}, classification={}, qualification={}, key=(0,),
        ),
    ]

    kept = ExplorationService._deduplicate(candidates)

    assert len(kept) == 1
    evidence = kept[0].qualification
    assert {item["source_name"] for item in evidence["source_provenance"]} == {"greenhouse", "lever"}
    assert evidence["source_conflicts"]["city"] == {
        "greenhouse:gh-1": "London",
        "lever:lever-1": "Manchester",
    }


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_run_walks_through_the_real_phases_and_counts_real_work(tmp_path: Path) -> None:
    boards = {"alpha": [posting("a1"), posting("a2")], "beta": [posting("b1")]}
    boards["alpha"][0]["content"] = "Synthetic finance internship. Starting January 2027 for six months."
    service, transport = service_with(tmp_path, boards)
    explorations = ExplorationService(service)
    try:
        state = explorations.start(force=True)
        assert state["status"] == "running"
        final = explorations.wait_for(state["run_id"], 20)
        assert final is not None
        assert final["status"] == "completed", final
        assert [entry["phase"] for entry in final["phases"]] == list(EXPLORATION_PHASES)
        assert all(entry["status"] == "completed" for entry in final["phases"])
        assert final["sources_total"] == 2
        assert final["sources_completed"] == 2
        assert final["sources_succeeded"] == 2
        assert final["sources_failed"] == 0
        assert final["sources_pending"] == 0
        # Three postings were really read: the counters follow the work.
        assert final["offers_read"] == 3
        assert final["offers_qualified"] == 3
        assert final["offers_persisted"] == 3
        assert len(transport.calls) == 2
        assert len(service.list_jobs()) == 3
        stored = service.get_job(service.list_jobs()[0]["id"])
        temporal_facts = stored["qualification_facts"]["temporal_facts"]
        assert stored["qualification_facts"]["source_provenance"]
        assert stored["qualification_facts"]["source_provenance"][0]["source_id"] == "a1"
        assert any(
            fact["fact_type"] == "start"
            and fact["value"] == {"day": None, "month": 1, "year": 2027}
            and fact["quote"] == "Starting January 2027"
            for fact in temporal_facts
        )
        # The published snapshot is the one of this run.
        assert service.get_exploration()["run_id"] == final["run_id"]
    finally:
        explorations.shutdown()


def test_at_most_two_sources_are_consulted_at_the_same_time(tmp_path: Path) -> None:
    boards = {token: [posting(f"{token}-1")] for token in ("alpha", "beta", "gamma", "delta")}
    service, transport = service_with(tmp_path, boards, delay=0.05)
    explorations = ExplorationService(service)
    try:
        state = explorations.start(force=True)
        final = explorations.wait_for(state["run_id"], 30)
        assert final is not None and final["status"] == "completed", final
        assert len(transport.calls) == 4
        assert transport.max_concurrent == 2
        assert final["sources_completed"] == 4
    finally:
        explorations.shutdown()


def test_cancellation_stops_between_two_sources_and_keeps_the_previous_results(tmp_path: Path) -> None:
    boards = {token: [posting(f"{token}-1")] for token in ("alpha", "beta", "gamma", "delta")}
    service, transport = service_with(tmp_path, boards)
    explorations = ExplorationService(service)
    try:
        first = explorations.start(force=True)
        first_state = explorations.wait_for(first["run_id"], 20)
        assert first_state is not None and first_state["status"] == "completed"
        published_run_id = service.get_exploration()["run_id"]

        gate = threading.Event()
        transport.gate = gate
        before = len(transport.calls)
        second = explorations.start(force=True)
        assert wait_until(lambda: len(transport.calls) >= before + 2), "the run never consulted two sources"
        cancelled = explorations.cancel(second["run_id"])
        assert cancelled is not None
        assert cancelled["cancel_requested"] is True
        gate.set()
        final = explorations.wait_for(second["run_id"], 20)
        assert final is not None
        assert final["status"] == "cancelled"
        assert final["sources_completed"] == 2
        assert final["sources_succeeded"] == 2
        # The two remaining sources were never consulted.
        assert len(transport.calls) == before + 2
        # The interrupted search did not overwrite the previous results.
        assert service.get_exploration()["run_id"] == published_run_id
    finally:
        transport.gate = None
        explorations.shutdown()


def test_a_failing_source_is_isolated_and_the_other_offers_are_kept(tmp_path: Path) -> None:
    boards = {"alpha": [posting("a1")], "beta": [posting("b1")]}
    service, transport = service_with(tmp_path, boards, failing=("beta",))
    explorations = ExplorationService(service)
    try:
        state = explorations.start(force=True)
        final = explorations.wait_for(state["run_id"], 20)
        assert final is not None and final["status"] == "completed", final
        assert final["sources_failed"] == 1
        assert final["sources_succeeded"] == 1
        assert final["offers_persisted"] == 1
        assert len(service.list_jobs()) == 1
        failed = [item for item in final["outcomes"] if item["status"] == "error"]
        assert len(failed) == 1
        assert failed[0]["company"] == "Banque fictive"
    finally:
        explorations.shutdown()


def test_a_run_left_open_by_a_previous_process_is_reported_as_interrupted(tmp_path: Path) -> None:
    service, _ = service_with(tmp_path, {"alpha": [posting("a1")]})
    backend = CareerExplorationBackend(service)
    store = ExplorationRunStore(load=backend.load_runs_document, save=backend.save_runs_document)
    store.save(ExplorationRun(run_id="explore_run_synthetic_open", started_at="2026-10-20T10:00:00+00:00"))
    explorations = ExplorationService(service)
    try:
        state = explorations.state("explore_run_synthetic_open")
        assert state is not None
        assert state["status"] == "interrupted"
        assert state["finished_at"]
        assert "arrêtée" in state["message"]
    finally:
        explorations.shutdown()


def test_the_state_of_a_run_survives_a_reload(tmp_path: Path) -> None:
    service, _ = service_with(tmp_path, {"alpha": [posting("a1")]})
    explorations = ExplorationService(service)
    state = explorations.start(force=True)
    final = explorations.wait_for(state["run_id"], 20)
    assert final is not None and final["status"] == "completed"
    explorations.shutdown()

    # A new local process reads the very same state from the local store.
    reloaded = ExplorationService(service)
    try:
        again = reloaded.state(state["run_id"])
        assert again is not None
        assert again["status"] == "completed"
        assert again["offers_persisted"] == final["offers_persisted"]
        assert again["phases"] == final["phases"]
    finally:
        reloaded.shutdown()


def test_a_second_run_is_refused_while_one_is_running(tmp_path: Path) -> None:
    boards = {token: [posting(f"{token}-1")] for token in ("alpha", "beta")}
    service, transport = service_with(tmp_path, boards)
    gate = threading.Event()
    transport.gate = gate
    explorations = ExplorationService(service)
    try:
        state = explorations.start(force=True)
        assert wait_until(lambda: len(transport.calls) >= 1)
        with pytest.raises(UserFacingError):
            explorations.start(force=True)
        gate.set()
        final = explorations.wait_for(state["run_id"], 20)
        assert final is not None and final["status"] == "completed"
    finally:
        transport.gate = None
        explorations.shutdown()


def test_no_exploration_thread_survives_the_shutdown(tmp_path: Path) -> None:
    boards = {token: [posting(f"{token}-1")] for token in ("alpha", "beta")}
    service, transport = service_with(tmp_path, boards)
    gate = threading.Event()
    transport.gate = gate
    explorations = ExplorationService(service)
    state = explorations.start(force=True)
    assert wait_until(lambda: len(transport.calls) >= 1)
    gate.set()
    explorations.shutdown(timeout=10)
    assert explorations.active_run_ids() == []
    final = explorations.state(state["run_id"])
    assert final is not None
    assert final["status"] in {"completed", "cancelled"}


def test_http_endpoints_start_read_and_cancel_a_run(tmp_path: Path) -> None:
    service, transport = service_with(tmp_path, {"alpha": [posting("a1")]})
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.post("/api/career/stage-search/explorations", json={"force": True})
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "running"
        run_id = payload["run_id"]

        state = client.get(f"/api/career/stage-search/explorations/{run_id}")
        assert state.status_code == 200
        assert state.json()["run_id"] == run_id
        for key in ("phase", "sources_total", "sources_completed", "sources_succeeded",
                    "sources_failed", "offers_read", "offers_qualified", "cancel_requested"):
            assert key in state.json()

        assert client.get("/api/career/stage-search/explorations/unknown-run").status_code == 404
        assert client.post("/api/career/stage-search/explorations/unknown-run/cancel").status_code == 404

        deadline = time.monotonic() + 20
        final = state.json()
        while final["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            final = client.get(f"/api/career/stage-search/explorations/{run_id}").json()
        assert final["status"] == "completed", final
        assert final["sources_succeeded"] == 1
        assert final["offers_persisted"] == 1

        listed = client.get("/api/career/stage-search/explorations").json()
        assert any(item["run_id"] == run_id for item in listed["runs"])

        assert client.post("/api/career/stage-search/explorations", json={"force": {"bad": 1}}).status_code == 422


def test_http_cancel_asks_the_running_exploration_to_stop(tmp_path: Path) -> None:
    boards = {token: [posting(f"{token}-1")] for token in ("alpha", "beta")}
    service, transport = service_with(tmp_path, boards)
    gate = threading.Event()
    transport.gate = gate
    with TestClient(create_app(base_dir=tmp_path, career_override=service)) as client:
        response = client.post("/api/career/stage-search/explorations", json={"force": True})
        run_id = response.json()["run_id"]
        assert wait_until(lambda: len(transport.calls) >= 1)
        cancelled = client.post(f"/api/career/stage-search/explorations/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["cancel_requested"] is True
        gate.set()
        deadline = time.monotonic() + 20
        final = cancelled.json()
        while final["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            final = client.get(f"/api/career/stage-search/explorations/{run_id}").json()
        assert final["status"] == "cancelled", final


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : les gardes JavaScript ne sont pas exécutables sur cette machine")


def test_the_frontend_polls_the_real_server_state(tmp_path: Path) -> None:
    html = (ROOT / "career_static" / "index.html").read_text(encoding="utf-8")
    assert "/career-static/js/exploration-progress.js" in html
    module_path = tmp_path / "exploration-progress.js"
    module_path.write_text(MODULE.read_text(encoding="utf-8"), encoding="utf-8")
    script = r'''
const assert = require("assert");
const fs = require("fs");
(0, eval)(fs.readFileSync(MODULE_PATH, "utf8"));
const progress = globalThis.CareerExplorationProgress;
assert.ok(progress, "the polling module must be loadable");
const requests = [];
const running = {
  run_id: "explore_run_synthetic", status: "running", phase: "qualifying",
  phase_order: ["preparing","consulting","normalizing","qualifying","deduplicating","ranking","persisting","completed"],
  phases_completed: 3, sources_total: 21, sources_completed: 8, sources_succeeded: 7,
  sources_failed: 1, offers_read: 340, offers_qualified: 57, cancel_requested: false,
};
const finished = Object.assign({}, running, {status: "completed", phase: "completed", phases_completed: 7});
let calls = 0;
let polls = 0;
global.fetch = (url, init) => {
  requests.push({url: url, method: (init && init.method) || "GET"});
  calls += 1;
  if ((init && init.method) === "POST") {
    return Promise.resolve({ok: true, status: 202, json: () => Promise.resolve(running)});
  }
  polls += 1;
  const body = polls >= 2 ? finished : running;
  return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(body)});
};
(async () => {
  const started = await progress.startExploration({force: true});
  assert.strictEqual(requests[0].url, "/api/career/stage-search/explorations");
  assert.strictEqual(requests[0].method, "POST");
  assert.strictEqual(started.run_id, "explore_run_synthetic");

  const seen = [];
  const handle = progress.poll("explore_run_synthetic", {onState: (state) => seen.push(state), intervalMs: 1});
  const final = await handle.promise;
  assert.strictEqual(requests[1].url, "/api/career/stage-search/explorations/explore_run_synthetic");
  assert.strictEqual(requests[1].method, "GET");
  assert.strictEqual(seen.length, 2);
  assert.strictEqual(final.status, "completed");

  const elements = {label: {textContent: ""}, percent: {textContent: ""}, detail: {textContent: ""}};
  const described = progress.renderState(running, elements);
  assert.strictEqual(described.percent, 43);
  assert.match(elements.label.textContent, /Qualification des offres/);
  assert.match(elements.detail.textContent, /8\/21 sources terminées/);
  assert.match(elements.detail.textContent, /7 réussies/);
  assert.match(elements.detail.textContent, /1 en erreur/);
  assert.match(elements.detail.textContent, /340 annonces lues/);
  assert.match(elements.detail.textContent, /57 offres qualifiées/);
  assert.strictEqual(progress.isTerminal(final), true);
  assert.strictEqual(progress.isTerminal(running), false);
})().catch((error) => { console.error(error); process.exit(1); });
'''.replace("MODULE_PATH", json.dumps(str(module_path)))
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
