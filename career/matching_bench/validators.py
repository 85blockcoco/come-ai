"""Validators of the adversarial matching bench (CVBOOST-08).

Two families of validators live here, and they must never be confused:

* **Hard invariants** (:data:`career.matching_bench.contracts.HARD_CHECKS`)
  describe the *contract* of the product.  A breach is a defect, not a
  score: evidence must be verbatim, a requirement must be traceable, contact
  data must never leak, what is absent must not be added, the same input must
  always give the same output, an unknown must stay unknown and the CV plan
  must never claim admissibility.

* **Semantic checks** (:data:`career.matching_bench.contracts.SEMANTIC_CHECKS`)
  compare the observed behaviour with the hand-written ground truth of each
  synthetic case.  They are the only place where a *rate* makes sense.

Every validator returns a plain dictionary so the result can be serialised in
the JSON report without any custom encoder.
"""

from __future__ import annotations

import json
import re
from typing import Any

from career.models import clean_text, normalized_text

from . import contracts
from .fixtures import PROFILE_FIELDS, Case

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\d.])(?:\+33\s?[1-9]|0[1-9])(?:[ .-]?\d{2}){4}(?![\d.])")
LINKEDIN = re.compile(r"linkedin\.com/in/[A-Za-z0-9_-]+", re.IGNORECASE)

#: Offer fields that the preparation panel may expose as direct evidence.
SOURCED_FIELDS = frozenset(
    {"languages_required", "eligibility_requirement", "role_level"}
)

#: The plan must never claim that the person is admissible for the offer.
ELIGIBILITY_CLAIM = re.compile(
    r"\b(?:admissib\w*|éligib\w*|eligib\w*|tu\s+es\s+admis\w*|tu\s+es\s+éligib\w*|"
    r"tu\s+es\s+eligib\w*|candidat\s+admis\w*)\b",
    re.IGNORECASE,
)

#: User-facing fields of the plan that carry its own sentences.  Machine keys
#: (``basis``, ``profile_field``…) are excluded: they are not claims.  Quoted
#: offer text is removed before the scan, because quoting a source is not
#: claiming anything.
NARRATIVE_FIELDS: dict[str, tuple[str, ...]] = {
    "cv_improvements": ("suggestion",),
    "letter_points": ("point",),
    "unverified_elements": ("note",),
    "cv_action_plan": ("suggested_change", "why", "action_label"),
    "checks": ("label", "detail"),
}

QUOTED = re.compile(r"«\s*(.*?)\s*»", re.DOTALL)

#: Interface labels the plan legitimately quotes: they are neither a fact
#: from the profile nor a fact from the offer.
UI_LABELS = frozenset(
    normalized_text(label)
    for label in (
        "Compétences",
        "Expériences",
        "Formation",
        "Langues",
        "Informations complémentaires",
        "Profil",
    )
)


#: A score-like key anywhere in the plan would mix the pertinence axis into
#: the coverage axis.
SCORE_KEY = re.compile(r'"(?:score|match_score|relevance_score|note_de_match)"\s*:')


def _result(check: str, ok: bool, detail: str, failures: list[str] | None = None) -> dict[str, Any]:
    return {
        "check": check,
        "ok": bool(ok),
        "detail": detail,
        "failures": list(failures or [])[:10],
    }


# --------------------------------------------------------------------- utils


def approved_corpus(case: Case) -> str:
    """Everything the person actually approved: profile fields and offer text."""
    parts = [case.profile_fields.get(name, "") for name in PROFILE_FIELDS]
    offer = case.offer_fields
    for name in ("title", "company", "description_original", "requirements",
                 "languages_required", "eligibility_requirement", "role_level"):
        parts.append(str(offer.get(name) or ""))
    return normalized_text(" ".join(part for part in parts if part))


def profile_corpus(case: Case) -> str:
    """The approved profile only, normalised."""
    return normalized_text(" ".join(case.profile_fields.get(name, "") for name in PROFILE_FIELDS))


