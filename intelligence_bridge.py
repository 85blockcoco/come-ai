"""Measured facts turned into a zero-spend routing decision.

:mod:`free_ai_router` is a pure decision layer: it never reads a model
registry, a catalogue, a configuration file or a clock.  This module is the
seam that feeds it, and the *only* place where observations become routing
input.  It performs no network call, reads no ``.env``, and invents no
number.

Two facts drive every decision it produces:

``quality``
    What the caller already measured for a (provider, model) pair: successes,
    failures and latency.  A pair never observed stays at a neutral rank, so
    an unmeasured model is never promoted over a measured one by accident.

``quota``
    What the caller observed about a provider's quota: a rejected or
    rate-limited provider is taken out of the running for a bounded cooldown.
    A quota nobody reported stays ``QuotaStatus.UNKNOWN``; it is never turned
    into an unlimited or an invented remaining count.

Capabilities need one deliberate translation.  The catalogue declares what a
model can *ingest* (``text``, ``code``, ``function_calling``, …) while the
router asks what a task *requires* (``ANALYSIS``, ``SPREADSHEETS``, …).
Handing spreadsheet data to a text model as text really does let it reason
about that data, so reasoning capabilities are derived from ``text``/``code``.
Vision is the exception and is never derived: a text model has not been shown
to see an image, so a vision task stays unsatisfied rather than being served
by a model that cannot do it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from statistics import median
from types import MappingProxyType
from typing import Any, Protocol

from free_ai_router import (
    AvailabilityStatus,
    Capability,
    ModelProfile,
    ModelRegistry,
    PriceDeclaration,
    PricingStatus,
    ProviderKind,
    ProviderState,
    QuotaState,
    QuotaStatus,
    RouterPolicy,
    RoutingDecision,
    RoutingMode,
    RouteRequest,
    build_route_request,
)


# A decision over a longer window than this stops being a measurement of the
# present.  Quality therefore only ever looks at recent history.
MAX_OBSERVED_EVENTS = 500
QUALITY_WINDOW = timedelta(days=14)
MIN_MEASURED_ATTEMPTS = 3
NEUTRAL_RANK = 50

# A provider that just refused with 429 is not retried for this long, unless
# the provider itself stated a ``Retry-After`` value.
DEFAULT_QUOTA_COOLDOWN = timedelta(minutes=15)
QUOTA_OBSERVATION_WINDOW = timedelta(hours=6)
AUTH_OBSERVATION_WINDOW = timedelta(hours=2)

# The chat speaks "ollama"; the router's enum value is "ollama_local".
PROVIDER_ALIASES: Mapping[str, ProviderKind] = MappingProxyType(
    {"ollama": ProviderKind.OLLAMA_LOCAL, "local": ProviderKind.OLLAMA_LOCAL}
)

LOCAL_PRICE_EVIDENCE = "local_gguf_execution_no_provider_billing"


class IntelligenceBridgeError(ValueError):
    """The caller supplied facts that cannot describe a routable model."""


class BridgeEvent(Protocol):
    """Structural shape of one measured execution.

    ``usage_ledger.UsageEvent`` satisfies it.  Anything else with the same
    attributes works too, which keeps this module free of storage concerns.
    """

    provider: str
    model: str
    outcome: str
    occurred_at: str
    latency_ms: int | None
    error_category: str | None
    retry_after_seconds: int | None


# --------------------------------------------------------------------------
# Declared models
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeclaredModel:
    """One model the host actually verified, before any quality measurement."""

    provider: str
    model_id: str
    capabilities: frozenset[str] = frozenset()
    context_window: int | None = None
    pricing: PricingStatus = PricingStatus.UNKNOWN
    price_evidence: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _coerce_provider(self.provider))
        object.__setattr__(self, "model_id", self.model_id.strip())
        if not self.provider or not self.model_id:
            raise IntelligenceBridgeError("Un modèle déclaré a besoin d'un fournisseur et d'un identifiant.")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        if self.context_window is not None and self.context_window <= 0:
            raise IntelligenceBridgeError("La fenêtre de contexte déclarée doit être positive.")
        if self.pricing is PricingStatus.ZERO_CONFIRMED and not (self.price_evidence or "").strip():
            # Zero spend requires proof, exactly as PriceDeclaration does.
            raise IntelligenceBridgeError("Un modèle à prix nul confirmé doit citer sa preuve.")
        object.__setattr__(self, "price_evidence", (self.price_evidence or "").strip() or None)


@dataclass(frozen=True, slots=True)
class QualityObservation:
    """Operational reliability a caller measured for one (provider, model)."""

    provider: str
    model: str
    attempts: int
    succeeded: int
    failed: int
    median_latency_ms: int | None = None
    last_observed_at: datetime | None = None

    @property
    def measured(self) -> bool:
        """True only once enough samples exist to say anything at all."""

        return self.attempts >= MIN_MEASURED_ATTEMPTS

    @property
    def quality_rank(self) -> int:
        """Bounded 0..100 rank; neutral when the sample is too small.

        This is a measurement of *operational reliability*, not of reasoning
        quality.  It never claims that a working model writes better answers.
        """

        if not self.measured or self.attempts <= 0:
            return NEUTRAL_RANK
        return max(0, min(100, round(100 * self.succeeded / self.attempts)))

    @property
    def success_rate(self) -> float | None:
        if self.attempts <= 0:
            return None
        return self.succeeded / self.attempts

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "attempts": self.attempts,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "measured": self.measured,
            "quality_rank": self.quality_rank,
            "median_latency_ms": self.median_latency_ms,
            "measurement": "observed_local_ledger_reliability_not_reasoning_quality",
        }


@dataclass(frozen=True, slots=True)
class QuotaObservation:
    """A quota fact observed for a provider, never an assumed one."""

    provider: str
    status: QuotaStatus = QuotaStatus.UNKNOWN
    remaining_requests: int | None = None
    reset_hint: str | None = None
    source: str | None = None
    blocked_until: datetime | None = None
    observed_at: datetime | None = None

    @property
    def blocks_now(self) -> bool:
        return self.blocked_until is not None

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "known": self.status is not QuotaStatus.UNKNOWN,
            "remaining_requests": self.remaining_requests,
            "reset_hint": self.reset_hint,
            "source": self.source,
            "blocked_until": self.blocked_until.isoformat() if self.blocked_until else None,
        }


# --------------------------------------------------------------------------
# Capability translation
# --------------------------------------------------------------------------

_CATALOGUE_CAPABILITIES: Mapping[str, frozenset[Capability]] = {
    "text": frozenset({Capability.TEXT}),
    "code": frozenset({Capability.CODE}),
    "function_calling": frozenset({Capability.FUNCTION_CALLING}),
    "structured_output": frozenset({Capability.STRUCTURED_OUTPUT}),
    "long_context": frozenset({Capability.LONG_CONTEXT}),
}

# A model that reads text and code can be handed data as text: a spreadsheet
# extract, a document body, a finance case.  Vision is deliberately absent.
_REASONED_CAPABILITIES = frozenset({Capability.ANALYSIS, Capability.DOCUMENTS, Capability.SPREADSHEETS})


def router_capabilities(declared: Iterable[str]) -> frozenset[Capability]:
    """Translate catalogue capability names into router capabilities."""

    translated: set[Capability] = set()
    for name in declared:
        translated |= _CATALOGUE_CAPABILITIES.get(name.strip().casefold(), frozenset())
    if {Capability.TEXT, Capability.CODE} <= translated:
        translated |= _REASONED_CAPABILITIES
    return frozenset(translated)


# --------------------------------------------------------------------------
# Observation
# --------------------------------------------------------------------------


def _coerce_provider(value: Any) -> str:
    """Normalise a provider name; an empty one is a fact the caller must skip."""

    provider = str(value or "").strip().casefold()
    alias = PROVIDER_ALIASES.get(provider)
    return alias.value if alias is not None else provider


def _parse_moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def observe_quality(events: Iterable[BridgeEvent], *, now: datetime | None = None) -> dict[tuple[str, str], QualityObservation]:
    """Aggregate measured reliability per (provider, model).

    Events outside the quality window, or without a readable timestamp, are
    ignored rather than guessed at.  ``now`` is injectable so the aggregation
    is reproducible in tests.
    """

    moment = _parse_moment(now) if now is not None else datetime.now(timezone.utc)
    cutoff = moment - QUALITY_WINDOW
    grouped: dict[tuple[str, str], list[BridgeEvent]] = {}
    for event in events:
        occurred = _parse_moment(getattr(event, "occurred_at", None))
        if occurred is None or occurred < cutoff or occurred > moment + timedelta(minutes=1):
            continue
        provider = _coerce_provider(getattr(event, "provider", "")).strip()
        model = str(getattr(event, "model", "") or "").strip()
        outcome = str(getattr(event, "outcome", "") or "").strip().casefold()
        if not provider or not model or outcome not in {"succeeded", "failed"}:
            continue
        grouped.setdefault((provider, model), []).append(event)

    observations: dict[tuple[str, str], QualityObservation] = {}
    for (provider, model), group in grouped.items():
        latencies = sorted(
            int(event.latency_ms)
            for event in group
            if isinstance(getattr(event, "latency_ms", None), int)
            and not isinstance(getattr(event, "latency_ms", None), bool)
            and int(event.latency_ms) >= 0
        )
        succeeded = sum(1 for event in group if str(event.outcome).casefold() == "succeeded")
        stamps = [_parse_moment(event.occurred_at) for event in group]
        observations[(provider, model)] = QualityObservation(
            provider=provider,
            model=model,
            attempts=len(group),
            succeeded=succeeded,
            failed=len(group) - succeeded,
            median_latency_ms=int(median(latencies)) if latencies else None,
            last_observed_at=max(stamp for stamp in stamps if stamp is not None),
        )
    return observations


def _cooldown(event: BridgeEvent) -> timedelta:
    """Prefer the provider's own ``Retry-After`` over the local default."""

    raw = getattr(event, "retry_after_seconds", None)
    if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 86_400:
        return timedelta(seconds=raw)
    return DEFAULT_QUOTA_COOLDOWN


