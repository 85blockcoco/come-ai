# SPEC-048 — Palette de commandes + raccourcis clavier

**Mission :** CVBOOST-85 · **Branche :** `agent/spec-048-cmd_palette`
**Date :** 2026-10-26 · **Périmètre :** `desktop_static/` uniquement (route `/app` inchangée)

## Objectif

Donner à l’interface bureau NAGE un accès clavier complet : une palette de
commandes unique pour naviguer, filtrer, actualiser et ouvrir un dossier, plus
des raccourcis globaux utilisables sans souris. Aucune requête externe, aucune
soumission automatique, aucune donnée réelle n’est nécessaire au fonctionnement
de la palette.

## Livrables

| Fichier | Rôle |
|---|---|
| `desktop_static/index.html` | Bouton « Commandes » (⌘K) dans la barre supérieure |
| `desktop_static/app.js` | Palette, filtrage accent-insensible, navigation clavier, dialogue des raccourcis |
| `desktop_static/app.css` | Styles de la palette, des raccourcis et adaptations petit écran |
| `tests/test_desktop_command_palette.py` | Garde-fous statiques + tests Node du filtrage (5 tests) |
| `scripts/check_spec048_cdp.py` | Parcours navigateur réel Chrome headless via CDP (21 vérifications) |
| `docs/agent-reports/SPEC-048-CMD-PALETTE.md` | Ce rapport |

## Fonctionnalités

### Palette de commandes

- Ouverture par le bouton **Commandes**, par `⌘K` / `Ctrl+K`, ou par `/`.
- Champ de recherche unique avec filtrage **insensible aux accents et à la casse**
  (`memoire` trouve « Mémoire », `aujourd` trouve « Aujourd’hui »).
- Classement : préfixe du libellé → sous-chaîne → description/mots-clés →
  sous-séquence de secours. Le terme saisi est surligné dans le libellé.
- Navigation `↑` / `↓`, `Home` / `End`, `Entrée` pour exécuter, `Échap` pour
  fermer, `Tab` maintenu dans le champ (pas de fuite de focus).
- Exécution possible à la souris (survol = sélection, clic = exécution).
- 13 commandes de base : 7 vues, actualiser, filtrer les offres, afficher les
  raccourcis, et 3 liens externes (Career, V5, V3).
- Jusqu’à 4 **dossiers en cours** (dédupliqués, progression < 100 %) sont
  proposés dynamiquement ; exécuter la commande ouvre le modal local
  « Dossier prêt » (`/api/career/apply-kit`). Rien n’est envoyé à un employeur.
- Compteur de résultats annoncé via une zone `role="status"` `aria-live`.

### Raccourcis clavier

| Raccourci | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Ouvrir / fermer la palette |
| `/` | Ouvrir la vue Offres et placer le curseur dans le filtre |
| `?` | Ouvrir la référence des raccourcis |
| `R` | Actualiser toutes les sources locales |
| `Alt+1` … `Alt+7` | Aujourd’hui, Candidatures, Suivi, Offres, Assistant, Missions, Mémoire |
| `G` puis `D` | Aujourd’hui |
| `G` puis `A` | Candidatures |
| `G` puis `S` | Suivi |
| `G` puis `O` | Offres |
| `G` puis `C` | Terminal (assistant) |
| `G` puis `M` | Missions |
| `G` puis `E` | Mémoire |
| `↑` `↓` `Entrée` | Naviguer / exécuter dans la palette |
| `Échap` | Fermer la palette, les raccourcis ou le modal supérieur |

Les raccourcis à une touche (`R`, `/`, `?`, `G`) sont neutralisés dès que le
focus est dans un champ de saisie, un textarea, un select ou un élément
`contenteditable`, pour ne jamais gêner l’écriture d’un message ou d’un filtre.

## Accessibilité

- Dialogue `role="dialog"` + `aria-modal="true"`, nommé par `aria-labelledby`.
- Champ `role="combobox"` avec `aria-autocomplete="list"`,
  `aria-controls`, `aria-expanded`, `aria-activedescendant` et
  `aria-label="Rechercher une commande"`.