def offer_corpus(case: Case) -> str:
    """The offer text only, normalised."""
    offer = case.offer_fields
    parts = [str(offer.get(name) or "") for name in
             ("title", "description_original", "requirements", "languages_required",
              "eligibility_requirement", "role_level")]
    return normalized_text(" ".join(part for part in parts if part))


def resolve_ref(case: Case, ref: str, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find the preparation requirements a ground-truth reference points to."""
    needle = normalized_text(ref)
    if not needle:
        return []
    exact = [item for item in requirements if needle == normalized_text(item.get("text"))]
    if exact:
        return exact
    return [item for item in requirements if needle in normalized_text(item.get("text"))]


def strip_quotes(text: str) -> str:
    """Remove every « ... » fragment: quoting a source is not a claim."""
    return QUOTED.sub(" ", text)


def _narrative_text(prep: dict[str, Any]) -> str:
    parts: list[str] = []
    for field, keys in NARRATIVE_FIELDS.items():
        value = prep.get(field)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts.extend(str(item.get(key) or "") for key in keys)
                else:
                    parts.append(str(item))
        elif isinstance(value, str):
            parts.append(value)
    parts.append(str(prep.get("disclaimer") or ""))
    coverage = prep.get("cv_coverage") or {}
    if isinstance(coverage, dict):
        parts.append(str(coverage.get("disclaimer") or ""))
    return strip_quotes(" ".join(parts))


# ----------------------------------------------------------- hard invariants


def check_evidence_verbatim(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Every quoted proof must be an exact substring of the approved profile."""
    prep = observation.get("prep") or {}
    failures: list[str] = []
    for item in prep.get("matched_elements") or []:
        field = str(item.get("profile_field") or "")
        evidence = str(item.get("evidence") or "")
        source = case.profile_fields.get(field, "")
        if not evidence:
            failures.append(f"exigence « {item.get('requirement')} » : preuve vide")
        elif evidence not in source:
            failures.append(
                f"exigence « {item.get('requirement')} » : la preuve {evidence!r} n'est pas une "
                f"sous-chaîne exacte du champ profil {field!r}"
            )
    for action in prep.get("cv_action_plan") or []:
        if str(action.get("status")) != "supported":
            continue
        evidence = str(action.get("profile_evidence") or "")
        if not evidence:
            failures.append(f"action {action.get('id')} : étayée mais sans preuve")
        elif evidence not in profile_corpus_source(case):
            failures.append(
                f"action {action.get('id')} : la preuve {evidence!r} n'est pas une sous-chaîne "
                "exacte du profil approuvé"
            )
    return _result(
        "evidence_verbatim",
        not failures,
        f"{len(prep.get('matched_elements') or [])} preuve(s) vérifiée(s) dans le profil approuvé.",
        failures,
    )


def profile_corpus_source(case: Case) -> str:
    """Raw (not normalised) concatenation of the approved profile fields."""
    return " ".join(case.profile_fields.get(name, "") for name in PROFILE_FIELDS)


def check_requirement_traceable(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Every requirement of the plan must be found back in the offer."""
    prep = observation.get("prep") or {}
    offer = case.offer_fields
    failures: list[str] = []
    for requirement in prep.get("requirements") or []:
        text = str(requirement.get("text") or "")
        source = str(requirement.get("source") or "")
        if source in SOURCED_FIELDS:
            field = source
            source_text = clean_text(offer.get(field), limit=30_000)
            if not text or text not in source_text:
                failures.append(
                    f"exigence « {text} » : aucune citation verbatim du champ {field!r} de l'offre"
                )
            continue
        if source == "requirements":
            haystack = clean_text(offer.get("requirements"), limit=20_000)
        elif source == "description_original":
            haystack = clean_text(offer.get("description_original"), limit=30_000)
        else:
            failures.append(f"exigence « {text} » : source inconnue {source!r}")
            continue
        if text not in haystack:
            failures.append(
                f"exigence « {text} » : aucune sous-chaîne correspondante dans le champ {source!r} de l'offre"
            )
    return _result(
        "requirement_traceable",
        not failures,
        f"{len(prep.get('requirements') or [])} exigence(s) retracée(s) dans l'offre.",
        failures,
    )


def check_locator_resolves(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Every provenance record must point at a resolvable passage."""
    from career.offer_requirements import resolve_locator

    analysis = observation.get("requirements") or {}
    offer = case.offer_fields
    failures: list[str] = []
    for requirement in analysis.get("requirements") or []:
        source_field = str(requirement.get("source_field") or "")
        locator = str(requirement.get("locator") or "")
        text = str(requirement.get("text") or "")
        try:
            passage = resolve_locator(offer, source_field, locator)
        except Exception as error:  # pragma: no cover - defensive
            failures.append(f"exigence {requirement.get('id')} : locator illisible ({error})")
            continue
        if not passage:
            failures.append(f"exigence {requirement.get('id')} : locator {locator!r} ne résout aucun passage")
            continue
        if text not in passage and text not in clean_text(offer.get(source_field), limit=30_000):
            failures.append(
                f"exigence {requirement.get('id')} : le texte cité n'est pas dans le passage résolu"
            )
    return _result(
        "locator_resolves",
        not failures,
        f"{len(analysis.get('requirements') or [])} provenance(s) résolue(s).",
        failures,
    )


def check_negation_handled(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """A negated statement is never a mandatory requirement."""
    analysis = observation.get("requirements") or {}
    failures: list[str] = []
    for requirement in analysis.get("requirements") or []:
        if not requirement.get("negated"):
            continue
        modality = str(requirement.get("modality") or "")
        if modality == "required":
            failures.append(
                f"exigence {requirement.get('id')} : une phrase niée est présentée comme obligatoire"
            )
    return _result(
        "negation_handled",
        not failures,
        "Les exigences niées restent signalées comme telles.",
        failures,
    )


def check_no_contact_leak(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Contact data must never appear in the decision surface of the plan."""
    prep = observation.get("prep") or {}
    failures: list[str] = []
    contact = case.contact
    decision_surface: list[tuple[str, str]] = []
    for item in prep.get("requirements") or []:
        decision_surface.append(("requirement", str(item.get("text") or "")))
    for item in prep.get("matched_elements") or []:
        decision_surface.append(("preuve", str(item.get("evidence") or "")))
    for item in prep.get("unverified_elements") or []:
        decision_surface.append(("note", str(item.get("note") or "")))
    for action in prep.get("cv_action_plan") or []:
        decision_surface.append(("action", str(action.get("suggested_change") or "")))
        decision_surface.append(("action", str(action.get("profile_evidence") or "")))
    for improvement in prep.get("cv_improvements") or []:
        decision_surface.append(("amélioration", str(improvement.get("suggestion") or "")))
    for point in prep.get("letter_points") or []:
        decision_surface.append(("lettre", str(point.get("point") or "")))
    for kind, text in decision_surface:
        for name, value in contact.items():
            if value and value in text:
                failures.append(f"{kind} : la donnée de contact {name!r} du profil est citée")
        if EMAIL.search(text):
            failures.append(f"{kind} : une adresse e-mail apparaît dans le plan")
        if PHONE.search(text):
            failures.append(f"{kind} : un numéro de téléphone apparaît dans le plan")
        if LINKEDIN.search(text):
            failures.append(f"{kind} : une URL de réseau professionnel apparaît dans le plan")
    return _result(
        "no_contact_leak",
        not failures,
        f"{len(decision_surface)} fragment(s) de plan inspecté(s).",
        failures,
    )


def check_absent_not_added(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """What the profile does not prove must not be presented as proven."""
    prep = observation.get("prep") or {}
    failures: list[str] = []
    matched_requirements = {str(item.get("requirement")) for item in prep.get("matched_elements") or []}
    verified_requirements = {str(item.get("requirement")) for item in prep.get("unverified_elements") or []}
    for action in prep.get("cv_action_plan") or []:
        status = str(action.get("status"))
        requirement = str(action.get("requirement") or "")
        evidence = str(action.get("profile_evidence") or "")
        if status == "supported":
            if not evidence:
                failures.append(f"action {action.get('id')} : étayée sans preuve")
            if requirement in verified_requirements:
                failures.append(f"action {action.get('id')} : une exigence non étayée est présentée comme étayée")
        elif status == "needs_evidence":
            if evidence:
                failures.append(
                    f"action {action.get('id')} : une exigence sans preuve porte une preuve {evidence!r}"
                )
            if requirement in matched_requirements:
                failures.append(f"action {action.get('id')} : exigence étayée classée « à vérifier »")
    coverage = prep.get("cv_coverage") or {}
    total = int(coverage.get("requirements_total") or 0)
    supported = int(coverage.get("supported") or 0)
    if supported != len(matched_requirements):
        failures.append(
            f"couverture : {supported} exigence(s) annoncée(s) étayée(s) pour "
            f"{len(matched_requirements)} exigence(s) réellement étayée(s)"
        )
    if int(coverage.get("to_verify") or 0) != len(verified_requirements):
        failures.append(
            f"couverture : {coverage.get('to_verify')} exigence(s) « à vérifier » annoncée(s) pour "
            f"{len(verified_requirements)} réellement à vérifier"
        )
    expected_percent = round((supported / total) * 100) if total else 0
    if int(coverage.get("coverage_percent") or 0) != expected_percent:
        failures.append(
            f"couverture : pourcentage annoncé {coverage.get('coverage_percent')} "
            f"au lieu de {expected_percent}"
        )
    return _result(
        "absent_not_added",
        not failures,
        f"{len(prep.get('cv_action_plan') or [])} action(s) de plan vérifiée(s).",
        failures,
    )


def check_unknown_stays_unknown(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """A dimension declared unknown must not be resolved by the bench."""
    prep = observation.get("prep") or {}
    analysis = observation.get("requirements") or {}
    education = observation.get("education") or {}
    eligibility = observation.get("eligibility") or {}
    match = observation.get("match") or {}
    failures: list[str] = []
    for dimension in case.oracle.get("unknown_dimensions") or []:
        if dimension == "requirements":
            if prep.get("requirements"):
                failures.append("exigences : des exigences sont détectées alors que l'offre n'en contient pas")
            if analysis.get("requirements"):
                failures.append("exigences : la couche de provenance en détecte alors que l'offre n'en contient pas")
        elif dimension == "profile":
            if prep.get("matched_elements"):
                failures.append("profil : des éléments sont étayés alors que le profil est vide")
        elif dimension == "education_level":
            if str(education.get("status")) != "to_verify":
                failures.append(
                    f"niveau académique : statut {education.get('status')!r} alors que l'offre n'en dit rien"
                )
            if education.get("evidence"):
                failures.append("niveau académique : une preuve est produite alors que l'offre n'en dit rien")
        elif dimension == "education_ambiguous":
            if str(education.get("status")) != "to_verify":
                failures.append(
                    f"niveau académique : statut {education.get('status')!r} alors que le niveau est ambigu"
                )
        elif dimension == "contract_type":
            if str(eligibility.get("target_status")) != "to_verify":
                failures.append(
                    f"type de contrat : statut {eligibility.get('target_status')!r} alors qu'il est indéterminé"
                )
        elif dimension == "duration":
            if eligibility.get("duration_min_months") is not None or eligibility.get("duration_max_months") is not None:
                failures.append("durée : une durée est affirmée alors qu'elle est inconnue")
            if str(eligibility.get("target_status")) != "to_verify":
                failures.append("durée : le contrat est jugé alors que la durée manque")
        elif dimension == "start_month":
            if eligibility.get("start_month") is not None:
                failures.append("mois de début : un mois est affirmé alors qu'il est inconnu")
        elif dimension == "relevance":
            statuses = [str(item.get("status")) for item in match.get("components") or []]
            if "unknown" not in statuses:
                failures.append("pertinence : aucun composant n'est signalé comme inconnu")
        elif dimension == "personal_eligibility":
            # The plan must never turn an advertised level into a personal
            # admission: the check lives in ``axis_separation``.
            if ELIGIBILITY_CLAIM.search(_narrative_text(prep)):
                failures.append("admissibilité personnelle : le plan affirme une admission")
    return _result(
        "unknown_stays_unknown",
        not failures,
        f"{len(case.oracle.get('unknown_dimensions') or [])} dimension(s) inconnue(s) contrôlée(s).",
        failures,
    )


def check_axis_separation(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """The CV plan must not claim admissibility nor borrow the pertinence score."""
    prep = observation.get("prep") or {}
    failures: list[str] = []
    narrative = _narrative_text(prep)
    claim = ELIGIBILITY_CLAIM.search(narrative)
    if claim:
        failures.append(f"le plan affirme une admissibilité ({claim.group(0)!r})")
    serialized = json.dumps(prep, ensure_ascii=False, default=str)
    if SCORE_KEY.search(serialized):
        failures.append("le plan contient un score : il mélange l'axe pertinence à l'axe couverture")
    coverage = prep.get("cv_coverage") or {}
    disclaimer = str(coverage.get("disclaimer") or "")
    if "probabilité" not in disclaimer:
        failures.append("la couverture documentaire ne porte pas son avertissement (ce n'est pas une probabilité)")
    return _result(
        "axis_separation",
        not failures,
        "Le plan CV reste sur l'axe couverture documentaire.",
        failures,
    )


def check_determinism(case: Case, observation: dict[str, Any], replay_hash: str) -> dict[str, Any]:
    """Two identical executions must produce the same bytes."""
    from .runner import observation_hash

    current = observation_hash(observation)
    failures = [] if current == replay_hash else [
        "deux exécutions sur les mêmes entrées ont produit des résultats différents"
    ]
    return _result(
        "determinism",
        not failures,
        f"empreinte stable : {current[:16]}",
        failures,
    )


# ----------------------------------------------------------- semantic checks


def check_requirement_detection(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Real requirements must be detected, and only them."""
    prep = observation.get("prep") or {}
    requirements = list(prep.get("requirements") or [])
    failures: list[str] = []
    details: list[dict[str, Any]] = []
    for oracle in case.requirement_oracles:
        found = resolve_ref(case, oracle.ref, requirements)
        detected = bool(found)
        if oracle.should_be_requirement and not detected:
            failures.append(f"« {oracle.ref} » : exigence réelle non détectée")
        if not oracle.should_be_requirement and detected:
            failures.append(
                f"« {oracle.ref} » : passage non exigentiel détecté comme exigence ({found[0].get('text')!r})"
            )
        if len(found) > 1:
            failures.append(f"« {oracle.ref} » : référence ambiguë ({len(found)} exigences correspondent)")
        details.append(
            {
                "ref": oracle.ref,
                "expected_requirement": oracle.should_be_requirement,
                "detected": detected,
                "matched_texts": [str(item.get("text")) for item in found],
                "reason": oracle.reason,
            }
        )
    return _result(
        "requirement_detection",
        not failures,
        f"{len(details)} référence(s) confrontée(s) à la détection.",
        failures,
    ) | {"details": details}


def check_support_decision(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """A requirement is only covered when the proof covers its decisive part."""
    prep = observation.get("prep") or {}
    requirements = list(prep.get("requirements") or [])
    matched = {str(item.get("requirement")) for item in prep.get("matched_elements") or []}
    failures: list[str] = []
    details: list[dict[str, Any]] = []
    for oracle in case.requirement_oracles:
        if not oracle.should_be_requirement:
            continue
        found = resolve_ref(case, oracle.ref, requirements)
        if len(found) != 1:
            details.append(
                {
                    "ref": oracle.ref,
                    "expected_supported": oracle.supported,
                    "actual_supported": None,
                    "verdict": "non applicable (exigence non détectée)",
                    "reason": oracle.reason,
                }
            )
            continue
        requirement = str(found[0].get("text"))
        actual = requirement in matched
        verdict = "conforme"
        if actual and not oracle.supported:
            verdict = "faux positif : couverture annoncée sans preuve décisive"
            failures.append(f"« {oracle.ref} » : {verdict}")
        elif not actual and oracle.supported:
            verdict = "faux négatif : couverture réelle non détectée"
            failures.append(f"« {oracle.ref} » : {verdict}")
        details.append(
            {
                "ref": oracle.ref,
                "requirement": requirement,
                "expected_supported": oracle.supported,
                "actual_supported": actual,
                "verdict": verdict,
                "reason": oracle.reason,
            }
        )
    return _result(
        "support_decision",
        not failures,
        f"{len(details)} exigence(s) confrontée(s) à la vérité terrain.",
        failures,
    ) | {"details": details}


def check_eligibility_verdict(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """The admissibility verdict must follow the offer's own facts."""
    eligibility = observation.get("eligibility") or {}
    status = str(eligibility.get("target_status") or "")
    actual = contracts.ELIGIBILITY_BY_TARGET_STATUS.get(status, "unknown")
    expected = str(case.oracle.get("eligibility"))
    failures: list[str] = []
    if actual != expected:
        failures.append(
            f"admissibilité : verdict {actual!r} (statut {status!r}) au lieu de {expected!r}"
        )
    return _result(
        "eligibility_verdict",
        not failures,
        f"statut de qualification {status!r}.",
        failures,
    )


def check_education_verdict(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """The advertised level must be reported without deducing the candidate's."""
    education = observation.get("education") or {}
    actual = str(education.get("status") or "")
    expected = str(case.oracle.get("education_status"))
    failures: list[str] = []
    if actual != expected:
        failures.append(f"niveau académique : statut {actual!r} au lieu de {expected!r}")
    return _result(
        "education_verdict",
        not failures,
        f"niveau académique annoncé {actual!r}.",
        failures,
    )


def check_relevance_components(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """The pertinence components must follow the brief."""
    match = observation.get("match") or {}
    components = {str(item.get("key")): str(item.get("status")) for item in match.get("components") or []}
    expected = (case.oracle.get("relevance") or {}).get("components") or {}
    failures: list[str] = []
    for key, status in expected.items():
        actual = components.get(str(key))
        if actual != status:
            failures.append(f"pertinence : composant {key!r} = {actual!r} au lieu de {status!r}")
    return _result(
        "relevance_components",
        not failures,
        f"{len(expected)} composant(s) de pertinence vérifié(s).",
        failures,
    )


def check_quoted_material_verbatim(case: Case, observation: dict[str, Any]) -> dict[str, Any]:
    """Every fragment the plan quotes must come from the profile or the offer."""
    prep = observation.get("prep") or {}
    corpus = approved_corpus(case)
    failures: list[str] = []
    quoted_total = 0

    def _check(kind: str, text: str) -> None:
        nonlocal quoted_total
        for fragment in QUOTED.findall(text):
            quoted_total += 1
            normalized = normalized_text(fragment)
            if not normalized or normalized in UI_LABELS:
                continue
            if normalized not in corpus:
                failures.append(f"{kind} : le fragment {fragment!r} n'est ni au profil ni dans l'offre")

    for improvement in prep.get("cv_improvements") or []:
        _check("amélioration", str(improvement.get("suggestion") or ""))
    for point in prep.get("letter_points") or []:
        _check("lettre", str(point.get("point") or ""))
    for action in prep.get("cv_action_plan") or []:
        _check(f"action {action.get('id')}", str(action.get("suggested_change") or ""))
        _check(f"action {action.get('id')}", str(action.get("why") or ""))
    return _result(
        "quoted_material_verbatim",
        not failures,
        f"{quoted_total} fragment(s) cité(s) controlé(s).",
        failures,
    )


#: Hard invariant validators, in the order they are reported.
HARD_VALIDATORS = (
    check_evidence_verbatim,
    check_requirement_traceable,
    check_locator_resolves,
    check_negation_handled,
    check_no_contact_leak,
    check_absent_not_added,
    check_unknown_stays_unknown,
    check_axis_separation,
)

#: Semantic validators.
SEMANTIC_VALIDATORS = (
    check_requirement_detection,
    check_support_decision,
    check_eligibility_verdict,
    check_education_verdict,
    check_relevance_components,
    check_quoted_material_verbatim,
)