def observe_quotas(
    events: Iterable[BridgeEvent],
    *,
    now: datetime | None = None,
    quota_cooldown: timedelta = DEFAULT_QUOTA_COOLDOWN,
    auth_window: timedelta = AUTH_OBSERVATION_WINDOW,
) -> dict[str, QuotaObservation]:
    """Derive provider quota state from observed failures only.

    Rule, deliberately narrow: a provider is *exhausted* when a quota failure
    was observed recently enough that a retry would still be inside the
    provider's own cooldown.  Everything else stays ``UNKNOWN``.  This never
    reports a remaining request count, because none was measured.
    """

    moment = _parse_moment(now) if now is not None else datetime.now(timezone.utc)
    latest_quota: dict[str, tuple[datetime, timedelta]] = {}
    latest_auth: dict[str, datetime] = {}
    for event in events:
        occurred = _parse_moment(getattr(event, "occurred_at", None))
        if occurred is None or occurred > moment + timedelta(minutes=1):
            continue
        provider = _coerce_provider(getattr(event, "provider", "")).strip()
        category = str(getattr(event, "error_category", "") or "").strip().casefold()
        if category == "quota":
            cooldown = _cooldown(event) if getattr(event, "retry_after_seconds", None) is not None else quota_cooldown
            previous = latest_quota.get(provider)
            if previous is None or occurred > previous[0]:
                latest_quota[provider] = (occurred, cooldown)
        elif category == "authentication" and occurred >= moment - auth_window:
            if occurred > latest_auth.get(provider, datetime.min.replace(tzinfo=timezone.utc)):
                latest_auth[provider] = occurred

    observations: dict[str, QuotaObservation] = {}
    for provider, (occurred, cooldown) in latest_quota.items():
        blocked_until = occurred + cooldown
        if blocked_until <= moment:
            continue  # The cooldown elapsed; nothing is asserted either way.
        observations[provider] = QuotaObservation(
            provider=provider,
            status=QuotaStatus.EXHAUSTED,
            remaining_requests=None,
            reset_hint=blocked_until.isoformat(),
            source=f"observed_error_category_quota_within_{int(cooldown.total_seconds())}s",
            blocked_until=blocked_until,
            observed_at=occurred,
        )
    for provider, occurred in latest_auth.items():
        if provider in observations:
            continue
        observations[provider] = QuotaObservation(
            provider=provider,
            status=QuotaStatus.UNKNOWN,
            source=f"observed_error_category_authentication_at_{occurred.isoformat()}",
            observed_at=occurred,
        )
    return observations


