"""Constitution exécutable — règles métier formelles, versionnées, testables.

SPEC-014.  Les règles métier du workspace Career (fraîcheur, matching,
déduplication, confidentialité, export) sont formalisées ici sous forme de
règles atomiques.  Une règle est une expression déterministe évaluée sur un
contexte nommé ; elle ne prétend jamais prédire une décision humaine et
n'appelle jamais le réseau.

Choix structurants :

* le DSL est un sous-ensemble de CEL (Common Expression Language) interprété
  par un analyseur syntaxique écrit pour ce projet.  Aucun ``eval`` ni
  ``exec`` : une expression ne peut ni lire un fichier ni lancer un
  processus ;
* une expression renvoie un booléen.  Vrai = la règle est respectée ;
* une donnée absente n'est pas une violation : le résultat est marqué
  ``not_evaluable`` et la règle ne compte ni dans le score ni dans les
  violations critiques.  Inventorier une donnée manquante doit rester un
  travail humain ;
* la gouvernance (draft → review → approbation → active → dépréciée →
  archivée), le versionnage, les signatures et l'audit vivent dans
  :mod:`career.constitution_store`, la dérive dans
  :mod:`career.constitution_audit`.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from workspace_core import UserFacingError

from .models import clean_text, utc_now


# --- Constantes du domaine ---------------------------------------------------

CONSTITUTION_VERSION = "1.0.0"

DOMAINS: tuple[str, ...] = ("freshness", "matching", "dedup", "privacy", "export")
ENTITY_TYPES: tuple[str, ...] = ("offer", "profile", "evidence", "requirement", "matching", "export")
RULE_STATUSES: tuple[str, ...] = ("draft", "active", "deprecated", "archived")
SEVERITIES: tuple[str, ...] = ("info", "warning", "error", "critical")
SEVERITY_ORDER: dict[str, int] = {"info": 0, "warning": 1, "error": 2, "critical": 3}
DSL_TYPES: tuple[str, ...] = ("cel",)
SUPPORTED_DSL_TYPES: tuple[str, ...] = ("cel",)

#: Une expression est validée syntaxiquement avant d'être stockée.
MAX_EXPRESSION_LENGTH = 2_000
MAX_RULE_ID_LENGTH = 160
RULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")

#: Clés réservées dans un contexte d'évaluation.
ENTITY_ID_KEY = "entity_id"
ENTITY_TYPE_KEY = "entity_type"


class ConstitutionError(Exception):
    """Base des erreurs de la Constitution exécutable."""


class ExpressionError(ConstitutionError):
    """L'expression est syntaxiquement invalide."""


class EvaluationError(ConstitutionError):
    """L'expression est valide mais ne peut pas être évaluée sur ce contexte."""


class MissingFieldError(EvaluationError):
    """Un champ référencé par l'expression est absent du contexte."""


# --- Modèles de données ------------------------------------------------------


@dataclass
class Rule:
    """Règle atomique de la Constitution."""

    rule_id: str
    name: str
    domain: str
    version: int
    status: str
    description: str
    rationale: str
    expression: str
    dsl_type: str
    parameters: dict[str, Any]
    scope: list[str]
    tags: list[str]
    created_at: str
    updated_at: str
    created_by: str
    approved_by: str | None = None
    approved_at: str | None = None
    severity: str = "error"
    remediation: str | None = None
    source_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "domain": self.domain,
            "version": self.version,
            "status": self.status,
            "description": self.description,
            "rationale": self.rationale,
            "expression": self.expression,
            "dsl_type": self.dsl_type,
            "parameters": dict(self.parameters),
            "scope": list(self.scope),
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "severity": self.severity,
            "remediation": self.remediation,
            "source_reference": self.source_reference,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Rule":
        return cls(
            rule_id=str(data.get("rule_id", "")),
            name=str(data.get("name", "")),
            domain=str(data.get("domain", "")),
            version=int(data.get("version", 1) or 1),
            status=str(data.get("status", "draft")),
            description=str(data.get("description", "")),
            rationale=str(data.get("rationale", "")),
            expression=str(data.get("expression", "")),
            dsl_type=str(data.get("dsl_type", "cel")),
            parameters=dict(data.get("parameters") or {}),
            scope=list(data.get("scope") or []),
            tags=list(data.get("tags") or []),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            created_by=str(data.get("created_by", "")),
            approved_by=data.get("approved_by"),
            approved_at=data.get("approved_at"),
            severity=str(data.get("severity", "error") or "error"),
            remediation=data.get("remediation"),
            source_reference=data.get("source_reference"),
        )


@dataclass
class RuleSet:
    """Ensemble cohérent de règles, versionné et daté."""

    ruleset_id: str
    name: str
    version: int
    rules: list[str]
    description: str
    effective_from: str
    effective_until: str | None = None
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleset_id": self.ruleset_id,
            "name": self.name,
            "version": self.version,
            "rules": list(self.rules),
            "description": self.description,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleSet":
        return cls(
            ruleset_id=str(data.get("ruleset_id", "")),
            name=str(data.get("name", "")),
            version=int(data.get("version", 1) or 1),
            rules=list(data.get("rules") or []),
            description=str(data.get("description", "")),
            effective_from=str(data.get("effective_from", "")),
            effective_until=data.get("effective_until"),
            supersedes=data.get("supersedes"),
        )


@dataclass
class ValidationResult:
    """Résultat de l'évaluation d'une règle sur une entité."""

    entity_id: str
    entity_type: str
    rule_id: str
    passed: bool
    details: dict[str, Any]
    severity: str
    remediation: str | None = None
    status: str = "failed"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "rule_id": self.rule_id,
            "passed": self.passed,
            "details": dict(self.details),
            "severity": self.severity,
            "remediation": self.remediation,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class Violation:
    """Règle non respectée sur une entité."""

    rule_id: str
    entity_id: str
    entity_type: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "severity": self.severity,
            "message": self.message,
            "details": dict(self.details),
            "remediation": self.remediation,
        }


@dataclass
class ConformanceReport:
    """Rapport de conformité d'une entité face à un RuleSet."""

    entity_id: str
    entity_type: str
    ruleset_version: int
    total_rules: int
    passed: int
    warnings: int
    errors: int
    critical: int
    compliance_score: float
    violations: list[Violation]
    trends: dict[str, float]
    ruleset_id: str = ""
    not_evaluable: int = 0
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "ruleset_version": self.ruleset_version,
            "total_rules": self.total_rules,
            "passed": self.passed,
            "warnings": self.warnings,
            "errors": self.errors,
            "critical": self.critical,
            "compliance_score": self.compliance_score,
            "violations": [violation.to_dict() for violation in self.violations],
            "trends": dict(self.trends),
            "ruleset_id": self.ruleset_id,
            "not_evaluable": self.not_evaluable,
            "checked_at": self.checked_at,
        }


# --- DSL : analyse lexicale --------------------------------------------------

_TOKEN_RE = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<number>\d+\.\d+|\.\d+|\d+)"
    r"|(?P<string>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op><=|>=|==|!=|&&|\|\||[-+*/%<>!])"
    r"|(?P<punct>[.,()\[\]])"
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any
    position: int


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    result: list[str] = []
    index = 0
    while index < len(body):
        character = body[index]
        if character == "\\" and index + 1 < len(body):
            index += 1
            result.append(_ESCAPES.get(body[index], body[index]))
        else:
            result.append(character)
        index += 1
    return "".join(result)


