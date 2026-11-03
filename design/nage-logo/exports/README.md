# NAGe — exports vectoriels statiques

Dossier généré à partir de `../prototype.html` (rendu Playwright/Chromium headless,
mêmes fonctions que `exportCurrent()` : `controlPoints(P)`, `sampleChain()`,
`widthAt()`, `ribbonPath()`). Les SVG sont **100 % statiques** : aucun JS, aucune
animation, aucun référencement au runtime du prototype.

## Contenu

| Fichier | Variante | Contenu |
|---|---|---|
| `nage-logo.svg` | Dégradé émeraude + éclat | defs `gEm` + `gSheen` + `fGlow`, ruban double + halo, mot « NAGe » `#eafff4`, fond transparent |
| `nage-logo-mono.svg` | Monochrome | Aucune def superflue, ruban plat `#00d47a`, mot « NAGe » `#00d47a`, fond transparent |
| `nage-logo-stencil.svg` | Contour gravé | Ruban en trait `stroke="url(#gEm2)"` (largeur 3.5), **sans wordmark**, fond transparent |
| `nage-word-only.svg` | Mot seul | Ancien `<text>` « NAGe » typographique, `fill #eafff4`, viewBox ajustée au bbox réel (±119 × −53..37) |
| `nage-ribbon-half.svg` | Moitié gauche seule | Ruban gradient sans le miroir `<g transform="scale(-1,1)">` ni le mot — c'est l'équivalent du `#halfL` du prototype, prêt pour une animation CSS (ex. `translateX` pendant une intro) |
| `preview-*.png` | Rasterisés 512×512 | Aperçu de chaque SVG sur fond `#050705` |
| `gallery.html` | Contrôle qualité | Les 5 SVG inline à 512 / 96 / 32 px sur fond noir, + bandeau damier pour vérifier le fond transparent |
| `_build.py` | Générateur | Playwright (venv repo). Régénère tout : `…/.venv/bin/python _build.py` |

## Geometrie & symétrie

- Moitié **gauche** échantillonnée (Catmull-Rom, 10 pts/segment ≈ 170 points de
  contour), moitié droite obtenue par `<g transform="scale(-1,1)"><use
  href="#ribbonGeo"/></g>` — symétrie parfaite, aucun path dupliqué.
- Coordonnées `toFixed(2)`. Le `d` du ruban reste en séquence `L…L Q … L … Q … Z`
  (même construction que le prototype ; les lobes autour du tressaut central
  imposent le double-S).
- ViewBox des 4 fichiers ruban : `-424 -270 848 540` — le carré
  `-256 -256 512 512` du prototype **rognait** les lobes extrêmes (glow inclus,
  la géométrie va à x ≈ ±410) ; les exports livrent le logo entier.
- `layout` viewport wordmark : la police `Space Grotesk` est requise pour un
  rendu identique (sinon repli `system-ui`). Si l'app l'embarque déjà, rien à faire ;
  sinon prévoir la fonte (ou convertir le texte en contours pour les cas critiques).

## Où intégrer côté app

Aucune connexion : ce sont des assets autonomes (transparent, viewBox dédiée,
aucun id qui fuite — chaque fichier a son propre domaine `ribbonGeo`/`gEm`/…).

- **Écran d'accueil statique** (avant ou à la place de la séquence animée du
  prototype) : `nage-logo.svg`, affiché dans un carré, fond sombre `#050705`
  conseillé pour préserver le halo `fGlow`. En inline SVG plutôt qu'en
  `<object>`/`<img>` si l'on veut que la fonte Google s'applique.
- **App / spinner monochrome** (favicon, loader, état « éco » du thème) :
  `nage-logo-mono.svg` — le plus léger, une seule couleur `#00d47a`, plus
  sûr sur tout fond sombre de l'app.
- **Marque-page / signature discrète** : `nage-logo-stencil.svg` — contour
  seul, se fond dans une UI, pas de mot.
- **Titres, onglets, splash textuel** : `nage-word-only.svg`.
- **Intro animée (CSS)** dans une vue de l'app : poser
  `nage-ribbon-half.svg` dans un conteneur `#halfL` (position absolue,
  `animation: translateX`) et dupliquer le visuel dans `#halfR` avec
  `transform: scaleX(-1)` — le miroir est géré par CSS, pas par un ajout de path.
- **Preview réseaux / docs** : les `preview-*.png` (bitmap), à ne pas committer
  dans l'app.

## Régénérer

```sh
/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python _build.py
```

Lit `../prototype.html` en `file://`, attend `DOMContentLoaded`, évalue la
géométrie dans la page (P du prototype, finition par défaut `gradient`,
constantes intactes) et réécrit ce dossier. `gallery.html` est réémis avec les
viewBox à jour.

*Généré le 26 octobre 2026 — géométrie par défaut : `wEnd 7, wLobe 20, wKink 30, kx 52, ky 64, kt 0.55`.*
