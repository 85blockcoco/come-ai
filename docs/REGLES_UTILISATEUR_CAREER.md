# RÈGLES UTILISATEUR — CAREER (constantes produit, non négociables)

Date : 2026-10-20 · Source : l'utilisateur lui-même, en séance.
Portée : tout code, classement, UI ou conseil de la partie Career qui touche à
la recherche et au classement des offres. Toute mission (actuelle ou future)
doit respecter ces règles ; la relecture et l'intégration les vérifient.

## R1 — JAMAIS un stage en France : destinations 100 % à l'étranger

> « je ne cherche absolument pas un stage en France, uniquement à l'étranger. »

- Une offre dont le **lieu de travail est en France** est **exclue ou fortement
  déclassée** du classement (shortlist, radar, suggestions), quel que soit
  son score thématique.
- Les **graines par défaut** des lieux préférés ne doivent pas proposer la
  France comme destination principale (le défaut actuel `PRIMARY_LOCATIONS`
  inclut « Paris / primary » : à remplacer pour le profil de l'utilisateur par
  des villes étrangères).
- Le classement ne doit **jamais** être « preference-free » : il doit pondérer
  la localisation déclarée (exclure la France, promouvoir les cibles).
- Cas frontière : une entreprise française avec lieu de travail hors France
  compte comme hors France (le critère est le **lieu de travail**, pas la
  nationalité du groupe).
- Les préférences de lieux (table `preferences`, `kind = 'location'`) restent
  modifiables par l'utilisateur dans l'app (formulaire Profil → Préférences).

## R2 — Le résumé d'une offre doit contenir TOUTE l'information visible

> « il y a des données que je lis sur la page officielle des offres mais qui
> ne sont pas mentionnées dans le résumé, le classement est donc faussé. »

- Toute information **visible sur la page officielle** doit apparaître dans le
  résumé : dates (ouverture, clôture, début), type de contrat, lieu de travail
  exact, niveau d'études requis, rémunération **si affichée**, missions,
  responsabilités, conditions (mobilité, autorisation de travail, langue).
- Information absente ou illisible → champ marqué **« non affiché »**, jamais
  inventé, jamais déduit par géographie approximative.
- Le **classement pénalise** les résumés incomplets : un score gonflé par des
  informations qu'on n'a pas réellement lues est un faux positif. Une exigence
  non prouvable reste non prouvable (cohérence avec le lot CV Boost).

## R3 — Cibles géographiques (confirmé par l'utilisateur le 2026-10-20)

> « partout ailleurs que la France. »

- Tout lieu de travail **hors de France** est éligible ; pas de liste
  restrictive de pays.
- Mesure immédiate appliquée à ses données réelles le 2026-10-20 : la
  destination « Paris » a été **désactivée** dans ses préférences (serveur
  local, `priority: 0`) — les cinq autres destinations européennes et
  « Autres villes européennes » restent actives.
- Reste à faire côté code (après intégration des lots agents) : le classement
  doit devenir **sensible aux préférences** et **exclure/déclasser la France**
  (voir R1) — tant que le classement reste « preference-free », cette
  correction des données ne suffit pas à elle seule.

## Traçabilité

- Chaque mission qui modifie le classement ou l'extraction d'offres doit
  citer ces règles dans son rapport (`docs/agent-reports/`).
- Mission 10 (intégration) vérifie ces règles après chaque lot fusionné.