# --------------------------------------------------------------------------
# Registry construction
# --------------------------------------------------------------------------


def _provider_kind(provider: str) -> ProviderKind:
    text = provider.strip().casefold()
    if text in PROVIDER_ALIASES:
        return PROVIDER_ALIASES[text]
    try:
        return ProviderKind(text)
    except ValueError as error:
        raise IntelligenceBridgeError(f"Fournisseur inconnu pour le routage : {text!r}.") from error


def _price_declaration(declared: DeclaredModel) -> PriceDeclaration:
    if declared.pricing is PricingStatus.ZERO_CONFIRMED:
        return PriceDeclaration.confirmed_zero(declared.price_evidence or "")
    return PriceDeclaration(status=declared.pricing, evidence=declared.price_evidence)


def build_model_registry(
    declared: Iterable[DeclaredModel],
    *,
    quality: Mapping[tuple[str, str], QualityObservation] | None = None,
    quotas: Mapping[str, QuotaObservation] | None = None,
) -> ModelRegistry:
    """Assemble a routable registry from declared models and observations.

    A model whose price is not explicitly confirmed zero is still registered,
    so the router can name the exact refusal (``price_unknown``,
    ``zero_price_unconfirmed``, ``price_not_zero``) instead of silently
    dropping it.
    """

    declared_models = list(declared)
    if not declared_models:
        raise IntelligenceBridgeError("Aucun modèle déclaré : le routage n'a rien à choisir.")
    if len(declared_models) > 2_000:
        raise IntelligenceBridgeError("Trop de modèles déclarés pour un routage local.")

    quality = {(_coerce_provider(provider), model): observation
               for (provider, model), observation in (quality or {}).items()}
    quotas = {_coerce_provider(provider): observation
              for provider, observation in (quotas or {}).items()}
    registry = ModelRegistry()
    declared_ids: set[str] = set()
    for model in declared_models:
        if model.model_id in declared_ids:
            raise IntelligenceBridgeError(f"Modèle déclaré deux fois : {model.model_id!r}.")
        declared_ids.add(model.model_id)
        provider = _provider_kind(model.provider)
        observation = quality.get((provider.value, model.model_id))
        registry.register_model(
            ModelProfile(
                model_id=model.model_id,
                provider=provider,
                capabilities=router_capabilities(model.capabilities),
                price=_price_declaration(model),
                quality_rank=observation.quality_rank if observation else NEUTRAL_RANK,
                context_window=model.context_window,
            )
        )

    seen: set[str] = set()
    for model in declared_models:
        provider = _provider_kind(model.provider)
        if provider.value in seen:
            continue
        seen.add(provider.value)
        observation = quotas.get(provider.value)
        blocked = observation is not None and observation.status is QuotaStatus.EXHAUSTED and observation.blocks_now
        registry.set_provider_state(
            ProviderState(
                provider=provider,
                availability=AvailabilityStatus.AVAILABLE if not blocked else AvailabilityStatus.UNAVAILABLE,
                quota=QuotaState(
                    status=observation.status if observation is not None else QuotaStatus.UNKNOWN,
                    remaining_requests=observation.remaining_requests if observation is not None and blocked else None,
                    reset_hint=observation.reset_hint if observation is not None and blocked else None,
                    source=observation.source if observation is not None else "never_reported_by_provider",
                ),
                note="cooldown_observé" if blocked else None,
            )
        )
    return registry


