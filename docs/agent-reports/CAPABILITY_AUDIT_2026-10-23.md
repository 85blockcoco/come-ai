# Côme IA Career — Audit de capacités autonomes (23 oct 2026, 13:30)

Audit produit sur données réelles de production (64 missions exécutées par flotte d'agents,
télémétrie de la journée du 23/10). Objectif : établir ce qui fonctionne en autonomie
aujourd'hui, avec quel taux de réussite mesurable, et où la vérification automatique
est encore fine. Résumé pour revue externe.

## 1. Ce que le système exécute en autonomie aujourd'hui

| Capacité | État | Preuve / mécanisme de vérification |
|---|---|---|
| Recherche d'offres multi-sources | **Autonome** | Connecteurs WtJ/Jobteaser (06, sk08), risque source (sk01), dates (sk02) |
| Déduplication & fraîcheur | **Autonome** | 07/sk06 (dédup), 36 (freshness), > 40 paires adversariales testées |
| Classement fit CV↔offre | **Autonome, déterministe** | 21 matching, sk03 requirements-fit, sk20 exhaustivité. Scores reproductibles (pas d'IA floue) |
| Analyse structure CV + ATS | **Autonome** | 01 structure, 04 formats PDF/DOCX, 54 mots-clés vs offre (158 tests) |
| Reformulation expérience/cursus | **Autonome sous contrat anti-invention** | 55, 56 : toute reformulation cite ses faits sources ; banc adversarial (08, ~100 couples) rejette les inventions |
| Lettres multi-IA avec arbitrage | **Autonome puis choix utilisateur** | 57 + 52 Arena : plusieurs IA produisent, un score comparé, l'humain tranche |
| Kit candidature 1-clic | **Livré (59)**, à vérifier en navigateur | agrège CV/lettres/checklist pour l'offre ciblée |
| Suivi candidatures & relances | **Autonome (drafts)** | 09 dashboard, 64 relances chronologiques (brouillons, jamais d'envoi), 71 bilan, 72 briefing J-1 |
| Traçabilité & preuve | **Autonome** | 46 registre de traçabilité, 38 evidence center (chaque fait cite sa preuve), 47 fraîcheur des preuves |
| Simulateur entretien | **Autonome (évaluation par grille)** | 62 STAR, 40 prépa, 66 FAQ minée ; notation par rubrique locale, pas d'IA externe |
| Infrastructure d'exécution agents | **Autonome après 5 incidents root-causés** | voir §3 |

## 2. Télémétrie réelle de la pipeline (23 oct)

- **64 missions exécutées au registre, 47 done « push-vérifiées »** (chaque livraison
  prouvée par existence de branche origin + contenu, vérifié par un gardien automatique
  indépendant du driver).
- **Faux « done » interceptés automatiquement** : 5 (~8% du volume de tentatives) —
  protocole `push_verified` : une mission ne compte livrée que si le push existe ET le
  contenu transforme réellement le code.
- Suites de tests : la base `main` a ~1454 tests verts de référence ; l'intégration
  candidate actuelle porte **~6080 tests, 5838 verts (96%)** — le 4% restant est en
  réparation indexée (hunks perdus par des merges git automatiques, chaque correctif
  réappliqué par diff-lot et retesté).
- Incidents d'exécution d'agents rencontrés puis corrivés par filets permanents :
  modèle indisponible (pool restreint), quota API (retry auto multi-modèles), sortie
  précoce sans travail (« polite exit » → échec), worker figé (watchdog CPU automatique),
  double soumission (inflight guard tri-source).
- Mesure de productivité utilisateur (16h → 3h45/semaine) : **non encore mesurée**, à
  instrumenter après merge (callbacks de temps de préparation de dossier).

## 3. Vérifications automatiques et leurs LACUNES (le cœur de ta question)

Ce que le système vérifie **déjà** lui-même :
1. Chaque affirmation produit-visible doit référencer une preuve (evidence center + traçabilité).
2. Toute reformulation est contrainte par les faits approuvés du profil (sk10), champ par champ.
3. Les invariants de données sont testés adversarialement (dédup, matching, dates).
4. La pipeline d'exécution se self-heal (voir incident list) et n'avance jamais sur un
   état non prouvé.

Lacunes honnêtes (aucun assombrissement) :
- **Exagération sémantique** : le système interdit d'inventer des faits, mais ne détecte
  pas finement qu'une reformulation *exagère* (un chiffre vrai présenté hors-contexte).
  Il faut un auditeur de sur-promesse (claim vs preuve, par phrase).
- **Éligibilité vérifiée** (visa, alternance, statut, école target) : les conditions sont
  extraites (sk17) mais pas **verdictées** (« cette offre t'est ouverte / non, et pourquoi »).
- **Layout ATS préservé** : les formats sont testés (04) mais pas de loop de régression
  visuelle entre versions de CV générées.
- **Apprentissage par résultats** : les variantes de CV/lettres ne sont pas encore
  câblées à leurs résultats réels (réponses/non-réponses) pour réordonner la stratégie.

## 4. Écart avec les 6 évolutions proposées

| Évolution | État actuel du système | Ce qui manque réellement |
|---|---|---|
| 1. Agent de stratégie | 60 (funnel) + 71 (bilan) + 72 (briefing) produisent le diagnostic | Déduire des PATTERNS d'offres gagnantes (secteur debout X vs Y) → mission dédiée |
| 2. Apprentissage par retours | Données disponibles (variantes avis coffres liées à candidatures) | Boucler variantes → résultat réels, avec garde-fous corrélation/causalité (petites données, jamais surestoter) |
| 3. Networking intelligent | Rien (mission 75 ajoutée ce jour : annuaire local depuis export LinkedIn) | Approches séquencées et suivis programmés |
| 4. Entretiens ultra-perso | 62 STAR + rubriques locales | Personnaliser par l'entretien réel (offre+entreprise+parcours) + évaluation argumentée, pas seulement grille |
| 5. Recherche approfondie entreprise | 53 web researcher (preuves) + 66 FAQ + **76 couche finance** | Un module « dossier entreprise » (activité, deals, résultats) comme brief d'entretien |
| 6. Superviseur de recrutement | 72 (briefing J-1) + 35 (command center) remplissent ce rôle de fait | Priorisation des urgences inter-candidatures (dépendances: money deadline, refus, relance) |

## 5. Composants d'aujourd'hui à NE PAS reconstruire

- Éxécution multi-agent (driver/orchestrator/gardien/watchdog) : ~5 classe d'incidents
  résolus avec filets permanents — la couche automatisation de PRODUCTION est un actif.
- Noyaux déterministes : dedup, géo, extraction, matching (tests adversariaux ≥ 145).
- Le couple preuve/traçabilité (38 + 46 + 47 + sk10) : différenciant structurel,
  impossible à reproposer en « ajout » plus tard.
- Consent guard : aucun envoi automatique, aucune donnée personnelle hors poste.

## 6. Priorités recommandées (issues de l'audit, pas d'inventaire de features)

1. **Auditeur de sur-promesse** (exagération, comparaison versions, justification des
   mots-clés) — c'est la plus grande marge de ton audit.
2. **Verdict d'éligibilité par offre** (visa/alternance/scolarité) sur base de règles.
3. **Boucle d'apprentissage variantes → résultats** (instrumentation de mesure incluse).
4. **Dossier entreprise** (bank research brief) pour l'entretien — ré utilise le web
   researcher à preuves + داده publiques (76 débloque le lexique).
5. **Instrumentation de productivité réelle** (temps par candidature avant/après)
   pour objectiver le gain et alimenter (2).
