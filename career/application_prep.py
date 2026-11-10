"""Deterministic, local application preparation for one stored Career offer.

This module compares two sets of *existing* facts: the requirements the
posting states, and the profile the person entered.  It never uses a model,
never performs a request, and never invents an experience, a skill, a
qualification or an achievement.  Every "matched" element must quote a real
excerpt of a profile field (verified at build time), and every unmatched
requirement is phrased as "not found in the profile", never as a claim that
the person lacks it.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .cv_quality.missions_extractor import extract_missions, missions_as_dicts
from .models import clean_text, normalized_text
from .offer_requirements import analyze_offer

MAX_REQUIREMENTS = 40
MAX_TEXT_LENGTH = 400
MAX_MATCHED = 20
MAX_IMPROVEMENTS = 8
MAX_CV_ACTIONS = 12
MAX_LETTER_POINTS = 6
MAX_SOURCE_EXCERPT = 4_000

# Profile fields consulted for the comparison.  Contact data is deliberately
# excluded: a preparation analysis must never quote or leak an e-mail address,
# a phone number or a LinkedIn URL.
PROFILE_FIELDS: tuple[str, ...] = ("skills", "experience", "education", "languages", "eligibility")

_CV_SECTION_LABELS: dict[str, str] = {
    "skills": "Compétences",
    "experience": "Expériences",
    "education": "Formation",
    "languages": "Langues",
    "eligibility": "Informations complémentaires",
}

_EMAIL_ADDRESS = re.compile(
    r"(?<![\w.!#$%&'*+/=?^`{|}~-])[A-Z0-9][A-Z0-9.!#$%&'*+/=?^_`{|}~-]{0,63}"
    r"@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+"
    r"(?![\w.-])",
    re.IGNORECASE,
)
_PHONE_NUMBER = re.compile(r"(?<![\w+])(?:\+|00)?\s*(?:\(?\d{1,4}\)?[\s.\-]*){2,8}\d(?!\w)")
_LINKEDIN_PROFILE = re.compile(
    r"(?i)(?:https?://)?(?:(?:[a-z]{2,3}|www)\.)?linkedin\.com/"
    r"(?:in|pub)/[a-z0-9%._~-]+(?:/[a-z0-9%._~-]+)*(?:[?#][^\s<>()\[\]{}\"']*)?"
)
_CONTACT_LINE = re.compile(
    r"^\s*(?:contact(?:\s+(?:details|information))?|e-?mail|phone|telephone|"
    r"t[eé]l[eé]phone|linkedin)\s*[:：-]",
    re.IGNORECASE,
)
_CONTACT_ONLY = frozenset(
    {
        "contact", "contact details", "contact information", "email", "e mail",
        "phone", "telephone", "telephone", "linkedin", "langues requises",
        "eligibilite", "eligibility",
    }
)
_STREET_ADDRESS = re.compile(
    r"^\s*\d{1,6}\s+.+\b(?:street|st|avenue|ave|drive|dr|road|rd|boulevard|blvd|lane|ln)\b",
    re.IGNORECASE,
)
_BENEFIT_ONLY_TEXT = re.compile(
    r"\b(?:tickets? restaurant|mutuelle|meal vouchers?|meal allowance|health insurance|"
    r"prise en charge des repas|prise en charge des frais de deplacement|"
    r"frais de deplacement|travel expenses covered|travel expenses reimbursed)\b",
    re.IGNORECASE,
)
_UNVERIFIED_REQUIREMENT_TEXT = re.compile(
    r"\b(?:to verify|to be verified|to confirm|to be confirmed|to check|to be checked|"
    r"a verifier|a confirmer|a controler|por verificar|por confirmar|a verificar|"
    r"a confirmar|da verificare|da confermare|zu prufen|zu bestatigen)\b",
    re.IGNORECASE,
)


def _exclude_contact_details(value: Any) -> str:
    """Remove contact-only lines and personal contact values from match text."""
    safe_lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        if _CONTACT_LINE.match(raw_line):
            continue
        line = _EMAIL_ADDRESS.sub(" ", raw_line)
        line = _LINKEDIN_PROFILE.sub(" ", line)

        def strip_phone(match: re.Match[str]) -> str:
            candidate = match.group(0)
            digit_count = sum(character.isdigit() for character in candidate)
            country_prefix = candidate.lstrip().startswith(("+", "00"))
            separators = sum(character in " .()-" for character in candidate)
            formatted_number = digit_count >= 9 and separators >= 2
            return " " if digit_count >= 8 and (country_prefix or formatted_number) else candidate

        line = _PHONE_NUMBER.sub(strip_phone, line)
        line = re.sub(r"\s+", " ", line).strip(" \t,;|:：-–—")
        if line and normalized_text(line).strip(" .:;-–—") not in _CONTACT_ONLY:
            safe_lines.append(line)
    return "\n".join(safe_lines)

# Words that are too generic to prove anything on their own: a requirement
# matching only on "expérience" or "connaissance" would create a false sense
# of correspondence.  Specific tokens (excel, anglais, lbo…) stay decisive.
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {
        "experience",
        "experiences",
        "connaissance",
        "connaissances",
        "maitrise",
        "niveau",
        "langue",
        "langues",
        "capacite",
        "capacites",
        "esprit",
        "sens",
        "equipe",
        "travail",
        "stages",
        "stage",
        "annees",
        "ans",
        "mois",
        "minimum",
        "required",
        "require",
        "requires",
        "knowledge",
        "skills",
        "ability",
        "abilities",
        "advanced",
        "strong",
        "good",
        "excellent",
        "proficiency",
        "data",
        "years",
        "year",
        "profil",
        "poste",
        "mission",
        "missions",
        "entreprise",
        "candidat",
        "candidate",
        "vous",
        "your",
        "avec",
        "pour",
        "dans",
        "that",
        "this",
        "have",
        "will",
        "their",
        "them",
        "other",
        "autres",
        "afin",
        "etre",
        " avoir",
    }
)

# Short, domain-specific skills are meaningful evidence even though their
# normalized spelling is shorter than the conservative four-character
# threshold below.  Keep this an explicit allowlist: accepting every short
# token would make articles and prepositions create false matches.
_SHORT_SKILL_TOKENS: frozenset[str] = frozenset(
    {"api", "aws", "cfa", "erp", "git", "sas", "sap", "sql", "vba"}
)

_CHECKS: tuple[dict[str, Any], ...] = (
    {
        "key": "no_invented_facts",
        "label": "Aucun fait inventé",
        "detail": "Chaque élément pertinent cite un extrait réel de ton profil ; aucune expérience ni compétence n’est créée.",
    },
    {
        "key": "contact_data_excluded",
        "label": "Données de contact exclues",
        "detail": "E-mail, téléphone et URL LinkedIn ne sont pas utilisés dans cette analyse.",
    },
    {
        "key": "local_only",
        "label": "Analyse locale déterministe",
        "detail": "Aucun modèle ni service externe n’est sollicité ; le résultat est reproductible à l’identique.",
    },
    {
        "key": "manual_review_required",
        "label": "Relecture requise",
        "detail": "Cette préparation est un brouillon factuel : relis-la avant toute candidature.",
    },
)


def _is_unknown_sentinel(text: str) -> bool:
    return normalized_text(text).strip(" .:;-") in {
        "unknown", "inconnu", "inconnue", "not specified", "unspecified",
        "not provided", "non precise", "non renseigne", "non renseignee",
    }


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in normalized_text(text).split()
        if (len(token) >= 4 or token in _SHORT_SKILL_TOKENS)
        and token not in _GENERIC_TOKENS
        and not token.isdigit()
    ]


def _segments(text: str) -> list[str]:
    """Split a profile field into reviewable segments, keeping their wording."""
    segments: list[str] = []
    for line in clean_text(text, limit=6_000).splitlines():
        for sentence in re.split(r"(?<=[.;\n])\s+", line):
            sentence = sentence.strip(" •-–*")
            if sentence:
                segments.append(sentence[:300])
    return segments


def extract_requirements(job: dict[str, Any]) -> list[dict[str, str]]:
    """Adapt the canonical provenance extractor to the CV preparation plan."""
    items: list[dict[str, str]] = []
    analysis = analyze_offer(job)
    for record in analysis.get("requirements") or []:
        if not isinstance(record, Mapping):
            continue
        if record.get("injection_suspect") or record.get("negated"):
            continue
        source = clean_text(record.get("source_field"), limit=80) or "requirements"
        # Education level already has a dedicated evidence-aware comparison;
        # don't turn the source field into a second generic CV requirement.
        if source == "role_level":
            continue
        statement = clean_text(_exclude_contact_details(record.get("text")), limit=MAX_TEXT_LENGTH)
        normalized_statement = normalized_text(statement)
        if (
            len(statement) < 4
            or "all rights reserved" in normalized_statement
            or bool(_STREET_ADDRESS.match(statement))
            or (
                clean_text(record.get("category"), limit=40) in {"other", "mobility"}
                and _BENEFIT_ONLY_TEXT.search(normalized_statement)
            )
        ):
            continue
        if _is_unknown_sentinel(statement):
            continue
        identity = normalized_statement.strip(" .:;,-–—")
        if any(
            identity == normalized_text(existing["text"]).strip(" .:;,-–—")
            for existing in items
        ):
            continue
        if len(items) >= MAX_REQUIREMENTS:
            break
        modality = clean_text(record.get("modality"), limit=40) or "unknown"
        if modality == "required" and _UNVERIFIED_REQUIREMENT_TEXT.search(normalized_statement):
            modality = "unknown"
        item = {
            "text": statement,
            "source": source,
            "modality": modality,
            "category": clean_text(record.get("category"), limit=40) or "other",
            "requirement_id": clean_text(record.get("id"), limit=80),
            "locator": clean_text(record.get("locator"), limit=80),
        }
        items.append(item)
    return items


def _profile_text(profile: dict[str, Any]) -> str:
    return " ".join(clean_text(profile.get(field), limit=6_000) for field in PROFILE_FIELDS)


def _find_evidence(profile: dict[str, Any], tokens: list[str]) -> tuple[str, str, list[str]] | None:
    """Return a verbatim profile excerpt supporting the requirement, if any."""
    normalized_tokens = list(dict.fromkeys(normalized_text(token) for token in tokens))
    candidates: list[tuple[tuple[int, int, int, int], str, str, list[str]]] = []
    for field_index, field in enumerate(PROFILE_FIELDS):
        field_value = clean_text(profile.get(field), limit=6_000)
        if not field_value:
            continue
        normalized_field = normalized_text(field_value)
        matched = [
            token for token in normalized_tokens if f" {token} " in f" {normalized_field} "
        ]
        if not matched:
            continue
        for segment_index, segment in enumerate(_segments(field_value)):
            normalized_segment = normalized_text(segment)
            hits = [token for token in matched if f" {token} " in f" {normalized_segment} "]
            if hits:
                # The excerpt must be a real, verbatim slice of the field.
                excerpt = clean_text(segment, limit=300)
                if normalized_text(excerpt) in normalized_field:
                    first_hit = min(normalized_tokens.index(token) for token in hits)
                    score = (first_hit, -len(hits), field_index, segment_index)
                    candidates.append((score, field, excerpt, hits[:6]))
    if not candidates:
        return None
    _, field, excerpt, hits = min(candidates, key=lambda candidate: candidate[0])
    return field, excerpt, hits


def _canonical_requirements(intelligence: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return the canonical requirement records carried by a snapshot.

    The snapshot is the single contract shared by the explorer, the detailed
    view, the matching panel, the CV preparation, the cover letter and the
    application checklist.  When it is present, the preparation panel reads
    the very same records — and therefore the very same identifiers.

    A statement flagged as an injection attempt is **never** a requirement:
    it stays visible as flagged evidence in the snapshot, but it is excluded
    here so that it can never become an action item, a CV gap or a quoted
    sentence of the cover letter.
    """
    if not isinstance(intelligence, Mapping):
        return []
    records = intelligence.get("requirements")
    if not isinstance(records, (list, tuple)):
        return []
    canonical: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if bool(record.get("injection_suspect")):
            continue
        identifier = clean_text(record.get("id"), limit=80)
        text = clean_text(_exclude_contact_details(record.get("text")), limit=MAX_TEXT_LENGTH)
        source_field = clean_text(record.get("source_field"), limit=80)
        if not identifier or not text:
            continue
        if source_field == "role_level":
            continue
        if _is_unknown_sentinel(text):
            continue
        canonical.append(
            {
                "id": identifier,
                "text": text,
                "source": clean_text(record.get("source_field"), limit=80) or "description_original",
                "source_field": source_field or "description_original",
                "locator": clean_text(record.get("locator"), limit=80),
                "modality": clean_text(record.get("modality"), limit=40) or "unknown",
                "category": clean_text(record.get("category"), limit=40) or "other",
            }
        )
    return canonical


