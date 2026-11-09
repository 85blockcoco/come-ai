# Côme IA — Inventaire Fonctionnel

## Objectif
Cataloguer toutes les fonctionnalités existantes du système Côme IA en les associant à la vision maître, aux modules code existants, à l'état démontré par les tests, et aux spécifications Spec Kit le cas échéant.

Chaque entrée contient :
- Identifiant unique
- Description sommaire
- Module/code concerné
- État code/tests
- Spécification Spec Kit correspondante
- Écart par rapport à la vision
- Priorité
- Dépendances
- Prochaine action recommandée

---

# PARTIE A — FONCTIONNALITÉS EXISTANTES (STATUT ✅ OU ⚠️)

## 1. Qualification des offres (qualify_offer)
- **Identifiant**: FUNC-001
- **Description**: Extraction des qualificatifs d'une offre (dates, type de contrat, durée, missions) depuis les descriptions d'offres d'emploi
- **Module/code concerné**: `career/service.py` — `_extract_qualification()`, `_apply_qualification()`, migration v8 (5 colonnes de citations)
- **État code/tests**: ✅ 11/11 tests de qualification persistence PASS (tests/test_qualification_persistence.py) ; exhaustivité test PASS (baseline 11.7% → 25.0% global fiche_pct)
- **Spécification Spec Kit**: `specs/001-persist-qualification-facts/`
- **Écart par rapport à la vision**: ✅ Compatible avec objectif Carrière & Candidatures (objectif 13); couvre start_date, employment_type, calendar_status
- **Priorité**: Critique (base de toutes les autres fonctionnalités)
- **Dépendances**: Aucune (infrastructure première)
- **Prochaine action recommandée**: Aucune — fonctionnalité complete et vérifiée

## 2. Persistence des qualificatifs
- **Identifiant**: FUNC-002
- **Description**: Enrichissement de la table `jobs` avec les colonnes de qualification (start_date, end_date, duration_months, contract_type) en utilisant COALESCE pour préserver les données existantes
- **Module/code concerné**: `career/service.py` — migration v8, `_apply_qualification()`, COALESCE preservation dans `import_job()`
- **État code/tests**: ✅ 1267/1271 tests PASS (4 échecs préexistants non liés) ; ruff linting passé ; latence import < 10% increase
- **Spécification Spec Kit**: `specs/001-persist-qualification-facts/`
- **Écart par rapport à la vision**: ✅ Compatible; assure la provenance (Principle IV: Mandatory Evidence & Provenance)
- **Priorité**: Critique
- **Dépendances**: Aucune
- **Prochaine action recommandée**: Aucune — implantation vérifiée

## 3. Résumé offre (summarize_offer)
- **Identifiant**: FUNC-003
- **Description**: Extension de `summarize_offer()` pour exposer les qualificatifs d'offre (start_month, duration_min_months, contract_type) pour mesure d'exhaustivité
- **Module/code concerné**: `career/application_prep.py`
- **État code/tests**: ✅ Tests passant ; intégration dans cycle d'exhaustivité
- **Spécification Spec Kit**: `specs/001-persist-qualification-facts/`
- **Écart par rapport à la vision**: ✅ Compatible; supporte objectif Études & apprentissage (objectif 14) et Carrière (objectif 15)
- **Priorité**: Élevée
- **Dépendances**: FUNC-002 (colonnes de qualification existantes)
- **Prochaine action recommandée**: Aucune

## 4. Constitution Spec Kit (v1.0.0)
- **Identifiant**: FUNC-004
- **Description**: 7 principes directeurs pour tout développement Côme IA (Career-First, Zero API Spend, Privacy by Design, Mandatory Evidence, Test-First, Git Protected, Simplicity)
- **Module/code concerné**: `.specify/memory/constitution.md`
- **État code/tests**: ✅ Document existant ; non testé au sens pytest mais Prinzipien verifié par revue
- **Spécification Spec Kit**: N/A (constitution de framework)
- **Écart par rapport à la vision**: ✅ Aligne tous les développements sur les principes directeurs
- **Priorité**: Critique (framework)
- **Dépendances**: Aucune
- **Prochaine action recommandée**: Aucune — consolidée

## 5. Inventaire des_specs existantes
- **Identifiant**: FUNC-005
- **Description**: Liste cataloguée des spécifications Spec Kit par cycle (001 à 008 planifiées)
- **Module/code concerné**: `specs/` directory — `specs/001-persist-qualification-facts/`, cycles 002-008 en planification
- **État code/tests**: ✅ 001 complet et vérifié; 002-008 en planification (voir roadmap-product.md)
- **Spécification Spec Kit**: Structure par cycle (spec.md, plan.md, research.md, data-model.md, contracts/interfaces.md, quickstart.md, checklists/requirements.md, tasks.md)
- **Écart par rapport à la vision**: ⚠️ Cycle 001 seulementimplémenté; 002-008 en planification seulement
- **Priorité**: Moyenne (catalogage en cours)
- **Dépendances**: FUNC-004 (constitution)
- **Prochaine action recommandée**: Continuer les cycles 002-008 selon roadmap

