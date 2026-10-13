"""Injected model/diagnostics exercise real staging, never real APIs or keys.

Diagnostic reports are fixtures, not proof that model-produced code ran. The
separate real-workflow test covers the operating-system sandbox.
"""

import json

import pytest

from devkit.evolution import EvolutionEngine, EvolutionError, evaluate_candidate
from devkit.evolution_providers import ProviderSettings, ProviderUnavailable
from devkit.exporting import source_fingerprint
from devkit.proposals import CodeProposal


ORIGINAL = "def answer():\n    return 1\n"
CORRECT = "def answer():\n    return 2\n"
WRONG = "def answer():\n    return 99\n"


class FixtureProvider:
    is_remote = False

    def __init__(self, replies, callback=None):
        self.replies = list(replies)
        self.contexts = []
        self.callback = callback
        self.last_usage = None

    def propose(self, context):
        self.contexts.append(context)
        if self.callback:
            self.callback()
        self.last_usage = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20,
                           "latency_ms": 25, "generation_requests": 1}
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "fictional-project"
    root.mkdir()
    (root / "core.py").write_text(ORIGINAL, encoding="utf-8")
    (root / "README.md").write_text("Fictional maintenance fixture\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/test_core.py").write_text("from core import answer\ndef test_answer():\n    assert answer() == 2\n", encoding="utf-8")
    (root / ".env").write_text("PRIVATE_VALUE=fictional\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data/private.txt").write_text("fictional private data", encoding="utf-8")
    return root


def fixture_report(root, *, status="passed", sandbox=True, receipt=True, count=3):
    failed = 1 if status == "failed" else 0
    return {"status": status, "source_fingerprint": source_fingerprint(root), "sandbox_used": sandbox,
            "pytest_receipt_verified": receipt, "tests_executed": count, "tests_passed": count - failed,
            "tests_failed": failed, "tests_skipped": 0, "tests_collected": count, "collection_errors": 0,
            "checks": [{"name": "pytest", "status": status, "output": "core.py:2 assertion failed" if failed else "fixture tests passed"}]}


def make_engine(project, tmp_path, provider, *, candidate_report=None):
    diagnostics = []
    factories = []

    def factory(root, settings):
        assert root == project
        factories.append(settings)
        return provider

    def diagnostic(root, **kwargs):
        diagnostics.append((root, kwargs))
        if root == project:
            assert kwargs["require_sandbox"] is False
            return fixture_report(root, status="failed", sandbox=False, receipt=False)
        assert kwargs["require_sandbox"] is True
        assert not (root / ".env").exists()
        assert not (root / "data").exists()
        if candidate_report:
            return candidate_report(root)
        return fixture_report(root, status="passed" if (root / "core.py").read_text() == CORRECT else "failed")

    engine = EvolutionEngine(project, tmp_path / "workshop", provider_factory=factory, diagnostic_runner=diagnostic)
    return engine, diagnostics, factories


def add_task(engine, files=None):
    return engine.store.add_task("Correct answer", "Make answer return 2.", files or ["core.py"], "Keep the full test suite.")


def settings(**kwargs):
    return ProviderSettings("ollama", "fixture-local", **kwargs)


def test_failed_first_candidate_gets_feedback_second_passes_without_touching_main(project, tmp_path):
    provider = FixtureProvider([CodeProposal(files={"core.py": WRONG}), CodeProposal(files={"core.py": CORRECT})])
    engine, diagnostics, _ = make_engine(project, tmp_path, provider)
    task = add_task(engine)
    result = engine.run_task(task["task_id"], settings(), max_attempts=2, max_requests=2)
    assert result["status"] == "needs_review"
    assert result["metrics"]["requests"] == 2
    assert result["metrics"]["attempts"] == 2
    assert result["metrics"]["total_tokens"] == 40
    assert len(diagnostics) == 3
    assert provider.contexts[1].issue["previous_attempt"]["status"] == "failed"
    assert provider.contexts[1].sources["core.py"] == ORIGINAL
    assert (project / "core.py").read_text() == ORIGINAL
    assert (project / "data/private.txt").read_text() == "fictional private data"
    candidate = engine.patches.candidate_path(result["candidate_id"])
    assert (candidate / "core.py").read_text() == CORRECT
    assert (candidate / "tests/test_core.py").read_text() == (project / "tests/test_core.py").read_text()
    preview = engine.patches.preview(result["candidate_id"])
    assert preview["validated"] is True
    assert "-    return 1\n+    return 2\n" in preview["diff"]
    persisted = json.loads((engine.evolution_dir / "runs" / result["run_id"] / "attempt-2.json").read_text())
    assert persisted["source_fingerprint"] == source_fingerprint(candidate)
    assert persisted["pytest_receipt_verified"] is True
    assert engine.store.get_task(task["task_id"])["status"] == "needs_review"


def test_request_budget_stops_invalid_proposals_without_extra_generation(project, tmp_path):
    provider = FixtureProvider([CodeProposal(files={"README.md": "Out of selection\n"}), CodeProposal(files={"core.py": CORRECT})])
    engine, diagnostics, _ = make_engine(project, tmp_path, provider)
    result = engine.run_task(add_task(engine)["task_id"], settings(), max_attempts=3, max_requests=1)
    assert result["status"] == "failed"
    assert result["candidate_id"] is None
    assert len(provider.contexts) == 1
    assert len(diagnostics) == 1
    assert result["metrics"]["requests"] == 1
    assert (project / "README.md").read_text() == "Fictional maintenance fixture\n"


