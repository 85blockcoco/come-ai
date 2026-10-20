# CVBOOST-03 — UX du plan CV : filtres, priorités et navigation

Date : 20 octobre 2026
Branche : `agent/cvboost-03`
Base : `7834e45d…` (worktree `codex/career-cv-boost`, SHA candidat fourni : aucun — départ de la
base vérifiée du pack, avec contrat défensif pour l'arrivée de CVBOOST-01/02).
Aucune dépendance ajoutée, aucun schéma modifié, aucune donnée réelle.

## 1. Ce qui a été construit

### 1.1 Nouveau module statique `career_static/cv_plan.js` (≈ 490 lignes)

Tout le rendu et la logique de la section « Plan précis pour ton CV » vivent désormais dans ce
module, chargé avant `career.js` (`defer`). Aucun appel réseau, aucun `window.prompt`,
aucun `navigator.clipboard`, aucun `fetch`/`api(` : le module est purement local.

- **Ordre déterministe** (`cvPlanRankKey`, `cvPlanCompareEntries`) : blocage factuel → exigence
  obligatoire → amélioration → préférence, puis priorité backend (`high` > `medium`), puis ordre
  d'arrivée. Aucun tri par « pertinence » estimée.
- **Filtres accessibles** : groupe `role="group" aria-label="Filtres du plan CV"` avec quatre
  boutons `aria-pressed` (Tous · N, À mettre en avant · N, À vérifier · N, Bloquants · N).
- **Compteurs + explication** : résumé de couverture documentaire (X/Y exigences, % ,
  langue cible), disclaimer non-probabiliste, et un bloc repliable « Que mesure la couverture
  documentaire ? ». Région `role="status" aria-live="polite"` annonçant chaque changement de
  filtre, chaque marque « revu ».
- **Navigation clavier** : Tab natif entre tous les boutons ; flèches ↑/↓ entre les conseils
  (en sautant les lignes masquées par un filtre), Home/End aux extrémités.
- **Bouton « Compléter mon profil »** : cible la bonne rubrique selon `section` (Compétences →
  `#profile-skills`, Expériences → `#profile-experience`, Formation → `#profile-education`,
  Langues → `#profile-languages`, Informations complémentaires → `#profile-eligibility`) ou la
  catégorie CVBOOST-02 (`Langue`, `Formation`, `Disponibilité` → Réglages, `Mobilité` → villes
  Stage Hunter). Cible inconnue → premier champ du formulaire de profil. Jamais un champ du CV
  source.
- **Bouton « Préparer dans le Studio »** : `openStudioForJob(job, langue_cible)` — offre
  préselectionnée, langue, mode « Gabarit local factuel », consentement décoché.
- **Marque « revu » locale** : clé `career_cv_plan_reviewed_<offre>` dans `localStorage`,
  tolérante (mode privé, JSON corrompu). Le CV source et le profil ne sont jamais modifiés ;
  la marque survit au re-rendu et au rechargement de page.
- **Contrat défensif CVBOOST-01/02** : `modality` (required/preferred/contextual), `category`,
  `provenance` (champ, ligne, passage), `source: "cv_structure"` et `item.filter` sont lus
  s'ils apparaissent ; en leur absence le comportement actuel est conservé. Une exigence préférée
  sans preuve n'est jamais comptée « bloquante » dès que `modality` est présent.

### 1.2 Accroches minimales (périmètre respecté)

- `career_static/career.js` :
  - `renderStagePrep` délègue la section plan à `renderCvPlanSection(target, prep, job)`
    (le rendu inline historique est supprimé) ;
  - `openStudioForJob` écrit la préselection dans `localStorage` (`career_studio_prefill`,
    mode toujours `local`) ;
  - `renderStudioJobOptions` restaure la sélection après rechargement (offre, langue, mode
    local, consentement non coché — un mode `ai` falsifié dans le stockage n'est jamais
    restauré) ;
  - deux `change` listeners persistants sur les sélecteurs d'offre et de langue.
- `career_static/index.html` : ajout de la feuille `cv_plan.css` et du script `cv_plan.js`
  **avant** `career.js`. Aucune navigation refondue : toujours les sept onglets existants.
- `career_static/cv_plan.css` : nouveaux styles réutilisant les tokens existants
  (`--border`, `--muted`, `--accent*`, `--danger-soft`, `--warning-soft`, `--good`, …) et
  breakpoint `@media (max-width: 760px)` (actions en pile pleine largeur).

### 1.3 Correctif inclus (découvert pendant la recette navigateur)

`.studio-consent { display: flex !important; … }` écrasait `[hidden]` : en mode gabarit local,
la ligne de consentement cloud restait **visible** alors que `hidden` était vrai. Ajout de
`.studio-consent[hidden] { display: none !important; }` dans `career.css` + garde statique
Python. Le mode IA reste inchangé (ligne visible, case requise).

## 2. Validation

### 2.1 Tests JS comportementaux (Node 22, stubs DOM contrôlés, sans navigateur simulé)

`tests/test_career_cv_plan_ux.py` — 11 tests, le module `cv_plan.js` et les vrais helpers
`career.js` sont injectés et exécutés :

- ordre déterministe (rang, priorité, ordre d'arrivée) + compteurs par filtre ;
- compteurs de filtres, `aria-pressed`, masquage, message `aria-live`, état vide annoncé ;
- texte de preuve (exigence, preuve, mots-clés non étayés), disclaimer et aide couverture ;
- bouton Studio : offre + langue cibles, aucune requête réseau ;
- ciblage « Compléter mon profil » par rubrique et par catégorie, fallback sans champ CV ;
- marque « revu » : persistance locale, survie au re-rendu, dé-marquage, aucune API ;
- navigation clavier (flèches, Home/End, Tab natif, lignes masquées) ;
- préselection Studio sur 3 sessions simulées (dont rechargement avec mémoire vide) : offre
  conservée, mode local, consentement non coché, zéro requête réseau, mode `ai` non restauré ;
- gardes statiques : aucun `window.prompt`/`confirm`/`alert`/`fetch`/`api(`/`clipboard`,
  tokens CSS réutilisés, media query mobile, sept onglets, `.studio-consent[hidden]`.

`tests/test_career_cv_action_plan.py::test_ui_renders_the_precise_cv_plan` a été mis à jour
(déplacement du rendu dans le module) ; ses assertions d'intention (plan, preuve, preuve
personnelle, Studio) restent couvertes.

### 2.2 Parcours navigateur réel (Chrome headless, DevTools Protocol, 100 % local)

- `scripts/cv_plan_browser_demo.py` : serveur de démo jetable (profil + offre synthétiques,
  stockage temporaire, tout réseau sortant refusé).
- `scripts/cv_plan_browser_journey.js` : pilote CDP via le WebSocket natif de Node (aucune
  dépendance, aucun téléchargement) ; vérifie en conditions réelles : rendu du plan, ordre des
  rangs, filtres, navigation clavier, marque « revu », préselection Studio (offre/langue/local,
  ligne de consentement non rendue), **survie de l'offre après rechargement de page**,
  **aucune requête hors loopback** (journalisée via CDP `Network`), zéro exception console, et
  viewport 412 px (actions empilées, pas de défilement horizontal).
- Captures : `docs/agent-reports/cvboost-03-captures/01-cv-plan-1440.png`,
  `02-cv-plan-bloquants-filtre.png`, `03-studio-preselection.png`, `04-cv-plan-mobile-412.png`.
- Résultat : `CVPLAN_BROWSER_JOURNEY_OK` (dernier run, captures régénérées après le correctif CSS).

### 2.3 Suites automatisées

- `pytest -q` complet : **1156 passed** (baseline 1141 ; +11 nouveaux tests, 2 existants
  révisés, aucune régression, aucun skip retiré) ;
- `ruff check .` : **All checks passed** ;
- `git diff --check` : propre.

## 3. Limites honnêtes

- **CVBOOST-01/02 non intégrés** (aucun SHA candidat fourni) : le contrat défensif est en place
  et testé par des fixtures portant `modality`/`category`/`provenance`, mais l'adoption réelle
  par `career/cv_quality/*` et `career/offer_requirements/*` reste à brancher côté intégrateur.
- La **langue cible** affichée provient du champ `language` de l'offre ; sur une offre sans langue
  connue, la couverture annonce « à confirmer » et la préselection de langue respecte la dernière
  langue choisie (jamais de substitution silencieuse).
- Le mode IA du Studio n'est **jamais** restauré par la préselection ; un utilisateur qui choisit
  « Amélioration par IA » doit reconfirmer son consentement à chaque retour sur la vue.

## 4. Rejeu

```bash
# Tests ciblés + gardes statiques
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest tests/test_career_cv_plan_ux.py -q

# Parcours navigateur complet
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m scripts.cv_plan_browser_demo --port 8917 &
node scripts/cv_plan_browser_journey.js --app-port 8917 --captures docs/agent-reports/cvboost-03-captures
```