---

# PARTIE B — FONCTIONNALITÉS EN PLANIFICATION / MISSING

## 6. Extractor de missions
- **Identifiant**: FUNC-006
- **Description**: Extraction automatique des informations de mission depuis les offres d'emploi (titres, objectifs, durées, compétences associées)
- **Module/code concerné**: Non encore implanté — à ajouter dans le pipeline d'extraction
- **État code/tests**: ❌ Non implémenté; absent de `career/service.py`
- **Spécification Spec Kit**: En planification (voir roadmap-product.md — Cycle 007)
- **Écart par rapport à la vision**: ❌ Manquant; objectif Carrière & candidatures (15) et Conseiller personnel (18) nécessitent données de mission
- **Priorité**: Élevée (dépendance pour d'autres fonctionnalités)
- **Dépendances**: FUNC-001 (infrastructure qualification), FUNC-005 (catalogage specs)
- **Prochaine action recommandée**: Démarrer spécification Cycle 007

## 7. Extracteur d'éducation
- **Identifiant**: FUNC-007
- **Description**: Extraction des informations éducatives (diplômes, établissements, dates) depuis les profils et offres
- **Module/code concerné**: Non encore implanté
- **État code/tests**: ❌ Non implémenté
- **Spécification Spec Kit**: En planification (voir roadmap-product.md — Cycle 008)
- **Écart par rapport à la vision**: ❌ Manquant; objectif Études & apprentissage (14) nécessite suivi éducatif
- **Priorité**: Moyenne
- **Dépendances**: FUNC-001 (infrastructure commune)
- **Prochaine action recommandée**: Démarrer spécification Cycle 008

## 8. Normalisation de localisation (city/country split)
- **Identifiant**: FUNC-008
- **Description**: Sépérage champs localisation en ville/pays, gestion multi-sites
- **Module/code concerné**: À implémenter dans l'extraction des qualificatifs
- **État code/tests**: ⚠️ Partiel; champs localisation existants mais format mixte
- **Spécification Spec Kit**: En planification (voir roadmap-product.md — Cycle 004)
- **Écart par rapport à la vision**: ⚠️ Partiel; objectif Mobilité (17) et Conseiller personnel (18) nécessitent localisation normalisée
- **Priorité**: Moyenne
- **Dépendances**: FUNC-001, FUNC-005
- **Prochaine action recommandée**: Démarrer Cycle 004

## 9. Regex Durée étendue (_DURATION)
- **Identifiant**: FUNC-009
- **Description**: Extension du regex `_DURATION` pour capturer semaines et semestres en plus des mois actuels
- **Module/code concerné**: `career/service.py` — expressions rationnelles d'extraction
- **État code/tests**: ⚠️ Regex actuelle; 6 offres supplémentaires possibles (voir SPECKIT_INTEGRATION_SUMMARY.md)
- **Spécification Spec Kit**: En planification (voir roadmap-product.md — Cycle 003)
- **Écart par rapport à la vision**: ⚠️ Limité; objectif Durée (objectif 13) incomplet
- **Priorité**: Faible (amélioration incrémentale)
- **Dépendances**: FUNC-001
- **Prochaine action recommandée**: Démarrer Cycle 003

## 10. R2 champs: salaire, conditions, éducation, missions
- **Identifiant**: FUNC-010
- **Description**: Ajout des champs R2 (salary, education, conditions, missions) aux offres qualifiées pour porter l'exhaustivité globale à ≥ 70%
- **Module/code concerné**: `career/service.py` — nouvelles colonnes de migration; `application_prep.py` affichage
- **État code/tests**: ❌ Non implémenté; dépendant des cycles 002-004
- **Spécification Spec Kit**: En planification (voir roadmap-product.md — Cycle 005)
- **Écart par rapport à la vision**: ❌ Manquant; objectif exhaustive global ≥ 70% non atteint (actuel 25%)
- **Priorité**: Très élevée (cible d'exhaustivité)
- **Dépendances**: FUNC-002, FUNC-003, FUNC-004 (cycles préliminaires)
- **Prochaine action recommandée**: Démarrer Cycle 005 après cycles 002-004 complets

---

# PARTIE C — ÉCarts PAR VISION MAÎTRE

| Identifiant | Écart | Impact Vision | Priorité Correction |
|---|---|---|---|
| FUNC-006 | Extractor missions manquant | Carrière 15, Conseiller 18 | Élevée |
| FUNC-007 | Extracteur éducation manquant | Études 14 | Moyenne |
| FUNC-008 | Normalisation localisation partielle | Mobilité 17, Conseiller 18 | Moyenne |
| FUNC-009 | Regex durée incomplète | Durée 13 | Faible |
| FUNC-010 | R2 champs absents | Exhaustivité globale ≥70% | Très élevée |