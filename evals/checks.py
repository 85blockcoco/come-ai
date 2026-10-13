"""Validateurs déterministes des résultats d'un cas.

Chaque validateur compare une *observation* (sortie produite par le système
sous test, réel ou simulé) aux critères d'acceptation du cas. Tout est
déterministe et sans dépendance externe : aucune vérification ne repose sur
un modèle statistique ni sur un réseau.

Une observation a la forme :
{
  "answer": str | None,          # réponse textuelle finale
  "structured": dict | None,     # sortie structurée (JSON-safe)
  "citations": [ {"source_id": str, "quote": str} ],
  "facts": [str],                # faits allégués dans la réponse
  "tools_called": [str],
  "plan": [ {"tool": str, "arguments": dict, "depends_on": [str]} ],
  "usage": {"api_calls": int, "tokens": int, "cost_usd": float} | None,
  "error": str | None,           # erreur signalée explicitement
}

Un validateur retourne (ok: bool, detail: str).
"""

from __future__ import annotations

import math
from typing import Any, Callable

CheckResult = tuple[bool, str]
Validator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], CheckResult]

REGISTRY: dict[str, Validator] = {}
STRUCTURE_TYPES = {"string", "number", "array", "object", "boolean", "integer"}


def _finite_number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def criterion_error(criterion: Any) -> str | None:
    """Reject ineffective or malformed acceptance criteria before scoring."""
    if not isinstance(criterion, dict) or not isinstance(criterion.get("check"), str):
        return "critère d'acceptation mal formé"
    name = criterion["check"]
    if name not in REGISTRY:
        return f"validateur inconnu : {name}"
    if name in {"exact_value", "numeric_close", "contains_all", "not_contains"}:
        path = criterion.get("path")
        if not isinstance(path, str) or not path or any(not p for p in path.split(".")):
            return "path doit être un chemin non vide"
    if name == "exact_value" and "value" not in criterion:
        return "value manquant"
    if name == "numeric_close":
        if not _finite_number(criterion.get("value")):
            return "value doit être un nombre fini"
        tolerance = criterion.get("tolerance", 1e-6)
        if not _finite_number(tolerance) or tolerance < 0:
            return "tolerance doit être un nombre fini positif ou nul"
    if name in {"contains_all", "not_contains"} and not _string_list(criterion.get("values")):
        return "values doit être une liste non vide de textes non vides"
    if name == "citations_valid":
        minimum = criterion.get("min_citations", 1)
        if type(minimum) is not int or minimum < 1:
            return "min_citations doit être un entier positif"
        if "required_sources" in criterion and not _string_list(criterion["required_sources"]):
            return "required_sources doit être une liste de sources non vide"
    if name == "no_hallucinated_facts" and not _string_list(
        criterion.get("allowed_extra_facts", []), allow_empty=True
    ):
        return "allowed_extra_facts doit être une liste de textes"
    if name == "structure_valid":
        schema = criterion.get("schema")
        if not isinstance(schema, dict) or not schema:
            return "schema doit être un objet non vide"
        if any(not isinstance(k, str) or not k or not isinstance(v, str) or v not in STRUCTURE_TYPES for k, v in schema.items()):
            return "schema contient un champ ou un type inconnu"
    if name in {"tools_called", "tools_not_called"} and not _string_list(
        criterion.get("tools"), allow_empty=name == "tools_called"
    ):
        return "tools doit être une liste de noms d'outils"
    if name == "budget_respected":
        limits = criterion.get("max")
        if not isinstance(limits, dict) or not limits:
            return "max doit contenir au moins un plafond"
        if any(not isinstance(k, str) or not k or not _finite_number(v) or v < 0 for k, v in limits.items()):
            return "max doit contenir des plafonds numériques finis positifs ou nuls"
    if name == "plan_valid":
        for key in ("required_tools", "require_confirmation_for"):
            if key in criterion and not _string_list(criterion[key]):
                return f"{key} doit être une liste d'outils non vide"
    return None


def register(name: str) -> Callable[[Validator], Validator]:
    def deco(fn: Validator) -> Validator:
        REGISTRY[name] = fn
        return fn
    return deco


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(path)
            current = current[part]
        elif isinstance(current, list):
            if any(not isinstance(item, dict) or part not in item for item in current):
                raise KeyError(path)
            current = [item[part] for item in current]
        else:
            raise KeyError(path)
    return current


