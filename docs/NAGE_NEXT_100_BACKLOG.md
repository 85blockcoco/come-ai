# NAGE NEXT 100 — Backlog (10 lots × 10 missions)

Statut: **spécifié** (pas encore exécuté). Branche de travail : `agent/nage-next-100` (à créer).
Coordination Codex : ne pas toucher `devkit/**`, `desktop_static/**` (réservés à Codex pendant l'intégration).
Fichiers partagés (`career/router.py`, `come_ai_web.py`) : un seul écrivain à la fois.

Légende statuts : ⬜ spécifiée · 🔄 en cours · ✅ livrée (branche) · 🔗 intégrée · ✔ vérifiée.

---

## Lot A — Sources officielles internationales et fraîcheur (A01–A10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| A01 | Connecteur UK (Prospects/Gradcracker/TargetJobs) | career/connectors/uk_sources.py, tests/test_uk_sources.py | — | ≥30 tests, fixtures synthétiques, pas de réseau en test |
| A02 | Connecteur DE (Absolventa/StepStone trainee) | career/connectors/de_sources.py, tests/test_de_sources.py | — | ≥30 tests |
| A03 | Connecteur ES (IEFP/InfoJobs) | career/connectors/es_sources.py, tests/test_es_sources.py | — | ≥30 tests |
| A04 | Connecteur US (Handshake/USAJobs intern) | career/connectors/us_sources.py, tests/test_us_sources.py | — | ≥30 tests |
| A05 | Normalisation des champs source (titre, lieu, date) | career/source_normalizer.py, tests/test_source_normalizer.py | A01-A04 | contrat commun, ≥40 tests |
| A06 | Fraîcheur des offres (TTL, re-vérification URL) | career/offer_freshness.py, tests/test_offer_freshness.py | — | TTL 24h, 429 backoff |
| A07 | Déduplication cross-source (URL canonical + titre/entreprise) | career/cross_source_dedup.py, tests/test_cross_source_dedup.py | A05 | ≥40 tests, adversarial |
| A08 | Provenance et confiance par source | career/source_trust.py (existant) + tests | A01-A04 | score de confiance documenté |
| A09 | Cache local des offres avec invalidation | career/offer_cache.py, tests/test_offer_cache.py | A06 | TTL, purge, pas de données perso |
| A10 | Rapport de couverture sources (quelles sources actives) | career/source_coverage.py (existant) + tests | A01-A04 | rapport synthétique |

## Lot B — Qualification des stages (B01–B10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| B01 | Extraction robuste des dates de début/fin | career/offer_dates.py (existant) + tests | — | ≥40 cas, formats ISO/FR/EN |
| B02 | Détection de durée (≥6 mois, stage long) | career/duration_detector.py, tests/test_duration_detector.py | B01 | min 6 mois, edge cases |
| B03 | Détection langue de l'offre | career/translation_variants.py (existant) + tests | — | heuristique stopwords, mixte FR/EN |
| B04 | Détection type de contrat (stage/alternance/CDD) | career/contract_type.py, tests/test_contract_type.py | — | ≥30 cas |
| B05 | Niveau diplôme requis (BBA/Bac+4/M2/MBA) | career/degree_level.py, tests/test_degree_level.py | — | BBA, Bac+4, M1, M2, MBA |
| B06 | Filtrage géographique (pays/ville) | career/countries.py (existant) + tests | — | canonical codes |
| B07 | Exclusions géographiques utilisateur | career/geo_exclusions.py, tests/test_geo_exclusions.py | B06 | liste éditable |
| B08 | Score de pertinence stage (durée+langue+diplôme) | career/stage_fit.py, tests/test_stage_fit.py | B02,B03,B04,B05 | score 0-100 transparent |
| B09 | Filtre "international accessible BBA" | career/intl_filter.py, tests/test_intl_filter.py | B02,B05,B06 | ≥30 cas |
| B10 | Rapport de qualification par offre | career/qualification_report.py, tests/test_qualification_report.py | B08,B09 | JSON + MD |

## Lot C — Classement expliqué et shortlist (C01–C10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| C01 | Score expliqué (facteurs + poids) | career/scoring.py (existant) + tests | — | transparence |
| C02 | Shortlist automatique (top N par score) | career/shortlist.py, tests/test_shortlist.py | C01 | top 10, justifié |
| C03 | Comparaison d'offres (side-by-side) | career/offer_compare.py (existant) + tests | — | ≥2 offres |
| C04 | Déduplication dans la shortlist | career/job_deduplication.py (existant) + tests | C02 | pas de doublon |
| C05 | Raisonnement "pourquoi cette offre" | career/offer_rationale.py, tests/test_offer_rationale.py | C01 | texte FR |
| C06 | Filtre par secteur (finance, tech, consulting) | career/sector_filter.py, tests/test_sector_filter.py | — | liste éditable |
| C07 | Filtre par type de stage (M&A, CIB, corp fin) | career/finance_family.py, tests/test_finance_family.py | — | familles finance |
| C08 | Tri par date limite / urgence | career/deadline_sort.py, tests/test_deadline_sort.py | B01 | dates limites |
| C09 | Export shortlist CSV/JSON | career/shortlist_export.py, tests/test_shortlist_export.py | C02 | CSV + JSON |
| C10 | Dashboard shortlist (texte) | career/shortlist_dashboard.py, tests/test_shortlist_dashboard.py | C02,C09 | résumé lisible |

## Lot D — Profil approuvé, preuves, import CV (D01–D10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| D01 | Import CV PDF/DOCX robuste | career/profile_import.py (existant) + tests | — | PDF/DOCX, erreurs gérées |
| D02 | Extraction sections CV (exp, edu, skills) | career/cv_parser.py, tests/test_cv_parser.py | D01 | sections détectées |
| D03 | Validation profil (champs requis) | career/profile_validation.py, tests/test_profile_validation.py | — | ≥20 cas |
| D04 | Registre de preuves (evidence) | career/evidence_registry.py, tests/test_evidence_registry.py | — | append-only |
| D05 | Approbation de preuve (humain) | career/evidence_approval.py, tests/test_evidence_approval.py | D04 | validation explicite |
| D06 | Fraîcheur des preuves (date) | career/evidence_freshness.py, tests/test_evidence_freshness.py | D04 | TTL configurable |
| D07 | Lien preuve → claim | career/evidence_link.py, tests/test_evidence_link.py | D04,D05 | traçabilité |
| D08 | Import LinkedIn (local, consentement) | career/linkedin_import.py, tests/test_linkedin_import.py | D01 | consent OFF par défaut |
| D09 | Fusion de profils (dédup) | career/profile_merge.py, tests/test_profile_merge.py | D01,D08 | conflits signalés |
| D10 | Rapport de complétude profil | career/profile_readiness.py (existant) + tests | D03 | score 0-100 |

## Lot E — Adaptation factuelle du CV et variantes (E01–E10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| E01 | Génération CV adapté (factuel) | career/cv_variants.py (existant) + tests | D04,D05 | uniquement faits approuvés |
| E02 | Variante par métier (finance, tech, consulting) | career/cv_by_role.py, tests/test_cv_by_role.py | E01 | gabarits par famille |
| E03 | Variantes par langue (EN/DE/ES) | career/translation_variants.py (existant) + tests | E01 | détection + lexique/arena |
| E04 | Vérification factuelle (claim_check) | career/claim_check.py (existant) + tests | E01,D04 | labels + suggestions |
| E05 | Score qualité CV (dossier_quality) | career/dossier_quality.py (existant) + tests | E04 | score 0-100 |
| E06 | Export CV PDF/DOCX | career/document_export.py (existant) + tests | E01 | PDF + DOCX |
| E07 | Diff visuel avant/après | career/cv_diff.py, tests/test_cv_diff.py | E01 | diff lisible |
| E08 | Versioning des variantes | career/cv_versions.py, tests/test_cv_versions.py | E01 | historique |
| E09 | Validation humaine avant export | career/cv_approval.py, tests/test_cv_approval.py | E05 | gate explicite |
| E10 | Rapport de génération CV | career/cv_generation_report.py, tests/test_cv_generation_report.py | E01-E09 | synthèse |

## Lot F — Lettres de motivation ciblées et langues (F01–F10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| F01 | Génération lettre ciblée | career/cover_letter.py, tests/test_cover_letter.py | D04,E01 | faits approuvés uniquement |
| F02 | Lettre multi-langues | career/cover_letter_i18n.py, tests/test_cover_letter_i18n.py | F01,E03 | EN/DE/ES/FR |
| F03 | Ton et style (formel/concis) | career/letter_tone.py, tests/test_letter_tone.py | F01 | paramétrable |
| F04 | Personnalisation par entreprise | career/letter_company.py, tests/test_letter_company.py | F01,C05 | faits entreprise |
| F05 | Vérification factuelle lettre | career/claim_check.py (réutiliser) + tests | F01,E04 | même gate |
| F06 | Score qualité lettre | career/dossier_quality.py (réutiliser) + tests | F05 | score 0-100 |
| F07 | Export lettre PDF/DOCX | career/document_export.py (existant) + tests | F01 | PDF + DOCX |
| F08 | Modèles de lettre par secteur | career/letter_templates.py, tests/test_letter_templates.py | F01 | finance/tech/consulting |
| F09 | Validation humaine avant envoi | career/letter_approval.py, tests/test_letter_approval.py | F06 | gate explicite |
| F10 | Rapport de génération lettre | career/letter_generation_report.py, tests/test_letter_generation_report.py | F01-F09 | synthèse |

## Lot G — Dossier de candidature, exports et formulaires (G01–G10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| G01 | Apply-kit par offre (dossier prêt) | career/apply_kit.py (existant) + tests | E01,F01 | readiness score |
| G02 | Réponses types copiables | career/quick_answers.py (existant) + tests | E01,F01 | ≥9 réponses |
| G03 | Guide ATS par plateforme | career/ats_guide.py (existant) + tests | — | greenhouse/lever/ashby |
| G04 | Confirmation d'envoi + relance | career/send_confirmation.py (existant) + tests | G01 | humain obligatoire |
| G05 | Export groupé (zip) | career/bundle_export.py, tests/test_bundle_export.py | G01 | zip + copie |
| G06 | Formulaires ATS (champs) | career/ats_forms.py, tests/test_ats_forms.py | G03 | champs + validation |
| G07 | Checklist de dossier | career/dossier_checklist.py, tests/test_dossier_checklist.py | G01 | items cochables |
| G08 | Prévisualisation dossier | career/dossier_preview.py, tests/test_dossier_preview.py | G01 | rendu texte |
| G09 | Suivi des envois (tracker) | career/apply_tracker.py, tests/test_apply_tracker.py | G04 | statuts |
| G10 | Rapport d'export | career/export_report.py, tests/test_export_report.py | G05,G06 | synthèse |

## Lot H — Entretiens, suivi et relances (H01–H10)

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation |
|---|---|---|---|---|
| H01 | Préparation entretien (questions probables) | career/interview.py (existant) + tests | C05,F04 | questions + réponses |
| H02 | Worksheets STAR | career/star_worksheets.py, tests/test_star_worksheets.py | H01 | complétude ≥0.8 |
| H03 | Briefing J-1 | career/j1_briefing.py (existant) + tests | H01,H02 | document unique |
| H04 | Suivi des candidatures | career/application_dashboard.py (existant) + tests | G09 | statuts |
| H05 | Moteur de relances | career/followup_engine.py, tests/test_followup_engine.py | H04 | relances dues |
| H06 | Calendrier entretiens (export ICS) | career/calendar_export.py (existant) + tests | H04 | ICS valide |
| H07 | Détection réponses email | career/mail_ingest.py (existant) + tests | H04 | IMAP consent |
| H08 | Journal d'audit décisions | career/audit_journal.py (existant) + tests | H04 | append-only |
| H09 | Bilan hebdo | career/weekly_review.py (existant) + tests | H04 | objectifs |
| H10 | Rapport de suivi | career/tracking_report.py, tests/test_tracking_report.py | H04-H09 | synthèse |

## Lot I — Fiabilité IA, mémoire utile, récupération (I01–I10)

> ⚠️ Réservé à Codex pendant l'intégration : ne pas toucher `devkit/**`, `desktop_static/**`.
> Missions marquées « attente coordination » si elles nécessitent ces fichiers.

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation | Statut |
|---|---|---|---|---|---|
| I01 | Mémoire personnelle (sources) | career/personal_memory.py, tests/test_personal_memory.py | — | stockage local | ⬜ |
| I02 | Récupération après erreur (retry/backoff) | career/recovery.py, tests/test_recovery.py | — | backoff exponentiel | ⬜ |
| I03 | Circuit breaker fournisseur | career/circuit_breaker.py, tests/test_circuit_breaker.py | — | seuil configurable | ⬜ |
| I04 | Validation de sortie IA (guardrails) | career/ai_guardrails.py, tests/test_ai_guardrails.py | — | règles déterministes | ⬜ |
| I05 | Traçabilité des décisions IA | career/ai_traceability.py, tests/test_ai_traceability.py | I01 | append-only | ⬜ |
| I06 | Cache des réponses IA | career/ai_cache.py, tests/test_ai_cache.py | — | TTL, invalidation | ⬜ |
| I07 | Fallback modèle (si indisponible) | career/model_fallback.py, tests/test_model_fallback.py | — | liste ordonnée | ⬜ |
| I08 | Évaluation qualité IA (score) | career/ai_quality.py, tests/test_ai_quality.py | I04 | score 0-100 | ⬜ |
| I09 | Mémoire de contexte (session) | career/context_memory.py, tests/test_context_memory.py | I01 | reset propre | ⬜ |
| I10 | Rapport de fiabilité IA | career/ai_reliability_report.py, tests/test_ai_reliability_report.py | I01-I09 | synthèse | ⬜ attente coordination (UI) |

## Lot J — Recettes, accessibilité, performances, régressions (J01–J10)

> ⚠️ Réservé à Codex pendant l'intégration : ne pas toucher `devkit/**`, `desktop_static/**`.
> Missions marquées « attente coordination » si elles nécessitent ces fichiers.

| ID | Mission | Fichiers autorisés | Dépendances | Critères d'acceptation | Statut |
|---|---|---|---|---|---|
| J01 | Recette bout-en-bout (10 offres) | tests/test_e2e_recipe.py, evals/ | G01,H04 | pipeline complet | ⬜ attente coordination |
| J02 | Accessibilité (a11y) UI | (réservé Codex) desktop_static/** | — | WCAG AA | ⬜ attente coordination |
| J03 | Performance perçue (skeleton) | (réservé Codex) desktop_static/** | — | <3s perçu | ⬜ attente coordination |
| J04 | Mode hors-ligne (PWA) | (réservé Codex) desktop_static/** | — | cache offline | ⬜ attente coordination |
| J05 | Responsive mobile | (réservé Codex) desktop_static/** | — | mobile OK | ⬜ attente coordination |
| J06 | Tests de régression (suite ciblée) | tests/test_regression_*.py | — | vert | ⬜ |
| J07 | Smoke test HTTP/navigateur | tests/test_smoke_http.py | — | /app 200 | ⬜ |
| J08 | Profiling performance backend | career/perf_profile.py, tests/test_perf_profile.py | — | rapport | ⬜ |
| J09 | Monitoring erreurs | career/error_monitor.py, tests/test_error_monitor.py | — | logs structurés | ⬜ |
| J10 | Rapport de recette final | docs/agent-reports/NAGE_NEXT_100_RECIPE.md | J01-J09 | synthèse | ⬜ attente coordination |

---

## Lancement immédiat

Quatre premières missions indépendantes à plus forte valeur (aucune dépendance bloquante) :

1. **A01** — Connecteur UK (sources internationales, finance)
2. **B05** — Niveau diplôme requis (BBA/Bac+4/M2/MBA) — filtre clé utilisateur
3. **C07** — Filtre par type de stage finance (M&A, CIB, corp fin)
4. **D04** — Registre de preuves (fondation pour CV factuel)

Branches : `agent/n100-A01-uk-sources`, `agent/n100-B05-degree-level`, `agent/n100-C07-finance-family`, `agent/n100-D04-evidence-registry`.
Worktrees isolés. Pool modèles : coût nul vérifié (beam-free, mimo-v2.6-flash-free, deepseek-v4.1-flash-free).

Coordination : SHA, tests et conflits transmis à Codex via `messages/nage_next_100_note.md`.