def _injection_suspect_ids(intelligence: Mapping[str, Any] | None) -> list[str]:
    """Return the identifiers of the statements excluded as injection attempts."""
    if not isinstance(intelligence, Mapping):
        return []
    records = intelligence.get("requirements")
    if not isinstance(records, (list, tuple)):
        return []
    identifiers: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if not bool(record.get("injection_suspect")):
            continue
        identifier = clean_text(record.get("id"), limit=80)
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


def _intelligence_block(
    intelligence: Mapping[str, Any] | None,
    canonical: list[dict[str, Any]],
    matched_requirement_ids: list[str],
    unverified_requirement_ids: list[str],
) -> dict[str, Any]:
    """Return the shared identifiers exposed by the preparation panel."""
    if not isinstance(intelligence, Mapping):
        return {}
    return {
        "job_id": clean_text(intelligence.get("job_id"), limit=80),
        "schema_version": int(intelligence.get("schema_version") or 1),
        "source_hash": clean_text(intelligence.get("source_hash"), limit=64),
        "requirement_ids": [record["id"] for record in canonical],
        "requirements_by_id": {record["id"]: record for record in canonical},
        "matched_requirement_ids": list(matched_requirement_ids),
        "unverified_requirement_ids": list(unverified_requirement_ids),
        "to_verify_requirement_ids": list(unverified_requirement_ids),
        # The statements refused as injection attempts are listed, never
        # silently dropped: they are visible, they are not requirements.
        "injection_suspect_ids": _injection_suspect_ids(intelligence),
        "missing": [
            {
                "field": clean_text(item.get("field"), limit=120),
                "label": clean_text(item.get("label"), limit=160),
                "status": clean_text(item.get("status"), limit=40) or "to_verify",
                "reason": clean_text(item.get("reason"), limit=500),
            }
            for item in intelligence.get("missing") or []
            if isinstance(item, Mapping)
        ],
        "contradictions": [
            {
                "id": clean_text(item.get("id"), limit=80),
                "topic": clean_text(item.get("topic"), limit=80),
                "kind": clean_text(item.get("kind"), limit=80),
            }
            for item in intelligence.get("contradictions") or []
            if isinstance(item, Mapping)
        ],
    }


