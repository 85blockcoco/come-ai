"""Routeur V6 à dépense nulle, sans réseau et sans dépendance à une clé.

Ce module est volontairement une *couche de décision*, pas un client Gemini,
OpenRouter ou Ollama.  Il ne lit pas ``.env``, n'ouvre aucune connexion et ne
connaît aucun nom de modèle prétendument gratuit.  L'application hôte injecte
à la place un registre explicite de modèles, leur prix vérifié et leur état
déclaré.  Un adaptateur réseau futur peut consommer :class:`ProviderInvocation`
après que cette couche a approuvé le modèle.

La règle par défaut est plus stricte qu'un simple filtre de préférence : un
modèle ne peut être retenu que si son fournisseur est autorisé localement, sa
disponibilité est déclarée, et son prix est explicitement confirmé à zéro.
Un quota inconnu reste inconnu dans la décision ; il n'est jamais transformé
en quota illimité ou en nombre inventé.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias


MAX_CLASSIFICATION_CHARS = 12_000
MAX_FUNCTION_ARGUMENT_DEPTH = 8
MAX_FUNCTION_ARGUMENT_ITEMS = 256
MAX_FUNCTION_ARGUMENT_STRING_CHARS = 16_000


JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | tuple["JsonValue", ...]
    | Mapping[str, "JsonValue"]
)


class FreeAIRouterError(ValueError):
    """Configuration ou préparation invalide, sans exposer de secret."""


class FunctionCallValidationError(FreeAIRouterError):
    """Un appel de fonction proposé ne respecte pas le contrat approuvé."""


class RoutingMode(StrEnum):
    """Modes visibles dans les réglages de Côme AI V6."""

    AUTOMATIC = "automatic"
    OFFLINE = "offline"
    PERFORMANCE = "performance"


class ProviderKind(StrEnum):
    """Fournisseurs pris en charge par les futurs adaptateurs seulement."""

    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    OLLAMA_LOCAL = "ollama_local"


class Capability(StrEnum):
    """Capacités déclarées par configuration, jamais supposées par un nom."""

    TEXT = "text"
    ANALYSIS = "analysis"
    DOCUMENTS = "documents"
    SPREADSHEETS = "spreadsheets"
    VISION = "vision"
    CODE = "code"
    LONG_CONTEXT = "long_context"
    STRUCTURED_OUTPUT = "structured_output"
    FUNCTION_CALLING = "function_calling"


class TaskKind(StrEnum):
    """Classification déterministe utilisée pour exprimer les besoins."""

    GENERAL = "general"
    DOCUMENT_ANALYSIS = "document_analysis"
    SPREADSHEET_ANALYSIS = "spreadsheet_analysis"
    VISION_ANALYSIS = "vision_analysis"
    CODE_ASSISTANCE = "code_assistance"
    TOOL_ORCHESTRATION = "tool_orchestration"


class PricingStatus(StrEnum):
    """Une étiquette de coût : seule ``ZERO_CONFIRMED`` est admissible."""

    UNKNOWN = "unknown"
    ZERO_UNCONFIRMED = "zero_unconfirmed"
    ZERO_CONFIRMED = "zero_confirmed"
    NON_ZERO = "non_zero"


class AvailabilityStatus(StrEnum):
    """État fourni par l'application ou un futur test explicite de connexion."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class QuotaStatus(StrEnum):
    """Le routeur ne transforme jamais ``UNKNOWN`` en valeur numérique."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"


class RouteStatus(StrEnum):
    SELECTED = "selected"
    DENIED = "denied"


class RejectionCode(StrEnum):
    """Codes stables pour l'UI et les tests, avec texte français séparé."""

    MODEL_DISABLED = "model_disabled"
    PROVIDER_NOT_AUTHORIZED = "provider_not_authorized"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_AVAILABILITY_UNKNOWN = "provider_availability_unknown"
    OFFLINE_REQUIRES_LOCAL = "offline_requires_local"
    PRICING_UNKNOWN = "pricing_unknown"
    ZERO_PRICE_UNCONFIRMED = "zero_price_unconfirmed"
    PRICE_NOT_ZERO = "price_not_zero"
    QUOTA_EXHAUSTED = "quota_exhausted"
    MISSING_CAPABILITY = "missing_capability"


_PROVIDER_LABELS: dict[ProviderKind, str] = {
    ProviderKind.GEMINI: "Gemini",
    ProviderKind.OPENROUTER: "OpenRouter",
    ProviderKind.OLLAMA_LOCAL: "Ollama local",
}

_REJECTION_TEXT: dict[RejectionCode, str] = {
    RejectionCode.MODEL_DISABLED: "modèle désactivé dans la configuration locale",
    RejectionCode.PROVIDER_NOT_AUTHORIZED: "fournisseur non autorisé par la politique locale",
    RejectionCode.PROVIDER_UNAVAILABLE: "fournisseur déclaré indisponible",
    RejectionCode.PROVIDER_AVAILABILITY_UNKNOWN: "disponibilité du fournisseur non confirmée",
    RejectionCode.OFFLINE_REQUIRES_LOCAL: "le mode hors ligne exige Ollama local",
    RejectionCode.PRICING_UNKNOWN: "prix inconnu",
    RejectionCode.ZERO_PRICE_UNCONFIRMED: "prix annoncé nul mais non confirmé",
    RejectionCode.PRICE_NOT_ZERO: "prix déclaré non nul",
    RejectionCode.QUOTA_EXHAUSTED: "quota déclaré épuisé",
    RejectionCode.MISSING_CAPABILITY: "capacité requise absente",
}

