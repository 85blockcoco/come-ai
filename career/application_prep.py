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
from typing import Any

from .models import clean_text, normalized_text

MAX_REQUIREMENTS = 40
MAX_TEXT_LENGTH = 400
MAX_MATCHED = 20
MAX_IMPROVEMENTS = 8
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
        "strong",
        "good",
        "excellent",
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
    """Extract the requirement statements the posting itself contains."""
    items: list[dict[str, str]] = []

    def add(text: Any, source: str) -> None:
        statement = clean_text(text, limit=MAX_TEXT_LENGTH)
        if len(statement) < 4:
            return
        if any(statement.casefold() == existing["text"].casefold() for existing in items):
            return
        if len(items) >= MAX_REQUIREMENTS:
            return
        items.append({"text": statement, "source": source})

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
    normalized_tokens = {normalized_text(token) for token in tokens}
    for field in PROFILE_FIELDS:
        field_value = clean_text(profile.get(field), limit=6_000)
        if not field_value:
            continue
        normalized_field = normalized_text(field_value)
        matched = sorted(
            token for token in normalized_tokens if f" {token} " in f" {normalized_field} "
        )
        if not matched:
            continue
        for segment in _segments(field_value):
            normalized_segment = normalized_text(segment)
            hits = [token for token in matched if f" {token} " in f" {normalized_segment} "]
            if hits:
                # The excerpt must be a real, verbatim slice of the field.
                excerpt = clean_text(segment, limit=300)
                if normalized_text(excerpt) in normalized_field:
                    return field, excerpt, hits[:6]
    return None


def prepare_application(
    profile: dict[str, Any] | None,
    intake: dict[str, Any] | None,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Build the factual preparation panel for one stored offer."""
    profile = profile or {}
    intake = intake or {}
    # Guided-intake answers are the person's own declared facts and may be
    # quoted alongside the profile, but contact data never is.
    intake_answers = intake.get("answers") if isinstance(intake.get("answers"), dict) else {}
    working_profile = {field: clean_text(profile.get(field), limit=6_000) for field in PROFILE_FIELDS}
    for key in ("strengths", "missions"):
        extra = clean_text(intake_answers.get(key), limit=3_000)
        if extra:
            working_profile["experience"] = f"{working_profile['experience']}\n{extra}".strip()

    requirements = extract_requirements(job)
    profile_blob = normalized_text(_profile_text(working_profile))

    matched: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    for requirement in requirements:
        tokens = _tokens(requirement["text"])
        if not tokens or not profile_blob:
            unverified.append(
                {
                    "requirement": requirement["text"],
                    "note": "Non trouvé dans ton profil : aucun élément comparable n’y figure (vérifie, complète ou ajuste si pertinent).",
                }
            )
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
                }
            )
        else:
            unverified.append(
                {
                    "requirement": requirement["text"],
                    "note": "Non trouvé dans ton profil : aucun élément comparable n’y figure (vérifie, complète ou ajuste si pertinent).",
                }
            )
    matched = matched[:MAX_MATCHED]

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
        improvements.append(
            {
                "suggestion": (
                    f"Si ce n’est pas déjà explicite, fais apparaître « {item['matched_on'][0]} » dans la "
                    f"section compétences du CV face à l’exigence « {clean_text(item['requirement'], limit=120)} »."
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
        "source_excerpt": clean_text(job.get("description_original"), limit=MAX_SOURCE_EXCERPT),
        "matched_elements": matched,
        "unverified_elements": unverified,
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
    requirements = extract_requirements(job)
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
        "missions": [clean_text(r.get("text"), limit=300) for r in requirements],
        "prerequisites_count": len(requirements),
        "official_url": clean_text(job.get("official_url"), limit=2_000),
        "uncertainty": [
            "Résumé local déterministe ; aucune invention. Les champs absents restent inconnus."
        ],
    }
