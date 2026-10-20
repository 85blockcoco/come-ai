"""Fictitious model transports verify real routing/accounting policies."""
from devkit.evolution_providers import ProviderSettings, ProviderUnavailable
from devkit.intelligence_router import RoutedCorrectionProvider
from devkit.proposals import CodeProposal, ProposalContext
import pytest


class Catalogue:
    def eligible(self, provider): return [{"model_id": "gemini-3.8-flash"}]
    def choose_model(self, provider, requested="auto", exclude_models=()):
        return "gemini-3.8-flash" if "gemini-3.8-flash" not in exclude_models else "gemini-3.6-flash"


def test_verified_same_provider_fallback_respects_budget_and_records_real_calls(tmp_path):
    calls = []
    class Adapter:
        def __init__(self, settings):
            self.model = settings.model
            self.last_usage = {}
        def propose(self, context):
            calls.append(self.model)
            self.last_usage = {"generation_requests": 1, "latency_ms": 2, "input_tokens": None, "output_tokens": None, "total_tokens": None}
            if len(calls) == 1:
                raise ProviderUnavailable("fictitious outage", "transient", http_status=503)
            self.last_usage.update(input_tokens=12, output_tokens=8, total_tokens=20)
            return CodeProposal(files={"core.py": "value = 42\n"})
    settings = ProviderSettings("gemini", "auto", allow_remote=True, gemini_free_project_confirmed=True)
    router = RoutedCorrectionProvider(tmp_path, settings, catalog=Catalogue(), factory=lambda root, cfg: Adapter(cfg))
    router.remaining_requests = 2
    proposal = router.propose(ProposalContext({"title": "Fixture"}, {"core.py": "value = 1\n"}))
    assert proposal.files["core.py"] == "value = 42\n"
    assert calls == ["gemini-3.8-flash", "gemini-3.6-flash"]
    assert router.last_usage["generation_requests"] == 2
    assert router.last_usage["total_tokens"] == 20
    assert len(router.ledger.list_events()) == 2


@pytest.mark.parametrize("status,category", [(401, "authentication"), (403, "authentication"), (429, "quota")])
def test_auth_and_quota_never_rotate_models(tmp_path, status, category):
    calls = []
    class Adapter:
        last_usage = {}
        def propose(self, context):
            calls.append(True)
            self.last_usage = {"generation_requests": 1, "latency_ms": 1}
            raise ProviderUnavailable("fictitious refusal", category, http_status=status)
    router = RoutedCorrectionProvider(tmp_path, ProviderSettings("gemini", "auto", True, True), catalog=Catalogue(), factory=lambda root, cfg: Adapter())
    router.remaining_requests = 3
    with pytest.raises(ProviderUnavailable):
        router.propose(ProposalContext({}, {"core.py": "value = 1\n"}))
    assert len(calls) == 1


def test_missing_configuration_dispatches_no_model_call(tmp_path):
    with pytest.raises(ProviderUnavailable, match="clé"):
        RoutedCorrectionProvider(tmp_path, ProviderSettings("gemini", "auto", True, True), catalog=Catalogue())
