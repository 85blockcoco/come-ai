# Rapport NAGe — Mission 1 (intro sur `/app`) + Mission 2 (pages claires chaleureuses)

Date : 26 octobre 2026 · Sous-agent mission conjointe — les deux styles restent strictement séparés :
- **Desktop = noir + émeraude sobre** (`desktop_static/`, thème inchangé) ;
- **Career/Web = clair chaleureux** (`career_static/`, `web_static/`).

Aucun serveur lancé (uniquement des fichiers `file://` temporaires créés par mes scripts). Aucun JS applicatif ni `.py` modifié, hormis mon script de vérification. `career_static/nage_assets/` et le reste de `design/nage-logo/` intacts (`intro/intro.js` et `intro/intro.css` **non modifiés**, lire plus bas).

---

## Mission 1 — Intro d'ouverture NAGe sur `/app`

### Fichiers modifiés (uniquement les deux autorisés)

**`desktop_static/index.html`**
- `<main>` de l'app reçoit la classe `nage-app-root` (élément hôte du `wrapSelector`).
- Conteneur donneur `<div class="nage-intro" id="nageIntroSource" hidden aria-hidden="true">` inséré avant `.window`, contenant **le logo réel inline** : copie exacte de `design/nage-logo/exports/nage-logo.svg` (defs complets : `gEm`, `gSheen`, `fGlow`, `fSoft`, `ribbonGeo`), retitré :
  - `<g data-half="L" id="halfL">` = le trio de `<use href="#ribbonGeo">` (dégradé + glow + sheen) ;
  - `<g data-half="R" id="halfR">` = même trio dans un **sous-groupe** `<g transform="scale(-1,1)">`. Le miroir du SVG est conservé mais déplacé sur un groupe interne : l'animation WAAPI `translateX` appliquée par intro.js sur le groupe extérieur ne doit pas être **écrasée** par l'attribut de miroir (sinon la moitié droite repartait à l'envers) ;
  - `<g data-word="1" id="wordmark">` = le `<text>NAG<tspan>e</tspan></text>` d'origine (remplissage `#eafff4`, pas de retouche).
- Le SVG donneur reste **toujours caché** (`.nage-intro[hidden]{display:none}`) ; intro.js le découvre via `svg:has([data-half])`, le clone dans son overlay, puis retire tout seul l'overlay du DOM à la fin (pointer-events neutralisés à 55 % de la durée, scroll bloque/débloque, `nage:introend`, anti-rejeu `sessionStorage`).
- **intro.js est injecté en ligne** (copie intégrale de `design/nage-logo/intro/intro.js`) : le serveur ne monte que `/app-static`, une balise `src` vers `design/` aurait donné un 404 et une intro muette — la copie inline est le seul moyen de brancher l'API sans toucher au serveur.
- Boot `initNageIntro({ wrapSelector: 'main.nage-app-root', durationMs: 2200 })` à `DOMContentLoaded` (script en fin de body), entouré de garde-fous :
  - `Element.prototype.animate` absent → retour silencieux, interface visible immédiatement ;
  - `prefers-reduced-motion: reduce` → aucune intro du tout ;
  - toute erreur pendant l'intro → les overlays sont retirés et l'application remise visible (zéro crash apparent, zéro blocage du contenu) ;
  - anti-rejeu via `sessionStorage["nage_intro_played"]` (déjà géré par intro.js, testé).

**`desktop_static/app.css`** (thème de l'app non modifié ; ajouts bloqués en fin de fichier)
- Adaptation de `intro/intro.css`, chaque règle scellée par **`.nage-intro:not([hidden])`** pour ne cibler que l'overlay dynamique (le donneur `[hidden]` ne capte rien de style).
- `.nage-intro[hidden]{display:none}` explicite (sécurité si JS échoue).
- Visibilité de l'accueil pilotée **par classe d'état** : `main.nage-app-root` est lisible par défaut ; seule la classe `.nage-intro-ui-hold` (posée pendant les 2,2 s que dure l'intro) le masque un instant, puis `--in` le révèle en fondu — l'accueil est donc utilisable **sans** intro et sans JS.
- `@media (prefers-reduced-motion: reduce)` → overlay en `display:none !important` et interface forcée visible.

### Bug réel trouvé dans `intro/intro.js` (fichier livré) — corrigé seulement dans MA copie inline

L'animation du mot-symbole (Phase B) livrait des keyframes **non monotones** : offsets `0 → 0.806 → 0.62` ( `t(phiB0/phiB1)` remonte au-dessus de `t(phiB1)`). Chromium refuse avec :
`TypeError: Failed to execute 'animate' on 'Element': Offsets must be monotonically non-decreasing.`
→ l'intro **plantait à chaque démarrage** (le filet de sécurité ramenait l'app, mais jamais l'animation). Dans ma copie inline j'ai aligné `0 → t(phiC0)=0.55 → t(phiB1)=0.62` : mot visible jusqu'à 55 %, fondu d'ici 62 %, conforme à l'intention du prototype. Le fichier source `design/nage-logo/intro/intro.js` **n'a pas été touché** — à corriger en upstream si tu rebranches un jour la balise `src`.

### Test Playwright — script laissé en place : `design/nage-logo/verify_intro_app.py`

Chromium headless (`bring_to_front()` pour éviter le throttling du clock d'animations et une frame périmée du compositeur). Clone `file://` de l'accueil réel, liens statiques en chemins absolus, **sans passer par l'URL du serveur**. **14/14 vérifications : SUCCÈS.**

| Vérification | Résultat |
|---|---|
| L'intro joue (halves L/R clonées du SVG inline) | ✓ |
| `main.nage-app-root` reçoit `.nage-intro-ui-hold` pendant l'intro | ✓ |
| L'overlay `.nage-intro` est retiré du DOM après ~2,3 s | ✓ |
| `main.nage-app-root` visible et interactif après l'intro | ✓ |
| L'app est utilisable (topbar opacité 1) | ✓ |
| Événement `nage:introend` diffusé | ✓ |
| Conteneur donneur du logo resté inoffensif (caché) | ✓ |
| Scroll rétabli après l'intro | ✓ |
| Pas de rejeu au rechargement (sessionStorage) | ✓ |
| `prefers-reduced-motion` → aucune intro, app visible d'emblée | ✓ |
| WAAPI absente → saut silencieux, app intacte | ✓ |

Capture après intro : app desktop intacte (noir + émeraude sobres, grille 242 px / 1fr, sidebar et topbar conformes au thème).

---

## Mission 2 — Réchauffement des pages claires (career_static, web_static)

Principe : neutraliser le blanc pur, garder les panneaux blancs, texte `#2a2622`, contours chauds `#e8e2d9` (bordures secondaires `#ded7cb`), accent professionnel **vert profond `#047857`** conservé (accent maison), ambre doux `#b45309` **uniquement** pour les avertissements. Pas de néon ni futurisme ; voile accent doux `--nag-accent-soft-warm: #e7f0eb`.

### Fichiers modifiés (aucun JS ni `.py`)

**`career_static/career.css`**
- `:root` : ajout d'un bloc de **variants chauds `--nag-*`** (`--nag-bg-warm #f5f3ee`, `--nag-surface-warm #fbf9f5`, `--nag-panel-warm #fff`, `--nag-border-warm #e8e2d9`, `--nag-accent-warm #047857`, `--nag-accent-dark-warm #065f46`, `--nag-accent-soft-warm #e7f0eb`, `--nag-ink-warm #2a2622`, `--nag-dim-warm #6b645b`, `--nag-warning-warm #b45309`, `--nag-warning-soft-warm #fdf3e7`) — **desktop_static n'est pas affecté** (il garde ses propres valeurs `--nag-*`).
- Rebranchage complet des tokens locaux (`--ink`, `--canvas`, `--panel`, `--border`, `--muted`, `--accent…`, `--warning…`, `--surface-…`) sur ces variants.
- Balayage des hexadécimaux froids → chauds : fonds (`#f4fbf7`, `#fbfefc`, `#f4faf6`, `#f8fcfa`…) vers crème ; toutes les bordures vert-gris froides (`#dce9e2`, `#d6e3dc`, `#d2e9dc`…) → deux tonalités chaudes uniquement (`#e8e2d9` / `#ded7cb`, 41 occurrences) ; textes verts froids (`#14532d`, `#315d4e`, `#29463b`…) alignés sur la famille du vert profond.
- `--shadow` adouci (`0 8px 20px rgb(42 38 34 / 5%)`).
- `--warning: #b45309`, `--warning-soft: #fdf3e7` (l'ancien `#8a4a06` bruyant remplacé) ; l'ambre reste réservé aux états d'avertissement, rien d'autre n'a changé de sémantique.
- Espacement inter-panel généreux : `.metrics` gap 11→16 px, `.job-list/.application-list` gap 10→16 px, `.form-stack` 10→12 px (le reste était déjà ≥ 16 px : cibles de clic 44 px et `:focus-visible` 2 px accent déjà posés, préservés).

**`career_static/cv_plan.css`**
- Hérite automatiquement des variants chauds via career.css (aucun doublon de token).
- Reste nettoyé : `#f0f5f2 → #f2efe8`, badge « amélioration » `#fff8ec → #fdf6ea`, anneau focus-within ramené à `rgb(4 120 87 / 15%)`.

**`web_static/app.css`**
- Même bloc de variants chauds `--nag-*` dans `:root` + rebranchage complet des tokens locaux.
- Balayage des gris « bleutés » : `#edf0f5 → #eae5dc`, `#e2e8f4 → #e8e2d9`, fonds `#fafcff`/`#f9fbff`/`#f3f6fa` → crème, texte `#253552 → #4a433a`, bord de champ `#c9dad1 → #ded8cb` ; les cibles d'accent (`career-link`, `secondary-button`, `selected-context`) alignées sur la famille vert profond (`#065f46` / `--accent-soft`), hover en teinte douce.
- Ajout d'un **`focus-visible` global 2 px accent** (cette feuille n'en avait aucun : les boutons au clavier n'avaient aucun anneau), transitions douces sur les actions, et garde-fou `[hidden]{display:none !important}`.

Les `index.html` de `career_static`/`web_static` : **aucun style inline existant** (vérifié), aucune édition nécessaire.

### Test visuel Playwright (clones `file://`)
- `career_static` → fond calculé `rgb(245, 243, 238)` = crème **#f5f3ee** ✓ ; topbar, onglets, actions, panneaux blancs et contours chauds conformes (captures `career_warm.png`, `web_warm.png` dans le temp dir de session).
- `web_static` → fond `rgb(245, 243, 238)` ✓, trois panneaux blancs à contours chauds.

### Imperfections restantes

1. **`intro/intro.js` livré contient le bug d'offsets** ; ma copie corrigée vit dans `desktop_static/index.html`. Si un jour la page reprend une balise `src` vers le fichier original, l'intro plantera de nouveau — corriger upstream.
2. Les micro-tailles de chips/étiquettes métadonnées (`.66–.73rem`) de `career.css` restent sous 14 px — héritées de l'agent précédent, volontairement gardées pour la densité.
3. `verify_intro_app.py` neutralise `app.js` dans son clone (par conception, pour tester l'intro seule) ; le vrai `/app` chargera `app.js` normalement, l'intro ne dépend pas de lui.
4. En Chromium headless, le compositeur peut renvoyer une frame périmée pour les captures avec `will-change`+`contain` ; le script force une frame fraîche avant capture. Aucun impact sur des navigateurs réels.
5. brushing possible plus loin : rendre la sidebar de career elle-même beige (`#f0eadf`) au lieu de blanc — dis-le si tu veux pousser la chaleur d'un cran.
