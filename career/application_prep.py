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

from .models import clean_text, normalized_text

MAX_REQUIREMENTS = 40
MAX_TEXT_LENGTH = 400
MAX_MATCHED = 20
MAX_IMPROVEMENTS = 8
MAX_CV_ACTIONS = 12
MAX_LETTER_POINTS = 6
MAX_SOURCE_EXCERPT = 4_000

# Public boards often supply only their description, not a separate
# requirements field. These markers identify explicitly labelled sections or
# requirement statements; their wording is quoted, never rewritten as a fact.
_REQUIREMENT_HEADINGS = frozenset(
    {
        "requirements", "qualifications", "required qualifications",
        "minimum qualifications", "preferred qualifications", "your profile",
        "what you bring", "what we are looking for", "who you are",
        "profil", "profil recherche", "votre profil", "qualifications requises",
        "competences requises", "prerequis",
    }
)
_OTHER_SECTION_HEADINGS = frozenset(
    {
        "responsibilities", "your responsibilities", "what you will do",
        "what you ll do", "about us", "about the role", "benefits",
        "what we offer", "missions", "vos missions", "responsabilites",
        "avantages", "a propos", "notre entreprise", "notre offre",
    }
)
_EXPLICIT_REQUIREMENT_MARKERS = (
    "required", "must have", "you must", "proficiency in", "fluent in",
    "requires", "requis", "requise", "recherche", "maitrise de",
    "maitrise d", "exige", "exigee", "vous devez",
)

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

# Legal footers and page furniture frequently arrive in ATS descriptions as
# if they were requirements. They are never useful CV evidence and create
# misleading suggestions (for example, matching the word ``with``).
_REQUIREMENT_NOISE_MARKERS = (
    "all rights reserved",
    "privacy policy",
    "terms of use",
    "equal opportunity employer",
    "retail clients are not the intended recipients",
    "do not act upon this communication",
    "north wacker drive",
    "copyright",
)


def _infer_modality(text: str) -> str:
    normalized = normalized_text(text)
    if any(marker in f" {normalized} " for marker in (" required ", " must ", " minimum ", " mandatory ", " requis ", " requise ")):
        return "required"
    if any(marker in f" {normalized} " for marker in (" preferred ", " nice to have ", " plus ", " desirable ", " souhaite ")):
        return "preferred"
    return "unknown"

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


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in normalized_text(text).split()
        if (len(token) >= 4 or token in _SHORT_SKILL_TOKENS)
        and token not in _GENERIC_TOKENS
        and not token.isdigit()
        and token not in {"with", "from", "into", "than", "that", "this", "your", "their", "have", "will"}
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
    """Extract the requirement statements the posting itself contains."""
    items: list[dict[str, str]] = []

    def add(text: Any, source: str) -> None:
        statement = clean_text(text, limit=MAX_TEXT_LENGTH)
        if len(statement) < 4:
            return
        normalized_statement = normalized_text(statement)
        if any(marker in normalized_statement for marker in _REQUIREMENT_NOISE_MARKERS):
            return
        if any(statement.casefold() == existing["text"].casefold() for existing in items):
            return
        if len(items) >= MAX_REQUIREMENTS:
            return
        items.append({"text": statement, "source": source, "modality": _infer_modality(statement)})

    structured = clean_text(job.get("requirements"), limit=20_000)
    for line in structured.splitlines():
        add(line, "requirements")
    if not structured:
        # A description is untrusted source text, not an instruction to this
        # program. Conservative lexical extraction is explicitly incomplete;
        # a bounded original excerpt is also returned for human inspection.
        in_requirements = False
        description = clean_text(job.get("description_original"), limit=30_000)
        for line in description.splitlines():
            line = line.strip()
            if not line:
                continue
            prefix = line.split(":", 1)[0]
            heading = normalized_text(prefix)
            if heading in _OTHER_SECTION_HEADINGS:
                in_requirements = False
                continue
            if heading in _REQUIREMENT_HEADINGS:
                in_requirements = True
                if ":" in line and line.split(":", 1)[1].strip():
                    add(line, "description_original")
                continue
            for statement in re.split(r"(?<=[.!?])\s+", line):
                normalized = normalized_text(statement)
                explicit = any(
                    f" {marker} " in f" {normalized} "
                    for marker in _EXPLICIT_REQUIREMENT_MARKERS
                )
                if in_requirements or explicit:
                    add(statement, "description_original")
                if len(items) >= MAX_REQUIREMENTS:
                    break
            if len(items) >= MAX_REQUIREMENTS:
                break
    languages = clean_text(job.get("languages_required"), limit=400)
    if languages:
        add(f"Langues requises : {languages}", "languages_required")
    eligibility = clean_text(job.get("eligibility_requirement"), limit=400)
    if eligibility:
        add(f"Éligibilité : {eligibility}", "eligibility_requirement")
    role_level = clean_text(job.get("role_level"), limit=200)
    if role_level:
        add(f"Niveau visé : {role_level}", "role_level")
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
        text = clean_text(record.get("text"), limit=MAX_TEXT_LENGTH)
        if not identifier or not text:
            continue
        canonical.append(
            {
                "id": identifier,
                "text": text,
                "source": clean_text(record.get("source_field"), limit=80) or "description_original",
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
    working_profile = {field: clean_text(profile.get(field), limit=6_000) for field in PROFILE_FIELDS}
    for key in ("strengths", "missions"):
        extra = clean_text(intake_answers.get(key), limit=3_000)
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
        section = _CV_SECTION_LABELS.get(item["profile_field"], "profil")
        action = "mets en avant" if item["profile_field"] in {"skills", "languages"} else "rends explicite dans"
        improvements.append(
            {
                "suggestion": (
                    f"Si ce n’est pas déjà explicite, {action} la section « {section} » du CV "
                    f"« {item['matched_on'][0]} » face à l’exigence « {clean_text(item['requirement'], limit=120)} »; "
                    "ne change ni le niveau ni les faits."
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
        "missions": [clean_text(r.get("text"), limit=300) for r in requirements],
        "prerequisites_count": len(requirements),
        "requirement_ids": [
            clean_text(r.get("requirement_id"), limit=80) for r in requirements if r.get("requirement_id")
        ],
        "official_url": clean_text(job.get("official_url"), limit=2_000),
        "uncertainty": [
            "Résumé local déterministe ; aucune invention. Les champs absents restent inconnus."
        ],
    }