_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")
_FUNCTION_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,95}$")
_CALL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _coerce_enum(enum_type: type[StrEnum], value: StrEnum | str, label: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(item.value for item in enum_type)
        raise FreeAIRouterError(f"{label} invalide. Valeurs autorisées : {choices}.") from error


def _coerce_capabilities(values: Iterable[Capability | str]) -> frozenset[Capability]:
    return frozenset(_coerce_enum(Capability, value, "capacité") for value in values)  # type: ignore[arg-type]


def _coerce_task_kinds(values: Iterable[TaskKind | str]) -> frozenset[TaskKind]:
    return frozenset(_coerce_enum(TaskKind, value, "type de tâche") for value in values)  # type: ignore[arg-type]


def _coerce_providers(values: Iterable[ProviderKind | str]) -> frozenset[ProviderKind]:
    return frozenset(_coerce_enum(ProviderKind, value, "fournisseur") for value in values)  # type: ignore[arg-type]


def _freeze_json(
    value: Any,
    *,
    label: str,
    depth: int = 0,
) -> JsonValue:
    """Copy a small JSON-compatible value without accepting executable types."""

    if depth > MAX_FUNCTION_ARGUMENT_DEPTH:
        raise FunctionCallValidationError(f"{label} est trop profondément imbriqué.")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise FunctionCallValidationError(f"{label} contient un nombre non valide.")
        return value
    if isinstance(value, str):
        if len(value) > MAX_FUNCTION_ARGUMENT_STRING_CHARS:
            raise FunctionCallValidationError(f"{label} contient une chaîne trop longue.")
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_FUNCTION_ARGUMENT_ITEMS:
            raise FunctionCallValidationError(f"{label} contient trop d'éléments.")
        copied: dict[str, JsonValue] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise FunctionCallValidationError(f"{label} contient une clé non textuelle.")
            copied[key] = _freeze_json(child, label=label, depth=depth + 1)
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_FUNCTION_ARGUMENT_ITEMS:
            raise FunctionCallValidationError(f"{label} contient trop d'éléments.")
        return tuple(_freeze_json(child, label=label, depth=depth + 1) for child in value)
    raise FunctionCallValidationError(f"{label} contient un type non pris en charge.")


def _json_to_plain(value: JsonValue) -> Any:
    """Turn frozen values back into provider-ready plain JSON structures."""

    if isinstance(value, Mapping):
        return {key: _json_to_plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_json_to_plain(child) for child in value]
    return value


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


@dataclass(frozen=True, slots=True)
class PriceDeclaration:
    """A model price declaration with explicit provenance.

    ``evidence`` deliberately remains a configuration note rather than a live
    lookup result.  A real integration may refresh it only after the user has
    authorised that external check.
    """

    status: PricingStatus = PricingStatus.UNKNOWN
    evidence: str | None = None

    def __post_init__(self) -> None:
        status = _coerce_enum(PricingStatus, self.status, "statut de prix")
        object.__setattr__(self, "status", status)
        evidence = (self.evidence or "").strip() or None
        if status is PricingStatus.ZERO_CONFIRMED and not evidence:
            raise FreeAIRouterError(
                "Un prix nul confirmé doit inclure une preuve ou une note de configuration."
            )
        object.__setattr__(self, "evidence", evidence)

    @classmethod
    def confirmed_zero(cls, evidence: str) -> "PriceDeclaration":
        """Make the only price declaration accepted by strict free routing."""

        return cls(status=PricingStatus.ZERO_CONFIRMED, evidence=evidence)


@dataclass(frozen=True, slots=True)
class QuotaState:
    """Provider quota explicitly reported by configuration or a future adapter."""

    status: QuotaStatus = QuotaStatus.UNKNOWN
    remaining_requests: int | None = None
    reset_hint: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        status = _coerce_enum(QuotaStatus, self.status, "statut de quota")
        object.__setattr__(self, "status", status)
        if self.remaining_requests is not None:
            if not isinstance(self.remaining_requests, int) or self.remaining_requests < 0:
                raise FreeAIRouterError("Le quota restant doit être un entier positif ou nul.")
        if status is QuotaStatus.UNKNOWN and self.remaining_requests is not None:
            raise FreeAIRouterError(
                "Un quota inconnu ne peut pas contenir de valeur restante inventée."
            )
        if status is QuotaStatus.EXHAUSTED and self.remaining_requests not in {None, 0}:
            raise FreeAIRouterError(
                "Un quota épuisé ne peut pas annoncer des requêtes restantes."
            )
        if status is QuotaStatus.AVAILABLE and self.remaining_requests == 0:
            raise FreeAIRouterError(
                "Utilise le statut 'exhausted' lorsqu'aucune requête ne reste."
            )
        object.__setattr__(self, "reset_hint", (self.reset_hint or "").strip() or None)
        object.__setattr__(self, "source", (self.source or "").strip() or None)

    @classmethod
    def unknown(cls) -> "QuotaState":
        return cls()

    @property
    def known(self) -> bool:
        return self.status is not QuotaStatus.UNKNOWN

    def public_dict(self) -> dict[str, object]:
        """A truthful UI payload: no numeric value is fabricated for unknown."""

        if self.status is QuotaStatus.UNKNOWN:
            return {
                "status": self.status.value,
                "known": False,
                "remaining_requests": None,
                "reset_hint": None,
                "message": "Quota non communiqué : aucune valeur n'est inventée.",
            }
        if self.status is QuotaStatus.EXHAUSTED:
            return {
                "status": self.status.value,
                "known": True,
                "remaining_requests": 0,
                "reset_hint": self.reset_hint,
                "message": "Quota déclaré épuisé.",
            }
        return {
            "status": self.status.value,
            "known": True,
            "remaining_requests": self.remaining_requests,
            "reset_hint": self.reset_hint,
            "message": "Quota déclaré disponible.",
        }


@dataclass(frozen=True, slots=True)
class ProviderState:
    """Local, declared state.  It is never inferred from a failed route."""

    provider: ProviderKind
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    quota: QuotaState = field(default_factory=QuotaState.unknown)
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _coerce_enum(ProviderKind, self.provider, "fournisseur"))
        object.__setattr__(
            self,
            "availability",
            _coerce_enum(AvailabilityStatus, self.availability, "disponibilité"),
        )
        if not isinstance(self.quota, QuotaState):
            raise FreeAIRouterError("Le quota doit être un QuotaState explicite.")
        object.__setattr__(self, "note", (self.note or "").strip() or None)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Injectable model configuration; no provider model catalogue is embedded."""

    model_id: str
    provider: ProviderKind
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    price: PriceDeclaration = field(default_factory=PriceDeclaration)
    quality_rank: int = 0
    context_window: int | None = None
    enabled: bool = True
    display_name: str | None = None

    def __post_init__(self) -> None:
        model_id = self.model_id.strip()
        if not _MODEL_ID_PATTERN.fullmatch(model_id):
            raise FreeAIRouterError(
                "L'identifiant de modèle doit être une courte valeur de configuration sans espace."
            )
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "provider", _coerce_enum(ProviderKind, self.provider, "fournisseur"))
        object.__setattr__(self, "capabilities", _coerce_capabilities(self.capabilities))
        if not isinstance(self.price, PriceDeclaration):
            raise FreeAIRouterError("Le prix doit être une PriceDeclaration explicite.")
        if not isinstance(self.quality_rank, int) or not 0 <= self.quality_rank <= 100:
            raise FreeAIRouterError("quality_rank doit être un entier entre 0 et 100.")
        if self.context_window is not None and (
            not isinstance(self.context_window, int) or self.context_window <= 0
        ):
            raise FreeAIRouterError("context_window doit être un entier strictement positif ou None.")
        display_name = (self.display_name or "").strip() or None
        object.__setattr__(self, "display_name", display_name)

    @property
    def is_local(self) -> bool:
        return self.provider is ProviderKind.OLLAMA_LOCAL

    @property
    def label(self) -> str:
        return self.display_name or self.model_id


class ModelRegistry:
    """An in-memory registry whose content is supplied by the host application."""

    def __init__(
        self,
        models: Iterable[ModelProfile] = (),
        provider_states: Iterable[ProviderState] = (),
    ) -> None:
        self._models: dict[str, ModelProfile] = {}
        self._provider_states: dict[ProviderKind, ProviderState] = {}
        for model in models:
            self.register_model(model)
        for state in provider_states:
            self.set_provider_state(state)

    def register_model(self, model: ModelProfile) -> None:
        if not isinstance(model, ModelProfile):
            raise FreeAIRouterError("Le registre accepte uniquement des ModelProfile.")
        if model.model_id in self._models:
            raise FreeAIRouterError(f"Le modèle '{model.model_id}' est déjà enregistré.")
        self._models[model.model_id] = model

    def set_provider_state(self, state: ProviderState) -> None:
        if not isinstance(state, ProviderState):
            raise FreeAIRouterError("Le registre accepte uniquement des ProviderState.")
        self._provider_states[state.provider] = state

    def models(self) -> tuple[ModelProfile, ...]:
        """Stable iteration makes routing and explanations deterministic."""

        return tuple(
            sorted(
                self._models.values(),
                key=lambda model: (model.provider.value, model.model_id),
            )
        )

    def provider_state(self, provider: ProviderKind | str) -> ProviderState:
        provider_kind = _coerce_enum(ProviderKind, provider, "fournisseur")
        return self._provider_states.get(provider_kind, ProviderState(provider=provider_kind))


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    """Explicit authorization boundary for the zero-spend router.

    The default authorizes no provider.  This prevents a newly registered cloud
    model from becoming callable merely because it exists in a configuration
    file.  The host must opt in with ``RouterPolicy.zero_spend({...})``.
    """

    allowed_providers: frozenset[ProviderKind] = field(default_factory=frozenset)
    max_fallbacks: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_providers", _coerce_providers(self.allowed_providers))
        if not isinstance(self.max_fallbacks, int) or not 0 <= self.max_fallbacks <= 16:
            raise FreeAIRouterError("max_fallbacks doit être un entier entre 0 et 16.")

    @classmethod
    def zero_spend(
        cls,
        allowed_providers: Iterable[ProviderKind | str],
        *,
        max_fallbacks: int = 3,
    ) -> "RouterPolicy":
        """Build the strict policy; price validation remains non-negotiable."""

        return cls(
            allowed_providers=_coerce_providers(allowed_providers),
            max_fallbacks=max_fallbacks,
        )

    @classmethod
    def offline_only(cls, *, max_fallbacks: int = 3) -> "RouterPolicy":
        return cls.zero_spend({ProviderKind.OLLAMA_LOCAL}, max_fallbacks=max_fallbacks)


@dataclass(frozen=True, slots=True)
class TaskClassification:
    """A compact, reproducible interpretation of a request's technical needs."""

    kind: TaskKind
    required_capabilities: frozenset[Capability]
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _coerce_enum(TaskKind, self.kind, "type de tâche"))
        object.__setattr__(self, "required_capabilities", _coerce_capabilities(self.required_capabilities))
        object.__setattr__(self, "signals", tuple(sorted({str(item) for item in self.signals})))

    def with_capability(self, capability: Capability | str) -> "TaskClassification":
        return TaskClassification(
            kind=self.kind,
            required_capabilities=self.required_capabilities
            | frozenset({_coerce_enum(Capability, capability, "capacité")}),
            signals=self.signals,
        )


