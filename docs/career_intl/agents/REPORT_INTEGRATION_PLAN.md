# Rapport — Plan d'intégration minimal Career

Date : 18 octobre 2026  
Branche observée : `audit/total-v3-2026-10-14` @ `5ef814e`  
Statut : analyse uniquement — aucun code modifié, aucune branche fusionnée.

## 0. Convention de preuve

- `PREUVE GIT` : fait vérifiable par `git log`, `git diff`, `git merge-tree`, rapport versionné ou test cité.
- `JUGÉE` : déduction d'architecture, non directement prouvée par Git. Ces points sont explicitement marqués.

## 1. Résumé exécutif

L'intégration ne doit pas se faire par fusion globale. La branche `integration/career-home-daily-20261018` contient déjà un amalgame de briques (UI, consentement, profil, study coach, dossier, sources), mais elle est massive (272 fichiers pour la candidate équivalente, voir `LOT_G.md`). Le plan minimal retenu suit l'ordre demandé :

1. confidentialité ;
2. qualification ;
3. scoring ;
4. Aujourd'hui ;
5. profil ;
6. dossier ;
7. suivi.

Chaque lot doit être intégré seul, avec sa propre branche candidate, ses tests ciblés, puis la suite complète avant le lot suivant. `JUGÉE` : cette séquence minimise les conflits sur `come_ai_web.py`, `hybrid_chat.py` et `workspace_core.py`, qui sont les fichiers les plus disputés.

## 2. Carte des branches par lot

| Lot | Branches principales | Commits uniques vs `5ef814e` | Fichiers touchés | Source |
|---|---|---:|---:|---|
| 1. Confidentialité | `codex/t1-privacy-guards` | 33 fichiers | 33 | `LOT_G.md`, `REPORT_T1.md` |
| 1. Confidentialité | `feature/v3-consent-guard` | 3 | 94 | `LOT_D.md` D5-1/D5-2 |
| 1. Confidentialité | `integration/security-redaction-20261017` | 1 métier (`78ae9f8`) | 4 | `INTEGRATION_STATUS.md` |
| 2. Qualification | `codex/w2-offer-qualification` | 10 | 10 | `REPORT_W2.md` |
| 2. Qualification | `codex/configurable-search-criteria` | non compté ici | — | `REPORT_CONFIGURABLE_CRITERIA.md` |
| 2. Qualification | `codex/w3-source-connectors` | 46 | 46 | `REPORT_W3.md` |
| 2. Qualification | `codex/live-source-coverage` / `codex/source-expansion-wave2` | 8-12 | 45-113 | `REPORT_LIVE_SOURCE_EXPANSION.md`, `REPORT_SOURCE_EXPANSION_WAVE2.md` |
| 3. Scoring | `codex/ranking-evidence-truth` | — | — | `REPORT_RANKING_EVIDENCE_TRUTH.md` |
| 4. Aujourd'hui | `feature/come-today-connecteurs` | 17 | 53 | `LOT_G.md` |
| 4. Aujourd'hui | `integration/career-home-daily-20261018` | 21+ | 120+ | `INTEGRATION_STATUS.md` |
| 5. Profil | `integration/profile-study` | 2 | 74 | `LOT_G.md` |
| 5. Profil | `feature/profile-integration-v1` | 0 vs `5ef814e` | 0 | `LOT_G.md` (déjà contenu) |
| 5. Profil | `integration/profile-core` | 0 vs `5ef814e` | 0 | `LOT_G.md` (déjà contenu) |
| 6. Dossier | `feature/career-international-dossiers` | 12 | 112 | `LOT_G.md` |
| 6. Dossier | `feature/career-international-dossiers-oc` | 14 | 110 | `LOT_G.md` |
| 6. Dossier | `codex/application-prep-short-skills` | inclut candidate complète | 100+ | diff observé |
| 7. Suivi | aucune branche dédiée isolée | `JUGÉE` | — | pas de branche `followup` dans `git branch` |

## 3. Dépendances