# --------------------------------------------------------------------------
# The bridge
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BridgeFacts:
    """Everything the bridge needs, supplied by the host at decision time."""

    declared: tuple[DeclaredModel, ...] = ()
    quality: dict[tuple[str, str], QualityObservation] = field(default_factory=dict)
    quotas: dict[str, QuotaObservation] = field(default_factory=dict)


class IntelligenceBridge:
    """Decide which verified-free model should answer, from measured facts."""

    def __init__(
        self,
        facts: BridgeFacts,
        *,
        allowed_providers: Iterable[str],
        max_fallbacks: int = 2,
    ) -> None:
        self.facts = facts
        self.allowed_providers = frozenset(_provider_kind(name) for name in allowed_providers)
        if not self.allowed_providers:
            raise IntelligenceBridgeError("Un pont de routage sans fournisseur autorisé refuserait tout.")
        if isinstance(max_fallbacks, bool) or not isinstance(max_fallbacks, int) or not 0 <= max_fallbacks <= 16:
            raise IntelligenceBridgeError("Le nombre de replis doit être un entier entre 0 et 16.")
        self.policy = RouterPolicy.zero_spend(self.allowed_providers, max_fallbacks=max_fallbacks)
        self._registry = build_model_registry(facts.declared, quality=facts.quality, quotas=facts.quotas)
        from free_ai_router import FreeAIRouter

        self.router = FreeAIRouter(self._registry, self.policy)

    @property
    def registry(self) -> ModelRegistry:
        return self._registry

    def decide(
        self,
        message: str,
        *,
        mode: RoutingMode | str = RoutingMode.AUTOMATIC,
        requested_capabilities: Iterable[str] = (),
        approved_tool_names: Iterable[str] = (),
        tool_registry: Any = None,
        max_fallbacks: int | None = None,
    ) -> RoutingDecision:
        """Route one request; raises nothing, always returns a decision."""

        request: RouteRequest = build_route_request(
            message,
            mode=mode,
            requested_capabilities=requested_capabilities,
            tool_registry=tool_registry,
            approved_tool_names=approved_tool_names,
            max_fallbacks=max_fallbacks,
        )
        return self.router.route(request)

    def ordered_providers(self, decision: RoutingDecision) -> tuple[str, ...]:
        """Provider names to try, in the order the router approved them."""

        planned = (decision.primary, *decision.fallbacks)
        return tuple(model.provider.value for model in planned if model is not None)

    def public_state(self) -> dict[str, Any]:
        """Inert, secret-free description of what is routable right now."""

        return {
            "allowed_providers": sorted(provider.value for provider in self.allowed_providers),
            "max_fallbacks": self.policy.max_fallbacks,
            "declared_models": len(self.facts.declared),
            "quality": {
                f"{provider}/{model}": observation.public_dict()
                for (provider, model), observation in sorted(self.facts.quality.items())
            },
            "quotas": {provider: observation.public_dict() for provider, observation in sorted(self.facts.quotas.items())},
            "measurement_note": "quality is observed operational reliability, never a claimed reasoning benchmark",
        }


