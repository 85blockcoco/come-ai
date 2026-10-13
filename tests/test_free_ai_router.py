"""Offline contract tests for the V6 zero-spend model router.

The test suite only injects local configuration fixtures.  It does not load a
``.env``, instantiate a provider SDK or make a network request.
"""

from __future__ import annotations

import socket

import pytest

from free_ai_router import (
    AvailabilityStatus,
    Capability,
    FreeAIRouter,
    FreeAIRouterError,
    FunctionCallValidationError,
    FunctionTool,
    FunctionToolRegistry,
    ModelProfile,
    ModelRegistry,
    PriceDeclaration,
    PricingStatus,
    ProviderKind,
    ProviderState,
    QuotaState,
    QuotaStatus,
    RejectionCode,
    RouteStatus,
    RouterPolicy,
    RoutingMode,
    TaskKind,
    build_route_request,
    classify_task,
    prepare_function_calls,
)


def free_price() -> PriceDeclaration:
    """Fixture-only confirmation; no real-world model or price is asserted."""

    return PriceDeclaration.confirmed_zero("fixture configuration approved by test")


def model(
    model_id: str,
    provider: ProviderKind,
    capabilities: set[Capability],
    *,
    price: PriceDeclaration | None = None,
    quality: int = 50,
    context: int | None = 32_000,
) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        provider=provider,
        capabilities=frozenset(capabilities),
        price=price or free_price(),
        quality_rank=quality,
        context_window=context,
    )


def registry(
    *models: ModelProfile,
    states: tuple[ProviderState, ...] = (),
) -> ModelRegistry:
    return ModelRegistry(models=models, provider_states=states)


def available_state(
    provider: ProviderKind,
    *,
    quota: QuotaState | None = None,
) -> ProviderState:
    return ProviderState(
        provider=provider,
        availability=AvailabilityStatus.AVAILABLE,
        quota=quota or QuotaState.unknown(),
    )


def test_strict_zero_spend_denies_unknown_unconfirmed_and_non_zero_prices() -> None:
    models = (
        model(
            "fixture-unknown",
            ProviderKind.GEMINI,
            {Capability.TEXT},
            price=PriceDeclaration(PricingStatus.UNKNOWN),
        ),
        model(
            "fixture-unconfirmed",
            ProviderKind.GEMINI,
            {Capability.TEXT},
            price=PriceDeclaration(PricingStatus.ZERO_UNCONFIRMED, "claim not verified"),
        ),
        model(
            "fixture-paid",
            ProviderKind.GEMINI,
            {Capability.TEXT},
            price=PriceDeclaration(PricingStatus.NON_ZERO, "configured paid rate"),
        ),
        model("fixture-confirmed-free", ProviderKind.GEMINI, {Capability.TEXT}),
    )
    app = FreeAIRouter(
        registry(*models, states=(available_state(ProviderKind.GEMINI),)),
        RouterPolicy.zero_spend({ProviderKind.GEMINI}),
    )

    decision = app.route(build_route_request("Bonjour"))

    assert decision.status is RouteStatus.SELECTED
    assert decision.primary is not None
    assert decision.primary.model_id == "fixture-confirmed-free"
    by_id = {item.model.model_id: item for item in decision.evaluations}
    assert RejectionCode.PRICING_UNKNOWN in by_id["fixture-unknown"].rejection_codes
    assert RejectionCode.ZERO_PRICE_UNCONFIRMED in by_id["fixture-unconfirmed"].rejection_codes
    assert RejectionCode.PRICE_NOT_ZERO in by_id["fixture-paid"].rejection_codes


def test_default_policy_refuses_an_otherwise_free_provider_until_explicitly_authorized() -> None:
    app = FreeAIRouter(
        registry(
            model("fixture-free", ProviderKind.GEMINI, {Capability.TEXT}),
            states=(available_state(ProviderKind.GEMINI),),
        )
    )

    decision = app.route(build_route_request("Bonjour"))

    assert decision.status is RouteStatus.DENIED
    assert decision.primary is None
    assert RejectionCode.PROVIDER_NOT_AUTHORIZED in decision.evaluations[0].rejection_codes
    assert "aucun appel externe" in " ".join(decision.explanations).casefold()