def classify_task(
    message: str,
    *,
    requested_capabilities: Iterable[Capability | str] = (),
    approved_tool_names: Iterable[str] = (),
) -> TaskClassification:
    """Classify only by deterministic local rules, never by a model call.

    The returned object intentionally does not retain the message.  The caller
    keeps the actual prompt separately if it later elects to send it to an
    approved provider.
    """

    if not isinstance(message, str):
        raise FreeAIRouterError("La demande doit être un texte.")
    cleaned = " ".join(message.split())
    if not cleaned:
        raise FreeAIRouterError("La demande ne peut pas être vide.")
    if len(cleaned) > MAX_CLASSIFICATION_CHARS:
        raise FreeAIRouterError(
            f"La demande dépasse la limite locale de {MAX_CLASSIFICATION_CHARS} caractères."
        )
    folded = _fold(cleaned)
    signals: list[str] = []
    required: set[Capability] = {Capability.TEXT}

    spreadsheet_terms = ("excel", "xlsx", "xls", "csv", "tableur", "spreadsheet", "tableau")
    document_terms = ("pdf", "document", "docx", "cours", "cv", "resume")
    vision_terms = ("image", "photo", "capture", "screenshot", "scan")
    code_terms = ("code", "python", "javascript", "typescript", "programme", "debug")
    analysis_terms = ("analyse", "analy", "calcul", "statistique", "finance", "synthese", "resume")

    has_spreadsheet = any(term in folded for term in spreadsheet_terms)
    has_document = any(term in folded for term in document_terms)
    has_vision = any(term in folded for term in vision_terms)
    has_code = any(term in folded for term in code_terms)
    has_analysis = any(term in folded for term in analysis_terms)
    tool_names = tuple(approved_tool_names)

    if has_spreadsheet:
        kind = TaskKind.SPREADSHEET_ANALYSIS
        required.update({Capability.SPREADSHEETS, Capability.ANALYSIS})
        signals.append("spreadsheet")
    elif has_vision:
        kind = TaskKind.VISION_ANALYSIS
        required.add(Capability.VISION)
        signals.append("vision")
    elif has_code:
        kind = TaskKind.CODE_ASSISTANCE
        required.add(Capability.CODE)
        signals.append("code")
    elif has_document:
        kind = TaskKind.DOCUMENT_ANALYSIS
        required.add(Capability.DOCUMENTS)
        signals.append("document")
    else:
        kind = TaskKind.GENERAL

    if has_analysis:
        required.add(Capability.ANALYSIS)
        signals.append("analysis")
    if tool_names:
        kind = TaskKind.TOOL_ORCHESTRATION
        required.add(Capability.FUNCTION_CALLING)
        signals.append("tools")
    required.update(_coerce_capabilities(requested_capabilities))
    return TaskClassification(
        kind=kind,
        required_capabilities=frozenset(required),
        signals=tuple(signals),
    )