def prepare_application(
    profile: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    job: dict[str, Any],
    *,
    intelligence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the factual preparation panel for one stored offer.

    ``intelligence`` is the versioned offer-intelligence snapshot of the
    offer.  When it is provided, the panel reads the canonical requirement
    records it carries, so every screen shows the same requirement with the
    same identifier.  Without it, the historical local extraction is used.
    """
    profile = profile or {}
    intake = intake or {}
    if intelligence is None and isinstance(job.get("offer_intelligence"), Mapping):
        intelligence = job["offer_intelligence"]
    canonical = _canonical_requirements(intelligence)
    # Guided-intake answers are the person's own declared facts and may be
    # quoted alongside the profile, but contact data never is.
    intake_answers = intake.get("answers") if isinstance(intake.get("answers"), dict) else {}
    working_profile = {
        field: clean_text(_exclude_contact_details(profile.get(field)), limit=6_000)
        for field in PROFILE_FIELDS
    }
    for key in ("strengths", "missions"):
        extra = clean_text(_exclude_contact_details(intake_answers.get(key)), limit=3_000)
        if extra:
            working_profile["experience"] = f"{working_profile['experience']}\n{extra}".strip()

    if isinstance(intelligence, Mapping):
        requirements = [
            {
                "text": record["text"],
                "source": record["source"],
                "requirement_id": record["id"],
                "modality": record["modality"],
                "category": record["category"],
            }
            for record in canonical
        ]
    else:
        requirements = extract_requirements(job)
    profile_blob = normalized_text(_profile_text(working_profile))
    # SK-18 : les missions annoncées par l'offre, avec leur type et les
    # compétences techniques qu'elles impliquent. Ce sont des extraits
    # verbatim du texte de l'offre, jamais des reformulations.
    missions = missions_as_dicts(extract_missions(job.get("description_original", "")))
    matched: list[dict[str, Any]] = []
    matched_requirement_ids: list[str] = []
    unverified: list[dict[str, Any]] = []
    unverified_requirement_ids: list[str] = []
    for requirement in requirements:
        tokens = _tokens(requirement["text"])
        requirement_id = clean_text(requirement.get("requirement_id"), limit=80)
        if not tokens or not profile_blob:
            unverified.append(
                {
                    "requirement": requirement["text"],
                    "note": "Non trouvé dans ton profil : aucun élément comparable n’y figure (vérifie, complète ou ajuste si pertinent).",
                    **({"requirement_id": requirement_id} if requirement_id else {}),
                }
            )
            unverified_requirement_ids.append(requirement_id)
            continue
        evidence = _find_evidence(working_profile, tokens)
        if evidence:
            field, excerpt, hits = evidence
            matched.append(
                {
                    "requirement": requirement["text"],
                    "profile_field": field,
                    "evidence": excerpt,
                    "matched_on": hits,
                    **({"requirement_id": requirement_id} if requirement_id else {}),
                }
            )
            matched_requirement_ids.append(requirement_id)
        else:
            unverified.append(
                {
                    "requirement": requirement["text"],
                    "note": "Non trouvé dans ton profil : aucun élément comparable n’y figure (vérifie, complète ou ajuste si pertinent).",
                    **({"requirement_id": requirement_id} if requirement_id else {}),
                }
            )
            unverified_requirement_ids.append(requirement_id)
    matched = matched[:MAX_MATCHED]
    matched_requirement_ids = matched_requirement_ids[:MAX_MATCHED]

    cv_action_plan: list[dict[str, Any]] = []
    for index, item in enumerate(matched[:MAX_CV_ACTIONS], start=1):
        section = _CV_SECTION_LABELS.get(item["profile_field"], "Profil")
        evidence = clean_text(item["evidence"], limit=300)
        requirement = clean_text(item["requirement"], limit=300)
        cv_action_plan.append(
            {
                "id": f"supported-{index}",
                "priority": "high" if index <= 3 else "medium",
                "status": "supported",
                "action_type": "move_up" if item["profile_field"] in {"skills", "languages"} else "rephrase",
                "action_label": "Mettre en avant" if item["profile_field"] in {"skills", "languages"} else "Reformuler fidèlement",
                "section": section,
                "offer_reference": f"Exigence détectée n°{index}",
                "profile_reference": f"Profil local · {section}",
                "requirement_id": matched_requirement_ids[index - 1] if index - 1 < len(matched_requirement_ids) else "",
                "requirement": requirement,
                "profile_evidence": evidence,
                "matched_on": list(item.get("matched_on") or []),
                "suggested_change": (
                    f"Dans la rubrique « {section} », rends plus visible cet élément déjà présent, "
                    f"sans modifier les faits : « {evidence} ». Adapte seulement l’ordre et la formulation "
                    "à la langue de l’offre."
                ),
                "why": f"Cette preuve locale correspond à l’exigence de l’offre : « {requirement} ».",
                "fact_safe": True,
                "evidence_quality": (
                    "needs_quantification"
                    if item["profile_field"] == "experience" and not re.search(r"\d", evidence)
                    else "documented"
                ),
            }
        )
    remaining_slots = max(0, MAX_CV_ACTIONS - len(cv_action_plan))
    for index, item in enumerate(unverified[:remaining_slots], start=1):
        requirement = clean_text(item["requirement"], limit=300)
        cv_action_plan.append(
            {
                "id": f"needs-evidence-{index}",
                "priority": "high" if index <= 3 else "medium",
                "status": "needs_evidence",
                "action_type": "verify_before_adding",
                "action_label": "Ne pas ajouter sans preuve",
                "section": "À déterminer",
                "offer_reference": f"Exigence détectée non étayée n°{index}",
                "profile_reference": "Aucune preuve trouvée dans le profil local",
                "requirement_id": unverified_requirement_ids[index - 1] if index - 1 < len(unverified_requirement_ids) else "",
                "requirement": requirement,
                "profile_evidence": "",
                "matched_on": [],
                "missing_keywords": _tokens(requirement)[:6],
                "suggested_change": (
                    "Ne l’ajoute pas au CV maintenant. Si tu possèdes réellement cet acquis, renseigne "
                    "d’abord une preuve précise et vérifiable dans ton profil (contexte, action, résultat) ; "
                    "sinon laisse-le absent."
                ),
                "why": f"Aucune preuve correspondante n’a été trouvée dans le profil pour : « {requirement} ».",
                "fact_safe": True,
                "evidence_quality": "missing",
            }
        )
    total_requirements = len(requirements)
    supported_count = len(matched)
    target_language = clean_text(
        job.get("language") or job.get("language_code") or job.get("detected_language"), limit=40
    ) or "à confirmer"
    cv_coverage = {
        "requirements_total": total_requirements,
        "supported": supported_count,
        "to_verify": len(unverified),
        "coverage_percent": round((supported_count / total_requirements) * 100) if total_requirements else 0,
        "target_language": target_language,
        "label": "Couverture documentaire du CV",
        "disclaimer": (
            "Ce pourcentage mesure uniquement les exigences détectées et étayées par ton profil ; "
            "ce n’est ni une probabilité d’embauche ni une note du recruteur."
        ),
    }

    improvements: list[dict[str, str]] = []
    if not profile_blob:
        improvements.append(
            {
                "suggestion": "Complète ton profil local (compétences, expérience, formation, langues) : tant qu’il est vide, aucune comparaison factuelle n’est possible.",
                "basis": "profile",
            }
        )
    if profile_blob and not clean_text(working_profile.get("education")):
        improvements.append(
            {
                "suggestion": "Renseigne ta formation dans Mon profil : le niveau d’études exigé ne peut pas être comparé sans elle.",
                "basis": "profile.education",
            }
        )
    for item in matched[:4]:
        section = _CV_SECTION_LABELS.get(item["profile_field"], "Profil")
        improvements.append(
            {
                "suggestion": (
                    f"Si ce n’est pas déjà explicite, fais apparaître « {item['matched_on'][0]} » dans la "
                    f"section {section.casefold()} du CV face à l’exigence « {clean_text(item['requirement'], limit=120)} »."
                ),
                "basis": f"profile.{item['profile_field']}",
            }
        )
    for item in unverified[:4]:
        improvements.append(
            {
                "suggestion": (
                    f"Vérifie si tu peux documenter « {clean_text(item['requirement'], limit=120)} » dans ton profil ; "
                    "rien n’est ajouté automatiquement et rien n’est supposé."
                ),
                "basis": "job.requirements",
            }
        )
    improvements = improvements[:MAX_IMPROVEMENTS]

    letter_points: list[dict[str, str]] = []
    for item in matched:
        letter_points.append(
            {
                "point": (
                    f"L’offre demande « {clean_text(item['requirement'], limit=160)} » ; "
                    f"ton profil mentionne « {clean_text(item['evidence'], limit=160)} »."
                )
            }
        )
    letter_points = letter_points[:MAX_LETTER_POINTS]

    source_status = clean_text(job.get("source_status"), limit=40) or "unknown"
    deadline_status = clean_text(job.get("deadline_status"), limit=40)
    uncertainty: list[str] = []
    if source_status != "open":
        uncertainty.append(
            "La source ne confirme pas que cette offre est encore ouverte : vérifie la page officielle avant d’agir."
        )
    if deadline_status == "closed":
        uncertainty.append("La date limite connue est dépassée ou l’annonce est indiquée fermée.")
    if not clean_text(job.get("requirements"), limit=20_000):
        uncertainty.append(
            "La source ne fournit pas de champ d’exigences séparé : seuls des passages "
            "explicitement repérés dans sa description sont cités. Cette extraction lexicale "
            "peut être incomplète ; relis le texte source et l’offre officielle."
        )

    return {
        "job": {
            "id": clean_text(job.get("id"), limit=80),
            "title": clean_text(job.get("title"), limit=300),
            "company": clean_text(job.get("company"), limit=240),
            "official_url": clean_text(job.get("official_url"), limit=2_000),
            "source_name": clean_text(job.get("source_name"), limit=160),
            "source_status": source_status,
            "deadline_date": clean_text(job.get("deadline_date"), limit=32),
            "deadline_status": deadline_status,
            "last_verified_at": clean_text(job.get("last_verified_at"), limit=40),
        },
        "requirements": requirements,
        "offer_intelligence": _intelligence_block(
            intelligence, canonical, matched_requirement_ids, unverified_requirement_ids
        ),
        "missions": missions,
        "source_excerpt": clean_text(job.get("description_original"), limit=MAX_SOURCE_EXCERPT),
        "matched_elements": matched,
        "unverified_elements": unverified,
        "cv_action_plan": cv_action_plan,
        "cv_coverage": cv_coverage,
        "cv_improvements": improvements,
        "letter_points": letter_points,
        "uncertainty": uncertainty,
        "checks": [dict(check) for check in _CHECKS],
        "disclaimer": (
            "Préparation locale déterministe fondée sur les seuls textes de l’offre et de ton profil. "
            "Elle ne prédit aucune embauche, n’invente aucun fait et n’envoie aucune candidature."
        ),
    }


def reconcile_cv_plan_with_requirements_fit(
    preparation: dict[str, Any], requirements_fit: Mapping[str, Any]
) -> None:
    """Make the CV plan agree with canonical, evidence-aware fit verdicts.

    The text-match plan is useful for locating profile passages, but a token
    overlap alone cannot prove that a full offer requirement is satisfied.
    When canonical fit data is available, use its verdict for the coverage
    summary and downgrade partial, unsupported, or contradictory matches.
    """
    raw_fits = requirements_fit.get("fits")
    if not isinstance(raw_fits, list):
        return
    fits_by_id = {
        clean_text(fit.get("requirement_id"), limit=120): fit
        for fit in raw_fits
        if isinstance(fit, Mapping) and clean_text(fit.get("requirement_id"), limit=120)
    }

    # A board may repeat the exact same requirement in a structured field and
    # in its free-text description. Keep every canonical fit and citation in
    # ``requirements_fit`` / ``offer_intelligence``; collapse only the user
    # facing CV actions and coverage when wording, category, modality and
    # verdict are identical. Translations, different categories, and divergent
    # verdicts remain separate.
    intelligence = preparation.get("offer_intelligence")
    records_by_id = (
        intelligence.get("requirements_by_id", {})
        if isinstance(intelligence, Mapping)
        else {}
    )
    groups: list[dict[str, Any]] = []
    groups_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    group_by_requirement_id: dict[str, dict[str, Any]] = {}
    for fit in raw_fits:
        if not isinstance(fit, Mapping):
            continue
        requirement_id = clean_text(fit.get("requirement_id"), limit=120)
        text = clean_text(fit.get("requirement_text"), limit=400)
        identity = normalized_text(text)
        if not identity:
            identity = f"id:{requirement_id}" if requirement_id else f"row:{len(groups)}"
        key = (
            identity,
            clean_text(fit.get("category"), limit=80),
            clean_text(fit.get("modality"), limit=40),
            clean_text(fit.get("verdict"), limit=40),
        )
        group = groups_by_key.get(key)
        if group is None:
            group = dict(fit)
            group["requirement_ids"] = []
            group["source_references"] = []
            groups_by_key[key] = group
            groups.append(group)
        if requirement_id and requirement_id not in group["requirement_ids"]:
            group["requirement_ids"].append(requirement_id)
            record = records_by_id.get(requirement_id) if isinstance(records_by_id, Mapping) else None
            record = record if isinstance(record, Mapping) else {}
            group["source_references"].append(
                {
                    "requirement_id": requirement_id,
                    "source_field": clean_text(record.get("source_field"), limit=80),
                    "locator": clean_text(record.get("locator"), limit=80),
                    "text": clean_text(record.get("text") or text, limit=400),
                }
            )
            group_by_requirement_id[requirement_id] = group

    plan = preparation.get("cv_action_plan")
    if isinstance(plan, list):
        reconciled_plan: list[dict[str, Any]] = []
        plan_by_group: dict[int, dict[str, Any]] = {}
        for item in plan:
            if not isinstance(item, dict):
                continue
            requirement_id = clean_text(item.get("requirement_id"), limit=120)
            group = group_by_requirement_id.get(requirement_id)
            if group is not None:
                group_key = id(group)
                existing_item = plan_by_group.get(group_key)
                if existing_item is not None:
                    existing_item["requirement_ids"] = list(group["requirement_ids"])
                    existing_item["source_references"] = list(group["source_references"])
                    continue
                item["requirement_ids"] = list(group["requirement_ids"])
                item["source_references"] = list(group["source_references"])
                plan_by_group[group_key] = item
            else:
                reconciled_plan.append(item)
            if group is not None:
                reconciled_plan.append(item)
            fit = fits_by_id.get(requirement_id)
            verdict = clean_text(fit.get("verdict"), limit=40) if fit else ""
            if verdict not in {"to_verify", "unsupported", "contradicted"}:
                continue
            requirement = clean_text(fit.get("requirement_text") or item.get("requirement"), limit=300)
            evidence = clean_text(fit.get("profile_evidence") or item.get("profile_evidence"), limit=300)
            reason = clean_text(fit.get("reason"), limit=500)
            item["status"] = "needs_evidence"
            item["filter"] = "blocking" if verdict in {"unsupported", "contradicted"} else "verify"
            item["action_type"] = "do_not_overstate"
            item["action_label"] = (
                "Ne pas présenter comme conforme"
                if verdict in {"unsupported", "contradicted"}
                else "Vérifier la couverture complète"
            )
            item["profile_reference"] = (
                "Écart établi par le profil approuvé"
                if verdict in {"unsupported", "contradicted"}
                else "Preuve partielle à vérifier dans le profil approuvé"
            )
            item["profile_evidence"] = evidence
            item["evidence_quality"] = "partial" if evidence else "missing"
            item["blocking_note"] = (
                "Le profil prouve un niveau ou un fait différent de l’exigence. Tu peux uniquement décrire la preuve existante telle quelle ; ne la reformule pas comme si elle satisfaisait l’exigence."
                if verdict in {"unsupported", "contradicted"}
                else "Le profil contient un élément lié à l’exigence, mais il ne prouve pas encore tous ses éléments. N’affiche pas l’exigence complète comme acquise."
            )
            item["suggested_change"] = (
                f"Exigence : « {requirement} ». "
                + (f"Preuve approuvée : « {evidence} ». " if evidence else "Aucune preuve complète n’est enregistrée. ")
                + (f"{reason} " if reason else "")
                + "Présente seulement les faits prouvés et vérifie l’écart avant de préparer le dossier."
            )
            item["why"] = reason or item.get("why", "")
        preparation["cv_action_plan"] = reconciled_plan

    coverage = preparation.get("cv_coverage")
    if not isinstance(coverage, dict):
        return
    applicable_fits = [
        fit for fit in groups
        if isinstance(fit, Mapping) and fit.get("verdict") != "not_applicable"
    ]
    if not applicable_fits:
        return
    counts = {
        verdict: sum(1 for fit in applicable_fits if fit.get("verdict") == verdict)
        for verdict in ("supported", "to_verify", "unsupported", "contradicted")
    }
    total = len(applicable_fits)
    coverage.update(
        requirements_total=total,
        supported=counts["supported"],
        to_verify=counts["to_verify"],
        unsupported=counts["unsupported"],
        contradicted=counts["contradicted"],
        coverage_percent=round(counts["supported"] / total * 100),
        label="Exigences appuyées par des preuves suffisantes",
        disclaimer=(
            "Le taux compte les exigences dont la preuve approuvée a été jugée suffisante par la comparaison locale. "
            "Une preuve partielle, insuffisante ou absente ne compte pas comme conforme."
        ),
    )


def summarize_offer(job: dict[str, Any]) -> dict[str, Any]:
    """Local, deterministic, factual summary of one offer (no model, no network)."""
    intelligence = job.get("offer_intelligence")
    canonical = _canonical_requirements(intelligence if isinstance(intelligence, Mapping) else None)
    if isinstance(intelligence, Mapping):
        requirements = [
            {"text": record["text"], "source": record["source"], "requirement_id": record["id"]}
            for record in canonical
        ]
    else:
        requirements = extract_requirements(job)
    qualification = job.get("qualification_facts")
    qualification = qualification if isinstance(qualification, dict) else {}
    contract_type = clean_text(qualification.get("contract_type"), limit=120) or "unknown"
    start_month = qualification.get("start_month")
    if type(start_month) is not int or not 1 <= abs(start_month) <= 12:
        start_month = None
    duration_min = qualification.get("duration_min_months")
    if type(duration_min) is not int or not 1 <= duration_min <= 24:
        duration_min = None
    return {
        "title": clean_text(job.get("title"), limit=300),
        "company": clean_text(job.get("company"), limit=240),
        "location": ", ".join(part for part in (clean_text(job.get("city"), limit=120),
                                                clean_text(job.get("country"), limit=120)) if part),
        "start_date": clean_text(job.get("start_date"), limit=32),
        "end_date": clean_text(job.get("end_date"), limit=32),
        "deadline_date": clean_text(job.get("deadline_date"), limit=32),
        "posted_date": clean_text(job.get("posted_date"), limit=32),
        "duration_months": job.get("duration_months"),
        "contract_type": contract_type,
        "start_month": start_month,
        "duration_min_months": duration_min,
        "qualification_status": clean_text(qualification.get("target_status"), limit=40) or "to_verify",
        "qualification_missing": list(qualification.get("missing_fields") or []),
        "qualification_provenance": dict(qualification.get("provenance") or {}),
        # Clé historique : les extraits d'exigences (mesure d'exhaustivité et
        # repli d'affichage). Les missions réellement annoncées par l'offre
        # sont détaillées dans « mission_details ».
        "missions": [clean_text(r.get("text"), limit=300) for r in requirements],
        "mission_details": missions_as_dicts(
            extract_missions(job.get("description_original", ""))
        ),
        "prerequisites_count": len(requirements),
        "requirement_ids": [
            clean_text(r.get("requirement_id"), limit=80) for r in requirements if r.get("requirement_id")
        ],
        "official_url": clean_text(job.get("official_url"), limit=2_000),
        "uncertainty": [
            "Résumé local déterministe ; aucune invention. Les champs absents restent inconnus."
        ],
    }