def test_offline_routing_does_not_open_network_and_excludes_remote_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*_: object, **__: object) -> object:
        raise AssertionError("The pure router must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    app = FreeAIRouter(
        registry(
            model("fixture-cloud", ProviderKind.GEMINI, {Capability.TEXT}, quality=99),
            model("fixture-local", ProviderKind.OLLAMA_LOCAL, {Capability.TEXT}, quality=10),
            states=(
                available_state(ProviderKind.GEMINI),
                available_state(ProviderKind.OLLAMA_LOCAL),
            ),
        ),
        RouterPolicy.zero_spend({ProviderKind.GEMINI, ProviderKind.OLLAMA_LOCAL}),
    )

    decision = app.route(build_route_request("Réponds hors ligne", mode=RoutingMode.OFFLINE))

    assert decision.status is RouteStatus.SELECTED
    assert decision.primary is not None
    assert decision.primary.model_id == "fixture-local"
    assert all(candidate.model.provider is ProviderKind.OLLAMA_LOCAL for candidate in decision.evaluations if candidate.accepted)
    remote = next(item for item in decision.evaluations if item.model.model_id == "fixture-cloud")
    assert RejectionCode.OFFLINE_REQUIRES_LOCAL in remote.rejection_codes


def test_capability_matching_selects_the_only_eligible_model() -> None:
    app = FreeAIRouter(
        registry(
            model("fixture-text", ProviderKind.OLLAMA_LOCAL, {Capability.TEXT}, quality=1),
            model(
                "fixture-sheet-tools",
                ProviderKind.OPENROUTER,
                {Capability.TEXT, Capability.ANALYSIS, Capability.SPREADSHEETS, Capability.FUNCTION_CALLING},
                quality=2,
            ),
            states=(
                available_state(ProviderKind.OLLAMA_LOCAL),
                available_state(ProviderKind.OPENROUTER),
            ),
        ),
        RouterPolicy.zero_spend({ProviderKind.OLLAMA_LOCAL, ProviderKind.OPENROUTER}),
    )
    tool = FunctionTool(
        name="inspect_file",
        description="Inspecte un fichier sélectionné par identifiant opaque.",
        parameters_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
            "additionalProperties": False,
        },
        allowed_task_kinds=frozenset({TaskKind.TOOL_ORCHESTRATION}),
    )
    tool_registry = FunctionToolRegistry([tool])

    request = build_route_request(
        "Analyse ce fichier Excel avec l'outil approuvé",
        tool_registry=tool_registry,
        approved_tool_names=["inspect_file"],
    )
    decision = app.route(request)

    assert request.classification.kind is TaskKind.TOOL_ORCHESTRATION
    assert Capability.SPREADSHEETS in request.classification.required_capabilities
    assert Capability.FUNCTION_CALLING in request.classification.required_capabilities
    assert decision.primary is not None
    assert decision.primary.model_id == "fixture-sheet-tools"
    denied = next(item for item in decision.evaluations if item.model.model_id == "fixture-text")
    assert RejectionCode.MISSING_CAPABILITY in denied.rejection_codes


def test_availability_and_performance_fallback_plan_are_rational_and_deterministic() -> None:
    models = (
        model("fixture-high-quality", ProviderKind.GEMINI, {Capability.TEXT}, quality=90),
        model("fixture-local-backup", ProviderKind.OLLAMA_LOCAL, {Capability.TEXT}, quality=30),
        model("fixture-third", ProviderKind.OPENROUTER, {Capability.TEXT}, quality=20),
    )
    policy = RouterPolicy.zero_spend(
        {ProviderKind.GEMINI, ProviderKind.OLLAMA_LOCAL, ProviderKind.OPENROUTER},
        max_fallbacks=2,
    )
    all_available = registry(
        *models,
        states=(
            available_state(ProviderKind.GEMINI),
            available_state(ProviderKind.OLLAMA_LOCAL),
            available_state(ProviderKind.OPENROUTER),
        ),
    )
    request = build_route_request("Une réponse exigeante", mode=RoutingMode.PERFORMANCE)

    first = FreeAIRouter(all_available, policy).route(request)
    second = FreeAIRouter(all_available, policy).route(request)

    assert first.primary is not None
    assert first.primary.model_id == "fixture-high-quality"
    assert [item.model_id for item in first.fallbacks] == ["fixture-local-backup", "fixture-third"]
    assert first.explanations == second.explanations
    assert first.public_dict() == second.public_dict()

    provider_down = registry(
        *models,
        states=(
            ProviderState(ProviderKind.GEMINI, AvailabilityStatus.UNAVAILABLE),
            available_state(ProviderKind.OLLAMA_LOCAL),
            available_state(ProviderKind.OPENROUTER),
        ),
    )
    fallback_decision = FreeAIRouter(provider_down, policy).route(request)
    assert fallback_decision.primary is not None
    assert fallback_decision.primary.model_id == "fixture-local-backup"
    assert [item.model_id for item in fallback_decision.fallbacks] == ["fixture-third"]