@dataclass(frozen=True, slots=True)
class FunctionTool:
    """A server-owned function declaration, not executable user input."""

    name: str
    description: str
    parameters_schema: Mapping[str, JsonValue]
    allowed_task_kinds: frozenset[TaskKind] = field(default_factory=frozenset)
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not _FUNCTION_NAME_PATTERN.fullmatch(name):
            raise FreeAIRouterError("Le nom de fonction doit être un identifiant sûr en snake_case.")
        description = " ".join(self.description.split())
        if not description:
            raise FreeAIRouterError("Chaque fonction doit avoir une description.")
        frozen_schema = _freeze_json(self.parameters_schema, label="Le schéma de fonction")
        if not isinstance(frozen_schema, Mapping) or frozen_schema.get("type") != "object":
            raise FreeAIRouterError("Le schéma des paramètres doit être un objet JSON Schema.")
        properties = frozen_schema.get("properties", MappingProxyType({}))
        if not isinstance(properties, Mapping):
            raise FreeAIRouterError("Les propriétés du schéma doivent être un objet.")
        required = frozen_schema.get("required", ())
        if not isinstance(required, tuple) or not all(isinstance(item, str) for item in required):
            raise FreeAIRouterError("Les paramètres requis doivent être une liste de noms textuels.")
        unknown_required = sorted(set(required) - set(properties))
        if unknown_required:
            raise FreeAIRouterError(
                "Les paramètres requis sont absents du schéma : " + ", ".join(unknown_required)
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "parameters_schema", frozen_schema)
        object.__setattr__(self, "allowed_task_kinds", _coerce_task_kinds(self.allowed_task_kinds))

    def as_openai_tool(self) -> dict[str, object]:
        """Plain JSON compatible with OpenAI-style adapters, without imports."""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _json_to_plain(self.parameters_schema),
            },
        }

    def as_gemini_declaration(self) -> dict[str, object]:
        """Plain declaration a Gemini adapter can convert to its SDK type."""

        return {
            "name": self.name,
            "description": self.description,
            "parameters_json_schema": _json_to_plain(self.parameters_schema),
        }