- Options `role="option"` avec `aria-selected` synchronisé.
- Focus déplacé dans le champ à l’ouverture, piégé pendant la palette, puis
  restauré sur l’élément déclencheur à la fermeture.
- Dialogue des raccourcis : focus initial sur « Fermer », `Tab` piégé,
  `Échap` ferme, focus restauré.
- Compteur de résultats en `aria-live="polite"`.
- Respect de `prefers-reduced-motion` (règles globales existantes).

## Sécurité et confidentialité

- Aucune modification de la route `/app` ni du routeur FastAPI.
- Aucune requête externe : les liens Career/V5/V3 s’ouvrent dans un onglet local.
- Aucune soumission automatique : la seule action à effet de bord est la
  génération locale d’un dossier, déclenchée explicitement par l’utilisateur.
- La palette ne réinjecte jamais la saisie utilisateur en HTML : le seul
  `html` statique est l’icône SVG interne ; les libellés passent par
  `textContent`.
- Le parcours CDP a été exécuté sur une instance isolée
  (`create_app(base_dir=<répertoire temporaire>)`), sans données personnelles.

## Tests

### Garde-fous pytest

```text
.venv/bin/python -m pytest -q tests/test_desktop_command_palette.py
.....                                                                    [100%]
5 passed
```

Les tests vérifient : CSP (pas de script/style inline), présence des points
d’entrée, absence de injection HTML dans la palette, neutralisation des
raccourcis pendant la saisie, dispatch de la vue Suivi, styles requis, et le
classement du filtrage exécuté sous Node.

### Parcours Chrome headless / CDP

Commande :

```bash
.venv/bin/python scripts/check_spec048_cdp.py --base-url http://127.0.0.1:8898
```

Résultat : **21 PASS / 0 FAIL** sur Chrome headless piloté par CDP
(`connect_over_cdp`), avec :

- ouverture `Ctrl+K`, focus dans le champ, rôles ARIA ;
- filtrage « suivi » + surlignage, `Entrée` ouvre `#tracking` ;
- `Échap` ferme et restaure le focus sur le bouton ;
- `↓` + `Entrée` exécute la 2ᵉ commande ;
- `Alt+4` ouvre les Offres ;
- `/` focalise le filtre sans saisir de slash ;
- `?` ouvre la référence, `Échap` la ferme ;
- `G` puis `M` ouvre les Missions ;
- inventaire complet des 13 commandes et filtrage sans accent ;
- un dossier synthétique en cours devient une commande filtrable par entreprise ;
- aucune erreur JavaScript ni erreur console inattendue.

### Suite complète

```text
.venv/bin/python -m pytest -q
1 failed, 3071 passed, 1 skipped in 157.01s
```

L’unique échec est **pré-existant et sans rapport avec cette mission** :
`tests/test_career_agent.py::test_local_storage_profile_preferences_and_persistence`
(`assert 14 == 6` sur les familles de préférences du profil local). La base
avant mission comptait 3066 tests passés ; les 5 nouveaux tests de la palette
expliquent l’écart de comptage.

```text
node --check desktop_static/app.js  → OK
git diff --check                    → propre
ruff check tests/test_desktop_command_palette.py scripts/check_spec048_cdp.py
                                    → All checks passed
```

`ruff check .` conserve 4 erreurs pré-existantes hors périmètre
(`come_ai_web.py:513`, `night_supervisor.py:105/140/146`) ; aucun fichier
Python ajouté ou modifié par la mission n’est concerné.

## Notes d’intégration

- La branche de travail du worker est `worker/cvboost-85-1793041943737`.
- Le commit fonctionnel est publié sur `agent/spec-048-cmd_palette`, comme
  demandé par la mission.
- Aucun fichier applicatif hors `desktop_static/`, `tests/`, `scripts/` et
  `docs/` n’est modifié par cette mission ; `messages/result.json` est réécrit
  uniquement pour le rapport de mission exigé par l’orchestrateur.
