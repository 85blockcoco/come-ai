"""Real-service evidence, using only bounded synthetic inputs and no network."""

from __future__ import annotations

from dataclasses import replace
import json
import socket

import pytest

from evals.come_ai_target import ComeAITarget, NetworkAccessBlocked, load_real_cases
from evals.runner import execute_case, run_suite
from evals.schema import load_cases
from hybrid_chat import HybridChatService
from workspace_core import LocalTools


CASES = {case.id: case for case in load_real_cases()}


@pytest.mark.parametrize("case_id", [f"REAL-{number:03d}" for number in range(1, 10)])
def test_supported_handlers_execute_real_services(case_id):
    target = ComeAITarget()
    result = execute_case(CASES[case_id], target)
    assert result.outcome == "real", (result.reason, result.checks)
    assert result.execution_kind == "real"
    assert result.passed is True
    assert result.trace
    assert result.observation["usage"]["network_attempts"] == 0
    assert result.observation["usage"]["generation_requests"] == 0
    assert target._root is not None and not target._root.exists()
    assert result.trace[-1]["synthetic_only"] is True
    assert result.trace[-1]["model_generation_measured"] is False


def test_calculation_uses_service_and_cannot_echo_expected(monkeypatch):
    calls = []
    original = HybridChatService.ask

    def recording_ask(self, *args, **kwargs):
        calls.append(kwargs["message"])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HybridChatService, "ask", recording_ask)
    case = replace(CASES["REAL-001"], expected={"structured": {"value": -999}})
    output = ComeAITarget().run(case)
    assert calls == ["Calcule 350 * 1.20"]
    assert output.observation["structured"]["value"] == 420.0
    assert output.trace[0]["component"] == "HybridChatService"
    assert output.trace[0]["result"]["tool_events"][0]["tool"] == "calculate_expression"


def test_memory_trace_retains_native_citation_and_normalizes_runtime_ids():
    output = ComeAITarget().run(CASES["REAL-003"])
    imported = next(event for event in output.trace if event["method"] == "import_text")
    searched = next(event for event in output.trace if event["component"] == "PersonalMemoryStore" and event["method"] == "search")
    source_id = imported["result"]["source_id"]
    citation = searched["result"]["results"][0]["citation"]
    assert source_id == "SYNTHETIC-COURSE"
    assert citation["source_id"] == source_id
    assert citation["line_start"] == citation["line_end"] == 1
    assert "Cours synthétique de finance" in citation["label"]
    assert output.observation["citations"][0]["quote"] == CASES["REAL-003"].input["sources"][0]["text"]


def test_table_trace_proves_actual_tools_are_called(monkeypatch):
    calls = []
    original_inspect = LocalTools.inspect_file
    original_analyze = LocalTools.analyze_table

    def recording_inspect(self, *args, **kwargs):
        calls.append("inspect_file")
        return original_inspect(self, *args, **kwargs)

    def recording_analyze(self, *args, **kwargs):
        calls.append("analyze_table")
        return original_analyze(self, *args, **kwargs)

    monkeypatch.setattr(LocalTools, "inspect_file", recording_inspect)
    monkeypatch.setattr(LocalTools, "analyze_table", recording_analyze)
    output = ComeAITarget().run(CASES["REAL-004"])
    assert calls == ["inspect_file", "analyze_table"]
    analyzed = next(event for event in output.trace if event["component"] == "LocalTools" and event["method"] == "analyze_table")
    assert analyzed["result"]["numeric_statistics"]["revenus"]["sum"] == 220.0
    assert output.observation["structured"]["source_unchanged"] is True


def test_write_gate_never_invokes_workbook_writer(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("The gated workbook writer must not run.")

    monkeypatch.setattr(LocalTools, "create_analysis_workbook", forbidden)
    result = execute_case(CASES["REAL-006"], ComeAITarget())
    assert result.outcome == "real"
    assert result.passed is True
    assert not any(event["component"] == "LocalTools" and event["method"] == "create_analysis_workbook"
                   for event in result.trace)
    assert any(event["component"] == "LocalOrchestrator" and event.get("tool") == "create_analysis_workbook"
               and event["status"] == "needs_confirmation" for event in result.trace)


def test_all_real_handlers_ignore_dotenv_credentials_and_private_memory_override(tmp_path, monkeypatch):
    private_store = tmp_path / "private-store-must-not-exist"
    monkeypatch.setenv("COME_AI_MEMORY_DIR", str(private_store))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-sentinel-not-a-key")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No .env or credentials may be read by this suite.")

    monkeypatch.setattr("workspace_core.read_dotenv", forbidden)
    monkeypatch.setattr("workspace_core.AppConfig.load", forbidden)
    monkeypatch.setattr("hybrid_chat.read_dotenv", forbidden)
    monkeypatch.setattr("hybrid_chat._credential", forbidden)
    target = ComeAITarget()
    run = run_suite(target, list(CASES.values()), persist=False)
    assert run["metrics"]["cases_passed"] == 15
    assert run["metrics"]["cases_unsupported"] == 1
    assert not private_store.exists()
    assert "synthetic-sentinel-not-a-key" not in json.dumps(run)


