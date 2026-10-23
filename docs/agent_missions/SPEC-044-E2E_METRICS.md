# MISSION CVBOOST-79 — SPEC-044 — Instrumentation + évaluation de bout en bout sur 10 offres réelles

> **Priorité : P0** — Issue de l'audit externe 23/10 §4 : « le gain 16h → 3h45 n'a jamais
> été mesuré ». Remplace l'assertion par des données. Chaîné sur : 59 (kit), 77 (audit),
> 76 (couche finance), fichier offre réelles fournies PAR L'UTILISATEUR.

## OBJECTIF
1) Instrumenter le temps réel passer par étape du parcours candidature.
2) Conduire l'évaluation de bout en bout sur **10 offres RÉELLES fournies par
   l'utilisateur** avec des candidats synthétiques (aucune donnée réelle personnelle
   dans le dépôt), mesurer systématiquement : qualité des dossiers, erreurs détectées
   (par 77), temps de correction, degré d'intervention humaine.

## PÉRIMÈTRE BUILD
Crée `career/metrics.py`, `career/eval_e2e.py` et leurs tests.

FONCTIONS
1. `metrics.py` : hook-chronométrage par étape (import CV, veut génération dossier
   tout comme x ligne de chest cover letter, audit 77, correction utilisateur) ;
   stockage local SQLite, export CSV/JSON (pas d'observateurs tier).
2. `eval_e2e.py` :
   - lecture de 10 offres réelles (fichiers locaux fournis par l'utilisateur dans
     `evals/real_offers/` — crédibilité : exclues de git sauf les résultats).
   - pour chaque offre : pipeline complet, puis rapport {temps par étape, score
     qualité 77, erreurs trouvées avant correction, corrections utilisateur
     mesurées (nb + durée), note finale sur papier}.
   - averaging et rapport agrégé avec CONFIANCE (n=10 : pas de conclusion forte, les
     tendances sont signalées comme indicatives).
3. Livrables : « dashboard » textuel + fiches MD par offre. Pas de cloud, tout local.

## CONTRAT
- Les 10 offres réelles ne quittent jamais le poste, même pas en logs mail.
- Test ≥ 30 : fixtures synthétiques reproduisant le protocole, hook timing robuste
  (pause/reprise), rapport aggregé, edge cases (offre sans réponse attendue, annotation).
- Rapport `docs/agent-reports/CVBOOST-79-E2E_METRICS.md`
- Branche `agent/spec-044-e2e-metrics`
