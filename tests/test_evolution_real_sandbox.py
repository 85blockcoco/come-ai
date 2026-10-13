"""Actual diagnostics/staging with fake generation; not a real-model claim."""
import os
import sys
from pathlib import Path
import pytest

from devkit.evolution import EvolutionEngine
from devkit.evolution_manager import EvolutionManager
from devkit.proposals import CodeProposal


@pytest.mark.skipif(sys.platform != "darwin" or os.environ.get("COME_AI_DIAGNOSTICS_OFFLINE") == "1", reason="La vraie sandbox de ce scénario se vérifie séparément, hors d’une sandbox déjà active")
def test_demo_uses_real_sandbox_and_preserves_immutable_acceptance_tests(tmp_path, monkeypatch):
    class FakeGeneration:
        is_remote = False
        provider_id = "fixture_local"
        model_id = "fixture_generator"
        last_usage = {}
        def propose(self, context):
            assert list(context.sources) == ["error_redaction.py"]
            corrected = context.sources["error_redaction.py"].replace("text = str(error)", "text = str(error)\n    text = re.sub(r'sk-or-v1-[A-Za-z0-9_-]+', '[masked]', text)")
            self.last_usage = {"generation_requests": 1, "latency_ms": 1}
            return CodeProposal(files={"error_redaction.py": corrected})
    monkeypatch.setattr("devkit.intelligence_router.create_routed_provider", lambda root, settings: FakeGeneration())
    def real_engine(root, storage, **kwargs):
        kwargs["python_executable"] = Path(sys.executable)
        return EvolutionEngine(root, storage, **kwargs)
    monkeypatch.setattr("devkit.evolution_manager.EvolutionEngine", real_engine)
    manager = EvolutionManager(tmp_path, tmp_path / ".devkit")
    result = manager.run_demo(max_requests=1)
    assert result["status"] == "needs_review", result
    assert result["main_application_modified"] is False
    assert result["model"] == "fixture_generator"
    assert result["metrics"]["requests"] == 1
    assert result["candidate_id"]
    assert "sk-or-v1-" in result["diff"]
    baseline = [event for event in result["events"] if event["phase"] == "baseline" and event["status"] == "failed"]
    assert baseline[0]["data"]["tests_failed"] == 1
    verified = [event for event in result["events"] if event["phase"] == "validation"]
    assert verified[-1]["data"]["tests_passed"] == 3