def test_unknown_quota_is_reported_truthfully_without_invented_allowance() -> None:
    app = FreeAIRouter(
        registry(
            model("fixture-local", ProviderKind.OLLAMA_LOCAL, {Capability.TEXT}),
            states=(available_state(ProviderKind.OLLAMA_LOCAL),),
        ),
        RouterPolicy.offline_only(),
    )

    decision = app.route(build_route_request("Question", mode=RoutingMode.OFFLINE))
    public = decision.public_dict()

    quota = public["quota"]
    assert isinstance(quota, list)
    assert quota == [
        {
            "provider": "ollama_local",
            "status": "unknown",
            "known": False,
            "remaining_requests": None,
            "reset_hint": None,
            "message": "Quota non communiqué : aucune valeur n'est inventée.",
        }
    ]
    assert "illimité" not in str(public).casefold()
    assert "inconnu" in " ".join(decision.explanations).casefold()


@pytest.mark.parametrize("remaining_requests", [None, 0])
def test_exhausted_quota_is_never_used_as_a_hidden_fallback(remaining_requests) -> None:
    app = FreeAIRouter(
        registry(
            model("fixture-exhausted", ProviderKind.GEMINI, {Capability.TEXT}),
            states=(
                available_state(
                    ProviderKind.GEMINI,
                    quota=QuotaState(status=QuotaStatus.EXHAUSTED, remaining_requests=remaining_requests),
                ),
            ),
        ),
        RouterPolicy.zero_spend({ProviderKind.GEMINI}),
    )

    decision = app.route(build_route_request("Bonjour"))

    assert decision.status is RouteStatus.DENIED
    assert RejectionCode.QUOTA_EXHAUSTED in decision.evaluations[0].rejection_codes
    disclosed = app.registry.provider_state(ProviderKind.GEMINI).quota.public_dict()
    assert disclosed["status"] == "exhausted"
    assert disclosed["remaining_requests"] == remaining_requests


def test_structured_function_call_preparation_and_validation_never_executes_a_tool() -> None:
    classification = classify_task("Analyse mon CSV", approved_tool_names=["inspect_file"])
    registry = FunctionToolRegistry(
        [
            FunctionTool(
                name="inspect_file",
                description="Lit les métadonnées d'un fichier choisi dans l'espace contrôlé.",
                parameters_schema={
                    "type": "object",
                    "properties": {"file_id": {"type": "string"}},
                    "required": ["file_id"],
                    "additionalProperties": False,
                },
                allowed_task_kinds=frozenset({TaskKind.TOOL_ORCHESTRATION}),
            )
        ]
    )
    prepared = prepare_function_calls(
        classification,
        registry,
        approved_names=["inspect_file"],
    )

    assert prepared.allowed_names == ("inspect_file",)
    assert prepared.provider_payload("gemini")[0]["name"] == "inspect_file"
    assert prepared.provider_payload("openai_compatible")[0]["function"]["name"] == "inspect_file"
    call = prepared.validate_proposal(
        call_id="call-42",
        name="inspect_file",
        arguments={"file_id": "opaque-file-id"},
    )
    assert call.name == "inspect_file"
    assert dict(call.arguments) == {"file_id": "opaque-file-id"}
    with pytest.raises(FunctionCallValidationError, match="Arguments non autorisés"):
        prepared.validate_proposal(
            call_id="call-43",
            name="inspect_file",
            arguments={"file_id": "opaque-file-id", "path": "/tmp/not-authorized"},
        )
    with pytest.raises(FunctionCallValidationError, match="n'a pas été autorisée"):
        prepared.validate_proposal(call_id="call-44", name="run_shell", arguments={})


def test_bad_zero_price_confirmation_and_missing_tool_registry_fail_closed() -> None:
    with pytest.raises(FreeAIRouterError, match="preuve"):
        PriceDeclaration(PricingStatus.ZERO_CONFIRMED)
    with pytest.raises(FreeAIRouterError, match="registre d'outils"):
        build_route_request("Utilise l'outil", approved_tool_names=["inspect_file"])