def test_quota_waits_for_explicit_action_without_retry(project, tmp_path):
    provider = FixtureProvider([ProviderUnavailable("Fictional quota exhausted.", "quota"), CodeProposal(files={"core.py": CORRECT})])
    engine, diagnostics, _ = make_engine(project, tmp_path, provider)
    task = add_task(engine)
    result = engine.run_task(task["task_id"], settings(), max_attempts=3, max_requests=3)
    assert result["status"] == "waiting_provider"
    assert "quota" in result["reason"]
    assert len(provider.contexts) == 1
    assert len(diagnostics) == 1
    assert engine.run_next(settings())["status"] == "idle"
    assert len(provider.contexts) == 1


def test_missing_provider_configuration_calls_no_model_or_diagnostics(project, tmp_path):
    calls = []

    def missing(root, settings):
        calls.append("configuration")
        raise ProviderUnavailable("Fictional missing key.", "missing_configuration")

    def forbidden(*args, **kwargs):
        pytest.fail("Diagnostics must not run when no provider is configured.")

    engine = EvolutionEngine(project, tmp_path / "workshop", provider_factory=missing, diagnostic_runner=forbidden)
    result = engine.run_task(add_task(engine)["task_id"], ProviderSettings("gemini", "gemini-2.5-flash", allow_remote=True))
    assert result["status"] == "waiting_provider"
    assert result["metrics"]["requests"] == 0
    assert calls == ["configuration"]


def test_remote_provider_needs_explicit_opt_in_before_generation(project, tmp_path):
    provider = FixtureProvider([CodeProposal(files={"core.py": CORRECT})])
    provider.is_remote = True
    engine, diagnostics, _ = make_engine(project, tmp_path, provider)
    result = engine.run_task(add_task(engine)["task_id"], ProviderSettings("gemini", "gemini-2.5-flash"))
    assert result["status"] == "waiting_provider"
    assert len(provider.contexts) == 0
    assert diagnostics == []


def test_source_change_during_generation_invalidates_proposal(project, tmp_path):
    def edit():
        (project / "README.md").write_text("A concurrent user edit\n", encoding="utf-8")

    provider = FixtureProvider([CodeProposal(files={"core.py": CORRECT})], callback=edit)
    engine, diagnostics, _ = make_engine(project, tmp_path, provider)
    result = engine.run_task(add_task(engine)["task_id"], settings())
    assert result["status"] == "failed"
    assert result["candidate_id"] is None
    assert len(diagnostics) == 1
    assert (project / "core.py").read_text() == ORIGINAL
    assert (project / "README.md").read_text() == "A concurrent user edit\n"


@pytest.mark.parametrize("change", [{"sandbox_used": False}, {"pytest_receipt_verified": False},
                                    {"source_fingerprint": "invalid"}, {"tests_executed": 0},
                                    {"tests_executed": 2, "tests_passed": 2}])
def test_candidate_requires_isolation_receipt_fingerprint_and_full_baseline(project, tmp_path, change):
    provider = FixtureProvider([CodeProposal(files={"core.py": CORRECT})])
    engine, _, _ = make_engine(project, tmp_path, provider, candidate_report=lambda root: {**fixture_report(root), **change})
    result = engine.run_task(add_task(engine)["task_id"], settings(), max_attempts=1, max_requests=1)
    assert result["status"] == "failed"
    assert engine.patches.preview(result["candidate_id"])["validated"] is False
    assert (project / "core.py").read_text() == ORIGINAL


def test_cancellation_before_setup_has_no_side_effects_or_generation(project, tmp_path):
    provider = FixtureProvider([CodeProposal(files={"core.py": CORRECT})])
    engine, diagnostics, factories = make_engine(project, tmp_path, provider)
    result = engine.run_task(add_task(engine)["task_id"], settings(), is_cancelled=lambda: True)
    assert result["status"] == "cancelled"
    assert not provider.contexts and not factories and not diagnostics
    assert (project / "core.py").read_text() == ORIGINAL


def test_execution_lock_blocks_a_second_engine(project, tmp_path):
    provider = FixtureProvider([])
    engine, _, _ = make_engine(project, tmp_path, provider)
    other = EvolutionEngine(project, engine.storage_root)
    with engine.execution_lock():
        with pytest.raises(EvolutionError, match="déjà en cours"):
            other.run_next(settings())


@pytest.mark.parametrize("kwargs", [{"max_requests": 0}, {"max_requests": 4}, {"max_attempts": True},
                                    {"session_timeout_seconds": float("inf")}])
def test_invalid_budget_refused_before_claiming_task(project, tmp_path, kwargs):
    provider = FixtureProvider([])
    engine, diagnostics, factories = make_engine(project, tmp_path, provider)
    task = add_task(engine)
    with pytest.raises(EvolutionError):
        engine.run_task(task["task_id"], settings(), **kwargs)
    assert engine.store.get_task(task["task_id"])["status"] == "queued"
    assert not factories and not diagnostics


def test_diagnostic_queue_import_requires_current_failures_and_deduplicates(project, tmp_path):
    engine, _, _ = make_engine(project, tmp_path, FixtureProvider([]))
    passing = fixture_report(project)
    assert engine.import_diagnostic_issue(passing) is None
    report = fixture_report(project, status="failed", sandbox=False, receipt=False)
    first = engine.import_diagnostic_issue(report)
    assert first["selected_files"] == ["core.py"]
    assert engine.import_diagnostic_issue(report)["task_id"] == first["task_id"]
    assert engine.import_diagnostic_issue({**report, "source_fingerprint": "stale"}) is None
    assert len(engine.store.list_tasks()) == 1


def test_test_file_changes_require_integrity_review_even_with_passing_tests(project):
    report = fixture_report(project)
    result = evaluate_candidate(report, report, [{"path": "tests/test_core.py", "operation": "modify"}])
    assert result["status"] == "needs_review"
    assert result["test_integrity_review_required"] is True
    assert result["auto_release_eligible"] is False
    assert result["main_application_modified"] is False