```text
confidentialité
  -> qualification (les connecteurs et l'exploration publient des données; le consentement cloud et la rédaction doivent exister avant tout envoi de contexte)
  -> scoring (le libellé de pertinence dépend de qualification_status)
  -> Aujourd'hui (affiche offres + score + état profil)
  -> profil (contexte profil, import, chat cloud)
  -> dossier (brouillon IA avec consentement_external)
  -> suivi (reprise de dossiers, historique, statuts)
```

Preuves :
- `REPORT_RANKING_EVIDENCE_TRUTH.md` : le libellé de présentation dépend de `qualification_status` (`to_verify`, `non_conforming`).
- `REPORT_T1.md` : le consentement cloud est requis avant tout envoi de fichier/résultat local.
- `INTEGRATION_STATUS.md` : le parcours dossier réutilise le profil, les critères et l'analyse.

## 4. Chevauchements et conflits prévisibles

Fichiers contestés (`PREUVE GIT` : `LOT_G.md` G.2 et préflight T1) :

| Fichier | Lots en conflit | Nature du chevauchement |
|---|---|---|
| `come_ai_web.py` | confidentialité, profil, Aujourd'hui, dossier | routes, schémas, Origin, consentement, profil, career home |
| `hybrid_chat.py` | confidentialité, profil | contexte local, cloud consent, PCE |
| `workspace_core.py` | confidentialité, outils | boucle d'outils, masquage, allow_writes |
| `task_queue.py` | confidentialité | `redact_text`, motifs secrets |
| `career/service.py` | qualification, scoring, Aujourd'hui, dossier | découverte, critères, résumé, dossier |
| `career/router.py` | qualification, scoring, dossier | endpoints stage-search, summary, application |
| `career_static/index.html`, `career_static/career.js` | UI map, détail, summary, dossier, Aujourd'hui | carte, tri, fiche, dossier |
| `devkit/exporting.py` | confidentialité, profil | rédaction différente (`LOT_F.md` F.3) |

`JUGÉE` : le conflit le plus dangereux est `come_ai_web.py`, car T1, profile-core, memory et la candidate touchent le même schéma sans coordination. Il faut intégrer la confidentialité d'abord, puis réappliquer les autres lots par petits hunks.

## 5. Ordre d'intégration minimal

### Lot 1 — Confidentialité

- Branches : `codex/t1-privacy-guards`, `feature/v3-consent-guard`, `integration/security-redaction-20261017`.
- Objectif : rédaction récursive des résultats d'outils, consentement cloud par requête, Origin sur les routes, garde serveur.
- Dépendances : aucune ; doit passer en premier.
- Risques : `consent_guard` est importé depuis `f1af740` dans T1 (`REPORT_T1.md`) ; ne pas dupliquer le garde. `devkit/exporting.redact_text` masque un ensemble différent de secrets (`LOT_F.md` F.3), donc une unification est nécessaire.
- Tests après lot :
  - `tests/test_hybrid_chat.py`, `tests/test_hybrid_web.py`, `tests/test_come_ai_v3.py`
  - `tests/test_consent_guard_*.py` (185 passés selon `REPORT_MEGA.md`)
  - `tests/test_security_payload_redaction_v3.py`, `tests/test_personal_profile_confidentiality.py`, `tests/test_v3_cloud_lock.py`
  - `evals/tests/test_come_ai_target.py`
- Validation humaine : confirmer que l'UI expose une confirmation explicite avant envoi cloud ; T1 a volontairement laissé l'API seule (`REPORT_T1.md`).

### Lot 2 — Qualification

