# SPEC-053 — Performance perçue (`/app`)

> Mission CVBOOST-90 · branche `agent/spec-053-perf_ux` · 2026-10-28
> Base : `8c3b0de` (`agent/spec-052-a11y_mobile`, seule lignée contenant
> `desktop_static/`).

## Contexte

L'interface bureau NAGE (`desktop_static/`, route `/app`) charge six sources en
parallèle et rend chaque vue dès qu'une source répond. Deux défauts restaient
perceptibles :

1. **Attente sans repère** — un unique squelette générique de trois lignes
   remplaçait toute la vue, puis le contenu provoquait un saut de mise en page ;
   les dialogues détail (dossier, guide ATS, réponses types) restaient fermés
   pendant toute la requête, sans retour visuel.
2. **Actions perçues comme lentes** — « marqué envoyé » attendait la réponse
   API puis un rechargement complet du tracker avant d'afficher quoi que ce
   soit ; les fiches détail n'étaient demandées qu'au clic.

La mission ajoute trois mécanismes : **squelettes**, **mise à jour optimiste**
et **préchargement**.

## Périmètre livré

### `desktop_static/index.html`

- Barre de progression globale `#progressBar` (`role="progressbar"`,
  `aria-label`, `aria-valuetext`, `hidden` par défaut), 2 px, non bloquante.

### `desktop_static/app.css`

- Squelettes structurés : `.skeleton-view`, `.skeleton-card`, `.skeleton-row`,
  `.skeleton-line` (largeurs `w25`/`w40`/`w60`/`w80`), `.skeleton-kpi`,
  `.skeleton-dialog`, animation `shimmer` (déjà neutralisée par
  `prefers-reduced-motion`).
- Barre de progression `progress-slide` et état `.pipeline-item.optimistic`
  (fond discret, liseré, suffixe « sync »).
- Aucune animation ajoutée hors des règles `prefers-reduced-motion` existantes.

### `desktop_static/app.js`

- **Squelettes** : `skeletonCard()`, `skeletonRow()`, `skeletonList()`,
  `loading(view)` ; chaque vue (`today`, `applications`, `tracking`, `offers`,
  `missions`, `memory`) réserve la forme réelle (4 KPI + 3 lignes, 6 lignes
  pour les offres). L'annonce reste unique (`role="status"`,
  `aria-live="polite"`), les blocs visuels sont `aria-hidden`.
- **Dialogues squelette** : `skeletonDialog()` ouvre immédiatement la fenêtre
  (`aria-busy="true"`) avant l'appel API pour « préparer », « guide » et
  « réponses » ; le contenu réel remplace le squelette.
- **Mise à jour optimiste** : `markSent()` insère la candidature en tête du
  tracker avant l'appel `send-confirmation`, avec `optimistic: true` et annonce
  live ; en cas d'échec, l'instantané `structuredClone` est restauré et le
  message « Modification annulée » est affiché. La confirmation humaine
  (`askChannel`) reste obligatoire : aucun envoi automatique.
- **Préchargement** : cache TTL 30 s (`prefetchJson`, `apiCached`), déclenché
  au `pointerenter` **et** au `focus` des boutons « guide » / « réponses »,
  ainsi qu'au survol/focus des entrées de navigation (`prefetchView`, sources
  manquantes uniquement). Une fenêtre de grâce de 1,5 s (`recentlyFetched`)
  empêche le doublon focus-déclenché juste après le clic ; une erreur n'est
  jamais conservée en cache.
- **Barre de progression** : `beginProgress()`/`endProgress()` autour de chaque
  `api()` ; apparition différée de 120 ms pour éviter le clignotement sur les
  réponses locales rapides.

## Tests automatisés — `tests/test_desktop_perf.py` (17 tests)

Tests statiques, sans réseau ni donnée réelle : forme et sémantique des
squelettes, squelette par vue, ordre squelette → requête dans les dialogues,
ordre mise à jour → réseau et rollback, marquage visuel, préchargement
survol/focus + anti-doublon + TTL, barre différée, absence d'URL externe,
syntaxe JS via `node --check`.

