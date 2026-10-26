# MISSION CVBOOST-75 — SPEC-040 — Annuaire networking local (contacts, anciens élèves, équipes cibles)

> **Priorité : P1** — Répond à « identifier les équipes, recruteurs et anciens élèves
> pertinents à contacter ». Repose SUREMENT sur les missions : sk10 (profil candidat),
> 53 (web researcher à preuves), sk11 (dossiers).

## OBJECTIF
Construire une base locale de contacts professionnels cibles (recruteurs, teams d'un
département banquier, anciens de ton école) alimentée par (1) l'export LinkedIn de
l'utilisateur (fichier local, importé par lui-même, jamais scraping), et (2) des faits
publics collectés via le Web Researcher avec preuves traçables.

## PÉRIMÈTRE BUILD
Crée `career/networking.py`, `career/networking_schema.py` et leurs tests.

FONCTIONS
1. Import d'un export LinkedIn local ( décompressé `Profile.csv`, `Connections.csv`) : les
   faits du fichier sont taggés `source=linkedin_export` SANS être envoyés nulle part.
2. Schéma contact local : { nom, poste, entreprise, école, relation (1er/2nd/alumni),
   notes, dernier contact, prochaine action } ; tous les champs vivent en SQLite local.
3. Génère des  Cibles recommandées par la voracité : match entre (poste cible de l'utilisateur)
   et (poste/département du contact), alumni-matching, Franchen finance-specific (IBC,
   M&A, TMT, coverage desks).  Chaque recommendation cite SA PROVENANCE (qui le dit, où).
4. Brouillons de messages de networking par modèle (1er contact alumni, recruteur
   d'école, coverage desk) — rédigés depuis les faits approuvés du profil, SEGMENTés ;
   aucun envoi (le brouillon s'exporte dans un fichier, l'utilisateur envoie lui-même).

## SÉCURITÉ (blocants)
- Import et local uniquement. Jamais d'annuaire public ou de scraping massif de profils.
- Web Researcher : 1 page par entreprise au max par recherche, preuve obligatoire.
- Pas d'exportation des données car le fichier zip reste local.

## TESTS
≥ 35 cas : parsing CSV LinkedIn, alumni-policy, détails, recommandations dédupliquées,
brouillons contingents, purge.

## RAPPORT
`docs/agent-reports/CVBOOST-75-NETWORKING.md` — branche `agent/spec-040-networking`.