- Branches : `codex/w2-offer-qualification`, `codex/configurable-search-criteria`, `codex/w3-source-connectors`, puis vagues de sources vérifiées.
- Objectif : qualification factuelle des offres, critères configurables, connecteurs ATS bornés, registre de sources vérifiées.
- Dépendances : après confidentialité, car la découverte/exploration ne doit pas contourner les gardes cloud.
- Risques : migration de critères et de statuts (`conforming`, `non_conforming`, `to_verify`) ; sources non vérifiées ne doivent pas être ajoutées automatiquement (`REPORT_LIVE_SOURCE_EXPANSION.md`).
- Tests après lot :
  - `tests/test_career_offer_qualification.py`, `tests/test_career_configurable_contract_criteria.py`
  - `tests/test_career_exploration.py`, `tests/test_career_discovery_selection.py`
  - `tests/test_career_public_ats_connectors.py`, `tests/test_career_verified_source_expansion.py`
  - `tests/test_career_international_criteria_binding.py`, `tests/test_internship_contract_conflicts.py`
  - `scripts/live_source_check`
- Validation humaine : approuver chaque nouvel employeur/board ajouté au registre ; ne pas traiter une réponse HTTP comme preuve suffisante (`REPORT_LIVE_SOURCE_EXPANSION.md`).

### Lot 3 — Scoring

- Branches : `codex/ranking-evidence-truth`.
- Objectif : séparer score de pertinence et libellé de présentation selon `qualification_status` ; normalisation HTML centralisée pour les connecteurs.
- Dépendances : après qualification, car le libellé dépend de `qualification_status`.
- Risques : risque de régression du tri si le score numérique est mal interprété ; l'interface doit dire « Pertinence selon tes critères » et non « Correspondance stage » (`REPORT_RANKING_EVIDENCE_TRUTH.md`).
- Tests après lot :
  - `tests/test_career_stage_hunter.py`, `tests/test_career_home_offers.py`
  - `tests/test_career_exploration.py`, `tests/test_career_explorer_web.py`
  - `tests/test_career_international_criteria_binding.py`, `tests/test_career_duration_windows_v3.py`
- Validation humaine : vérifier manuellement que les offres `to_verify` n'affichent pas de ton vert et que le score reste explicable.

### Lot 4 — Aujourd'hui

- Branches : `feature/come-today-connecteurs`, `integration/career-home-daily-20261018` (à découper, pas à fusionner tel quel).
- Objectif : accueil Career, dernier état local, au plus trois offres, bouton d'exploration, comparaison de scans identiques.
- Dépendances : après scoring, car l'accueil affiche le score et les statuts.
- Risques : la branche candidate est massive et contient des éléments hors périmètre (study coach, dossier, profil). `JUGÉE` : il faut extraire seulement les fichiers Aujourd'hui, pas fusionner la branche entière.
- Tests après lot :
  - `tests/test_career_home_offers.py`, `tests/test_career_explorer_web.py`
  - `tests/test_career_exploration.py`, `tests/test_career_stage_hunter.py`
  - `tests/test_career_stage_hunter_ui_guards.py`, `tests/test_rc_career_dialogs.py`
  - `node --check v5_static/v5.js` et `git diff --check`
- Validation humaine : valider le comportement « ne lance aucune recherche au chargement » et la comparaison uniquement si critères identiques.

### Lot 5 — Profil

- Branches : `integration/profile-study`, plus les modules `personal_profile/` et `profile_chat.py` présents dans la candidate.
- Note : `feature/profile-integration-v1` et `integration/profile-core` sont déjà contenus dans `5ef814e` (`LOT_G.md` : 0 commit, 0 fichier). Ne pas les réintégrer comme s'ils apportaient du nouveau code.
- Objectif : profil personnel isolé, import avec approbation par champ, contexte profil, consentement cloud lié au profil.
- Dépendances : après confidentialité et Aujourd'hui ; `profile-core` touche `come_ai_web.py` et `hybrid_chat.py`, donc il doit être réappliqué après le Lot 1.
- Risques : conflits avec T1 sur `come_ai_web.py`/`hybrid_chat.py` ; stockage SQLite profil ; consentement profil (`allow_profile_cloud`) ne couvre pas les fichiers/résultats d'outils du chat général (`T1_PREFLIGHT.md`).
- Tests après lot :
  - `tests/test_personal_profile_*.py`, `tests/test_profile_web.py`, `tests/test_profile_chat_integration.py`
  - `tests/test_career_profile_context_bridge.py`, `tests/test_career_profile_readiness.py`
  - `tests/test_devkit_profile_study_exporting.py`, `tests/test_v5_web.py`