def _tokenize(expression: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    length = len(expression)
    while position < length:
        match = _TOKEN_RE.match(expression, position)
        if match is None:
            raise ExpressionError(
                f"Caractère inattendu à la position {position + 1} : {expression[position]!r}."
            )
        kind = match.lastgroup or ""
        text = match.group()
        start = match.start()
        position = match.end()
        if kind == "space":
            continue
        if kind == "number":
            value: Any = float(text) if "." in text else int(text)
            tokens.append(_Token("number", value, start))
        elif kind == "string":
            tokens.append(_Token("string", _unquote(text), start))
        elif kind == "ident":
            tokens.append(_Token("ident", text, start))
        elif kind == "op":
            tokens.append(_Token("op", text, start))
        else:
            tokens.append(_Token("punct", text, start))
    tokens.append(_Token("end", None, length))
    return tokens


# --- DSL : arbre syntaxique --------------------------------------------------


class _Node:
    """Nœud d'un arbre d'expression CEL restreint."""

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        raise NotImplementedError


@dataclass(frozen=True)
class _Literal(_Node):
    value: Any

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        return self.value


@dataclass(frozen=True)
class _Path(_Node):
    parts: tuple[str, ...]

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        return resolve_path(self.parts, context, scope)


@dataclass(frozen=True)
class _GetAttr(_Node):
    base: _Node
    name: str

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        value = self.base.evaluate(context, scope)
        if isinstance(value, Mapping) and self.name in value:
            return value[self.name]
        raise MissingFieldError(f"Champ absent : {self.name}.")


@dataclass(frozen=True)
class _Index(_Node):
    base: _Node
    index: _Node

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        container = self.base.evaluate(context, scope)
        key = self.index.evaluate(context, scope)
        try:
            if isinstance(container, Mapping):
                return container[key]
            if isinstance(container, (list, tuple)):
                return container[int(key)]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise MissingFieldError(f"Index introuvable : {key!r}.") from error
        raise EvaluationError("Indexation impossible sur cette valeur.")


@dataclass(frozen=True)
class _Unary(_Node):
    operator: str
    operand: _Node

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        value = self.operand.evaluate(context, scope)
        if self.operator == "!":
            if not isinstance(value, bool):
                raise EvaluationError("L'opérateur « ! » attend un booléen.")
            return not value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise EvaluationError("L'opérateur « - » attend un nombre.")
        return -value


@dataclass(frozen=True)
class _Binary(_Node):
    operator: str
    left: _Node
    right: _Node

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        if self.operator == "&&":
            left = self.left.evaluate(context, scope)
            if not isinstance(left, bool):
                raise EvaluationError("L'opérateur « && » attend des booléens.")
            if not left:
                return False
            right = self.right.evaluate(context, scope)
            if not isinstance(right, bool):
                raise EvaluationError("L'opérateur « && » attend des booléens.")
            return right
        if self.operator == "||":
            left = self.left.evaluate(context, scope)
            if not isinstance(left, bool):
                raise EvaluationError("L'opérateur « || » attend des booléens.")
            if left:
                return True
            right = self.right.evaluate(context, scope)
            if not isinstance(right, bool):
                raise EvaluationError("L'opérateur « || » attend des booléens.")
            return right
        left = self.left.evaluate(context, scope)
        right = self.right.evaluate(context, scope)
        return apply_binary(self.operator, left, right)


@dataclass(frozen=True)
class _ListNode(_Node):
    items: tuple[_Node, ...]

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        return [item.evaluate(context, scope) for item in self.items]


@dataclass(frozen=True)
class _Call(_Node):
    path: tuple[str, ...]
    args: tuple[_Node, ...]

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        name = self.path[-1]
        if name == "has":
            if len(self.args) != 1:
                raise EvaluationError("« has » attend un seul argument.")
            return path_exists(self.args[0], context, scope)
        values = [argument.evaluate(context, scope) for argument in self.args]
        if name == "size":
            _expect_arity(name, values, 1)
            return _size_of(values[0])
        if name == "int":
            _expect_arity(name, values, 1)
            return _to_int(values[0])
        if name == "double":
            _expect_arity(name, values, 1)
            return _to_float(values[0])
        if name == "string":
            _expect_arity(name, values, 1)
            return _to_string(values[0])
        if name == "bool":
            _expect_arity(name, values, 1)
            return _to_bool(values[0])
        raise EvaluationError(f"Fonction inconnue : {'.'.join(self.path)}.")


@dataclass(frozen=True)
class _Macro(_Node):
    kind: str
    receiver: _Node
    variable: str
    predicate: _Node

    def evaluate(self, context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
        values = self.receiver.evaluate(context, scope)
        if isinstance(values, Mapping) or not isinstance(values, (list, tuple, str)):
            raise EvaluationError(f"La macro « {self.kind} » attend une liste.")
        if isinstance(values, str):
            values = list(values)
        if self.kind == "map":
            mapped: list[Any] = []
            for element in values:
                child_scope = dict(scope)
                child_scope[self.variable] = element
                mapped.append(self.predicate.evaluate(context, child_scope))
            return mapped
        matched: list[Any] = []
        for element in values:
            child_scope = dict(scope)
            child_scope[self.variable] = element
            outcome = self.predicate.evaluate(context, child_scope)
            if not isinstance(outcome, bool):
                raise EvaluationError(f"Le prédicat de « {self.kind} » doit renvoyer un booléen.")
            if outcome:
                matched.append(element)
        if self.kind == "all":
            return len(matched) == len(values)
        if self.kind == "exists":
            return bool(matched)
        if self.kind == "filter":
            return matched
        raise EvaluationError(f"Macro inconnue : {self.kind}.")


def _expect_arity(name: str, values: Sequence[Any], arity: int) -> None:
    if len(values) != arity:
        raise EvaluationError(f"« {name} » attend {arity} argument(s).")


def _size_of(value: Any) -> int:
    if isinstance(value, (str, list, tuple, dict)):
        return len(value)
    raise EvaluationError("« size » attend une chaîne, une liste ou un objet.")


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        raise EvaluationError("« int » n'accepte pas un booléen.")
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError as error:
            raise EvaluationError("« int » attend un nombre convertible.") from error
    raise EvaluationError("« int » attend un nombre.")


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        raise EvaluationError("« double » n'accepte pas un booléen.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as error:
            raise EvaluationError("« double » attend un nombre convertible.") from error
    raise EvaluationError("« double » attend un nombre.")


def _to_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise EvaluationError("« string » attend une valeur simple.")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise EvaluationError("« bool » attend un booléen.")


def resolve_path(parts: Sequence[str], context: Mapping[str, Any], scope: Mapping[str, Any]) -> Any:
    """Résout un chemin pointé dans le contexte ou la portée de macro."""
    if not parts:
        raise MissingFieldError("Chemin vide.")
    head = parts[0]
    if head in scope:
        current: Any = scope[head]
        remaining = parts[1:]
    else:
        current = context
        remaining = parts
    for part in remaining:
        if isinstance(current, Mapping):
            if part not in current:
                raise MissingFieldError(f"Champ absent : {'.'.join(parts)}.")
            current = current[part]
        else:
            raise MissingFieldError(f"Champ absent : {'.'.join(parts)}.")
    return current


def path_exists(node: _Node, context: Mapping[str, Any], scope: Mapping[str, Any]) -> bool:
    """Retourne vrai si le chemin référencé existe dans le contexte."""
    if not isinstance(node, _Path):
        try:
            node.evaluate(context, scope)
        except MissingFieldError:
            return False
        return True
    parts = node.parts
    if parts[0] in scope:
        current: Any = scope[parts[0]]
        remaining = parts[1:]
    else:
        current = context
        remaining = parts
    for part in remaining:
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return False
    return True


def _equals(left: Any, right: Any) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return list(left) == list(right)
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return dict(left) == dict(right)
    if left is None or right is None:
        return left is None and right is None
    return bool(left == right)


def apply_binary(operator: str, left: Any, right: Any) -> Any:
    """Applique un opérateur binaire CEL restreint."""
    if operator == "==":
        return _equals(left, right)
    if operator == "!=":
        return not _equals(left, right)
    if operator == "in":
        if isinstance(right, (list, tuple)):
            return any(_equals(left, item) for item in right)
        if isinstance(right, str):
            return isinstance(left, str) and left in right
        if isinstance(right, Mapping):
            return left in right
        raise EvaluationError("« in » attend une liste, une chaîne ou un objet à droite.")
    if operator in {"<", "<=", ">", ">="}:
        if isinstance(left, bool) or isinstance(right, bool):
            raise EvaluationError("La comparaison d'un booléen avec un nombre n'a pas de sens.")
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if operator == "<":
                return left < right
            if operator == "<=":
                return left <= right
            if operator == ">":
                return left > right
            return left >= right
        if isinstance(left, str) and isinstance(right, str):
            if operator == "<":
                return left < right
            if operator == "<=":
                return left <= right
            if operator == ">":
                return left > right
            return left >= right
        raise EvaluationError(f"Comparaison impossible entre {type(left).__name__} et {type(right).__name__}.")
    if operator == "+":
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        return _arithmetic(operator, left, right)
    return _arithmetic(operator, left, right)


def _arithmetic(operator: str, left: Any, right: Any) -> Any:
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        raise EvaluationError("Opération arithmétique impossible : l'opérand gauche n'est pas un nombre.")
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        raise EvaluationError("Opération arithmétique impossible : l'opérand droit n'est pas un nombre.")
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if operator == "/":
        if right == 0:
            raise EvaluationError("Division par zéro.")
        if isinstance(left, int) and isinstance(right, int):
            quotient = abs(left) // abs(right)
            return -quotient if (left < 0) != (right < 0) else quotient
        return left / right
    if operator == "%":
        if right == 0:
            raise EvaluationError("Division par zéro.")
        if isinstance(left, int) and isinstance(right, int):
            remainder = abs(left) % abs(right)
            return -remainder if left < 0 else remainder
        raise EvaluationError("Le modulo n'est défini que pour des entiers.")
    raise EvaluationError(f"Opérateur inconnu : {operator}.")


# --- DSL : analyse syntaxique ------------------------------------------------

_MACRO_NAMES = ("all", "exists", "filter", "map")
_GLOBAL_FUNCTIONS = ("size", "int", "double", "string", "bool", "has")
_LITERALS = {"true": True, "false": False, "null": None}


class _Parser:
    """Analyseur descendant récursif du sous-ensemble CEL."""

    def __init__(self, expression: str) -> None:
        self.expression = expression
        self.tokens = _tokenize(expression)
        self.index = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def advance(self) -> _Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, kind: str, value: Any = None) -> _Token | None:
        token = self.current
        if token.kind == kind and (value is None or token.value == value):
            return self.advance()
        return None

    def expect(self, kind: str, value: Any = None) -> _Token:
        token = self.accept(kind, value)
        if token is None:
            raise ExpressionError(f"Syntaxe invalide : {self._describe(self.current)}.")
        return token

    @staticmethod
    def _describe(token: _Token) -> str:
        if token.kind == "end":
            return "fin d'expression inattendue"
        return f"« {token.value} » inattendu à la position {token.position + 1}"

    def parse(self) -> _Node:
        node = self.parse_or()
        if self.current.kind != "end":
            raise ExpressionError(f"Syntaxe invalide : {self._describe(self.current)}.")
        return node

    def parse_or(self) -> _Node:
        node = self.parse_and()
        while self.accept("op", "||"):
            node = _Binary("||", node, self.parse_and())
        return node

    def parse_and(self) -> _Node:
        node = self.parse_relation()
        while self.accept("op", "&&"):
            node = _Binary("&&", node, self.parse_relation())
        return node

    def parse_relation(self) -> _Node:
        node = self.parse_additive()
        token = self.current
        if token.kind == "op" and token.value in {"<", "<=", ">", ">=", "==", "!="}:
            self.advance()
            return _Binary(str(token.value), node, self.parse_additive())
        if token.kind == "ident" and token.value == "in":
            self.advance()
            return _Binary("in", node, self.parse_additive())
        return node

    def parse_additive(self) -> _Node:
        node = self.parse_multiplicative()
        while True:
            token = self.current
            if token.kind == "op" and token.value in {"+", "-"}:
                self.advance()
                node = _Binary(str(token.value), node, self.parse_multiplicative())
                continue
            return node

    def parse_multiplicative(self) -> _Node:
        node = self.parse_unary()
        while True:
            token = self.current
            if token.kind == "op" and token.value in {"*", "/", "%"}:
                self.advance()
                node = _Binary(str(token.value), node, self.parse_unary())
                continue
            return node

    def parse_unary(self) -> _Node:
        token = self.current
        if token.kind == "op" and token.value in {"!", "-"}:
            self.advance()
            return _Unary(str(token.value), self.parse_unary())
        return self.parse_member()

    def parse_member(self) -> _Node:
        node = self.parse_primary()
        while True:
            if self.accept("punct", "."):
                name = self.expect("ident").value
                if self.current.kind == "punct" and self.current.value == "(":
                    arguments = self.parse_arguments()
                    node = self.build_call(node, str(name), arguments)
                    continue
                node = _GetAttr(node, str(name))
                continue
            if self.accept("punct", "["):
                index = self.parse_or()
                self.expect("punct", "]")
                node = _Index(node, index)
                continue
            return node

    def parse_arguments(self) -> list[_Node]:
        self.expect("punct", "(")
        arguments: list[_Node] = []
        if not (self.current.kind == "punct" and self.current.value == ")"):
            arguments.append(self.parse_or())
            while self.accept("punct", ","):
                arguments.append(self.parse_or())
        self.expect("punct", ")")
        return arguments

    def build_call(self, receiver: _Node, name: str, arguments: list[_Node]) -> _Node:
        if name in _MACRO_NAMES:
            if len(arguments) != 2:
                raise ExpressionError(f"La macro « {name} » attend deux arguments (variable, prédicat).")
            variable = arguments[0]
            if not isinstance(variable, _Path) or len(variable.parts) != 1:
                raise ExpressionError(f"Le premier argument de « {name} » doit être un identifiant simple.")
            return _Macro(name, receiver, variable.parts[0], arguments[1])
        path = _flatten_path(receiver)
        if path is None:
            raise ExpressionError(f"Appel de fonction invalide : {name}().")
        return _Call(path + (name,), tuple(arguments))

    def parse_primary(self) -> _Node:
        token = self.current
        if token.kind == "number":
            self.advance()
            return _Literal(token.value)
        if token.kind == "string":
            self.advance()
            return _Literal(token.value)
        if token.kind == "punct" and token.value == "(":
            self.advance()
            node = self.parse_or()
            self.expect("punct", ")")
            return node
        if token.kind == "punct" and token.value == "[":
            self.advance()
            items: list[_Node] = []
            if not (self.current.kind == "punct" and self.current.value == "]"):
                items.append(self.parse_or())
                while self.accept("punct", ","):
                    items.append(self.parse_or())
            self.expect("punct", "]")
            return _ListNode(tuple(items))
        if token.kind == "ident":
            self.advance()
            name = str(token.value)
            if name in _LITERALS:
                return _Literal(_LITERALS[name])
            if self.current.kind == "punct" and self.current.value == "(":
                arguments = self.parse_arguments()
                if name not in _GLOBAL_FUNCTIONS:
                    raise ExpressionError(f"Fonction inconnue : {name}().")
                return _Call((name,), tuple(arguments))
            return _Path((name,))
        raise ExpressionError(f"Syntaxe invalide : {self._describe(token)}.")


def _flatten_path(node: _Node) -> tuple[str, ...] | None:
    if isinstance(node, _Path):
        return node.parts
    if isinstance(node, _GetAttr):
        inner = _flatten_path(node.base)
        if inner is not None:
            return inner + (node.name,)
        return (node.name,)
    return None


@lru_cache(maxsize=1024)
def compile_expression(expression: str) -> _Node:
    """Compile une expression CEL restreinte (cache mémoire, jamais ``eval``)."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("L'expression est vide.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"L'expression dépasse {MAX_EXPRESSION_LENGTH} caractères.")
    return _Parser(expression).parse()


def evaluate_expression(expression: str, context: Mapping[str, Any] | None = None) -> Any:
    """Évalue une expression CEL restreinte sur un contexte."""
    node = compile_expression(expression)
    return node.evaluate(context if isinstance(context, Mapping) else {}, {})


def _walk(node: _Node) -> Iterable[_Node]:
    yield node
    if isinstance(node, _GetAttr):
        yield from _walk(node.base)
    elif isinstance(node, _Index):
        yield from _walk(node.base)
        yield from _walk(node.index)
    elif isinstance(node, _Unary):
        yield from _walk(node.operand)
    elif isinstance(node, _Binary):
        yield from _walk(node.left)
        yield from _walk(node.right)
    elif isinstance(node, _ListNode):
        for item in node.items:
            yield from _walk(item)
    elif isinstance(node, _Call):
        for argument in node.args:
            yield from _walk(argument)
    elif isinstance(node, _Macro):
        yield from _walk(node.receiver)
        yield from _walk(node.predicate)


def _collect_paths(node: _Node, output: list[str], bound: frozenset[str] = frozenset()) -> None:
    """Collecte les chemins pointés complets d'une expression.

    Les variables de macro (``field``, ``req``) ne sont pas des données :
    elles sont exclues des identifiants.
    """
    if isinstance(node, _Path):
        if node.parts[0] not in bound:
            dotted = ".".join(node.parts)
            if dotted not in output:
                output.append(dotted)
        return
    if isinstance(node, _GetAttr):
        inner = _flatten_path(node.base)
        if inner is not None:
            if inner[0] not in bound:
                dotted = ".".join(inner + (node.name,))
                if dotted not in output:
                    output.append(dotted)
            return
        _collect_paths(node.base, output, bound)
        return
    if isinstance(node, _Index):
        _collect_paths(node.base, output, bound)
        _collect_paths(node.index, output, bound)
        return
    if isinstance(node, _Unary):
        _collect_paths(node.operand, output, bound)
        return
    if isinstance(node, _Binary):
        _collect_paths(node.left, output, bound)
        _collect_paths(node.right, output, bound)
        return
    if isinstance(node, _ListNode):
        for item in node.items:
            _collect_paths(item, output, bound)
        return
    if isinstance(node, _Call):
        for argument in node.args:
            _collect_paths(argument, output, bound)
        return
    if isinstance(node, _Macro):
        _collect_paths(node.receiver, output, bound)
        _collect_paths(node.predicate, output, bound | {node.variable})
        return


def expression_identifiers(expression: str) -> list[str]:
    """Liste les chemins pointés référencés par une expression."""
    node = compile_expression(expression)
    identifiers: list[str] = []
    _collect_paths(node, identifiers)
    return identifiers


def expression_summary(expression: str) -> dict[str, Any]:
    """Résumé structuré d'une expression (autocomplétion, audit, UI)."""
    node = compile_expression(expression)
    macros = sorted({current.kind for current in _walk(node) if isinstance(current, _Macro)})
    constants: list[Any] = []
    for current in _walk(node):
        if isinstance(current, _Literal) and isinstance(current.value, (int, float, str, bool)):
            if current.value not in constants:
                constants.append(current.value)
    return {
        "identifiers": expression_identifiers(expression),
        "macros": macros,
        "constants": constants,
        "node_count": sum(1 for _ in _walk(node)),
    }


def check_expression(expression: str) -> dict[str, Any]:
    """Vérifie la syntaxe d'une expression sans l'exécuter."""
    try:
        summary = expression_summary(expression)
    except ExpressionError as error:
        return {"valid": False, "error": str(error), "identifiers": [], "macros": [], "constants": []}
    return {"valid": True, "error": None, **summary}


# --- Validation des règles ----------------------------------------------------


def validate_rule_payload(payload: Mapping[str, Any]) -> list[str]:
    """Retourne la liste des problèmes d'une règle (liste vide = règle valide)."""
    problems: list[str] = []
    rule_id = clean_text(payload.get("rule_id"), limit=MAX_RULE_ID_LENGTH)
    if not rule_id:
        problems.append("L'identifiant de règle est obligatoire.")
    elif not RULE_ID_PATTERN.match(rule_id):
        problems.append("L'identifiant de règle doit être en minuscules, séparé par des points (ex. freshness.certification.max_age).")
    if not clean_text(payload.get("name"), limit=200):
        problems.append("Le nom de la règle est obligatoire.")
    domain = clean_text(payload.get("domain"), limit=40)
    if domain not in DOMAINS:
        problems.append(f"Le domaine doit être l'un de : {', '.join(DOMAINS)}.")
    dsl_type = clean_text(payload.get("dsl_type") or "cel", limit=20)
    if dsl_type not in SUPPORTED_DSL_TYPES:
        problems.append(
            f"Le DSL « {dsl_type} » n'est pas exécutable localement : seul « cel » est pris en charge par le moteur."
        )
    expression = clean_text(payload.get("expression"), limit=MAX_EXPRESSION_LENGTH)
    if not expression:
        problems.append("L'expression de la règle est obligatoire.")
    else:
        try:
            compile_expression(expression)
        except ExpressionError as error:
            problems.append(f"Expression invalide : {error}")
    scope = payload.get("scope") or []
    if not isinstance(scope, (list, tuple)) or not scope:
        problems.append("Le périmètre doit contenir au moins un type d'entité.")
    else:
        for item in scope:
            if clean_text(item, limit=40) not in ENTITY_TYPES:
                problems.append(f"Type d'entité inconnu dans le périmètre : {clean_text(item, limit=40)}.")
    severity = clean_text(payload.get("severity") or "error", limit=20)
    if severity not in SEVERITIES:
        problems.append(f"La sévérité doit être l'un de : {', '.join(SEVERITIES)}.")
    parameters = payload.get("parameters")
    if parameters is not None and not isinstance(parameters, Mapping):
        problems.append("Les paramètres doivent être un objet.")
    return problems


def normalize_rule_payload(
    payload: Mapping[str, Any],
    *,
    version: int = 1,
    status: str = "draft",
    now: str | None = None,
    created_by: str = "local",
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Normalise une règle en un enregistrement stable et JSON-sûr."""
    stamp = now or utc_now()
    parameters = payload.get("parameters")
    normalized_parameters = dict(parameters) if isinstance(parameters, Mapping) else {}
    return {
        "rule_id": clean_text(payload.get("rule_id"), limit=MAX_RULE_ID_LENGTH),
        "name": clean_text(payload.get("name"), limit=200),
        "domain": clean_text(payload.get("domain"), limit=40),
        "version": int(version),
        "status": clean_text(status, limit=20) or "draft",
        "description": clean_text(payload.get("description"), limit=4_000),
        "rationale": clean_text(payload.get("rationale"), limit=4_000),
        "expression": clean_text(payload.get("expression"), limit=MAX_EXPRESSION_LENGTH),
        "dsl_type": clean_text(payload.get("dsl_type") or "cel", limit=20),
        "parameters": normalized_parameters,
        "scope": [clean_text(item, limit=40) for item in (payload.get("scope") or []) if clean_text(item, limit=40)],
        "tags": [clean_text(item, limit=60) for item in (payload.get("tags") or []) if clean_text(item, limit=60)],
        "created_at": stamp,
        "updated_at": stamp,
        "created_by": clean_text(created_by, limit=120) or "local",
        "approved_by": clean_text(approved_by, limit=120) if approved_by else None,
        "approved_at": approved_at,
        "severity": clean_text(payload.get("severity") or "error", limit=20) or "error",
        "remediation": clean_text(payload.get("remediation"), limit=1_000) if payload.get("remediation") else None,
        "source_reference": clean_text(payload.get("source_reference"), limit=400) if payload.get("source_reference") else None,
    }


# --- Contexte d'entité -------------------------------------------------------


def _contract_type(value: Any) -> str:
    """Normalise un libellé de contrat vers la nomenclature de qualification."""
    text = clean_text(value, limit=80).lower().replace("-", "_")
    aliases = {
        "stage": "stage",
        "internship": "stage",
        "intern": "stage",
        "stagiaire": "stage",
        "cdd": "cdd",
        "fixed_term": "cdd",
        "contrat_a_duree_determinee": "cdd",
        "cdi": "cdi",
        "permanent": "cdi",
        "vie": "vie",
    }
    return aliases.get(text, text)


def build_entity_context(
    entity_type: str,
    payload: Mapping[str, Any],
    *,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """Construit le contexte d'évaluation à partir d'une entité métier.

    Seules les valeurs réellement connues sont présentes : un champ absent
    reste absent, la règle correspondante sera marquée « non évaluable »
    plutôt que violée.
    """
    reference = reference_date or date.today()
    context: dict[str, Any] = {
        ENTITY_ID_KEY: clean_text(payload.get("id") or payload.get(ENTITY_ID_KEY), limit=160),
        ENTITY_TYPE_KEY: clean_text(entity_type, limit=40),
    }
    matching: dict[str, Any] = {}
    freshness: dict[str, Any] = {}
    dedup: dict[str, Any] = {}
    privacy: dict[str, Any] = {}
    export: dict[str, Any] = {}

    scoring = payload.get("scoring")
    score = payload.get("score")
    if isinstance(scoring, Mapping):
        total = scoring.get("score")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            matching["score"] = total
        weights = scoring.get("weights")
        if isinstance(weights, Mapping) and weights:
            matching["score_weights"] = {
                "total": sum(value for value in weights.values() if isinstance(value, (int, float)))
            }
    elif isinstance(score, Mapping):
        total = score.get("total", score.get("score"))
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            matching["score"] = total
    elif isinstance(score, (int, float)) and not isinstance(score, bool):
        matching["score"] = score

    duration = payload.get("duration_months")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        matching["duration_months"] = duration

    start_month = payload.get("start_month")
    if isinstance(start_month, (int, float)) and not isinstance(start_month, bool):
        matching["start_month"] = int(start_month)
    else:
        start_date = clean_text(payload.get("start_date"), limit=32)
        if start_date:
            try:
                matching["start_month"] = date.fromisoformat(start_date).month
            except ValueError:
                pass

    contract_type = clean_text(payload.get("contract_type") or payload.get("employment_type"), limit=80)
    if contract_type:
        matching["contract_type"] = _contract_type(contract_type)

    requirements = payload.get("critical_requirements")
    if isinstance(requirements, (list, tuple)):
        matching["critical_requirements"] = [
            {
                "text": clean_text(item.get("text") if isinstance(item, Mapping) else item, limit=240),
                "covered": bool(item.get("covered")) if isinstance(item, Mapping) else False,
            }
            for item in requirements
        ]

    if "score_weights" not in matching:
        from .scoring import SCORING_WEIGHTS  # import tardif : évite un cycle au chargement du module

        matching["score_weights"] = {"total": sum(SCORING_WEIGHTS.values())}

    posted_date = clean_text(payload.get("posted_date"), limit=32)
    if posted_date:
        try:
            age = (reference - date.fromisoformat(posted_date)).days
            freshness["offer"] = {"posted_max_age_days": age}
        except ValueError:
            pass

    certification_age = payload.get("certification_max_age_days")
    if isinstance(certification_age, (int, float)) and not isinstance(certification_age, bool):
        freshness["certification"] = {"max_age_days": certification_age}

    similarity = payload.get("similarity_threshold")
    if isinstance(similarity, (int, float)) and not isinstance(similarity, bool):
        dedup["similarity_threshold"] = similarity

    pii_fields = payload.get("pii_fields")
    if isinstance(pii_fields, (list, tuple)):
        privacy["pii_fields"] = [
            {
                "field": clean_text(item.get("field") if isinstance(item, Mapping) else item, limit=120),
                "encrypted": bool(item.get("encrypted")) if isinstance(item, Mapping) else False,
            }
            for item in pii_fields
        ]

    export_size = payload.get("export_size_mb")
    if isinstance(export_size, (int, float)) and not isinstance(export_size, bool):
        export["docx"] = {"max_size_mb": export_size}

    if matching:
        context["matching"] = matching
    if freshness:
        context["freshness"] = freshness
    if dedup:
        context["dedup"] = dedup
    if privacy:
        context["privacy"] = privacy
    if export:
        context["export"] = export
    return context


# --- Moteur d'évaluation -----------------------------------------------------


class ConstitutionEngine:
    """Moteur d'évaluation des règles de la Constitution.

    Le moteur ne connaît ni le disque ni le réseau : il reçoit des règles et
    un contexte, et renvoie des résultats déterminists.
    """

    def __init__(
        self,
        rules: Mapping[str, Rule | Mapping[str, Any]] | None = None,
        *,
        store: Any = None,
    ) -> None:
        self.store = store
        self._rules: dict[str, Rule] = {}
        for rule_id, rule in (rules or {}).items():
            self._rules[rule_id] = rule if isinstance(rule, Rule) else Rule.from_dict(rule)

    # -- résolution des règles -------------------------------------------------

    def register(self, rule: Rule | Mapping[str, Any]) -> Rule:
        """Enregistre (ou remplace) une règle dans le moteur."""
        resolved = rule if isinstance(rule, Rule) else Rule.from_dict(rule)
        self._rules[resolved.rule_id] = resolved
        return resolved

    def resolve_rule(self, rule_id: str) -> Rule | None:
        """Retourne la version effective d'une règle (active ou dépréciée).

        Quand un store est fourni, la version effective est relue à chaque
        appel : une règle approuvée entre deux évaluations doit l'être
        immédiatement, sans cache obsolète.
        """
        if self.store is not None:
            effective = self.store.effective_rule(rule_id)
            if effective is None:
                return None
            return Rule.from_dict(effective)
        return self._rules.get(rule_id)

    def resolve_ruleset(self, ruleset_id: str) -> RuleSet | None:
        """Retourne un RuleSet depuis le store ou le cache local."""
        if self.store is None:
            return None
        payload = self.store.get_ruleset(ruleset_id)
        if payload is None:
            return None
        return RuleSet.from_dict(payload)

    def effective_rules(self, *, domain: str | None = None) -> list[Rule]:
        """Liste les règles effectives connues du moteur."""
        if self.store is not None:
            rules = [
                Rule.from_dict(payload)
                for payload in self.store.list_rules(status="active") + self.store.list_rules(status="deprecated")
            ]
        else:
            rules = list(self._rules.values())
        if domain:
            rules = [rule for rule in rules if rule.domain == domain]
        return sorted(rules, key=lambda rule: rule.rule_id)

    # -- évaluation ------------------------------------------------------------

    def evaluate(
        self,
        rule: Rule,
        context: Mapping[str, Any] | None = None,
        *,
        entity_id: str = "",
        entity_type: str = "",
    ) -> ValidationResult:
        """Évalue une règle sur un contexte et renvoie un résultat détaillé."""
        payload = context if isinstance(context, Mapping) else {}
        resolved_id = entity_id or clean_text(payload.get(ENTITY_ID_KEY), limit=160)
        resolved_type = entity_type or clean_text(payload.get(ENTITY_TYPE_KEY), limit=40)
        severity = rule.severity if rule.severity in SEVERITIES else "error"
        remediation = rule.remediation or clean_text(rule.parameters.get("remediation"), limit=1_000) or None
        details: dict[str, Any] = {
            "expression": rule.expression,
            "dsl_type": rule.dsl_type,
            "domain": rule.domain,
            "rule_name": rule.name,
            "rule_version": rule.version,
        }
        try:
            value = evaluate_expression(rule.expression, payload)
        except MissingFieldError as error:
            details["status"] = "not_evaluable"
            details["reason"] = str(error)
            return ValidationResult(
                entity_id=resolved_id,
                entity_type=resolved_type,
                rule_id=rule.rule_id,
                passed=False,
                details=details,
                severity="warning" if severity != "critical" else severity,
                remediation=remediation or "Renseigner la donnée manquante pour que la règle puisse être évaluée.",
                status="not_evaluable",
                message=str(error),
            )
        except EvaluationError as error:
            details["status"] = "error"
            details["reason"] = str(error)
            return ValidationResult(
                entity_id=resolved_id,
                entity_type=resolved_type,
                rule_id=rule.rule_id,
                passed=False,
                details=details,
                severity=severity,
                remediation=remediation or "Corriger l'expression ou le contexte fourni.",
                status="error",
                message=str(error),
            )
        if not isinstance(value, bool):
            details["status"] = "error"
            details["reason"] = "L'expression doit renvoyer un booléen."
            return ValidationResult(
                entity_id=resolved_id,
                entity_type=resolved_type,
                rule_id=rule.rule_id,
                passed=False,
                details=details,
                severity=severity,
                remediation=remediation or "Faire renvoyer un booléen à l'expression.",
                status="error",
                message="L'expression doit renvoyer un booléen.",
            )
        details["status"] = "passed" if value else "failed"
        details["value"] = value
        return ValidationResult(
            entity_id=resolved_id,
            entity_type=resolved_type,
            rule_id=rule.rule_id,
            passed=value,
            details=details,
            severity=severity if not value else "info",
            remediation=remediation if not value else None,
            status="passed" if value else "failed",
            message="Règle respectée." if value else "Règle non respectée.",
        )

    def evaluate_all(self, ruleset: RuleSet, entity: Mapping[str, Any]) -> list[ValidationResult]:
        """Évalue toutes les règles d'un RuleSet sur une entité."""
        payload = entity if isinstance(entity, Mapping) else {}
        results: list[ValidationResult] = []
        for rule_id in ruleset.rules:
            rule = self.resolve_rule(rule_id)
            if rule is None:
                continue
            results.append(self.evaluate(rule, payload))
        return results

    def check_conformance(self, entity: Mapping[str, Any], ruleset_id: str) -> ConformanceReport:
        """Évalue une entité face à un RuleSet et renvoie le rapport de conformité."""
        ruleset = self.resolve_ruleset(ruleset_id)
        if ruleset is None:
            raise UserFacingError(f"Le jeu de règles « {ruleset_id} » est introuvable.")
        payload = entity if isinstance(entity, Mapping) else {}
        results = self.evaluate_all(ruleset, payload)
        passed = sum(1 for result in results if result.passed)
        not_evaluable = sum(1 for result in results if result.status == "not_evaluable")
        failed = [result for result in results if not result.passed and result.status != "not_evaluable"]
        warnings = sum(1 for result in failed if result.severity == "warning")
        errors = sum(1 for result in failed if result.severity == "error")
        critical = sum(1 for result in failed if result.severity == "critical")
        denominator = passed + len(failed)
        score = (passed / denominator) if denominator else 1.0
        violations = [
            Violation(
                rule_id=result.rule_id,
                entity_id=result.entity_id,
                entity_type=result.entity_type,
                severity=result.severity,
                message=result.message,
                details=result.details,
                remediation=result.remediation,
            )
            for result in failed
        ]
        trends = self._trends(payload, score)
        return ConformanceReport(
            entity_id=clean_text(payload.get(ENTITY_ID_KEY), limit=160),
            entity_type=clean_text(payload.get(ENTITY_TYPE_KEY), limit=40),
            ruleset_version=ruleset.version,
            total_rules=len(results),
            passed=passed,
            warnings=warnings,
            errors=errors,
            critical=critical,
            compliance_score=round(score, 4),
            violations=violations,
            trends=trends,
            ruleset_id=ruleset_id,
            not_evaluable=not_evaluable,
            checked_at=utc_now(),
        )

    def _trends(self, entity: Mapping[str, Any], score: float) -> dict[str, float]:
        """Historique de score de conformité (store) ou score courant seul."""
        entity_id = clean_text(entity.get(ENTITY_ID_KEY), limit=160)
        trends: dict[str, float] = {"latest": round(score, 4)}
        if self.store is None or not entity_id:
            return trends
        history = self.store.conformance_history(entity_id, limit=10)
        scores = [float(item.get("compliance_score", 0.0)) for item in reversed(history)]
        if scores:
            trends["previous"] = round(scores[-1], 4)
            trends["delta"] = round(score - scores[-1], 4)
            trends["history_length"] = float(len(scores))
        return trends

    def get_violations(self, entity: Mapping[str, Any], severity_min: str = "warning") -> list[Violation]:
        """Liste les violations d'une entité au-dessus d'un seuil de sévérité."""
        threshold = SEVERITY_ORDER.get(severity_min, SEVERITY_ORDER["warning"])
        violations: list[Violation] = []
        for rule in self.effective_rules():
            result = self.evaluate(rule, entity)
            if result.passed or result.status == "not_evaluable":
                continue
            if SEVERITY_ORDER.get(result.severity, 0) < threshold:
                continue
            violations.append(
                Violation(
                    rule_id=result.rule_id,
                    entity_id=result.entity_id,
                    entity_type=result.entity_type,
                    severity=result.severity,
                    message=result.message,
                    details=result.details,
                    remediation=result.remediation,
                )
            )
        return violations


# --- Catalogue de règles par défaut ------------------------------------------

#: Règles issues du code existant : elles décrivent un comportement réel,
#: vérifiable dans le dépôt (colonne ``source_reference``).
#: Règles proposées : elles restent en ``draft`` tant qu'elles ne sont pas
#: approuvées — la Constitution ne s'attribue pas le droit d'imposer un seuil
#: qui n'existe pas encore dans le produit.
DEFAULT_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_id": "matching.score.minimum_match",
        "name": "Score minimum pour un match",
        "domain": "matching",
        "description": "Une offre n'est considérée comme correspondante qu'à partir de 45 points.",
        "rationale": "Le score est un signal de priorité déterministe ; en dessous de 45 points l'offre n'est pas pertinente.",
        "expression": "matching.score >= 45",
        "scope": ["offer"],
        "tags": ["score", "seuil"],
        "severity": "warning",
        "remediation": "Compléter le profil ou les exigences de l'offre pour clarifier la correspondance.",
        "source_reference": "career/service.py:147-149",
        "status": "active",
    },
    {
        "rule_id": "matching.score.strong_match",
        "name": "Score d'une correspondance forte",
        "domain": "matching",
        "description": "Une correspondance forte commence à 70 points.",
        "rationale": "Au-delà de 70 points, l'offre recoupe les préférences déclarées et les faits connus.",
        "expression": "matching.score >= 70",
        "scope": ["offer"],
        "tags": ["score", "seuil"],
        "severity": "info",
        "source_reference": "career/service.py:147-149",
        "status": "active",
    },
    {
        "rule_id": "matching.duration_months.minimum",
        "name": "Durée minimale d'un stage",
        "domain": "matching",
        "description": "Une offre de stage doit proposer au moins six mois.",
        "rationale": "Durée minimale retenue par la qualification des offres.",
        "expression": "matching.duration_months >= 6",
        "scope": ["offer"],
        "tags": ["durée", "seuil"],
        "severity": "error",
        "remediation": "Vérifier la durée annoncée ou les préférences de durée du profil.",
        "source_reference": "career/offer_qualification.py:135",
        "status": "active",
    },
    {
        "rule_id": "matching.duration_months.maximum",
        "name": "Durée maximale d'un stage",
        "domain": "matching",
        "description": "Une offre de stage ne dépasse pas vingt-quatre mois.",
        "rationale": "Au-delà, l'offre n'est plus un stage et sort du périmètre de l'espace Career.",
        "expression": "matching.duration_months <= 24",
        "scope": ["offer"],
        "tags": ["durée", "seuil"],
        "severity": "error",
        "source_reference": "career/offer_qualification.py:152",
        "status": "active",
    },
    {
        "rule_id": "matching.start_month.allowed",
        "name": "Mois de début admis",
        "domain": "matching",
        "description": "Les stages commencent en janvier, février ou mars.",
        "rationale": "Fenêtre de démarrage retenue par la qualification des offres.",
        "expression": "matching.start_month in [1, 2, 3]",
        "scope": ["offer"],
        "tags": ["calendrier", "seuil"],
        "severity": "warning",
        "source_reference": "career/offer_qualification.py:159",
        "status": "active",
    },
    {
        "rule_id": "matching.contract_type.allowed",
        "name": "Types de contrat admis",
        "domain": "matching",
        "description": "Les contrats retenus sont stage, CDD, CDI et VIE.",
        "rationale": "Liste des contrats traités par la qualification locale.",
        "expression": "matching.contract_type in ['stage', 'cdd', 'cdi', 'vie']",
        "scope": ["offer"],
        "tags": ["contrat"],
        "severity": "error",
        "source_reference": "career/offer_qualification.py:163",
        "status": "active",
    },
    {
        "rule_id": "matching.score_weights.total",
        "name": "Somme des poids de scoring",
        "domain": "matching",
        "description": "Les poids de scoring totalisent cent points.",
        "rationale": "Un score sur cent suppose des poids complets ; toute dérive fausserait la comparaison.",
        "expression": "matching.score_weights.total == 100",
        "scope": ["offer", "matching"],
        "tags": ["scoring", "cohérence"],
        "severity": "critical",
        "remediation": "Réaligner career/scoring.py sur la grille de poids officielle.",
        "source_reference": "career/scoring.py:17",
        "status": "active",
    },
    {
        "rule_id": "freshness.certification.max_age_days",
        "name": "Âge maximal d'une certification",
        "domain": "freshness",
        "description": "Une certification de plus de 365 jours doit être renouvelée.",
        "rationale": "Une certification périmée fausserait les correspondances.",
        "expression": "freshness.certification.max_age_days <= 365",
        "scope": ["evidence"],
        "tags": ["fraîcheur", "certification"],
        "severity": "warning",
        "remediation": "Renouveler la certification ou documenter la date de référence.",
        "status": "draft",
    },
    {
        "rule_id": "freshness.offer.posted_max_age_days",
        "name": "Ancienneté maximale d'une offre",
        "domain": "freshness",
        "description": "Une offre publiée depuis plus de quatre-vingt-dix jours est considérée comme périmée.",
        "rationale": "Les offres non actualisées ne reflètent plus le marché local.",
        "expression": "freshness.offer.posted_max_age_days <= 90",
        "scope": ["offer"],
        "tags": ["fraîcheur", "offre"],
        "severity": "warning",
        "remediation": "Actualiser la source de l'offre ou vérifier sa publication.",
        "status": "draft",
    },
    {
        "rule_id": "dedup.similarity_threshold",
        "name": "Seuil de similarité pour la déduplication",
        "domain": "dedup",
        "description": "Proposition : deux offres sont considérées comme doublons à partir de 0,92 de similarité.",
        "rationale": "La déduplication actuelle compare des clés exactes (identifiant de source, URL canonique) : un seuil de similarité reste à valider avant d'être appliqué.",
        "expression": "dedup.similarity_threshold >= 0.92",
        "scope": ["offer"],
        "tags": ["doublons", "seuil"],
        "severity": "warning",
        "status": "draft",
    },
    {
        "rule_id": "privacy.pii_fields.encrypted",
        "name": "Champs personnels chiffrés",
        "domain": "privacy",
        "description": "Chaque champ personnel exporté doit être chiffré.",
        "rationale": "Les données personnelles ne quittent jamais l'espace local sans protection.",
        "expression": "privacy.pii_fields.all(field, field.encrypted == true)",
        "scope": ["profile", "evidence", "export"],
        "tags": ["confidentialité"],
        "severity": "critical",
        "remediation": "Chiffrer le champ ou le retirer de l'export.",
        "status": "draft",
    },
    {
        "rule_id": "export.docx.max_size_mb",
        "name": "Taille maximale d'un export DOCX",
        "domain": "export",
        "description": "Un export DOCX ne dépasse pas dix mégaoctets.",
        "rationale": "Un export volumineux n'est plus lisible et alourdit l'espace local.",
        "expression": "export.docx.max_size_mb <= 10",
        "scope": ["export"],
        "tags": ["export", "seuil"],
        "severity": "warning",
        "remediation": "Réduire la taille de l'export ou corriger la source.",
        "status": "draft",
    },
    {
        "rule_id": "matching.critical_requirements.covered",
        "name": "Exigences critiques couvertes",
        "domain": "matching",
        "description": "Toutes les exigences critiques de l'offre doivent être couvertes par le profil.",
        "rationale": "Une exigence critique non couverte signale un vrai blocage, pas une préférence.",
        "expression": "matching.critical_requirements.all(req, req.covered == true)",
        "scope": ["offer", "requirement"],
        "tags": ["exigences", "bloquant"],
        "severity": "error",
        "remediation": "Traiter l'exigence critique ou documenter pourquoi elle ne s'applique pas.",
        "status": "draft",
    },
)

#: Jeux de règles par défaut.
DEFAULT_RULESETS: tuple[dict[str, Any], ...] = (
    {
        "ruleset_id": "career.core",
        "name": "Constitution Career — socle",
        "description": "Règles effectivement appliquées par le workspace Career au démarrage.",
        "rules": [rule["rule_id"] for rule in DEFAULT_RULES if rule.get("status") == "active"],
    },
    {
        "ruleset_id": "career.offres",
        "name": "Constitution Career — offres",
        "description": "Règles de qualification applicables aux offres importées.",
        "rules": [rule["rule_id"] for rule in DEFAULT_RULES if "offer" in rule.get("scope", [])],
    },
)


# --- Génération de tests ------------------------------------------------------


def _synthetic_context(rule: Rule, *, satisfying: bool) -> dict[str, Any]:
    """Construit un contexte synthétique pour une règle de comparaison simple."""
    context: dict[str, Any] = {}
    try:
        identifiers = expression_identifiers(rule.expression)
    except ExpressionError:
        return context
    for identifier in identifiers:
        parts = identifier.split(".")
        node = context
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = 1
    return context


def generate_rule_tests(rules: Iterable[Rule | Mapping[str, Any]]) -> str:
    """Génère un fichier pytest à partir des règles actives.

    Les tests générés vérifient deux propriétés simples et vérifiables :
    une expression syntaxiquement valide reste évaluable sans lever d'erreur,
    et une règle de comparaison simple respecte son sens (vrai quand la
    contrainte est satisfaite, faux sinon).
    """
    resolved = [rule if isinstance(rule, Rule) else Rule.from_dict(rule) for rule in rules]
    lines: list[str] = [
        '"""Tests générés automatiquement depuis la Constitution exécutable.',
        "",
        "Fichier généré — ne pas éditer à la main. Régénérer avec :",
        "    python -m career.constitution test --generate-tests",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import pytest",
        "",
        "from career.constitution import ConstitutionEngine, Rule",
        "",
        "",
        "RULES = [",
    ]
    for rule in sorted(resolved, key=lambda item: item.rule_id):
        lines.append(f"    Rule.from_dict({rule.to_dict()!r}),")
    lines.extend(
        [
            "]",
            "",
            "",
            "@pytest.mark.parametrize(\"rule\", RULES, ids=lambda rule: rule.rule_id)",
            "def test_rule_expression_is_evaluable(rule: Rule) -> None:",
            '    """Une règle stockée ne doit jamais lever une erreur d\'évaluation."""',
            "    engine = ConstitutionEngine()",
            "    result = engine.evaluate(rule, {})",
            "    assert result.status in {\"passed\", \"failed\", \"not_evaluable\"}",
            "",
            "",
            "@pytest.mark.parametrize(\"rule\", RULES, ids=lambda rule: rule.rule_id)",
            "def test_rule_expression_returns_a_boolean(rule: Rule) -> None:",
            '    """Une expression de règle renvoie un booléen ou signale l\'erreur."""',
            "    engine = ConstitutionEngine()",
            "    result = engine.evaluate(rule, {})",
            "    assert result.status != \"error\" or result.details.get(\"reason\")",
            "",
        ]
    )
    return "\n".join(lines)


# --- Interface en ligne de commande -------------------------------------------


def _default_base_dir() -> Path:
    return Path.cwd()


def _store_for_cli(base_dir: Path) -> Any:
    from .constitution_store import ConstitutionStore

    return ConstitutionStore(base_dir)


def _cli_validate(store: Any) -> int:
    problems: list[str] = []
    for payload in store.list_rules():
        rule = Rule.from_dict(payload)
        for issue in validate_rule_payload(rule.to_dict()):
            problems.append(f"{rule.rule_id} (v{rule.version}) : {issue}")
        if rule.status == "active" and not rule.approved_by:
            problems.append(f"{rule.rule_id} (v{rule.version}) : règle active sans approbation enregistrée.")
    if problems:
        for problem in problems:
            print(f"✗ {problem}")
        print(f"\n{len(problems)} problème(s) de conformité de la Constitution.")
        return 1
    print(f"✓ Constitution valide — {len(store.list_rules())} règle(s) contrôlée(s).")
    return 0


def _cli_check(store: Any, entities: Sequence[Path], *, fail_on_critical: bool = False) -> int:
    engine = ConstitutionEngine(store=store)
    failures = 0
    checked = 0
    critical = 0
    for entity_path in entities:
        try:
            payload = json.loads(entity_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"✗ {entity_path} : lecture impossible ({error}).")
            failures += 1
            continue
        entity_type = str(payload.get("entity_type") or "offer")
        context = payload.get("context") or build_entity_context(entity_type, payload)
        context.setdefault(ENTITY_ID_KEY, str(payload.get("id") or entity_path.stem))
        context.setdefault(ENTITY_TYPE_KEY, entity_type)
        ruleset_id = str(payload.get("ruleset_id") or "career.core")
        try:
            report = engine.check_conformance(context, ruleset_id)
        except UserFacingError as error:
            print(f"✗ {entity_path} : {error}")
            failures += 1
            continue
        checked += 1
        print(f"• {report.entity_id or entity_path.stem} : score {report.compliance_score:.2f} "
              f"({report.passed}/{report.total_rules} règles respectées, {report.critical} critique(s))")
        for violation in report.violations:
            print(f"    - [{violation.severity}] {violation.rule_id} : {violation.message}")
        critical += report.critical
    if failures:
        print(f"\n{failures} entité(s) non contrôlable(s).")
        return 1
    if fail_on_critical and critical:
        print(f"\n{critical} violation(s) critique(s) : la Constitution n'est pas respectée.")
        return 1
    print(f"\n{checked} entité(s) contrôlée(s).")
    return 0


def _cli_generate_tests(store: Any, output: Path | None) -> int:
    rules = [Rule.from_dict(payload) for payload in store.list_rules(status="active")]
    content = generate_rule_tests(rules)
    if output is None:
        print(content)
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"✓ {len(rules)} règle(s) transformée(s) en tests : {output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée ``python -m career.constitution``."""
    parser = argparse.ArgumentParser(prog="career.constitution", description="Constitution exécutable (SPEC-014).")
    parser.add_argument("--base-dir", default=None, help="Racine de l'espace Career local.")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="Valider toutes les règles stockées.")
    validate_parser.add_argument("--all", action="store_true", help="Valider toutes les règles (défaut).")

    check_parser = subparsers.add_parser("check", help="Contrôler la conformité des entités.")
    check_parser.add_argument("--all-entities", action="store_true", help="Contrôler toutes les entités fournies.")
    check_parser.add_argument("--entity", action="append", default=[], help="Fichier JSON d'une entité (répétable).")
    check_parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Rendre un code de sortie non nul si une violation critique est détectée.",
    )

    test_parser = subparsers.add_parser("test", help="Générer des tests depuis les règles.")
    test_parser.add_argument("--generate-tests", action="store_true", help="Générer un fichier pytest.")
    test_parser.add_argument("--output", default=None, help="Fichier de sortie des tests générés.")

    arguments = parser.parse_args(argv)
    if not arguments.command:
        parser.print_help()
        return 0

    base_dir = Path(arguments.base_dir).resolve() if arguments.base_dir else _default_base_dir()
    store = _store_for_cli(base_dir)
    if arguments.command == "validate":
        return _cli_validate(store)
    if arguments.command == "check":
        return _cli_check(
            store,
            [Path(item) for item in arguments.entity],
            fail_on_critical=bool(getattr(arguments, "fail_on_critical", False)),
        )
    if arguments.command == "test":
        output = Path(arguments.output) if arguments.output else None
        return _cli_generate_tests(store, output)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée CLI
    raise SystemExit(main())
