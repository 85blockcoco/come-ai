# NAGe — Letterforms vectorielles (monoline)

Dossier créé pour le wordmark « NAGe » : tracés SVG purs (aucun `<text>`, aucune police,
aucune dépendance de fonte). Style : sans-serif géométrique monoline, joints arrondis
(`stroke-linecap="round"` / `stroke-linejoin="round"` partout), premium et minimaliste.

## Fichiers

| Fichier | Rôle |
|---|---|
| `nage-word.svg` | Spécimen des 3 graisses (`word-w1` fin, `word-w2` standard, `word-w3` bold) dans un seul fichier, x-positions identiques, bandes empilées. Un seul graphe partagé `#nage-glyphs` (source de vérité unique). |

## Repères du plan de référence

- `viewBox` du spécimen : `0 0 384 310`
- Baseline : `y = 112`
- Hauteur de capitale (N, A, G) : `72` → sommets à `y = 40`
- x-height du « e » : `42` → haut du bol à `y = 89 − 21 = 68…70` selon l'arc
- Abord gauche : `x = 40`
- Épaisseur de trait : **11** en standard (≈ 10/64 du corps de 72), **9** en fin, **13.5** en bold (×1.25)

## Dimensions par glyphe (tracé hors épaisseur)

| Glyphe | x-debut | x-fin | Largeur | Hauteur (y) | Vertical |
|---|---|---|---|---|---|
| **N** | 40 | 96 | 56 | 40 → 112 | pleine capitale |
| **A** | 120 | 180 | 60 | 40 → 112 | pleine capitale, apex en `x=150` |
| **G** | 204 | 276 | 72 (arc r=36, cx=240, cy=76) | 40 → 112 | pleine capitale |
| **e** | 301 | 343 | 42 (bol r=21, cx=322, cy=89) | 68 → 110 | **shift −2** (voir détail micro-typo) |

Extensions d'encre (standard, ±5.5 de part et d'autre du tracé) : mot de `x=34.5` à `x=348.5`, largeur d'encre ≈ `314`.

## Kerning recompté à la main

| Paire | Espace mécanique blanche (tracé à tracé) | Raisonnement optique |
|---|---|---|
| **N–A** | 24 (96 → 120) | La diagonale du N fuit vers le bas-droit et le pied gauche du A est large : 24 mécaniques donnent ≈ 19–20 d'optique, correct sans creux. Conservé. |
| **A–G** | 24 (180 → 204) | Le pied droit du A (x=180) face à l'estocade ouverte du G (x=204) : le G n'a rien en haut à droite (ouverture à ~260,46), l'optique demande un poil *plus* de vide. 24 retenu pour homogénéité monoline ; à +2 si sensation de serrage en grand corps. |
| **G–e** | 25 (276 → 301) | L'ouverture bas-droite du G (fin d'arc à 274,88) « respire » vers le e ; le e étant plus petit et remonté de 2, l'optique comble le défaut : 25 vs 24, ajustement de 1 px invisible mais juste. |

Lettres à gauche portées par `x=40`, coda « e » à `x=343` → le mot est presque
centré dans le plan (marges optiques ≈ 35 gauche / 35 droite avec l'encre standard).

## Détails de dessin assumés

- **N** : trois segments rectilignes, angle de diagonale 90° d'ouverture (40→96 sur 72 de haut),
  coins carrés *adoucis* par le round join — pas d'arrondi applati artificiel.
- **A** : contrebarre standard à `y=86`, odoriférée sur les jambes (`131–169`) ;
  pas d'apex en arc exagéré, le round join fait l'arrondi léger.
- **G** : arc r=36 ouvert en haut à droite (gap ~74° d'angle), refermé par une barre
  horizontale `y=88` entrant vers `x=244` (mi-œil du G). Aucune tige verticale fantaisie.
- **e** : crossbar pleine largeur à `y_local=89` + croissant fermé en haut/gauche/bas,
  ouverture fine en bas à droite (fin d'arc à 334, 106) — deux subs d'un même path,
  rendu monoline continu à l'œil.
- **Bonus micro-typo** : le `e` final est remonté de **2 unités** (`translate(0,-2)`).
  Non exagéré, il casse la horizontale mécanique de baseline — raffinement, pas tique.

## Règles de redimensionnement

1. **Échelle libre** : tout est stroke vectoriel, l'épaisseur suit `vector-effect` non
   nécessaire → à tel échelle, l'épaisseur scale avec la forme. Pour un rendu net à
   toute taille, conserver le ratio épaisseur/capitale ≈ **0.153** (11/72).
   En practice : `stroke-width = hauteur_capitale_rendue × 0.153`.
2. **Wordmark réduit au-dessus du ruban horizontal** (dans le prototype, zone `-256..256`) :
   - Échelle cible recommandée : hauteur capitale rendue ≈ **26–30 unités** du plan du ruban,
     soit `transform="scale(0.40)"` sur le groupe (72 → ~29).
   - Translater pour centrer : le mot d'encre va de x=34.5 à 348.5, centre ≈ 191.5 ;
     dans le plan prototype centré, utiliser
     `transform="translate(-191.5, offset_y) scale(0.40)"`.
   - En dessous de 24 unités rendues, basculer sur la graisse **fin** (`word-w1`, ratio 0.125)
     — le bold bave when réduit.
   - Ne jamais animer la graisse du wordmark ; n'animer que `opacity`/`transform`
     (comme le prototype, compatible GPU).
3. **Fond sombre** : peindre `currentColor` → `#eafff4` (brunt clair du prototype), ou
   remplacé par `url(#gEm)` (dégradé émeraude) assorti au ruban. Pas d'ombre portée.

## Insertion dans `design/nage-logo/prototype.html`

Ligne à coller à l'intérieur de `<div id="wordmark">` (le conteneur est vidé/renplî
par `buildWord()` — le test de rendu manuel se fait après coup ou en commentant `buildWord`) :

```html
<use href="letterforms/nage-word.svg#w2" transform="translate(-191.5,150) scale(0.42)" style="color:#eafff4"/>
```

⚠️ Référence externe par fragment (`href="...svg#w2"`) ne marche qu'en fichier servi via HTTP.
En inline (recommandé pour l'export SVG autonome), coller directement le contenu du
`<defs>` de `nage-word.svg` puis :

```html
<use href="#nage-glyphs" stroke-width="11" transform="translate(-191.5,150) scale(0.42)" style="color:#eafff4"/>
```