```
.venv/bin/python -m pytest -q tests/test_desktop_perf.py tests/test_desktop_a11y.py
→ 31 passed in 0.28s
```

`ruff check desktop_static scripts/check_desktop_perf_cdp.py tests/test_desktop_perf.py`
→ **All checks passed**.

## Vérification CDP — `scripts/check_desktop_perf_cdp.py` (15 contrôles)

Le script réutilise l'infrastructure isolée de la SPEC-052 : `create_app()`
dans un répertoire temporaire, API simulées en mémoire avec latence de 600 ms,
uvicorn sur port libre, Chrome `--headless=new` piloté par Playwright
`connect_over_cdp`.

Commande :

```
.venv/bin/python scripts/check_desktop_perf_cdp.py
→ RÉSULTAT : 15/15 contrôles réussis
→ reports/spec-053-perf-cdp.json
```

### Matrice exécutée

| # | Contrôle | Observation |
| --- | --- | --- |
| 01 | Squelette avant la réponse API | `.skeleton-view` présent, `#main[aria-busy=true]`, libellé « Chargement des données » |
| 02 | Barre différée 120 ms | visible pendant la latence simulée |
| 03 | Squelette structuré | ≥ 3 `.skeleton-row` + KPI, blocs `aria-hidden` |
| 04 | Fin de chargement | squelette détaché, barre masquée |
| 05 | Squelette spécifique Offres | 6 lignes réservées |
| 06 | Console | aucune erreur JavaScript |
| 07 | Survol « guide » | 1 requête `ats-guide` émise avant le clic |
| 08 | Clic « guide » | toujours 1 requête (cache consommé), dialogue réel affiché |
| 09 | Focus clavier « réponses » | préchargement `quick-answers` déclenché |
| 10 | « préparer » | dialogue squelette immédiat, `aria-busy=true` |
| 11 | Contenu réel | squelette remplacé par « Dossier prêt » |
| 12 | Envoi optimiste | ligne `.optimistic` + état `sync` avant la réponse |
| 13 | Confirmation | état optimiste retiré, toast « Envoi enregistré » |
| 14 | Panne API 500 | ligne optimiste annulée, toast « Modification annulée » |
| 15 | Aucun envoi automatique | zéro requête `send-confirmation` sans validation |

### Preuve de recette

- `reports/spec-053-perf-cdp.json` : 15 entrées, `failed: 0`, navigateur et
  horodatage inclus.
- Aucune donnée réelle : fixtures `example.invalid`, répertoire temporaire
  supprimé en fin d'exécution.

## Décisions

- **Squelettes plutôt que spinner** : la forme du contenu est réservée, ce qui
  supprime le décalage de mise en page et rend l'attente lisible.
- **Préchargement avec TTL + grâce** : le survol ne doit pas créer de trafic
  infini ; le focus qui suit un clic ne doit pas doubler la requête. Le cache
  est consommé une seule fois et purgé après 30 s.
- **Optimiste limité à une action locale et réversible** : la candidature est
  affichée immédiatement mais l'écriture serveur reste la source de vérité ;
  tout échec restaure l'instantané. Aucune soumission automatique n'est
  introduite.

## Limites

- Les contrôles CDP utilisent Chrome uniquement (Firefox/Safari non couverts).
- La latence est simulée côté serveur (600 ms) ; aucun profil réseau mobile
  lent (3G) n'est testé.
- Le préchargement ne concerne que les fiches détail et les sources de vue
  absentes ; il ne prérend pas les vues complètes.
- Aucune mesure Lighthouse/Web Vitals chiffrée : la recette est comportementale
  (squelette, ordre des requêtes, rollback).

## Fichiers

- `desktop_static/index.html`, `desktop_static/app.css`, `desktop_static/app.js`
- `tests/test_desktop_perf.py`
- `scripts/check_desktop_perf_cdp.py`
- `reports/spec-053-perf-cdp.json` (preuve machine des 15 contrôles)
- `docs/agent-reports/SPEC-053-perf-ux.md` (ce rapport)
