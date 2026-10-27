"""Vocabulary and contracts of the adversarial CV/offer matching bench (CVBOOST-08).

Pure data: no parsing, no network, no model, no clock.  Everything the bench
knows about its own vocabulary lives here so the fixtures, the runner, the
validators and the report cannot drift apart.

THREE AXES, NEVER MIXED
The bench measures three different things and refuses to add them up:

``couverture``
    Documentary coverage of the CV plan: how many *detected* requirements are
    backed by a verbatim excerpt of the approved profile.  It says nothing
    about hiring chances.

``admissibilite``
    Whether the offer's own facts (contract, duration, start month, academic
    level) are compatible with the criteria the person declared.  It says
    nothing about relevance.

``pertinence``
    The lexical similarity between the person's search brief and the offer.
    It says nothing about either of the two other axes.

A number from one axis must never be presented as a number from another one.
The ``axis_separation`` validator enforces that the CV plan never claims
admissibility, and the report keeps three separate metric blocks.
"""

from __future__ import annotations

SCHEMA_VERSION = "career-matching-bench/1"
THRESHOLDS_SCHEMA_VERSION = "career-matching-bench-thresholds/1"
SUITE_VERSION = "cvboost-08-suite-1"

#: Minimum number of synthetic CV/offer couples the bench must contain.
MIN_CASES = 100

#: The three axes a case belongs to.
AXES = ("couverture", "admissibilite", "pertinence")

#: Adversarial families.  Each family exists because it breaks a naive
#: lexical matcher in a different way.
FAMILIES: dict[str, str] = {
    "faux_positif_lexical": "Un mot partagé crée un faux lien (Excel / analyse financière…).",
    "langue_vs_enseignement": "La langue du programme confondue avec la langue exigée.",
    "contrat": "Type de contrat, durée et période : inadmissibilité déguisée en correspondance.",
    "diplome": "Niveau académique annoncé (M1, M2, Bachelor, doctorat) et accès réel.",
    "negation": "Une exigence niée (« pas requis ») traitée comme une exigence.",
    "avantages": "Un avantage ou une clause d'entreprise transformée en exigence.",
    "competence_offre_seule": "Compétence présente dans l'offre, absente du profil.",
    "profil_multilingue": "Profils et offres multilingues (FR/EN/DE/IT/ES).",
    "acronyme": "Acronymes courts ou longs (CAGR, ERP, PMO, UX, ROI).",
    "homonyme": "Même mot, deux sens (gestion, data, stage, audit).",
    "contact": "Données de contact qui ne doivent jamais être citées.",
    "vide_ou_inconnu": "Profil vide, offre muette, information inconnue.",
}

#: Hard invariants.  They describe the contract of the product, not a score:
#: a breach is a defect, never a "score".
HARD_CHECKS: dict[str, str] = {
    "evidence_verbatim": "Toute preuve citée est une sous-chaîne exacte du profil approuvé.",
    "requirement_traceable": "Toute exigence du plan est traçable dans l'offre (sous-chaîne ou champ sourcé).",
    "locator_resolves": "Chaque exigence issue du contrat de provenance pointe vers un passage résoluble.",
    "no_contact_leak": "Aucune donnée de contact (e-mail, téléphone, LinkedIn) n'apparaît dans le plan.",
    "absent_not_added": "Ce qui est absent du profil n'est jamais ajouté, ni présenté comme étayé.",
    "determinism": "Deux exécutions sur les mêmes entrées donnent le même résultat.",
    "unknown_stays_unknown": "Une information inconnue reste inconnue ; elle n'est jamais affirmée.",
    "axis_separation": "Le plan CV ne revendique ni l'admissibilité, ni une prédiction d'embauche.",
}

#: Semantic checks: the bench compares the observed behaviour with the
#: hand-written ground truth of each synthetic case.
SEMANTIC_CHECKS: dict[str, str] = {
    "requirement_detection": "Les exigences réellement exigées sont détectées, les autres ne le sont pas.",
    "support_decision": "Une exigence n'est dite étayée que si la preuve couvre sa partie décisive.",
    "eligibility_verdict": "Le verdict d'admissibilité correspond aux faits de l'offre.",
    "education_verdict": "Le niveau académique annoncé est restitué sans le déduire du profil.",
    "relevance_components": "Les composants de pertinence correspondent au brief demandé.",
    "quoted_material_verbatim": "Les fragments cités par le plan proviennent des sources, sans invention.",
}

#: Dimensions that may legitimately stay unknown.
UNKNOWN_DIMENSIONS = (
    "education_level",
    "education_ambiguous",
    "contract_type",
    "duration",
    "start_month",
    "requirements",
    "relevance",
    "profile",
    "personal_eligibility",
)

#: Mapping between the bench's eligibility verdict and the product's own
#: qualification status (``career.offer_qualification.qualify_offer``).
ELIGIBILITY_BY_TARGET_STATUS = {
    "conforming": "eligible",
    "non_conforming": "ineligible",
    "to_verify": "unknown",
}

#: Mapping between the bench's education verdict and
#: ``career.education_access.assess_education_access``.
EDUCATION_STATUSES = ("preferred", "consider", "to_verify", "outside_preference")

#: Reference date used for every date-sensitive call, so a run is
#: reproducible whatever the day of the year.
BENCH_AS_OF = "2026-10-01"

#: The bench never talks to the network.  This is stated in every report.
NETWORK_POLICY = (
    "Aucun appel réseau : le banc est 100 % local et déterministe. "
    "Aucune source officielle n'est contactée, aucun profil réel n'est utilisé."
)

#: Reserved example domains.  A fixture that mentions anything else is
#: rejected by the loader: the bench must stay free of real contact data.
ALLOWED_EMAIL_DOMAINS = ("exemple-fake.test", "example-fake.test")
ALLOWED_LINKEDIN_HOSTS = ("linkedin.com",)
