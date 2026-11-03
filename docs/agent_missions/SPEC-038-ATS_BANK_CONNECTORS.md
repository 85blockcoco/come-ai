# MISSION CVBOOST-73 — SPEC-038 — Connecteurs pages-carrières banques & détection ATS

> **Priorité : P1** — Secteur cible de l'utilisateur : finance (CIB, M&A, Corporate Finance).
> Chanter depuis CONNECTEURS (sk08, SPEC-fait) et DÉDUP (07/sk06). Worktree dédié.

## OBJECTIF Connecter le radar quotidien aux sites carrières des banques et institutions
financières via leurs plateformes ATS, et détecter automatiquement le type de plateforme
d'une offre à partir de son URL, pour trouver des offres inaccessibles par les moteurs classiques.

## PÉRIMÈTRE BUILD
Crée `career/connectors/ats_generic.py`, `career/connectors/ats_registry.py` et leurs tests.
Réutilise les interfaces injectables des connecteurs existants (pattern `welcome_jungle.py`, `apec.py`).

FONCTIONS
1. `ats_registry.py` : identifie la plateforme ATS d'une URL (snapshot local, signatures
   URL-path connues : `myworkdayjobs.com`, `.successfactors`, `greenhouse.io`, `taleo.net`,
   `smartrecruiters.com`, `camejobs.com`, `aplica.ai`), liste fermée et versionnée.
2. `ats_generic.py` : fetch HTML public + parse maquette JSON structurée quand présente
   (Workday expose un JSON `carbon` ; Greenhouse/SmartRecruiters ont des JSON boards publics
   `boards-api.greenhouse.io` etc.), détermine titre, lieu, département, description, poste.
3. Un polling par lot uniquement, TTL 24h sz Respecte le délai entre les runs ;
   User-Agent honnête ; respect 429 (backoff, et stop), jamais de contournement d'auth obligatoire.

## SITES FINANCE SANS DÉPENDANCE CLOUD
La liste des banques est une DONNÉE locale versionnée (`career/connectors/banks_list.json`),
éditable par l'utilisateur : noms, école ATS, pages carrière. Le connecteur ne contient PAS
la liste des banques codée en dur ; pointe le fichier.

## CONTRAT COMMUN
1. Tests ≥ 45 cas (URL→ATS, mapping JSON de chaque plateforme avec fixtures HTML/JET locales,
   collision champs, 429, TTL).
2. Aucun auth, aucun envoi, aucune donnée personnelle. `unknown` partout sinon ne sait pas.
3. Pas de nouvelle dépendance sans justification dans le rapport.
4. Rapport `docs/agent-reports/CVBOOST-73-ATS_CONNECTORS.md`.
5. branche `agent/spec-038-ats-connectors`.