def test_network_boundary_blocks_real_socket_operations_without_packets():
    target = ComeAITarget()
    with target.network_boundary():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with pytest.raises(NetworkAccessBlocked):
                client.connect(("127.0.0.1", 9))
        with pytest.raises(NetworkAccessBlocked):
            socket.getaddrinfo("blocked.synthetic.invalid", 443)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            with pytest.raises(NetworkAccessBlocked):
                client.sendto(b"synthetic", ("127.0.0.1", 9))
    assert target.network_attempts == 3


def test_unsupported_generation_and_core_contract_are_never_executed(monkeypatch):
    target = ComeAITarget()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unsupported cases must not execute.")

    monkeypatch.setattr(target, "_execute", forbidden)
    for case in [CASES["REAL-013"], load_cases()[0]]:
        result = execute_case(case, target)
        assert result.outcome == "unsupported"
        assert result.passed is None
        assert result.trace == []


def test_real_privacy_refusal_case_blocks_network_and_is_application_verified():
    case = CASES["REAL-009"]
    target = ComeAITarget()
    result = execute_case(case, target)
    assert case.application_verified is True
    assert result.outcome == "real"
    assert result.passed is True, (result.reason, result.checks)
    assert result.observation["usage"] == {
        "api_calls": 0, "generation_requests": 0, "network_attempts": 0,
    }
    assert any(event.get("status") == "refused" for event in result.trace)


def test_public_ats_connector_application_verified_path_is_synthetic_and_no_network():
    case = CASES["REAL-014"]
    target = ComeAITarget()
    result = execute_case(case, target)
    assert case.application_verified is True
    assert result.outcome == "real"
    assert result.passed is True, (result.reason, result.checks)
    assert result.observation["structured"]["synthetic_fixture"] is True
    assert result.observation["usage"]["network_attempts"] == 0


def test_execution_error_contains_type_without_private_exception_payload(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("synthetic-private-exception-sentinel")

    monkeypatch.setattr(HybridChatService, "ask", broken)
    result = execute_case(CASES["REAL-001"], ComeAITarget())
    assert result.outcome == "execution_error"
    assert result.passed is False
    assert result.reason == "RuntimeError"
    assert "synthetic-private-exception-sentinel" not in json.dumps(result.to_dict())


def test_incorrect_real_result_is_distinct_from_execution_error():
    case = CASES["REAL-001"]
    raw = json.loads(json.dumps(case.raw))
    raw["acceptance"][0]["value"] = 421.0
    incorrect_case = replace(case, raw=raw, acceptance=raw["acceptance"])
    result = execute_case(incorrect_case, ComeAITarget())
    assert result.outcome == "incorrect"
    assert result.execution_kind == "real"
    assert result.observation["structured"]["value"] == 420.0
    assert result.checks[0]["ok"] is False


def test_memory_and_csv_traces_are_deterministic_after_workspace_cleanup():
    target = ComeAITarget()
    for case_id in ("REAL-003", "REAL-004"):
        first = target.run(CASES[case_id])
        first_root = target._root
        second = target.run(CASES[case_id])
        assert first.trace == second.trace
        assert first.observation == second.observation
        assert first_root is not None and not first_root.exists()
        assert str(first_root) not in json.dumps(first.trace)


def test_fixture_path_rejection_cannot_create_external_file(tmp_path):
    case = CASES["REAL-004"]
    external = tmp_path / "must-not-exist.csv"
    raw = json.loads(json.dumps(case.raw))
    raw["input"]["file"]["name"] = str(external)
    bad_case = replace(case, raw=raw, input=raw["input"])
    result = execute_case(bad_case, ComeAITarget())
    assert result.outcome == "execution_error"
    assert result.reason == "ValueError"
    assert not external.exists()

