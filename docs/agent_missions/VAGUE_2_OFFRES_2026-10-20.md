# VAGUE 2 — « BEAUCOUP PLUS D'OFFRES, UN MAX BIEN ANALYSÉES »

Date : 2026-10-20 · Base : `main` après intégration des lots `cvboost-*`.
Règles applicables : `docs/REGLES_UTILISATEUR_CAREER.md` (R1 : jamais de France ;
R2 : résumé complet ; R3 : partout hors France).

> Ces missions attendent l'intégration des lots en cours (atelier : un chantier
> à la fois). Elles sont rédigées prêtes à être exécutées par le pilote autonome
> (`docs/PILOTE_AUTONOME.md`). Chaque prompt est autonome.

---

## Mission O1 — Exhaustivité du résumé d'offre (règle R2)

**Fichiers** : `career/stage_search.py`, `career/discovery.py`, `career/models.py`
(selon l'architecture retenue), tests dédiés.

**Objectif** : le résumé d'une offre doit contenir **tout** ce qui est visible
sur la page officielle : dates (ouverture, clôture, début), type de contrat,
lieu de travail exact (ville + pays explicite), niveau d'études, rémunération
**si affichée**, missions/responsabilités, conditions (mobilité, autorisation
de travail, langue), process de candidature.

**Contraintes** :
- Information absente ou illisible → champ `« non affiché »`, jamais inventé,
  jamais déduit par géographie approximative.
- Chaque champ renseigné porte sa **provenance** (extrait source exact) —
  cohérence avec le lot CV Boost.
- Le **score d'exhaustivité** entre dans le classement : un résumé incomplet
  ne peut pas dominer un résumé complet à contenu égal (pénalité documentée,
  jamais cachée).

**Tests adversariaux** : offre avec rémunération affichée (doit apparaître) ;
offre sans rémunération (doit dire « non affiché », pas d'invention) ; offre
dont la date est dans un tableau (doit être lue) ; offre en langue étrangère ;
deux offres quasi identiques (exhaustivité ne doit pas fusionner les faits).

**Livrable** : rapport `docs/agent-reports/O1-EXHAUSTIVITE.md`.

---

## Mission O2 — Scoring sensible aux préférences + exclusion France (règle R1)

**Fichiers** : `career/discovery.py` (classement), `career/stage_search.py`,
`career/service.py`, `career_static/career.js` (affichage de la raison du
classement), tests dédiés.

**Objectif** : le classement **n'est plus « preference-free »** :
- Une offre dont le **lieu de travail est en France** est exclue ou fortement
  déclassée, quel que soit son score thématico-temporel.
- Les préférences déclarées (table `preferences`, `kind = 'location'`,
  `enabled`/`priority`) pondèrent le score ; les lieux désactivés ne remontent
  pas (« Paris » est désactivé dans les données réelles de l'utilisateur).
- Cas frontière : entreprise française avec lieu de travail hors France =
  hors France (critère : **lieu de travail**, pas nationalité du groupe).
- Chaque classement affiche **la raison** (« exclue : France », « boostée :
  destination déclarée », « pénalisée : résumé incomplet »).

**Contraintes** : `SCHEMA_VERSION` inchangé ; aucune géo-inférence ;
`window.prompt` interdit ; le tri reste déterministe et testable.

**Tests adversariaux** : offre Paris 100 % thématique (doit être exclue) ;
offre « French Tech » basée à Londres (doit passer) ; offre à Genève avec
Genève déclarée (boost) ; lieu absent (pas d'exclusion automatique, penalite
« localisation inconnue »).

**Livrable** : rapport `docs/agent-reports/O2-SCORING-PREFERENCES.md`.

---

## Mission O3 — Cadre de connecteurs bornés (au-delà de la mission 06)

**Fichiers** : nouveau paquet `career/connectors/`, `career/discovery.py`,
tests dédiés.

**Objectif** : pouvoir ajouter des sources d'offres **réellement
démontrables**, chacune avec : page carrière officielle, provenance, date de
vérification, connecteur borné (timeout, pages max, débit), **santé de source**
(dernière vérification, échecs), compteurs (brutes, valides, finance, stages,
conformes, à vérifier) et **aucune invention**.

**Contraintes** : opt-in explicite par source ; aucune source inventée ; aucun
doublon gonflé artificiellement (la déduplication de la mission 07 reste la
référence) ; le connecteur ne s'exécute que sur action explicite de
l'utilisateur (jamais en arrière-plan non demandé).

**Tests adversariaux** : source injoignable (compteur d'échec, pas de pseudo
offre) ; page HTML malformée (aucune offre fabriquée) ; deux sources qui
republient la même offre (déduplication).

**Livrable** : rapport `docs/agent-reports/O3-CONNECTEURS.md`.

---

## Mission O4 — Mesure automatique d'exhaustivité (garde-fou)

**Fichiers** : `tests/test_offer_summary_exhaustiveness.py`, outil de mesure
réutilisant le rapport AUTO-001.

**Objectif** : un test de non-régression qui mesure, sur un corpus synthétique
+ sur la dernière exploration locale, le taux de champs renseignés du résumé ;
tout lot qui le fait baisser échoue la CI.

**Livrable** : rapport `docs/agent-reports/O4-EXHAUSTIVITE-GARDE-FOU.md`.

---

## Mission O5 — Re-classement local des offres déjà stockées

**Fichiers** : `career/service.py` (commande locale), tests dédiés.

**Objectif** : une fois O1+O2 livrées, re-scorer **hors réseau** toutes les
offres déjà découvertes avec la nouvelle logique (exclusion France, boosting
destinations, pénalité d'exhaustivité), et afficher l'avant/après à
l'utilisateur. Aucune nouvelle recherche réseau : uniquement les données
déjà stockées localement.

**Livrable** : rapport `docs/agent-reports/O5-RECLASSEMENT.md`.