def declared_local_model(model_id: str, *, context_window: int | None = None) -> DeclaredModel:
    """Declare a locally executed model: no provider bill can exist."""

    return DeclaredModel(
        provider=ProviderKind.OLLAMA_LOCAL.value,
        model_id=model_id,
        capabilities=frozenset({"code", "text"}),
        context_window=context_window,
        pricing=PricingStatus.ZERO_CONFIRMED,
        price_evidence=LOCAL_PRICE_EVIDENCE,
    )


def declared_from_catalogue(entry: Mapping[str, Any], provider: str) -> DeclaredModel | None:
    """Adapt one ``ModelCatalog`` record into a declared model.

    Returns ``None`` for a record that does not identify a model, so a malformed
    cache line cannot widen the routing table.
    """

    model_id = str(entry.get("model_id") or "").strip()
    if not model_id:
        return None
    raw_capabilities = entry.get("capabilities")
    if isinstance(raw_capabilities, str):
        capabilities = frozenset({raw_capabilities})
    elif isinstance(raw_capabilities, Sequence):
        capabilities = frozenset(str(item) for item in raw_capabilities if isinstance(item, str))
    else:
        capabilities = frozenset()
    try:
        pricing = PricingStatus(str(entry.get("price_status") or PricingStatus.UNKNOWN.value))
    except ValueError:
        pricing = PricingStatus.UNKNOWN
    context_window = entry.get("input_token_limit")
    return DeclaredModel(
        provider=provider,
        model_id=model_id,
        capabilities=capabilities,
        context_window=context_window if isinstance(context_window, int) and context_window > 0 else None,
        pricing=pricing,
        price_evidence=str(entry.get("price_evidence")) if entry.get("price_evidence") else None,
    )


def declared_from_eligible(entry: Mapping[str, Any], provider: str) -> DeclaredModel:
    """Confirm an eligible catalogue record without supplying missing facts.

    Eligibility must include an explicit zero price, its evidence and at least
    one supported capability. A partial cache record cannot inherit those facts
    from its presence in an eligible list.
    """

    evidence = entry.get("price_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise IntelligenceBridgeError("Une entrée éligible doit citer sa preuve de prix nul.")
    declared = declared_from_catalogue(entry, provider)
    if declared is None:
        raise IntelligenceBridgeError("Une entrée éligible du catalogue doit nommer son modèle.")
    if declared.pricing is not PricingStatus.ZERO_CONFIRMED:
        raise IntelligenceBridgeError("Une entrée éligible doit déclarer un prix nul confirmé.")
    if not router_capabilities(declared.capabilities):
        raise IntelligenceBridgeError("Une entrée éligible doit déclarer ses capacités prises en charge.")
    return declared


__all__ = [
    "AUTH_OBSERVATION_WINDOW",
    "BridgeEvent",
    "BridgeFacts",
    "DEFAULT_QUOTA_COOLDOWN",
    "DeclaredModel",
    "IntelligenceBridge",
    "IntelligenceBridgeError",
    "LOCAL_PRICE_EVIDENCE",
    "NEUTRAL_RANK",
    "PROVIDER_ALIASES",
    "QualityObservation",
    "QuotaObservation",
    "build_model_registry",
    "declared_from_catalogue",
    "declared_from_eligible",
    "declared_local_model",
    "observe_quality",
    "observe_quotas",
    "router_capabilities",
]
