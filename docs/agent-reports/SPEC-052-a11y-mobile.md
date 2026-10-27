# SPEC-052 — Accessibilité et responsive mobile (`/app`)

> Mission CVBOOST-89 · branche `agent/spec-052-a11y_mobile` · 2026-10-27
> Commit de référence : `8716c11` (seule lignée contenant `desktop_static/`).

## Contexte

L'interface bureau NAGE (`desktop_static/`, route `/app`) était pensée pour le
desktop : navigation aux seules icônes à 1080 px (libellés retirés de l'arbre
d'accessibilité), aucun lien d'évitement, `alert()`/`prompt()` natifs,
dialogues sans focus piégé, et un seul point de rupture CSS (1080 px) la
rendant inutilisable sous 720 px. La vue « Suivi » n'était en outre jamais
rendue à la navigation.

## Périmètre livré

### `desktop_static/index.html`
- Lien d'évitement `.skip-link` → `#main` (`tabindex="-1"` focusable), `h1`
  focusable, `main` ciblable.
- `type="button"` sur les 7 entrées de navigation ; libellés conservés dans
  l'arbre d'accessibilité quand la barre latérale passe en mode icônes.
- Repères : `role="region"` + `aria-label` sur les 7 vues, `role="status"`
  `aria-live="polite"` sur l'état serveur, régions live `#srAnnounce` et
  `#toast`, `aria-label` sur l'`aside` et la navigation.
- Champ de recherche enveloppé par un `<label class="search">` contenant un
  texte `.sr-only` « Filtrer les offres ».
- Métadonnées : `theme-color`, `color-scheme`, `description`, viewport existant
  conservé ; icônes SVG décoratives `aria-hidden="true"`.

### `desktop_static/app.css`
- Utilitaires `.sr-only` / `.skip-link`, anneau `:focus-visible` unique (3 px),
  `[hidden] { display: none !important }`.
- **Points de rupture** : `1080 px` (rail icônes, libellés masqués visuellement
  mais toujours lus), `720 px` (navigation horizontale en tête, `100dvh`,
  une colonne, dialogues pleine largeur), `480 px` (compaction, suppression du
  préfixe décoratif `SYS://`, `overflow-wrap: anywhere`), `pointer: coarse`
  (cibles ≥ 44 px), `prefers-reduced-motion`, `prefers-contrast: more`,
  `forced-colors: active`.
- Toast non bloquant (remplace les `alert`), styles de dialogue et de
  formulaire de confirmation d'envoi.
- Correction du débordement horizontal résiduel à 200 % de zoom / 480 px.

### `desktop_static/app.js`
- **Dialogues accessibles** : `mountDialog()` pose `role="dialog"`,
  `aria-modal="true"`, `aria-labelledby`, piège de focus `Tab`/`Shift+Tab`,
  fermeture `Échap` + clic hors cadre, restitution du focus au déclencheur ;
  bouton « Fermer » ajouté systématiquement (ApplyKit, Guide ATS, Réponses
  types).
- `prompt()`/`alert()` remplacés : `askChannel()` (dialogue labellisé avec
  `select` de canal pour « marquer envoyé ») et `notify()` (toast + région
  live) — plus aucun dialogue natif bloquant.
- Navigation clavier : flèches/`Home`/`End` dans la barre latérale,
  activation `Entrée`/`Espace`, focus du titre de vue + annonce au changement
  de vue, `hashchange` géré, lien d'évitement intercepté.
- Annonces : chargement, actualisation, filtre d'offres, copie et erreurs via
  la région live unique ; `aria-busy` pendant le chargement ; `document.title`
  suit la vue.
- Sémantique : `role="progressbar"` + `aria-valuenow`/`min`/`max` sur les
  barres, `role="log"` sur le fil de discussion, `aria-pressed` sur les modes
  assistant, `role="status"` sur l'indicateur de frappe.
- **Correction fonctionnelle** : `render()` ne dispatchait jamais la vue
  `tracking` ; ajout de `else if (view === "tracking") renderTracking();`.

## Tests automatisés — `tests/test_desktop_a11y.py` (14 tests)

Tests statiques, sans réseau ni donnée réelle : langue/viewport/repères, lien
d'évitement, noms accessibles de navigation, régions live, label explicite du
filtre, vues = régions étiquetées, unicité des ids et interdiction de
`tabindex` positif, utilitaires CSS (sr-only, focus, cibles tactiles,
breakpoints 720/480/coarse, reduced-motion, contraste, forced-colors), piège de
focus + Échap, sémantique clavier/progressbar/`aria-pressed`/log, absence de
`alert`/`prompt`/`confirm`, syntaxe JS via `node --check`.

```
.venv/bin/python -m pytest -q tests/test_desktop_a11y.py
→ 14 passed
```

## Vérification CDP — `scripts/check_desktop_a11y_cdp.py` (31 contrôles)

Le script démarre une instance FastAPI **isolée** :

- `create_app(Path(tempfile.mkdtemp(...)))` — aucun accès aux données
  utilisateur ;
- API simulées en mémoire (dashboard, pipeline, tracker, offres, overview,
  missions, guide ATS, apply-kit, réponses types) ;
- uvicorn sur un port libre, dans un thread ;
- Google Chrome `--headless=new --remote-debugging-port`, piloté par
  Playwright `chromium.connect_over_cdp` (Chrome 156.0.8078.48) ;
- aucun `alert`/`prompt`/`confirm` natif (sondes instrumentées avant le
  chargement) ; erreurs console et exceptions JS collectées.

Commande :

```
.venv/bin/python scripts/check_desktop_a11y_cdp.py
→ RÉSULTAT : 31/31 contrôles réussis
→ reports/spec-052-a11y-cdp.json
```

### Matrice exécutée

| Profil | Réglage | Contrôles |
| --- | --- | --- |
| Desktop | 1440 × 900 | 26 contrôles (repères, focus, clavier, dialogues, live, console) |
| Mouvement réduit | 1440 × 900, `prefers-reduced-motion: reduce` | animations ≤ 1 ms, scanlines masquées |
| Reflow | 720 × 450 (zoom 200 %) et 320 × 640 (zoom 400 %) | aucun débordement horizontal sur Aujourd'hui / Candidatures / Offres |
| Mobile | 390 × 844, `is_mobile`, `has_touch`, DPR 3 | débordement, nav horizontale, cibles ≥ 44 px, dialogue, recherche |

### Détail des 31 contrôles

```
01. langue française et titre NAGE
02. métadonnées viewport, theme-color et color-scheme
03. repères main, nav et aside nommés
04. les vues sont des régions étiquetées, une seule visible
05. aria-busy pendant le chargement puis retiré
06. régions live et statut présents
07. aucun débordement horizontal à 1440 px
08. lien d'évitement visible au premier Tab
09. le lien d'évitement déplace le focus sur main
10. anneau de focus visible sur la navigation
11. navigation : 7 boutons nommés, un seul aria-current
12. les flèches déplacent le focus dans la navigation
13. changement de vue : titre, région et annonce live
14. le titre du document suit la vue
15. hashchange ouvre la vue demandée
16. aucune image sans alternative, SVG décoratifs masqués
17. champ de recherche étiqueté, filtre annoncé
18. tous les contrôles visibles ont un nom accessible
19. progressbar avec valeurs accessibles
20. dialogue ATS : rôle, nom, focus initial
21. piège de focus : Tab reste dans le dialogue
22. Échap ferme le dialogue et rend le focus
23. notification non bloquante pour la copie
24. assistant : journal role=log et saisie étiquetée
25. aucune erreur console ni exception JavaScript
26. aucun dialogue natif bloquant
27. prefers-reduced-motion : animations neutralisées
28. reflow 200 % (720 px) et 400 % (320 px) sans débordement
29. mobile 390 px : aucun débordement horizontal
30. mobile : navigation horizontale, cibles ≥ 44 px
31. mobile : dialogue ATS dans le viewport, fermeture overlay, recherche
```

## Décisions

- **Aucune dépendance ajoutée** : le contrôle CDP réutilise Playwright et
  Chrome déjà présents dans l'environnement ; le script échoue proprement si
  Chrome est absent.
- **API simulées plutôt qu'un serveur statique** : les vues sont réellement
  rendues (pipeline, offres, missions), ce qui permet de tester les dialogues
  et les progressbars sans toucher aux données réelles.
- Libellés de navigation conservés dans l'arbre d'accessibilité en mode icônes
  (`clip-path: inset(50%)` au lieu de `display:none`).
- `alert`/`prompt` supprimés plutôt que doublés : un seul canal d'annonce
  (région live + toast), cohérent avec une navigation entièrement clavier.

## Limites

- Contrôles exécutés dans Chrome uniquement ; Firefox/Safari et VoiceOver ne
  sont pas couverts par ce script.
- Le « zoom 200 % » est émulé par reflow de la fenêtre (720 px / 320 px), pas
  par le zoom natif du navigateur ; le résultat couvre l'exigence WCAG 1.4.10
  (reflow) mais pas le zoom texte seul (1.4.4).
- Pas d'audit de contraste chiffré (axe-core) : le thème sombre NAGE est
  conservé et `prefers-contrast: more` renforce bordures/textes.
- Aucune donnée réelle, aucun envoi réseau externe : les fixtures sont
  synthétiques et les URL pointent vers `example.invalid`.

## Fichiers

- `desktop_static/index.html`, `desktop_static/app.css`, `desktop_static/app.js`
- `tests/test_desktop_a11y.py`
- `scripts/check_desktop_a11y_cdp.py`
- `reports/spec-052-a11y-cdp.json` (preuve machine des 31 contrôles)
- `docs/agent-reports/SPEC-052-a11y-mobile.md` (ce rapport)