- Validation humaine : confirmer l'approbation champ par champ et l'absence d'import automatique de CV ; valider la provenance du profil.

### Lot 6 — Dossier

- Branches : `feature/career-international-dossiers`, `feature/career-international-dossiers-oc`, `codex/application-prep-short-skills`.
- Objectif : dossier de candidature contrôlé, claims bornés, traduction contrôlée, export, sans envoi automatique.
- Dépendances : après profil et scoring ; utilise le profil, les critères et les offres.
- Risques : deux branches dossiers parallèles (`feature/career-international-dossiers` et `-oc`) avec rapports croisés ; risque de duplication. `application_prep` garde le statut « propose » et le vérificateur anti-invention (`f072b24`, `06bb5d0`).
- Tests après lot :
  - `tests/test_career_application_prep_regressions.py`, `tests/test_career_application_batch.py`
  - `tests/test_career_application_quality_fidelity.py`, `tests/test_career_export_international_fidelity.py`
  - `tests/test_application_claim_boundary.py`, `tests/test_application_date_provenance.py`, `tests/test_application_identifier_boundary.py`
  - `tests/test_career_translation_contract_v2.py`, `tests/test_translation_fidelity_regressions.py`
  - `tests/test_offer_fact_*.py`
- Validation humaine : relire les dossiers générés, vérifier qu'aucune candidature n'est envoyée automatiquement, valider les traductions et les claims.

### Lot 7 — Suivi

- Branches : aucune branche isolée dédiée dans l'état observé ; la fonctionnalité est dans la candidate (`application_batch.py`, recovery, statuts).
- Objectif : suivi persistant, reprise de dossiers, filtres de statuts, relances suggérées.
- Dépendances : après dossier.
- Risques : schéma SQLite version 8 avec migration 7→8 et pas de retour automatique (`INTEGRATION_STATUS.md`) ; risque de perte de données si rollback.
- Tests après lot :
  - `tests/test_career_application_batch.py`, `tests/test_career_batch_auto_language_v3.py`
  - `tests/test_career_batch_receipts.py`, `tests/test_career_batch_recovery_web.py`
  - `tests/test_career_dashboard_pipeline_v3.py`
  - `tests/test_conversation_history.py`, `tests/test_chat_history_atomicity.py`
- Validation humaine : valider la reprise après redémarrage serveur, les compteurs distincts des brouillons, et l'absence de synchronisation multi-appareils non annoncée.

## 6. Risques de migration

1. `personal_memory` utilise `SCHEMA_VERSION = 2` avec FTS5 (`LOT_E.md` E.2). Toute migration doit conserver la recherche et les index.
2. Le dossier utilise le schéma 8 avec migration 7→8 et pas de rollback automatique (`INTEGRATION_STATUS.md`). `JUGÉE` : faire une sauvegarde privée avant migration, comme déjà fait dans la candidate.
3. `consent_guard` stocke uniquement des métadonnées/empreintes, pas le contenu (`REPORT_T1.md`). Vérifier qu'aucune branche ne change ce contrat.
4. Les trois `redact_text` ne masquent pas le même ensemble (`LOT_F.md` F.3). `JUGÉE` : unifier autour de `task_queue.redact_text` comme T1 l'a décidé, puis étendre les tests.
5. `study_coach/` est absent de `5ef814e` mais présent dans la candidate (`LOT_E.md` E.5). `JUGÉE` : ne pas l'intégrer dans ces sept lots sauf décision explicite, car il élargit fortement la surface.
6. Les imports lourds (`pandas`, `openpyxl`) expliquent ~88 Mo de RSS et ~1,19 s de démarrage à froid (`LOT_F.md` F.5). `JUGÉE` : valider le budget de démarrage avant intégration finale.
7. Deux branches candidates sont identiques (`integration/career-international-core` et `integration/come-ai-v3-release-candidate`, 68 commits, 272 fichiers) (`LOT_G.md` G.4). `JUGÉE` : choisir un référentiel unique avant d'intégrer.

