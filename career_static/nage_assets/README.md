# Assets NAGe

Pack vectoriel statique du symbole et du logo NAGe, dérivé de la géométrie de référence du prototype. Les deux moitiés partagent une seule forme source ; la seconde est rendue par miroir SVG. Aucun asset ne contient de bitmap incorporé.

## Fichiers

- `favicon.svg` — symbole seul, prévu pour rester identifiable à petite taille.
- `favicon-32.png`, `favicon-64.png`, `favicon-180.png`, `favicon-512.png` — rendus PNG du favicon SVG, redimensionnés depuis le rendu Chromium.
- `nage-logo.svg` — version dégradée sobre, sans lueur ni animation.
- `nage-logo-mono.svg` — version monochrome `#00d47a`.
- `nage-logo-stencil.svg` — version contour gravé.
- `../../design/nage-logo/USAGE.md` — tailles, zone de protection et règles d’utilisation.
- `../../scripts/nage_intro_check.py` — contrôle headless Playwright des SVG.

Pour vérifier les assets depuis la racine du dépôt :

```sh
.venv/bin/python scripts/nage_intro_check.py
```