class FunctionToolRegistry:
    """Finite function allow-list that a model cannot enlarge at runtime."""

    def __init__(self, tools: Iterable[FunctionTool] = ()) -> None:
        self._tools: dict[str, FunctionTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: FunctionTool) -> None:
        if not isinstance(tool, FunctionTool):
            raise FreeAIRouterError("Le registre d'outils accepte uniquement des FunctionTool.")
        if tool.name in self._tools:
            raise FreeAIRouterError(f"La fonction '{tool.name}' est déjà déclarée.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> FunctionTool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise FunctionCallValidationError(
                f"La fonction '{name}' n'est pas dans l'allow-list locale."
            ) from error


@dataclass(frozen=True, slots=True)
class StructuredFunctionCall:
    """Validated, data-only call awaiting execution by the controlled host."""

    call_id: str
    name: str
    arguments: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PreparedFunctionCalls:
    """A restricted function contract passed to a future provider adapter."""

    classification: TaskClassification
    tools: tuple[FunctionTool, ...] = ()

    @property
    def allowed_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    @property
    def is_empty(self) -> bool:
        return not self.tools

    def provider_payload(self, protocol: str) -> list[dict[str, object]]:
        """Return inert JSON declarations for a named future adapter protocol."""

        if protocol == "openai_compatible":
            return [tool.as_openai_tool() for tool in self.tools]
        if protocol == "gemini":
            return [tool.as_gemini_declaration() for tool in self.tools]
        if protocol == "ollama":
            return [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": _json_to_plain(tool.parameters_schema),
                    },
                }
                for tool in self.tools
            ]
        raise FreeAIRouterError("Protocole de function calling inconnu.")

    def validate_proposal(
        self,
        *,
        call_id: str,
        name: str,
        arguments: Mapping[str, Any],
    ) -> StructuredFunctionCall:
        """Validate a provider response before *another* layer may execute it."""

        if not _CALL_ID_PATTERN.fullmatch(call_id):
            raise FunctionCallValidationError("L'identifiant d'appel de fonction est invalide.")
        tool = next((candidate for candidate in self.tools if candidate.name == name), None)
        if tool is None:
            raise FunctionCallValidationError(
                f"La fonction '{name}' n'a pas été autorisée pour cette requête."
            )
        frozen_arguments = _freeze_json(arguments, label="Les arguments de fonction")
        if not isinstance(frozen_arguments, Mapping):
            raise FunctionCallValidationError("Les arguments de fonction doivent être un objet JSON.")
        _validate_against_object_schema(frozen_arguments, tool.parameters_schema)
        return StructuredFunctionCall(
            call_id=call_id,
            name=name,
            arguments=frozen_arguments,
        )


def prepare_function_calls(
    classification: TaskClassification,
    registry: FunctionToolRegistry,
    *,
    approved_names: Iterable[str] = (),
) -> PreparedFunctionCalls:
    """Prepare only server-approved functions for a classified request.

    An empty ``approved_names`` yields no tools.  A prompt alone can therefore
    never expose a filesystem, shell, Python or network capability.
    """

    names = tuple(sorted(set(approved_names)))
    selected: list[FunctionTool] = []
    for name in names:
        tool = registry.get(name)
        if tool.allowed_task_kinds and classification.kind not in tool.allowed_task_kinds:
            raise FunctionCallValidationError(
                f"La fonction '{name}' n'est pas autorisée pour '{classification.kind.value}'."
            )
        selected.append(tool)
    return PreparedFunctionCalls(classification=classification, tools=tuple(selected))