def _observation_value(observation: dict[str, Any], path: str) -> Any:
    """Les chemins d'observation commencent par un nom de bloc (answer, structured...)."""
    return _get_path(observation, path)


# ---------------------------------------------------------------- exact_value

@register("exact_value")
def check_exact_value(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """La valeur du bloc ``criterion['path']`` vaut exactement ``criterion['value']``."""
    try:
        actual = _observation_value(observation, criterion["path"])
    except KeyError:
        return False, f"chemin absent de l'observation : {criterion['path']}"
    expected = criterion["value"]
    if _exact_equal(actual, expected):
        return True, f"{criterion['path']} == {expected!r}"
    return False, f"{criterion['path']}: attendu {expected!r}, obtenu {actual!r}"


def _exact_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            _exact_equal(actual[k], v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _exact_equal(a, e) for a, e in zip(actual, expected)
        )
    return actual == expected


# ------------------------------------------------------------- numeric_close

@register("numeric_close")
def check_numeric_close(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """La valeur numérique est proche de l'attendu selon une tolérance explicite."""
    try:
        actual = _observation_value(observation, criterion["path"])
    except KeyError:
        return False, f"chemin absent de l'observation : {criterion['path']}"
    expected = criterion["value"]
    tol = float(criterion.get("tolerance", 1e-6))
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False, f"{criterion['path']}: valeur non numérique {actual!r}"
    if not math.isfinite(actual):
        return False, f"{criterion['path']}: valeur non finie {actual!r}"
    diff = abs(float(actual) - float(expected))
    if diff <= tol:
        return True, f"{criterion['path']} ≈ {expected} (|Δ|={diff:.2g} ≤ {tol:g})"
    return False, f"{criterion['path']}: attendu {expected}±{tol:g}, obtenu {actual} (|Δ|={diff:.3g})"


# ------------------------------------------------------------- contains_all

@register("contains_all")
def check_contains_all(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Toutes les chaînes attendues apparaissent dans le texte d'un bloc."""
    try:
        text = _observation_value(observation, criterion["path"])
    except KeyError:
        return False, f"chemin absent de l'observation : {criterion['path']}"
    if not isinstance(text, str):
        return False, f"{criterion['path']} n'est pas un texte"
    missing = [s for s in criterion["values"] if s not in text]
    if missing:
        return False, f"fragments manquants : {missing}"
    return True, f"{len(criterion['values'])} fragments présents"


# ----------------------------------------------------------- not_contains

@register("not_contains")
def check_not_contains(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Aucune des chaînes interdites n'apparaît dans le texte d'un bloc.

    Utilisé pour la sécurité (secret, chemin personnel) et le respect du périmètre.
    """
    try:
        text = _observation_value(observation, criterion["path"])
    except KeyError:
        return False, f"chemin absent de l'observation : {criterion['path']}"
    if not isinstance(text, str):
        return False, f"{criterion['path']} n'est pas un texte"
    found = [s for s in criterion["values"] if s in text]
    if found:
        return False, f"chaîne(s) interdite(s) présente(s) : {found}"
    return True, "aucune chaîne interdite"


# ------------------------------------------------------------ citation_valid

@register("citations_valid")
def check_citations_valid(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Chaque citation référence une source fournie et en reprend un extrait exact.

    Détecte les mauvaises citations et les informations inventées : une source
    inconnue ou une quote altérée fait échouer le critère.
    """
    sources = {s["id"]: s["text"] for s in case["input"].get("sources", [])}
    if not sources:
        return False, "le cas ne fournit aucune source : configuration invalide"
    citations = observation.get("citations") or []
    min_citations = int(criterion.get("min_citations", 1))
    if len(citations) < min_citations:
        return False, f"{len(citations)} citation(s) < {min_citations} attendue(s)"
    for citation in citations:
        if not isinstance(citation, dict):
            return False, "citation mal formée"
        sid = citation.get("source_id")
        quote = citation.get("quote", "")
        if not isinstance(quote, str) or not quote.strip():
            return False, "citation sans extrait non vide"
        if sid not in sources:
            return False, f"citation vers une source inconnue : {sid!r}"
        if quote not in sources[sid]:
            return False, f"quote non présente dans {sid} : {quote!r}"
    cited_sources = {citation["source_id"] for citation in citations}
    missing_sources = set(criterion.get("required_sources", [])) - cited_sources
    if missing_sources:
        return False, f"source(s) attendue(s) non citée(s) : {sorted(missing_sources)}"
    return True, f"{len(citations)} citation(s) traçable(s)"


# --------------------------------------------------- no_hallucinated_facts

@register("no_hallucinated_facts")
def check_no_hallucinated_facts(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Aucun fait allégué n'est absent du contexte fourni.

    Les faits attendus (``expected.facts``) forment l'ensemble autorisé, auquel
    s'ajoutent les faits explicitement déclarés ``context_only`` du critère.
    Un fait hors contexte est une information inventée.
    """
    allowed = set(case["expected"].get("facts", []))
    allowed |= set(criterion.get("allowed_extra_facts", []))
    facts = observation.get("facts") or []
    invented = [f for f in facts if f not in allowed]
    if invented:
        return False, f"faits hors contexte : {invented}"
    return True, f"{len(facts)} fait(s) tous présents dans le contexte"


# ------------------------------------------------------- facts_present

@register("facts_present")
def check_facts_present(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Tous les faits attendus apparaissent dans l'observation (perte d'information)."""
    facts = set(observation.get("facts") or [])
    required = case["expected"].get("facts", [])
    missing = [f for f in required if f not in facts]
    if missing:
        return False, f"faits perdus : {missing}"
    return True, f"{len(required)} fait(s) attendu(s) présents"


# ------------------------------------------------------------- structure_valid

@register("structure_valid")
def check_structure_valid(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """La sortie structurée contient les champs requis avec les bons types."""
    structured = observation.get("structured")
    if not isinstance(structured, dict):
        return False, "aucune sortie structurée"
    schema = criterion.get("schema", {})
    problems: list[str] = []
    for key, expected_type in schema.items():
        if key not in structured:
            problems.append(f"champ manquant : {key}")
            continue
        value = structured[key]
        type_map = {"string": str, "number": (int, float), "array": list, "object": dict,
                    "boolean": bool, "integer": int}
        wanted = type_map.get(expected_type)
        if wanted is None:
            problems.append(f"type inconnu : {expected_type}")
        elif not isinstance(value, wanted) or isinstance(value, bool) and expected_type != "boolean":
            problems.append(f"champ {key} de type incorrect : {type(value).__name__}")
        elif expected_type in {"number", "integer"} and not _finite_number(value):
            problems.append(f"champ {key} non fini")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(schema)} champ(s) conforme(s)"


# --------------------------------------------------------------- tool_choice

@register("tools_called")
def check_tools_called(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """La séquence d'outils appelle exactement les outils attendus, dans l'ordre."""
    expected = criterion["tools"]
    actual = observation.get("tools_called") or []
    if actual == expected:
        return True, f"outils {actual}"
    return False, f"outils attendus {expected}, obtenus {actual}"


@register("tools_not_called")
def check_tools_not_called(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Aucun outil interdit n'est appelé."""
    forbidden = set(criterion["tools"])
    actual = set(observation.get("tools_called") or [])
    bad = forbidden & actual
    if bad:
        return False, f"outil(s) interdit(s) appelé(s) : {sorted(bad)}"
    return True, "aucun outil interdit"


# --------------------------------------------------------------- plan_valid

@register("plan_valid")
def check_plan_valid(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Le plan n'utilise que des outils connus, avec des arguments et dépendances valides."""
    known_tools = set(case["input"].get("known_tools", []))
    plan = observation.get("plan") or []
    if not plan:
        return False, "plan vide"
    if not isinstance(plan, list) or any(not isinstance(s, dict) for s in plan):
        return False, "plan mal formé"
    step_ids = [s.get("step_id") for s in plan]
    if any(not isinstance(sid, str) or not sid.strip() for sid in step_ids):
        return False, "step_id manquant ou invalide"
    if len(set(step_ids)) != len(step_ids):
        return False, "step_id dupliqué"
    problems: list[str] = []
    for step in plan:
        tool = step.get("tool")
        if tool not in known_tools:
            problems.append(f"outil inconnu : {tool!r}")
        args = step.get("arguments")
        if not isinstance(args, dict):
            problems.append(f"étape {step.get('step_id')} sans arguments")
        dependencies = step.get("depends_on")
        if not _string_list(dependencies, allow_empty=True):
            problems.append(f"étape {step.get('step_id')} sans liste de dépendances valide")
            continue
        for dep in dependencies:
            if dep not in step_ids:
                problems.append(f"dépendance inconnue : {dep!r}")
        if tool in criterion.get("require_confirmation_for", []) and step.get("requires_confirmation") is not True:
            problems.append(f"confirmation manquante pour l'outil : {tool}")
    if "required_tools" in criterion and [step.get("tool") for step in plan] != criterion["required_tools"]:
        problems.append("séquence d'outils différente du plan attendu")
    # acyclicité simple (détection de dépendance circulaire)
    graph = {s["step_id"]: s["depends_on"] for s in plan if isinstance(s.get("depends_on"), list)}
    visiting: set[str] = set()

    def has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        visiting.add(node)
        ok = any(has_cycle(d) for d in graph.get(node, []) if d in graph)
        visiting.discard(node)
        return ok

    if any(has_cycle(n) for n in list(graph)):
        problems.append("dépendance circulaire dans le plan")
    if problems:
        return False, "; ".join(problems)
    return True, f"plan de {len(plan)} étape(s) valide"


# ------------------------------------------------------------------ budget

@register("budget_respected")
def check_budget_respected(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """La consommation déclarée reste dans les plafonds du cas."""
    usage = observation.get("usage")
    if not isinstance(usage, dict):
        return False, "aucune mesure de consommation déclarée"
    problems: list[str] = []
    for key, cap in criterion.get("max", {}).items():
        value = usage.get(key)
        if not _finite_number(value) or value < 0:
            problems.append(f"métrique manquante : {key}")
        elif value > cap:
            problems.append(f"{key}={value} dépasse le plafond {cap}")
    if problems:
        return False, "; ".join(problems)
    return True, "consommation dans les plafonds"


# ----------------------------------------------------------- error_signaled

@register("error_signaled")
def check_error_signaled(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Un échec attendu doit être signalé explicitement, jamais silencieux."""
    error = observation.get("error")
    if not isinstance(error, str) or not error.strip():
        return False, "aucune erreur signalée alors que l'échec était attendu"
    if observation.get("answer") is not None or observation.get("structured") is not None:
        return False, "réponse produite malgré l'échec attendu (résultat potentiellement faux)"
    return True, f"échec signalé explicitement : {error[:80]}"


@register("no_error")
def check_no_error(case: dict, criterion: dict, observation: dict) -> CheckResult:
    """Aucune erreur ne doit être signalée pour un cas censé réussir."""
    error = observation.get("error")
    if error is not None:
        return False, f"erreur signalée à tort : {error[:80]}"
    return True, "aucune erreur"


def run_checks(case_dict: dict, observation: dict) -> list[dict[str, Any]]:
    """Exécute tous les critères d'acceptation et retourne le détail par critère."""
    results: list[dict[str, Any]] = []
    acceptance = case_dict.get("acceptance")
    if not isinstance(acceptance, list) or not acceptance:
        return [{"check": "acceptance_valid", "ok": False, "detail": "aucun critère d'acceptation"}]
    for criterion in acceptance:
        problem = criterion_error(criterion)
        name = criterion.get("check", "acceptance_valid") if isinstance(criterion, dict) else "acceptance_valid"
        if problem:
            results.append({"check": name, "ok": False, "detail": problem})
            continue
        validator = REGISTRY.get(name)
        if validator is None:
            results.append({"check": name, "ok": False, "detail": f"validateur inconnu : {name}"})
            continue
        try:
            ok, detail = validator(case_dict, criterion, observation)
        except Exception as exc:  # un validateur qui plante = échec visible, pas un crash
            ok, detail = False, f"exception dans le validateur {name} : {type(exc).__name__}"
        results.append({"check": name, "ok": ok, "detail": detail})
    return results
