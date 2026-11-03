# MISSION CVBOOST-78 — SPEC-043 — Verificateur d'éligibilité par offre (visa, alternance, école, dates)

> **Priorité : P0** — Issue de l'audit externe 23/10 §4-2. Verdict explicite par offre :
> ÉLIGIBLE / NON ÉLIGIBLE / À VÉRIFIER, avec les règles citées.
> Chaîné sur : sk17 (conditions extraites), sk02 (dates), 13 (géo).

## OBJECTIF
Confronter chaque offre au PROFIL APPROUVÉ de l'utilisateur et à un jeu de règles
locales lisibles pour produire un VERDICT d'éligibilité, avec motiovation clause par clause
— pour ne plus jamais candidater à une offre fermée à ton statut.

## PÉRIMÈTRE BUILD
Crée `career/eligibility.py`, `career/rules_eligibility.json` et leurs tests.

FONCTIONS
1. Règles locales versionnées (éditables par l'utilisateur) : contrat (alternance/STAGE),
   durée, niveau d'étude exigé vs niveau réel, filière exigée, statut de travaille
   (étudiant, contrat, visa — les tickets WORK AUTH sont explicites dans `rules`,
   remplis par l'utilisateur, jamais devinés ou «wortel»), localisation / mode de
   travail, langues requises.
2. Moteur : chaque règle examinée le profil et l'offre (les geste sk17-extract
   conditions), statut verdict; score unsafe: à défaut de preuve le moteur répond
   « À VÉRIFIER » (et liste le point ) — **jamais de verdict positif implicite**.
3. Output : {verdict, clauses: [{rule, exigence_offre, fait_profil, statut_ok,
   preuve}], etat suivant}.
4. Branches dans le radar/dailies (35) : les offres NON ÉLIGIBLES sont marquées et
   sorties du classement par défaut (elt visibles pour apprendre pourquoi).

## CONTRAT
- Aucune IA de rélve décisionnel : règles + extractions, récitatif d'audit.
- Test ≥ 45 cas : alternance OK, classe status, visa inconnu, durée courte, école
  exigence missing, langues, missing cond data → À VÉRIFIER, pas de faux positifs
  ÉLIGIBLE sans preuve.
- Rapport `docs/agent-reports/CVBOOST-78-ELIGIBILITY.md`
- Branche `agent/spec-043-eligibility`