def _validate_against_object_schema(
    arguments: Mapping[str, JsonValue],
    schema: Mapping[str, JsonValue],
) -> None:
    """Validate the conservative JSON Schema subset Côme AI needs locally."""

    properties = schema.get("properties", MappingProxyType({}))
    if not isinstance(properties, Mapping):
        raise FunctionCallValidationError("Le schéma de fonction est mal formé.")
    required = schema.get("required", ())
    if not isinstance(required, tuple):
        raise FunctionCallValidationError("Le schéma de fonction est mal formé.")
    missing = [name for name in required if name not in arguments]
    if missing:
        raise FunctionCallValidationError("Arguments requis manquants : " + ", ".join(missing))
    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise FunctionCallValidationError(
                "Arguments non autorisés : " + ", ".join(unexpected)
            )
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            continue
        expected_type = property_schema.get("type")
        if isinstance(expected_type, str) and not _matches_json_type(value, expected_type):
            raise FunctionCallValidationError(
                f"L'argument '{name}' doit être de type {expected_type}."
            )


def _matches_json_type(value: JsonValue, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, tuple)
    if expected_type == "null":
        return value is None
    # The future adapter may use a JSON Schema type outside this small local
    # validator.  Passing it through is safer than pretending it was checked.
    return True


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """The input to selection, devoid of credentials and network behaviour."""

    classification: TaskClassification
    mode: RoutingMode = RoutingMode.AUTOMATIC
    function_calls: PreparedFunctionCalls | None = None
    max_fallbacks: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _coerce_enum(RoutingMode, self.mode, "mode"))
        classification = self.classification
        if not isinstance(classification, TaskClassification):
            raise FreeAIRouterError("classification doit être un TaskClassification.")
        if self.function_calls is not None:
            if not isinstance(self.function_calls, PreparedFunctionCalls):
                raise FreeAIRouterError("function_calls doit être un PreparedFunctionCalls.")
            if not self.function_calls.is_empty:
                classification = classification.with_capability(Capability.FUNCTION_CALLING)
        object.__setattr__(self, "classification", classification)
        if self.max_fallbacks is not None and (
            not isinstance(self.max_fallbacks, int) or self.max_fallbacks < 0
        ):
            raise FreeAIRouterError("max_fallbacks doit être un entier positif ou nul.")


def build_route_request(
    message: str,
    *,
    mode: RoutingMode | str = RoutingMode.AUTOMATIC,
    requested_capabilities: Iterable[Capability | str] = (),
    tool_registry: FunctionToolRegistry | None = None,
    approved_tool_names: Iterable[str] = (),
    max_fallbacks: int | None = None,
) -> RouteRequest:
    """Convenience boundary used by a web handler before adapter invocation."""

    names = tuple(approved_tool_names)
    classification = classify_task(
        message,
        requested_capabilities=requested_capabilities,
        approved_tool_names=names,
    )
    if names and tool_registry is None:
        raise FreeAIRouterError("Un registre d'outils est requis pour préparer des function calls.")
    prepared = (
        prepare_function_calls(classification, tool_registry, approved_names=names)
        if tool_registry is not None
        else None
    )
    return RouteRequest(
        classification=classification,
        mode=_coerce_enum(RoutingMode, mode, "mode"),
        function_calls=prepared,
        max_fallbacks=max_fallbacks,
    )


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    model: ModelProfile
    accepted: bool
    rejection_codes: tuple[RejectionCode, ...] = ()
    score: tuple[object, ...] | None = None

    @property
    def rejection_messages(self) -> tuple[str, ...]:
        return tuple(_REJECTION_TEXT[code] for code in self.rejection_codes)


@dataclass(frozen=True, slots=True)
class ProviderQuotaDisclosure:
    provider: ProviderKind
    quota: QuotaState

    def public_dict(self) -> dict[str, object]:
        return {"provider": self.provider.value, **self.quota.public_dict()}


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    """Data passed from a selected route to a future, separately controlled adapter."""

    provider: ProviderKind
    model_id: str
    message: str
    function_calls: PreparedFunctionCalls | None = None