## 7. Tests recommandés après chaque lot

| Lot | Tests ciblés minimum | Preuve de comptage |
|---|---|---|
| 1 | hybrid chat/web, come_ai_v3, consent_guard, redaction, cloud lock | 7 passés pour T1 ciblé (`REPORT_T1.md`) ; 281 passés pour redaction (`INTEGRATION_STATUS.md`) |
| 2 | offer qualification, critères, exploration, connecteurs, sources | 785 passés après W2 (`REPORT_W2.md`) |
| 3 | stage hunter, home offers, exploration, critères, durées | 158 passés pour ranking (`REPORT_RANKING_EVIDENCE_TRUTH.md`) ; 216 pour M03 (`INTEGRATION_STATUS.md`) |
| 4 | home offers, explorer web, exploration, stage hunter, UI guards, dialogs | 79 passés pour home daily (`INTEGRATION_STATUS.md`) |
| 5 | personal profile, profile web/chat, context bridge, readiness | 74 fichiers / 21 tests pour profile-study (`LOT_G.md`) |
| 6 | application prep, batch, quality, export, claims, translation, offer facts | 342 passés batch recovery + 40 UI (`INTEGRATION_STATUS.md`) |
| 7 | application batch, receipts, recovery, dashboard, conversation history | mêmes suites que le lot 6, plus history |

Recommandation : exécuter la suite complète (`pytest -q`, baseline 749 passés à `5ef814e`, `LOT_B.md` B2-1) après chaque lot, mais ne pas additionner artificiellement les compteurs qui se recouvrent (`INTEGRATION_STATUS.md`).

## 8. Points nécessitant une validation humaine

1. Consentement cloud dans l'UI : T1 a volontairement laissé l'API seule ; l'envoi cloud avec fichier depuis l'interface actuelle est refusé (`REPORT_T1.md`).
2. Unification de la rédaction des secrets : les trois implémentations diffèrent (`LOT_F.md` F.3).
3. Ajout de sources : seules les sources vérifiées officiellement doivent entrer au registre (`REPORT_LIVE_SOURCE_EXPANSION.md`).
4. Dossier : aucun envoi automatique ; revue humaine des claims, traductions et langues (`f072b24`, `06bb5d0`).
5. Profil : approbation par champ, pas d'import automatique (`HANDOFF_AGENT_MEMOIRE.md` implicite dans la candidate).
6. Migration schéma 8 : validation d'une sauvegarde privée avant promotion (`INTEGRATION_STATUS.md`).
7. Nettoyage des 15 branches déjà contenues dans `5ef814e` : validation avant suppression (`LOT_G.md` G.4).
8. Décision sur l'inclusion de `study_coach/` : hors des sept lots sauf autorisation explicite (`LOT_E.md` E.5).

## 9. Branches à ne pas fusionner telles quelles

- `integration/career-home-daily-20261018` et `integration/career-international-core` / `integration/come-ai-v3-release-candidate` : trop larges, contiennent des éléments hors périmètre.
- `feature/career-international-dossiers` et `-oc` : choisir une seule version après revue croisée.
- `feature/profile-integration-v1` et `integration/profile-core` : déjà contenus dans `5ef814e`, donc aucune valeur nouvelle à fusionner.

## 10. Conclusion

Le plan minimal est séquentiel et conservateur : d'abord la confidentialité, puis la qualification, le scoring, Aujourd'hui, le profil, le dossier et enfin le suivi. Chaque lot doit être prouvé par ses tests ciblés et par la suite complète avant le suivant. Les fusions globales et les branches massives sont explicitement exclues. `JUGÉE` : cette discipline est nécessaire pour éviter de casser les gardes de confidentialité et les contrats de qualification déjà vérifiés.