# Assets NAGe

Pack vectoriel du symbole NAGe. Direction visuelle du 4 novembre 2026 : emblème symétrique en trait vert néon, inspiré de la planche fournie par Côme : https://chatgpt.com/s/m_6aeb412032d0819188467a4e53cf0451. Le favicon et l'icône utilisent un fond vert profond et un motif de lignes ; les petites tailles simplifient le motif et renforcent le trait. Les deux moitiés partagent une seule forme source ; la seconde est rendue par miroir SVG. Aucun SVG ne contient de bitmap incorporé.

## Fichiers

- `favicon.svg` — symbole seul, néon et motif, prévu pour rester identifiable à petite taille.
- `favicon-32.png`, `favicon-64.png`, `favicon-180.png`, `favicon-512.png` — rendus PNG du favicon SVG, redimensionnés depuis le rendu Chromium.
- `nage-logo.svg` — version dégradée verte avec lueur douce, sans animation.
- `nage-logo-mono.svg` — version monochrome `#00d47a`.
- `nage-logo-stencil.svg` — version en trait fin, sans lueur.
- `../../design/nage-logo/USAGE.md` — tailles, zone de protection et règles d’utilisation.
- `../../scripts/nage_intro_check.py` — contrôle headless Playwright des SVG.

Pour vérifier les assets depuis la racine du dépôt :

```sh
.venv/bin/python scripts/nage_intro_check.py
```