class ProviderAdapter(Protocol):
    """Extension point.  Implementations may use network only outside this module."""

    provider: ProviderKind

    def generate(self, invocation: ProviderInvocation) -> object: ...


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Inspectable route and genuinely free fallback plan."""

    status: RouteStatus
    request: RouteRequest
    primary: ModelProfile | None
    fallbacks: tuple[ModelProfile, ...]
    evaluations: tuple[CandidateEvaluation, ...]
    quota_disclosures: tuple[ProviderQuotaDisclosure, ...]
    explanations: tuple[str, ...]

    @property
    def is_selected(self) -> bool:
        return self.status is RouteStatus.SELECTED and self.primary is not None

    def build_invocation(self, message: str) -> ProviderInvocation:
        """Create data for an adapter without invoking it or validating secrets."""

        if not self.is_selected or self.primary is None:
            raise FreeAIRouterError("Aucun modèle n'a été approuvé pour cette demande.")
        if not isinstance(message, str) or not message.strip():
            raise FreeAIRouterError("Le message à transmettre doit être un texte non vide.")
        return ProviderInvocation(
            provider=self.primary.provider,
            model_id=self.primary.model_id,
            message=message,
            function_calls=self.request.function_calls,
        )

    def public_dict(self) -> dict[str, object]:
        """A UI-safe snapshot: explicit model state, no invented quota value."""

        return {
            "status": self.status.value,
            "primary": _public_model(self.primary) if self.primary else None,
            "fallbacks": [_public_model(model) for model in self.fallbacks],
            "required_capabilities": sorted(
                capability.value for capability in self.request.classification.required_capabilities
            ),
            "quota": [disclosure.public_dict() for disclosure in self.quota_disclosures],
            "explanations": list(self.explanations),
            "rejections": [
                {
                    "model_id": evaluation.model.model_id,
                    "codes": [code.value for code in evaluation.rejection_codes],
                }
                for evaluation in self.evaluations
                if not evaluation.accepted
            ],
        }


def _public_model(model: ModelProfile) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "label": model.label,
        "provider": model.provider.value,
        "local": model.is_local,
        "capabilities": sorted(capability.value for capability in model.capabilities),
    }


class FreeAIRouter:
    """Select a configuration-provided, verified-free model without I/O."""

    def __init__(self, registry: ModelRegistry, policy: RouterPolicy | None = None) -> None:
        if not isinstance(registry, ModelRegistry):
            raise FreeAIRouterError("registry doit être un ModelRegistry.")
        self.registry = registry
        self.policy = policy or RouterPolicy()
        if not isinstance(self.policy, RouterPolicy):
            raise FreeAIRouterError("policy doit être un RouterPolicy.")

    def route(self, request: RouteRequest) -> RoutingDecision:
        """Return an approval/denial and fallback plan; never call a provider."""

        if not isinstance(request, RouteRequest):
            raise FreeAIRouterError("request doit être un RouteRequest.")
        evaluations = tuple(self._evaluate(model, request) for model in self.registry.models())
        approved = sorted(
            (evaluation for evaluation in evaluations if evaluation.accepted),
            key=lambda evaluation: evaluation.score or (),
        )
        fallback_limit = self.policy.max_fallbacks
        if request.max_fallbacks is not None:
            fallback_limit = min(fallback_limit, request.max_fallbacks)

        if not approved:
            return RoutingDecision(
                status=RouteStatus.DENIED,
                request=request,
                primary=None,
                fallbacks=(),
                evaluations=evaluations,
                quota_disclosures=(),
                explanations=self._denial_explanations(request, evaluations),
            )

        primary = approved[0].model
        fallbacks = tuple(item.model for item in approved[1 : 1 + fallback_limit])
        planned_models = (primary, *fallbacks)
        disclosures = _quota_disclosures(planned_models, self.registry)
        return RoutingDecision(
            status=RouteStatus.SELECTED,
            request=request,
            primary=primary,
            fallbacks=fallbacks,
            evaluations=evaluations,
            quota_disclosures=disclosures,
            explanations=self._selection_explanations(request, primary, fallbacks, disclosures),
        )

    def _evaluate(self, model: ModelProfile, request: RouteRequest) -> CandidateEvaluation:
        state = self.registry.provider_state(model.provider)
        reasons: list[RejectionCode] = []
        if not model.enabled:
            reasons.append(RejectionCode.MODEL_DISABLED)
        if model.provider not in self.policy.allowed_providers:
            reasons.append(RejectionCode.PROVIDER_NOT_AUTHORIZED)
        if request.mode is RoutingMode.OFFLINE and not model.is_local:
            reasons.append(RejectionCode.OFFLINE_REQUIRES_LOCAL)
        if state.availability is AvailabilityStatus.UNAVAILABLE:
            reasons.append(RejectionCode.PROVIDER_UNAVAILABLE)
        elif state.availability is AvailabilityStatus.UNKNOWN:
            reasons.append(RejectionCode.PROVIDER_AVAILABILITY_UNKNOWN)
        if model.price.status is PricingStatus.UNKNOWN:
            reasons.append(RejectionCode.PRICING_UNKNOWN)
        elif model.price.status is PricingStatus.ZERO_UNCONFIRMED:
            reasons.append(RejectionCode.ZERO_PRICE_UNCONFIRMED)
        elif model.price.status is PricingStatus.NON_ZERO:
            reasons.append(RejectionCode.PRICE_NOT_ZERO)
        if state.quota.status is QuotaStatus.EXHAUSTED:
            reasons.append(RejectionCode.QUOTA_EXHAUSTED)
        missing = request.classification.required_capabilities - model.capabilities
        if missing:
            reasons.append(RejectionCode.MISSING_CAPABILITY)
        score = None if reasons else _selection_score(model, request.mode)
        return CandidateEvaluation(
            model=model,
            accepted=not reasons,
            rejection_codes=tuple(reasons),
            score=score,
        )

    def _selection_explanations(
        self,
        request: RouteRequest,
        primary: ModelProfile,
        fallbacks: Sequence[ModelProfile],
        disclosures: Sequence[ProviderQuotaDisclosure],
    ) -> tuple[str, ...]:
        mode_text = {
            RoutingMode.AUTOMATIC: "Mode automatique : préférence locale à capacités égales.",
            RoutingMode.OFFLINE: "Mode hors ligne : seuls les modèles Ollama locaux sont admissibles.",
            RoutingMode.PERFORMANCE: "Mode performance : meilleur quality_rank configuré parmi les modèles gratuits autorisés.",
        }[request.mode]
        required = ", ".join(
            capability.value for capability in sorted(request.classification.required_capabilities, key=str)
        )
        lines = [
            mode_text,
            f"Besoins validés : {required}.",
            (
                f"Sélection : {primary.label} via {_PROVIDER_LABELS[primary.provider]} "
                "(prix confirmé nul dans la configuration)."
            ),
        ]
        if fallbacks:
            lines.append(
                "Fallback gratuit autorisé : " + ", ".join(model.label for model in fallbacks) + "."
            )
        else:
            lines.append("Aucun fallback gratuit autorisé n'est actuellement configuré.")
        for disclosure in disclosures:
            if disclosure.quota.status is QuotaStatus.UNKNOWN:
                lines.append(
                    f"Quota {_PROVIDER_LABELS[disclosure.provider]} : inconnu, aucune valeur n'est inventée."
                )
            elif disclosure.quota.status is QuotaStatus.AVAILABLE:
                if disclosure.quota.remaining_requests is None:
                    lines.append(
                        f"Quota {_PROVIDER_LABELS[disclosure.provider]} : disponible, quantité non communiquée."
                    )
                else:
                    lines.append(
                        f"Quota {_PROVIDER_LABELS[disclosure.provider]} : "
                        f"{disclosure.quota.remaining_requests} requête(s) déclarée(s) restante(s)."
                    )
        return tuple(lines)

    def _denial_explanations(
        self,
        request: RouteRequest,
        evaluations: Sequence[CandidateEvaluation],
    ) -> tuple[str, ...]:
        lines = [
            "Aucun modèle n'est autorisé pour cette demande sans dépense.",
            "Le routeur n'enverra aucun appel externe.",
        ]
        if not self.policy.allowed_providers:
            lines.append("Aucun fournisseur n'a été autorisé dans la politique locale.")
        if request.mode is RoutingMode.OFFLINE:
            lines.append("Le mode hors ligne exige un modèle Ollama local disponible et confirmé gratuit.")
        if not evaluations:
            lines.append("Le registre de modèles est vide.")
            return tuple(lines)
        for evaluation in evaluations:
            if evaluation.rejection_codes:
                text = "; ".join(evaluation.rejection_messages)
                lines.append(f"{evaluation.model.label} refusé : {text}.")
        return tuple(lines)


def _selection_score(model: ModelProfile, mode: RoutingMode) -> tuple[object, ...]:
    """Lower is better.  All components are config data, so ordering is stable."""

    context = model.context_window or 0
    if mode is RoutingMode.AUTOMATIC:
        return (
            0 if model.is_local else 1,
            -model.quality_rank,
            -context,
            model.provider.value,
            model.model_id,
        )
    if mode is RoutingMode.PERFORMANCE:
        return (
            -model.quality_rank,
            -context,
            0 if model.is_local else 1,
            model.provider.value,
            model.model_id,
        )
    return (-model.quality_rank, -context, model.model_id)


def _quota_disclosures(
    models: Sequence[ModelProfile], registry: ModelRegistry
) -> tuple[ProviderQuotaDisclosure, ...]:
    providers = sorted({model.provider for model in models}, key=lambda provider: provider.value)
    return tuple(
        ProviderQuotaDisclosure(provider=provider, quota=registry.provider_state(provider).quota)
        for provider in providers
    )


__all__ = [
    "AvailabilityStatus",
    "CandidateEvaluation",
    "Capability",
    "FreeAIRouter",
    "FreeAIRouterError",
    "FunctionCallValidationError",
    "FunctionTool",
    "FunctionToolRegistry",
    "ModelProfile",
    "ModelRegistry",
    "PreparedFunctionCalls",
    "PriceDeclaration",
    "PricingStatus",
    "ProviderAdapter",
    "ProviderInvocation",
    "ProviderKind",
    "ProviderQuotaDisclosure",
    "ProviderState",
    "QuotaState",
    "QuotaStatus",
    "RejectionCode",
    "RouteRequest",
    "RouteStatus",
    "RouterPolicy",
    "RoutingDecision",
    "RoutingMode",
    "StructuredFunctionCall",
    "TaskClassification",
    "TaskKind",
    "build_route_request",
    "classify_task",
    "prepare_function_calls",
]
