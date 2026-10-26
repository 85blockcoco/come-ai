# MISSION CVBOOST-80 — SPEC-045 — Boucle d'apprentissage variantes → résultats réels

> **Priorité : P1** — Issue de l'audit externe 23/10 §4-3. « Relier chaque candidature,
> variante de CV et lettre aux réponses obtenues », avec garde-fous corrélation/causalité
> et jamais de conclusion forte sur petit échantillon. Chaîné sur : 64 (relances),
> 74 (états candidatures), 60 (funnel), 79 (instrumentation).

## OBJECTIF
Cable chaque dossier envoyé (variante de CV, variante de lettre, stratégie de relance)
à son RÉSULTAT OBSERVÉ (aucune réponse / refus / entretien / assessment), pour que le
système apprenne ce qui marche pour CET utilisateur, sans surestimer.

## PÉRIMÈTRE BUILD
Crée `career/learning.py` et leurs tests.

FONCTIONS
1. Registre des expériences : {candidature_id, variants (CV/lettre mots-clés, ton),
   contexte (secteur, lieu, source), résultat, date}. Importé depuis (74) + saisie
   manuelle pour les réponses hors système.
2. Analyse descriptive uniquement : taux de réponse par famille de variante/contexte,
   et écarts avec intervalle simple ; ANT principes: jamais de « modèle de scoring
   appris » avec <30 observations ; les conclusions rendue indicationnel et
   différenciant corrélation (cause explicite appelée).
3. Recommandations de priorisation : « sur les 14 dernières, les dossier basés sur
   des CV adaptés ATS-only ont eu 2 réponses vs 7 avec narrative+ATS » — ce type de
   gain, signalé comme INDICATIF, feed dans le briefing J-1 (72) et le superviseur.
4. Un moteur appris ne remplace jamais le verdict d'éligibilité (78) ni audit 77.

## CONTRAT
- Aucun modèle ML servi avant n≥30. Rien d'auto-réglage qui contournerait les verrous
  qualité (77/78 restent autoritaires).
- Test ≥ 40 cas : import séquen option manuel, absent d'informations, n<30 verrou,
  agrégations, garde-fous, rapports.
- Rapport `docs/agent-reports/CVBOOST-80-LEARNING_LOOP.md`
- Branche `agent/spec-045-learning-loop`
