"""Synthetic routing tests: no key, no provider, no personal file is used."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from free_ai_router import PricingStatus, QuotaStatus, RouteStatus, RoutingMode
from intelligence_bridge import (
    BridgeFacts,
    DeclaredModel,
    IntelligenceBridge,
    IntelligenceBridgeError,
    QualityObservation,
    QuotaObservation,
    declared_from_catalogue,
    declared_from_eligible,
    declared_local_model,
    observe_quality,
    observe_quotas,
    router_capabilities,
)


class Observed:
    """Minimal structural stand-in for ``usage_ledger.UsageEvent``."""

    def __init__(self, provider, outcome, occurred_at, model="unit-model", error_category=None, latency_ms=None, retry_after_seconds=None):
        self.provider = provider
        self.model = model
        self.outcome = outcome
        self.occurred_at = occurred_at
        self.error_category = error_category
        self.latency_ms = latency_ms
        self.retry_after_seconds = retry_after_seconds


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def free_gemini(model_id="gemini-3.8-flash"):
    return DeclaredModel(
        provider="gemini",
        model_id=model_id,
        capabilities=frozenset({"code", "text"}),
        pricing=PricingStatus.ZERO_CONFIRMED,
        price_evidence="conservative_allowlist_verified",
    )


def facts(*declared):
    return BridgeFacts(declared=tuple(declared))


def test_automatic_prefers_local_then_cloud_and_offline_keeps_local_only():
    bridge = IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                                allowed_providers=("ollama", "gemini"), max_fallbacks=2)
    automatic = bridge.decide("Bonjour", mode=RoutingMode.AUTOMATIC)
    assert automatic.status is RouteStatus.SELECTED
    assert automatic.primary is not None and automatic.primary.is_local
    assert bridge.ordered_providers(automatic) == ("ollama_local", "gemini")

    offline = bridge.decide("Bonjour", mode=RoutingMode.OFFLINE)
    assert offline.primary is not None and offline.primary.is_local
    assert bridge.ordered_providers(offline) == ("ollama_local",)
    # Every cloud model is refused with a named reason, never silently dropped.
    codes = {evaluation.model.model_id: {code.value for code in evaluation.rejection_codes}
             for evaluation in offline.evaluations if not evaluation.accepted}
    assert codes == {"gemini-3.8-flash": {"offline_requires_local"}}


def test_unconfirmed_zero_price_and_unknown_price_are_refused_by_the_router_itself():
    bridge = IntelligenceBridge(
        facts(
            declared_local_model("qwen3.5:2b-q4_K_M"),
            DeclaredModel(provider="gemini", model_id="gemini-3.8-flash",
                          capabilities=frozenset({"code", "text"}), pricing=PricingStatus.ZERO_UNCONFIRMED),
            DeclaredModel(provider="openrouter", model_id="vendor/paid-model",
                          capabilities=frozenset({"code", "text"}), pricing=PricingStatus.UNKNOWN),
            DeclaredModel(provider="openrouter", model_id="vendor/priced-model",
                          capabilities=frozenset({"code", "text"}), pricing=PricingStatus.NON_ZERO),
        ),
        allowed_providers=("ollama", "gemini", "openrouter"),
    )
    decision = bridge.decide("Bonjour", mode=RoutingMode.PERFORMANCE)
    codes = {evaluation.model.model_id: {code.value for code in evaluation.rejection_codes}
             for evaluation in decision.evaluations if not evaluation.accepted}
    # The paid model is named, priced and refused: no silent substitution.
    assert codes["vendor/priced-model"] == {"price_not_zero"}
    assert codes["vendor/paid-model"] == {"pricing_unknown"}
    assert "gemini-3.8-flash" in codes  # zero_unconfirmed, still refused
    assert decision.primary is not None and decision.primary.model_id == "qwen3.5:2b-q4_K_M"


def test_confirmed_zero_price_without_evidence_cannot_even_be_declared():
    with pytest.raises(IntelligenceBridgeError, match="preuve"):
        DeclaredModel(provider="gemini", model_id="gemini-3.8-flash", pricing=PricingStatus.ZERO_CONFIRMED)


def test_paid_model_is_not_selected_even_when_it_is_the_only_declared_model():
    bridge = IntelligenceBridge(
        facts(DeclaredModel(provider="openrouter", model_id="vendor/priced-model",
                            capabilities=frozenset({"code", "text"}), pricing=PricingStatus.NON_ZERO)),
        allowed_providers=("openrouter",),
    )
    decision = bridge.decide("Bonjour", mode=RoutingMode.PERFORMANCE)
    assert decision.status is RouteStatus.DENIED
    assert decision.primary is None
    assert decision.public_dict()["status"] == "denied"
    assert "price_not_zero" in json.dumps(decision.public_dict()["rejections"])


def test_quota_cooldown_removes_provider_without_inventing_a_remaining_count():
    exhausted = IntelligenceBridge(
        BridgeFacts(
            declared=(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
            quotas={"gemini": QuotaObservation(provider="gemini", status=QuotaStatus.EXHAUSTED,
                                               remaining_requests=0, reset_hint="2026-10-13T13:00:00+00:00",
                                               source="observed_error_category_quota_within_900s",
                                               blocked_until=NOW + timedelta(minutes=45))},
        ),
        allowed_providers=("ollama", "gemini"),
    )
    assert exhausted.ordered_providers(exhausted.decide("Bonjour")) == ("ollama_local",)

    # Once the provider reported nothing, nothing is asserted either way.
    unknown = IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                                  allowed_providers=("ollama", "gemini"))
    decision = unknown.decide("Bonjour")
    assert {row.provider.value for row in decision.quota_disclosures} == {"gemini", "ollama_local"}
    gemini_disclosure = next(row.public_dict() for row in decision.quota_disclosures if row.provider.value == "gemini")
    assert gemini_disclosure["status"] == "unknown"
    assert gemini_disclosure["known"] is False
    assert gemini_disclosure["remaining_requests"] is None
    assert "aucune" in gemini_disclosure["message"]


def test_observed_quota_failure_creates_a_bounded_cooldown_only():
    events = [Observed("gemini", "failed", (NOW - timedelta(minutes=5)).isoformat(), error_category="quota")]
    observations = observe_quotas(events, now=NOW)
    assert observations["gemini"].status.value == "exhausted"
    assert observations["gemini"].blocks_now is True
    assert observations["gemini"].remaining_requests is None
    bridge = IntelligenceBridge(
        BridgeFacts(declared=(declared_local_model("local"), free_gemini()), quotas=observations),
        allowed_providers=("ollama", "gemini"),
    )
    disclosure = bridge.registry.provider_state("gemini").quota.public_dict()
    assert disclosure["status"] == "exhausted"
    assert disclosure["remaining_requests"] is None
    # A cooldown that already elapsed stops blocking, and says nothing more.
    assert observe_quotas(events, now=NOW + timedelta(hours=2)) == {}


def test_provider_retry_after_is_preferred_over_the_local_default():
    events = [Observed("openrouter", "failed", (NOW - timedelta(minutes=2)).isoformat(),
                       error_category="quota", retry_after_seconds=3600)]
    observations = observe_quotas(events, now=NOW)
    assert "within_3600s" in observations["openrouter"].source
    assert observe_quotas(events, now=NOW + timedelta(minutes=45))["openrouter"].blocks_now is True


def test_observed_reliability_promotes_a_measured_model_over_an_unmeasured_one():
    stamp = (NOW - timedelta(hours=1)).isoformat()
    quality = observe_quality(
        [Observed("gemini", "succeeded", stamp, model="gemini-3.8-flash", latency_ms=120)] * 4
        + [Observed("ollama", "failed", stamp, model="qwen3.5:2b-q4_K_M", latency_ms=900)] * 4,
        now=NOW,
    )
    assert quality[("gemini", "gemini-3.8-flash")].quality_rank == 100
    assert quality[("ollama_local", "qwen3.5:2b-q4_K_M")].quality_rank == 0

    bridge = IntelligenceBridge(
        BridgeFacts(declared=(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()), quality=quality),
        allowed_providers=("ollama", "gemini"),
    )
    # In performance mode the measured model wins, and the reason stays a measurement.
    decision = bridge.decide("Bonjour", mode=RoutingMode.PERFORMANCE)
    assert decision.primary is not None and decision.primary.model_id == "gemini-3.8-flash"
    assert any("quality_rank" in line for line in decision.explanations)


def test_unmeasured_models_stay_neutral_and_are_never_promoted():
    quality = observe_quality([Observed("gemini", "succeeded", (NOW - timedelta(hours=1)).isoformat(),
                                        model="gemini-3.8-flash")], now=NOW)
    assert quality[("gemini", "gemini-3.8-flash")].quality_rank == 50
    assert quality[("gemini", "gemini-3.8-flash")].measured is False

    bridge = IntelligenceBridge(
        BridgeFacts(declared=(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()), quality=quality),
        allowed_providers=("ollama", "gemini"),
    )
    # One single success is not a benchmark: the conservative local order stands.
    assert bridge.decide("Bonjour", mode=RoutingMode.PERFORMANCE).primary.model_id == "qwen3.5:2b-q4_K_M"


def test_stale_events_are_ignored_rather_than_extrapolated():
    quality = observe_quality([Observed("gemini", "succeeded", "2026-01-01T00:00:00+00:00")], now=NOW)
    assert quality == {}
    assert observe_quality([Observed("gemini", "succeeded", "une date illisible")], now=NOW) == {}
    assert observe_quality([Observed("", "succeeded", NOW.isoformat())], now=NOW) == {}


def test_reasoning_capabilities_are_derived_but_vision_never_is():
    derived = router_capabilities(["text", "code"])
    # Data handed over as text really can be reasoned about...
    assert {"analysis", "spreadsheets", "documents"} <= derived
    # ...but no ingestion capability is invented from the same two names.
    assert "vision" not in derived
    assert "long_context" not in derived
    assert "structured_output" not in derived

    bridge = IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                                allowed_providers=("ollama", "gemini"))
    analysis = bridge.decide("Analyse ce tableau excel", requested_capabilities=("spreadsheets",))
    assert analysis.status is RouteStatus.SELECTED
    vision = bridge.decide("Décris cette image", requested_capabilities=("vision",))
    assert vision.status is RouteStatus.DENIED
    assert vision.primary is None


def test_local_execution_is_the_only_free_price_that_needs_no_provider():
    declared = declared_local_model("qwen3.5:2b-q4_K_M")
    assert declared.pricing is PricingStatus.ZERO_CONFIRMED
    assert declared.price_evidence  # proof is mandatory, never assumed


def test_a_bridge_without_allowed_provider_or_without_model_refuses_to_exist():
    with pytest.raises(IntelligenceBridgeError, match="fournisseur autorisé"):
        IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M")), allowed_providers=())
    with pytest.raises(IntelligenceBridgeError, match="Aucun modèle"):
        IntelligenceBridge(facts(), allowed_providers=("ollama",))
    with pytest.raises(IntelligenceBridgeError, match="déclaré deux fois"):
        IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), declared_local_model("qwen3.5:2b-q4_K_M")),
                           allowed_providers=("ollama",))


def test_public_state_exposes_measurements_without_ever_naming_a_model_prompt():
    events = [Observed("gemini", "failed", NOW.isoformat(), model="gemini-3.8-flash", error_category="quota", latency_ms=10)]
    bridge = IntelligenceBridge(
        BridgeFacts(declared=(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                    quality=observe_quality(events, now=NOW), quotas=observe_quotas(events, now=NOW)),
        allowed_providers=("ollama", "gemini"),
    )
    state = bridge.public_state()
    assert state["allowed_providers"] == ["gemini", "ollama_local"]
    assert state["quality"]["gemini/gemini-3.8-flash"]["measured"] is False
    assert "never a claimed reasoning benchmark" in state["measurement_note"]
    assert "key" not in json.dumps(state).casefold()


def test_unbounded_fallbacks_are_clamped_by_the_policy():
    bridge = IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                                allowed_providers=("ollama", "gemini"), max_fallbacks=0)
    assert bridge.decide("Bonjour").fallbacks == ()


def test_deterministic_decision_for_the_same_facts():
    bridge = IntelligenceBridge(facts(declared_local_model("qwen3.5:2b-q4_K_M"), free_gemini()),
                                allowed_providers=("ollama", "gemini"))
    first = bridge.decide("Bonjour")
    second = bridge.decide("Bonjour")
    assert first.public_dict() == second.public_dict()
    assert first.explanations == second.explanations


def test_zero_retry_after_cancels_an_older_cooldown_without_inventing_a_new_one():
    events = [
        Observed("gemini", "failed", (NOW - timedelta(seconds=10)).isoformat(), error_category="quota"),
        Observed("gemini", "failed", NOW.isoformat(), error_category="quota", retry_after_seconds=0),
    ]
    assert observe_quotas(events, now=NOW, quota_cooldown=timedelta(hours=1)) == {}


def test_aliases_combine_measured_local_quality_and_apply_it_to_the_router():
    events = [Observed(provider, "succeeded", NOW.isoformat(), model="local")
              for provider in ("ollama", "ollama_local", "OLLAMA")]
    quality = observe_quality(events, now=NOW)
    assert list(quality) == [("ollama_local", "local")]
    assert quality[("ollama_local", "local")].attempts == 3
    bridge = IntelligenceBridge(BridgeFacts(declared=(declared_local_model("local"),), quality=quality),
                                allowed_providers=("ollama",))
    assert bridge.decide("Bonjour").primary.quality_rank == 100


@pytest.mark.parametrize("alias", ["ollama", "ollama_local", "local", " OLLAMA "])
def test_a_local_quota_observation_blocks_the_same_provider_under_every_alias(alias):
    quotas = observe_quotas([Observed(alias, "failed", NOW.isoformat(), error_category="quota")], now=NOW)
    assert list(quotas) == ["ollama_local"]
    bridge = IntelligenceBridge(BridgeFacts(declared=(declared_local_model("local"),), quotas=quotas),
                                allowed_providers=("ollama",))
    assert bridge.decide("Bonjour").status is RouteStatus.DENIED


def test_aliases_are_also_normalized_for_directly_supplied_observations():
    bridge = IntelligenceBridge(
        BridgeFacts(
            declared=(declared_local_model("local"),),
            quality={("ollama", "local"): QualityObservation("ollama", "local", 3, 3, 0)},
            quotas={"ollama": QuotaObservation("ollama", QuotaStatus.EXHAUSTED,
                                               blocked_until=NOW + timedelta(minutes=1))},
        ),
        allowed_providers=("ollama",),
    )
    decision = bridge.decide("Bonjour")
    assert decision.status is RouteStatus.DENIED
    assert decision.evaluations[0].model.quality_rank == 100


@pytest.mark.parametrize("field", ["price_status", "price_evidence", "capabilities"])
@pytest.mark.parametrize("missing_value", [None, "", []])
def test_an_eligible_record_without_explicit_price_evidence_or_capabilities_is_refused(field, missing_value):
    entry = {"model_id": "vendor/model:free", "price_status": "zero_confirmed",
             "price_evidence": "public_catalogue_all_declared_prices_zero", "capabilities": ["text", "code"]}
    entry[field] = missing_value
    with pytest.raises(IntelligenceBridgeError):
        declared_from_eligible(entry, "openrouter")
    del entry[field]
    with pytest.raises(IntelligenceBridgeError):
        declared_from_eligible(entry, "openrouter")


@pytest.mark.parametrize("pricing", ["unknown", "non_zero", "zero_unconfirmed", "invalid"])
def test_an_eligible_record_must_explicitly_confirm_its_zero_price(pricing):
    with pytest.raises(IntelligenceBridgeError):
        declared_from_eligible({"model_id": "model", "price_status": pricing,
                                "price_evidence": "catalogue", "capabilities": ["text"]}, "gemini")


def test_catalogue_records_do_not_gain_undeclared_capabilities_or_a_zero_price():
    unknown = declared_from_catalogue({"model_id": "model", "capabilities": ["text"]}, "gemini")
    assert unknown.pricing is PricingStatus.UNKNOWN
    assert unknown.price_evidence is None
    bridge = IntelligenceBridge(facts(unknown), allowed_providers=("gemini",))
    assert bridge.decide("Bonjour").status is RouteStatus.DENIED
    text_only = declared_from_eligible({"model_id": "model", "price_status": "zero_confirmed",
                                       "price_evidence": "explicit_catalogue", "capabilities": ["text"]}, "gemini")
    assert text_only.capabilities == frozenset({"text"})
    decision = IntelligenceBridge(facts(text_only), allowed_providers=("gemini",)).decide("Analyse ce tableau excel")
    assert decision.status is RouteStatus.DENIED


@pytest.mark.parametrize("provider", ["gemini", "openrouter"])
def test_explicit_records_from_the_real_catalogue_contract_remain_routable(tmp_path, monkeypatch, provider):
    from devkit.model_catalog import ModelCatalog

    monkeypatch.setattr("devkit.evolution_providers._credential", lambda *_: "synthetic-test-only")

    def transport(*args):
        if provider == "gemini":
            return {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}]}
        return {"data": [{"id": "vendor/model:free", "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                           "architecture": {"output_modalities": ["text"]}}]}

    project = tmp_path.resolve()
    catalog = ModelCatalog(project, project / ".devkit", transport=transport)
    catalog.refresh(provider, gemini_free_project_confirmed=True)
    entry = catalog.eligible(provider, capability="text")[0]
    declared = declared_from_eligible(entry, provider)
    assert declared.price_evidence == entry["price_evidence"]
    assert declared.capabilities == frozenset(entry["capabilities"])
    assert declared.pricing is PricingStatus.ZERO_CONFIRMED
    assert IntelligenceBridge(facts(declared), allowed_providers=(provider,)).decide("Bonjour").status is RouteStatus.SELECTED
