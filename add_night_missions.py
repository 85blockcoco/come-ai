#!/usr/bin/env python3
"""Ajoute les missions nocturnes 60-72 (SPEC-025..037) : specs + registre.
Chaînées derrière 59 (deps) pour préserver l'ordre strict. Fixtures synthétiques uniquement.
Exécution: python3 add_night_missions.py"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs" / "agent_missions"

TEMPLATE = """# MISSION {spec} — {titre}

> **Priorité : {prio}** — Lot nocturne 2 (post-SPEC-024). Worktree dédié, push sur branche `{branch}`.

## Contexte
App Career / CVBoost : le dossier (SK-01..SK-11, SPEC-004..024) fournit la pipeline offre→CV→lettre→suivi.
{contexte}

## Mission
{mission}

## Modules (nouveaux, sans conflit avec les autres specs)
```
{modules}
```

## Contrats Python (must-have)
```python
{contrats}
```

## Règles
- Données : **fixtures synthétiques uniquement** (`tests/fixtures/*synthetic*.json`). Aucune donnée réelle.
- Tests : `.venv/bin/python -m pytest` → suite complète verte + `ruff check .` propre.
- Jamais de clé/secrets en dur ; tout via `os.environ`.
- API : routes REST via le pattern `create_app()` de `career/router.py`, sans casser `schema_version=7`.
{regles}
## Livrables
1. Code modules + tests (cas limites + au moins 1 test adversarial).
2. Endpoints REST servis via `create_app()` (smoke test obligatoire).
3. Rapport `docs/agent-reports/{spec}-{slug}.md` (livré, décisions, limites).
4. Push UNIQUEMENT sur la branche `{branch}` (jamais main).
"""

MISSIONS = [
    # ================= VAGUE 1 (après 59) — 4 en parallèle =================
    dict(
        id="60", spec="SPEC-025", prio="P1",
        titre="Analytics funnel candidatures", slug="analytics_funnel",
        branch="agent/spec-025-funnel-analytics", deps=["59"], group=3,
        contexte="Le suivi existe (statuts candidatures) mais rien ne quantifie où les candidatures meurent.",
        mission="Module analytics : entonnoir de conversion par étape, par semaine et par canal de source, avec détection automatique de l'étape goulot.",
        modules="career/analytics_funnel.py      # compute_funnel(), funnel_by_channel(), weakest_stage()\ntests/test_analytics_funnel.py\ntests/fixtures/analytics_synthetic.json",
        contrats="@dataclass\nclass FunnelStage:\n    stage: Literal[\"sent\",\"viewed\",\"prepped\",\"lettered\",\"followed_up\",\"interview\",\"offer\"]\n    count: int\n    conversion_from_prev: float  # 0.0-1.0\n\n@dataclass\nclass FunnelReport:\n    stages: list[FunnelStage]\n    weekly_series: dict[str, dict]   # ISO-week -> {stage: count}\n    bottleneck_stage: str\n    per_channel: dict[str, list[FunnelStage]]",
        regles="- Entonnoir vide → rapport dégénéré cohérent (jamais de division par zéro).\n",
    ),
    dict(
        id="61", spec="SPEC-026", prio="P1",
        titre="Comparateur d'offres côte à côte", slug="offer_compare",
        branch="agent/spec-026-offer-compare", deps=["59"], group=3,
        contexte="Le candidat hésite entre plusieurs offres similaires ; il faut comparer objectivement.",
        mission="Comparateur : attributs normalisés alignés par offre, score pondéré configurable, verdict lisible avec tie-breaker (fraîcheur + fit).",
        modules="career/offer_compare.py          # compare_offers(), DecisionMatrix, normalize_attr()\ntests/test_offer_compare.py\ntests/fixtures/offers_compare_synthetic.json",
        contrats="@dataclass\nclass OfferRow:\n    offer_id: str\n    attrs: dict[str, str | int | float | None]   # normalisés\n\n@dataclass\nclass CompareVerdict:\n    matrix: dict[str, dict[str, object]]      # attr -> offer -> valeur\n    weighted_scores: dict[str, float]\n    ranking: list[str]                         # offer_ids, best first\n    tie_breaker_used: bool",
        regles="- Attribut manquant → None explicite (jamais 0 par défaut) et tolérance dans le score.\n",
    ),
    dict(
        id="62", spec="SPEC-027", prio="P1",
        titre="Simulateur d'entretien STAR", slug="interview_sim",
        branch="agent/spec-027-interview-sim", deps=["59"], group=3,
        contexte="La préparation d'entretien est manuelle ; interview.py basique existe, à étendre sans le casser.",
        mission="Scheduler de questions par offre (mots-clés, secteur) + worksheets STAR guidées avec checklist de preuves et auto-évaluation chiffrée.",
        modules="career/interview_sim.py          # build_question_set(), StarWorksheet, self_score()\ntests/test_interview_sim.py\ntests/fixtures/interview_offers_synthetic.json",
        contrats="@dataclass\nclass InterviewQuestion:\n    kind: Literal[\"behavior\",\"technical\",\"motivation\",\"company\"]\n    question: str\n    evidence_needed: list[str]     # vers preuves du profil\n\n@dataclass\nclass StarWorksheet:\n    question_id: str\n    situation: str = \"\"\n    task: str = \"\"\n    action: str = \"\"\n    result: str = \"\"\n    completeness: float            # 0-1 calculé",
        regles="- ≥ 12 questions par offre, les 4 kinds présents ; génération déterministe (seed configurable).\n",
    ),
    dict(
        id="63", spec="SPEC-028", prio="P2",
        titre="Checklist documents administratifs stage", slug="stage_admin_docs",
        branch="agent/spec-028-stage-admin-docs", deps=["59"], group=3,
        contexte="Stage à l'étranger = papier (convention tripartite, visa, assurance) ; rien n'existe dans l'app.",
        mission="Moteur de checklist administrative par pays, statut par pièce (missing/in_progress/ok/not_applicable), preuves exigées, récap exportable.",
        modules="career/stage_admin_docs.py       # AdminChecklist, REQUIREMENTS_BY_COUNTRY, completeness()\ntests/test_stage_admin_docs.py\ntests/fixtures/admin_docs_synthetic.json",
        contrats="@dataclass\nclass AdminItem:\n    key: str                       # convention, insurance, work_permit...\n    label_fr: str\n    required: bool\n    status: Literal[\"missing\",\"in_progress\",\"ok\",\"not_applicable\"]\n    proof_refs: list[str]\n\n@dataclass\nclass AdminChecklist:\n    country: str\n    items: list[AdminItem]\n    blocking_missing: list[str]",
        regles="- REQUIREMENTS_BY_COUNTRY : FR + 4 pays déjà couverts par les connecteurs internationaux.\n",
    ),
    # ================= VAGUE 2 =================
    dict(
        id="64", spec="SPEC-029", prio="P1",
        titre="Moteur de relances chronologiques", slug="followup_engine",
        branch="agent/spec-029-followup-engine", deps=["60"], group=4,
        contexte="SPEC-025 dit QUI relancer ; il faut le QUAND et le COMBIEN (anti-spam).",
        mission="Planificateur de relances : lit candidatures + historique, calcule les actions du jour, refuse les sur-relances, s'intègre au cockpit existant.",
        modules="career/followup_engine.py        # FollowupPolicy, plan_today(), spam_guard()\ntests/test_followup_engine.py\ntests/fixtures/followups_synthetic.json",
        contrats="@dataclass\nclass FollowupAction:\n    application_id: str\n    due_date: str                  # ISO\n    reason: str                    # no_response_j7, viewed_no_reply, deadline_soon\n    channel: Literal[\"email\",\"portal\",\"in_person\"]\n\n@dataclass\nclass FollowupPlan:\n    date: str\n    actions: list[FollowupAction]\n    blocked_reasons: dict[str, str]  # app_id -> pourquoi bloqué",
        regles="- Windows : première relance J+7 ; jamais < 5 jours entre 2 relances d'une même candidature.\n",
    ),
    dict(
        id="65", spec="SPEC-030", prio="P2",
        titre="Export & partage lecture CV", slug="share_export",
        branch="agent/spec-030-share-export", deps=["61"], group=4,
        contexte="Envoyer un dossier propre à un contact/école exige un export standardisé et contrôlé.",
        mission="Générateur de bundle de candidature (ZIP + manifest.json) et vue 'lecture' partagée omettant les champs privés ; chaque export tracé.",
        modules="career/share_export.py           # build_bundle(), ShareView, redact()\ntests/test_share_export.py\ntests/fixtures/share_synthetic.json",
        contrats="@dataclass\nclass ShareBundle:\n    files: dict[str, bytes]        # path -> contenu\n    manifest: dict                 # version, offer_id, generated_at, checksums\n\n@dataclass\nclass ShareView:\n    fields: dict[str, object]      # champs autorisés uniquement\n    redacted: list[str]            # champs omis volontairement",
        regles="- Redaction en liste blanche stricte : les champs privés ne sortent jamais, même dans le manifest.\n",
    ),
    dict(
        id="66", spec="SPEC-031", prio="P2",
        titre="Minage FAQ sectorielle des offres", slug="faq_mining",
        branch="agent/spec-031-sector-faq", deps=["62"], group=4,
        contexte="Les offres scindées en base contiennent des formulations répétitives (attentes, outils, contraintes de stage).",
        mission="Extracteur qui regroupe les attentes par secteur/famille de poste et produit une FAQ sectorielle : questions probables + éléments de réponse issus des preuves du profil.",
        modules="career/faq_mining.py             # mine_sector_faq(), cluster_intents(), expected_questions()\ntests/test_faq_mining.py\ntests/fixtures/faq_offers_synthetic.json",
        contrats="@dataclass\nclass SectorFaq:\n    sector: str\n    top_terms: list[tuple[str, int]]      # (terme, fréquence)\n    likely_questions: list[str]\n    profile_answers: dict[str, list[str]] # q -> éléments de réponse du profil",
        regles="- Clustering déterministe (aucun appel réseau) ; fréquences vérifiées par test sur fixture.\n",
    ),
    dict(
        id="67", spec="SPEC-032", prio="P1",
        titre="Mode hors-ligne & cache local", slug="offline_mode",
        branch="agent/spec-032-offline-cache", deps=["63"], group=4,
        contexte="L'app doit rester utilisable sans réseau (train, Ariège, coupures) : recherche, dossier, checklist.",
        mission="Couche de cache local ?expire? pour les lectures (offres vues, checklists, dossiers) avec politique de fraîcheur et bandeau d'état hors-ligne.",
        modules="career/offline_mode.py           # OfflineCache, freshness_policy(), serve_or_cache()\ntests/test_offline_mode.py\ntests/fixtures/offline_synthetic.json",
        contrats="@dataclass\nclass CacheEntry:\n    key: str\n    payload: dict\n    fetched_at: str                # ISO\n    max_age_hours: int\n\n@dataclass\nclass OfflineDecision:\n    source: Literal[\"network\",\"cache\",\"stale\"]\n    age_hours: float | None\n    degraded_fields: list[str]     # champs servis 'stale'",
        regles="- Aucune écriture de donnée personnelle hors du workspace local ; cache chiffrable à disque (accepté: plain JSON tant que local user dir).\n",
    ),
    # ================= VAGUE 3 =================
    dict(
        id="68", spec="SPEC-033", prio="P2",
        titre="Variantes traduites du dossier (EN/DE/ES)", slug="translation_variants",
        branch="agent/spec-033-translation-variants", deps=["66"], group=5,
        contexte="Les connecteurs internationaux ramènent des offres EN/DE/ES ; adapter le dossier dans la langue est décisif.",
        mission="Variants de CV/lettre par langue : détecter la langue de l'offre, produire la variante traduite en s'appuyant sur l'arena multi-IA (SPEC-017) si disponible, sinon glossaire statique — jamais d'appel réseau sans arena.",
        modules="career/translation_variants.py   # detect_offer_lang(), build_variant(), LexiconGL\ncareer/lexicons/en.json + de.json + es.json (synthétiques)\ntests/test_translation_variants.py",
        contrats="@dataclass\nclass VariantReport:\n    offer_lang: Literal[\"en\",\"de\",\"es\",\"fr\"]\n    mode: Literal[\"arena\",\"lexicon\",\"passthrough\"]\n    translated_fields: dict[str, str]\n    untranslated: list[str]        # terms sans équivalent\n\n@dataclass\nclass LexiconGL:\n    lang: str\n    terms: dict[str, str]          # fr -> lang",
        regles="- Détection langue par heuristique locale (stopwords) ; test adversarial : offre mixte FR/EN.\n",
    ),
    dict(
        id="69", spec="SPEC-034", prio="P1",
        titre="Sauvegarde / restauration workspace", slug="workspace_backup",
        branch="agent/spec-034-workspace-backup", deps=["65"], group=5,
        contexte="Le workspace utilisateur (candidatures, dossiers, preuves) doit être exportable/restaurable sans perte.",
        mission="Backup ZIP versionné (manifest + checksums) et restore avec validation de schéma + diff avant écrasement ; jamais d'écrasement sans confirmation explicite de l'appelant.",
        modules="career/workspace_backup.py       # create_backup(), restore_backup(), diff_state()\ntests/test_workspace_backup.py\ntests/fixtures/backup_synthetic.json",
        contrats="@dataclass\nclass BackupManifest:\n    created_at: str\n    schema_version: int            # actuel = 7\n    files: list[str]\n    checksums: dict[str, str]\n\n@dataclass\nclass RestorePlan:\n    to_overwrite: list[str]\n    to_add: list[str]\n    conflicts: list[str]           # jamais résolus silencieusement",
        regles="- Restore refuse en cas de schema_version différent du workspace local sauf flag explicite upgrade=True.\n",
    ),
    dict(
        id="70", spec="SPEC-035", prio="P1",
        titre="Journal d'audit des décisions", slug="audit_journal",
        branch="agent/spec-035-audit-journal", deps=["64"], group=5,
        contexte="Traçabilité : chaque décision automatisée (score, suggestion de relance, verdict arena) doit être explicable a posteriori.",
        mission="Journal append-only des décisions (qui, quand, contexte, résultat) avec recherche/filtre et génération d'un rapport d'explication par décision.",
        modules="career/audit_journal.py          # AuditJournal, record(), explain()\ntests/test_audit_journal.py\ntests/fixtures/audit_synthetic.json",
        contrats="@dataclass\nclass AuditEntry:\n    decision_id: str\n    decision_type: str             # followup_scheduled, offer_ranked, arena_verdict...\n    context: dict\n    outcome: dict\n    at: str\n\n@dataclass\nclass AuditExplanation:\n    entry: AuditEntry\n    narrative: str                  # explication en français lisible\n    contributing_factors: list[tuple[str, float]]",
        regles="- Append-only : aucune API de modification/suppression ; hash-chaîné simple (prev_hash) avec détection de altération (test adversarial).\n",
    ),
    dict(
        id="71", spec="SPEC-036", prio="P2",
        titre="Bilan hebdo & objectifs", slug="weekly_review",
        branch="agent/spec-036-weekly-review", deps=["67"], group=5,
        contexte="Un bilan hebdomadaire (candidatures, effort vs résultats) motive et cale les objectifs.",
        mission="Agrégateur hebdo : N candidatures envoyées, taux de réponse, temps par étape, comparaison à l'objectif fixé, top 3 actions recommandées pour la semaine suivante.",
        modules="career/weekly_review.py          # weekly_summary(), objective_check(), recommend_next()\ntests/test_weekly_review.py\ntests/fixtures/weekly_synthetic.json",
        contrats="@dataclass\nclass WeeklySummary:\n    iso_week: str\n    applications_sent: int\n    responses: int\n    interview_rate: float\n    objective_met: bool | None\n    top_actions: list[str]         # max 3\n\n@dataclass\nclass Objective:\n    metric: Literal[\"applications\",\"responses\",\"interviews\"]\n    target: int\n",
        regles="- Objectifs absents → objective_met=None et top_actions basées sur les données seules.\n",
    ),
    # ================= VAGUE 4 =================
    dict(
        id="72", spec="SPEC-037", prio="P1",
        titre="Briefing J-1 veille d'entretien", slug="j1_briefing",
        branch="agent/spec-037-j1-briefing", deps=["68", "70"], group=6,
        contexte="La veille d'un entretien, tout doit être réuni en un seul document actionable.",
        mission="Générateur de briefing J-1 : fiche entreprise (sources), questions probables (SPEC-031), worksheets STAR remplies (SPEC-027), checklist administratives (SPEC-028) si stage à l'étranger, éléments à relire du CV — un seul JSON/export lien.",
        modules="career/j1_briefing.py            # build_j1_briefing(), BriefingDoc\ntests/test_j1_briefing.py\ntests/fixtures/j1_synthetic.json",
        contrats="@dataclass\nclass BriefingDoc:\n    application_id: str\n    company_facts: list[str]       # avec sources\n    top_questions: list[str]       # depuis SPEC-031\n    star_ready: list[str]          # worksheets complètes (>= 0.8 completeness)\n    admin_blockers: list[str]      # de SPEC-028 si applicable\n    cv_section_reread: list[str]",
        regles="- Briefing incomplet (worksheets vides) → document livré avec sections 'À COMPLÉTER' explicites, jamais masquées.\n",
    ),
]

# ---------- 1) Écrire les fichiers spec ----------
for m in MISSIONS:
    body = TEMPLATE.format(
        spec=m["spec"], titre=m["titre"], prio=m["prio"], branch=m["branch"],
        contexte=m["contexte"], mission=m["mission"], modules=m["modules"],
        contrats=m["contrats"], regles=m["regles"], slug=m["slug"],
    )
    path = DOCS / f"{m['spec']}-{m['slug'].upper()}.md"
    path.write_text(body, encoding="utf-8")
    print("spec →", path.name)

# ---------- 2) Mettre à jour le registre ----------
REG = ROOT / "missions_registry.json"
reg = json.load(open(REG, encoding="utf-8"))
existing = {m["id"] for m in reg["missions"]}
for m in MISSIONS:
    if m["id"] in existing:
        print("skip (déjà présent):", m["id"])
        continue
    reg["missions"].append({
        "id": m["id"],
        "title": f"{m['spec']} — {m['titre']}",
        "branch": m["branch"],
        "prompt_file": f"docs/agent_missions/{m['spec']}-{m['slug'].upper()}.md",
        "dependencies": m["deps"],
        "status": "pending",
        "description": m["desc"] if "desc" in m else m["mission"],
    })

# groups: index 3,4,5,6 relatifs à la fin : on appelle "vagues nocturnes"
# on calcule le max des indices existants et on appose les groupes à la fin
order = reg["execution_order"]
# idempotence : retirer d'éventuels anciens groupes nocturnes
new_ids = {m["id"] for m in MISSIONS}
for g in [g for g in order if any(x in new_ids for x in g)]:
    order.remove(g)

waves = {}
for m in MISSIONS:
    waves.setdefault(m["group"], []).append(m["id"])
for g in sorted(waves):
    order.append(waves[g])
    print("group →", waves[g])

json.dump(reg, open(REG, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("registre:", len(reg["missions"]), "missions |", len(order), "groupes d'ordre")
