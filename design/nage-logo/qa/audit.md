# Audit technique — `design/nage-logo/prototype.html`

Audit statique (lecture de code, aucune exécution). État du fichier au moment de la lecture : 26 oct 2026, version avec galerie + exporter SVG.
Référence visuelle : `NAGe _ éclat néon symétrique.png` (ruban coupé par les bords du cadre — toléré).

---

## 1. Constructeurs (`render()`, `build()`)

- **[MAJEUR] `p()` défini mais jamais utilisé dans `playIntro()`** — toutes les animations sont appelées via `el.animate()` direct, donc `currentAnims` reste vide en permanence. Conséquences en cascade : le `cancel()` de replay ne cancel rien (les animations se superposent à chaque clic/coupure de sliders), et le listener `focus` rejoue l'intro *à chaque* regain de focus (`if(!currentAnims.length)` est toujours vrai). Fix : pousser chaque animation dans `currentAnims` (ou filtrer/canceller via `el.getAnimations()`).
- **[MAJEUR] Collision d'IDs SVG dans la galerie** — chaque carte définit son propre `<path id="ribbonGeo">`, `gEm`, `gSheen`, `gEm2`… tous les IDs sont *globaux au document* : la carte mono n'a aucune définition de `gEm`/`gSheen` mais la carte gradient en redéfinit, et `url(#…)` résout vers la **première** occurrence du document. Ça fonctionne aujourd'hui par accident (définitions identiques), mais casse dès qu'un réglage de slider divergence la géo principale des cartes. Fix : préfixer les IDs par variante (`ribbonGeo-mono`, `gEm-mono`, …) ou isoler chaque carte dans un `<svg>` avec `id` unique + `use href="#id#variante"`.
- **[OK] Symétrie miroir** — conformément au critère (a) : `#halfR` porte `transform="scale(-1,1)"` dans le markup et `build(defsHost,{onlyBody:true})` n'écrit **pas** de second `ribbonGeo` ; les deux `<use href="#ribbonGeo">` partagent exactement la même géo. Pas de duplicata divergent. ✅
- **[OK] Croquis vs prototype** — points d'amorce conformes à la géo attendue : lobe haut entré à (-260,-112), extrême gauche (-392,-6), tressaut contre l'axe autour de (−30..−74, −6..84), amortissement lobe bas (-352,172). Le débordement (x=-392 hors viewBox ±256) est cohérent avec la référence (ruban rogné aux bords) — **[OK]**, mais :
  - **[MINEUR] Le crop dépend de `overflow:hidden` par défaut du `<svg>`** — si un jour le SVG est exporté avec `overflow:visible` ou rendu dans un contexte qui désactive le clip (certains viewers), la moitié gauche est moche. Fix : ajouter explicitement `overflow="hidden"` sur l'`<svg>` racine + un `clipPath` dans l'export SVG.
- **[OK] Polarité de `sampleChain` (Catmull-Rom `per=10`)** — formule standard (p0..p3, clamping aux bouts), 171 points, suffit pour un rendu lisse ; l'indexation `t=i/(N-1)` est correcte.
  - **[MAJEUR] Mais la paramétrisation est *uniforme par segment*, pas par longueur d'arc** → voir §2 (c'est la cause principale du bug de profil).

## 2. Profil d'épaisseur `widthAt()` — critère (b) — **bug principal**

Rappel cible : pics attendus aux emplacements des points d'amorce sur la ligne centrale.
Contrôle : `sampleChain(...,per=10)` → 17 segments → `t=i/170`.

| Élément | Emplacement réel sur la ligne centrale (t) | Pic codé dans `widthAt` | Verdict |
|---|---|---|---|
| Lobe haut (amorce (-260,-112) → extrême (-392,-6)) | segments 2–3 → centre ≈ t≈0.176 (le point extrême tombe à t≈0.16) | pic à **t=0.19, σ=0.13** | **[MINEUR]** pic légèrement décalé — tombe *sur le flanc descendant* (amorce de sortie) plutôt que sur le point extrême ; acceptable visuellement mais pas exact |
| Tressaut (double-S serré : segments 8–11, i≈80–110) | centre du zigzag ≈ **t≈0.56–0.62** (pas 0.44 !) | pic à **t=0.44, σ=0.11** | **[BLOQUANT] Le pic tombe clairement BEFORE le tressaut** (0.44 ≈ segment 7.5, c'est-à-dire la descente (-74,84)→(-30,-6), l'entrée du canal) — l'épaisseur maximale (30px) n'est donc *pas* sur le double-S mais sur le coude d'entrée. C'est le bug le plus probable, confirmé par simple lecture : les 4 points du tressaut codés `(-30,-6),(-66,-b),(-30,-b-14),(-a-18,b-46),(-a-30,b+30)` sont aux indices 8–11 → t∈[0.47,0.65], soit un centre ≈ **0.56**, pas 0.44. Fix : passer le centre du gaussien de kink à ≈0.56 et σ à ≈0.07–0.09 (le zigzag est serré), **et** re-paramétrer par longueur d'arc (voir point suivant). |
| Lobe bas (amorce (-a-30,b+30) → extrême (-352,172) → sortie (-300,212)) | segments 12–14 → centre ≈ t≈0.79 | pic à **t=0.80, σ=0.15** | **[OK]** alignement correct, mais le pic tombe aussi *entre* (-352,172) (t≈0.75) et la sortie, σ large masque l'imprécision. Tolérable. |

- **[MAJEUR] Racine commune : `t` n'est pas paramétré par longueur d'arc** — les segments n'ont pas la même longueur (le tressaut est très court, les lobes longs) ; tout réglage de `kx/ky/kt` *déplace* le t en temps réel des pics. Fix robuste : après `sampleChain`, ré-échantillonner selon la longueur d'arc cumulée (`arcLength` cumulée puis interpolation) et faire correspondre les pics `widthAt` aux longueurs normalisées des points d'amorce, ou bien calculer directement la largeur depuis les indices de contrôle (moitié par segment) plutôt que depuis un `t` global.
- **[MINEUR] Le facteur `taper` (arrondi des bouts)** `min(1, min(t,1-t)*10)` s'applique à une zone ≈ t<0.1 et t>0.9, soit ~17 points — fait son travail. **[OK]**.

## 3. `ribbonPath()` — auto-intersections (critère c) — descriptif

- **[OK] Le contour fermé** gauche→demi-cercle (Q vers le point central final)→droite retour→demi-cercle (Q vers c0) → assemble correctement, avec un `Q` par bout (le contrôle est placé exactement sur le point central → théoriquement un arc passant par le centre, acceptable pour des bouts arrondis).
- **[MAJEUR] Zones à risque d'auto-intersection du contour** (le path est en `fill`, les auto-intersections seront invisibles au `nonzero` mais *visibles sur le stencil* qui est en `stroke`, et moches sur le `sheen` en blend `screen`) :
  1. **Le tressaut (le plus à risque)** : inversion de sens quasi-180° sur les segments 8–11 (de (-30,-6) à (-a-30,b+30)) avec `wKink` réglable jusqu'à **44** (défaut 30) — côté intérieur des trois coudes, le bord "extérieur" va s'auto-croiser dès que la demi-largeur (≈15–22) dépasse le rayon de courbure local (rayon ≈ kx·kt ≈ 20–25 au mieux) → **pinch certain si l'utilisateur pousse `wKink` à 40+** ; déjà limite aux valeurs par défaut.
  2. **Le coude de retour du bas (segments 14–15, (-128,222)→(-100,244))** : virage serré en fin de course avec `wLobe` jusque 34 → risque de pinch côté intérieur du coude.
  3. **L'entrée du lobe haut ((-118,-164)→(-260,-112))** : rayon de courbure serré + montée de largeur (wEnd≈7 → wLobe≈20 en quelques segments) → léger risque côté intérieur du lobe.
- **[OK] Le calcul de normale** (différence centrée `q-r`) est stable et produit une normale cohérente ; il n'y a pas de saut tangent brutal mis à part aux virages ci-dessus.
- Recommandation (descriptive, pas de patch) : style QPainter / stylet "segments plus longs" — soit (i) lisser la normale (moyenne glissante sur ~5 points), soit (ii) cap la largeur locale par `min(w, rayonCourbureLocale×0.9)`, soit (iii) un offset polygonal à miter-limit mettant les sommets aigus en chanfrein (comme le `miter limit` de QPainter). Le simple clamp de largeur au tressaut suffit à éliminer le pinch visible.

## 4. Séquence d'ouverture `playIntro()` — critère (d)

- **[BLOQUANT] Le wordmark reste invisible à la fin de l'intro** — l'animation du `#wordmark` : keyframes `[{opacity:1},{opacity:1,offset:.30},{opacity:0,offset:.62}]` → la *dernière* keyframe implicitement offset=1 est `{opacity:0}`, et l'animation est en `fill:'both'` → elle **maintient opacity:0 à l'infini** après la fin. Le texte disparaît après la 1ʳᵉ lecture, et le bouton "masq./aff." (`#btnText`) ne peut plus rien faire : l'opacité inline est écrasée par le `fill` de l'animation. Fix : ajouter une keyframe finale `{opacity:0, offset:1}` + soit `fill:'forwards'` avec `a.onfinish=()=>a.cancel()` (et remettre l'inline), soit terminer la keyframe à l'opacité voulue (1) après le fondu.
- **[MAJEUR] Superposition des animations à chaque replay** — cf. §1 : `currentAnims` jamais rempli, `cancel()` ne cancel rien ; après 3–4 clics sur "Rejouer", les gliss/fade `fill:'both'` de runs précédents s'empilent sur les mêmes propriétés `transform`/`opacity` des mêmes éléments (`#halfL/#halfR/#wordmark/#fakeui/#logoSvg`) → artefacts visuels (easing contradictoires, opacity figée). C'est le risque "deux animations de même propriété" exactement décrit au critère (d).
- **[MAJEUR] Listener `focus`** — `addEventListener('focus',… if(!currentAnims.length))` → comme `currentAnims` est toujours vide, **chaque** retour d'onglet relance l'intro ; la garde `sessionStorage` (une seule fois par session) est ainsi court-circuitée. Fix : relier le conditionnement à `sessionStorage` (`nage_intro_played`), pas à `currentAnims`.
- **[MINEUR] Variable `Bris` calculée puis jamais utilisée** (tout comme `A0/A1/B0/C0/C1`, les offsets dans les keyframes sont codés en dur). Qui plus est la formule de `Bris` mélange `A0+Math.max(0.12, A1-A0)` en unités *de temps absolues* (s) avec des bornes en fraction de K — incohérence de dimension, sans conséquence puisque la variable est morte. Fix : soit brancher ces constantes sur les offsets des keyframes (source unique de vérité), soit supprimer.
- **[MINEUR] Durées désynchronisées** — animations des moitiés en `K+40` ms vs les autres en `K` ms : désynchronisation de fin imperceptible mais inutilement complexe. `[OK]` visuellement.
- **[MINEUR] `reduced` lu une seule fois au chargement** (`let reduced=matchMedia(...).matches`) : ne réagit pas au changement dynamique de l'OS. Non-bloquant, mais fix simple : `matchMedia(...).addEventListener('change',…)`.
- **[OK] Syntaxe des keyframes** — tous les `offset` explicites sont triés strictement croissants et ≤1 ; le dernier offset implicite est bien à 1 ; aucun offset dupliqué. ✅
- **[OK] Sélecteurs animés existent tous** : `#logoSvg`, `#halfL/#halfR`, `#wordmark`, `#fakeui`. Pas de sélecteur fantôme.
- **[MINEUR] `sheenIn` est du code mort** (défini, jamais appelé) — soit brancher son appel sur l'intro, soit supprimer.
- **[MINEUR] `window.__geo` debug** laissé dans `oninput` des sliders — à supprimer avant intégration.

## 5. `prefers-reduced-motion` (critère e)

- **[OK] Skip propre et non bloquant** : `reducedSkip` → styles inline immédiats (wordmark visible→puis w.style.opacity=0 ; fake UI opacity 1 ; moitiés écartées + opacity 0), `return` avant toute animation. Cohérent : pas d'intro, l'UI est là.
  - **[MINEUR] Incohérence dans le skip** : `w.style.opacity=0` masque le wordmark *définitivement* en mode reduced (aucune interface pour le réafficher si le user ne touche pas au bouton). Probablement voulu (l'intro a été skippée) mais surprenant : majoritairement on affiche le wordmark statiquement en mode réduit. À arbitrer.
  - **[OK] Le clic-plays est toujours actif en mode reduced** (l'utilisateur a la main, c'est lui qui choisit).

## 6. Centrage optique du wordmark (critère f)

- **[MAJEUR] `letter-spacing:18` sur le `<text>`** décale le centre optique : l'espacement est ajouté *après chaque glyphe, y compris le dernier*, donc l'avancement total (utilisé par `text-anchor="middle"`) inclut un trailing whitespace de 18 unités → le mot paraît décalé de **18/2 = 9 unités vers la gauche** par rapport à l'axe. Fix exact réglable :
  - **Option A (la plus simple)** : mettre `text x="9"` au lieu de `x="0"` (compense exactement la demi-largeur du trailing spacing ; régler finement ±1–2 px au besoin).
  - **Option B** : `NAG` est le mot principal, le `<tspan>`/"e" a sa propre taille (58) → lui donner un `dx` : `<tspan style="font-size:58" dx="-9">e</tspan>`.
  - **Option C (wrapper)** : séparé en 2 `<tspan>` (un pour `NAG`, un pour `e`) et ancrer chaque tspan séparément (`text-anchor:start` sur le 1ᵉʳ, position calculée manuellement via `dx`) — plus verbeux, inutile ici.
- **[OK] Baseline `y="14"`** — dans le système de coordonnées centrées (+14 vers le bas), place le texte approximativement au centre optique vertical du logo (les caractères majuscules culminent vers -46 avant la descente). Conforme.
- **[MINEUR] Le tspan `e` hérite du `letter-spacing:18`** mais comme c'est le dernier glyphe, ça ne change rien au centrage (c'est le 18 après `G` qui compte). La légère différence de taille (64 vs 58) est visuellement cohérente avec le croquis.

## 7. Responsive (critère g)

- **[MINEUR] Taille du logo : `width:min(46vh,430px)`** — sur un portrait mobile (≈390×844) le wrap fait 46vh ≈ 388px, mais `max-width:88vw` le borne à ≈343px. Le logo reste carré (`height:auto`) et tient dans le stage de 58vh. Prix à payer : sur un mobile bas (≈390×700), 46vh=322 > 58vh×0.55 — acceptable, mais la marge verticale sous le logo pour laisser respirer les contrôles est **très juste** (le wrap est centré, il déborde vers le bas jusqu'à ~5vh des contrôles).
  - Fix : passer le `min()` en `clamp(240px, min(46vh,430px), 88vw)` ou réduire à `min(40vh,430px)` sous 480px de large.
- **[MINEUR] `#stage` fixe `height:58vh; min-height:400px`** — sur iPhone SE/mini (≈375×667), 58vh=387 < min-height 400 → l'étage prend 400px de haut et 400px de logo dépassent sous les contrôles → **léger risque de masquer les contrôles** (z-index 6 les remonte visuellement, mais ils chevauchent le bas du logo). Non-bloquant, amélioreable via `min(58vh, calc(400px))` et une taille de logo réduite sous 460px de haut.
- **[MINEUR] `body{min-height:100vh}`** sur iOS Safari : `vh` inclut la barre dynamique → léger défilement fantôme. Fix : `min-height:100dvh` avec fallback `100vh`.

## 8. Panel & mobile portrait (critère h)

- **[OK] Panel 3→1 colonne déjà présent** via `@media (max-width:760px){ #panel{grid-template-columns:1fr} }`. ✅
- **[OK] Contrôles du stage (`#controls`)** — restent superposés, `z-index:6`, `pointer-events:auto` explicite sur les boutons (le stage est cliquable ailleurs). Fonctionnel.
- **[MINEUR] Hauteur stage 58vh sur iPhone** — cf. §7 : sur 667px de haut, 58vh + min-height 400px → 400px utilisés, les contrôles restent visibles mais le logo empiète visuellement dessus au premier rendu ; pas de cassage. Verdict : **acceptable mais vérifier sur un device réel ≤ 460px de large**.

---

## Synthèse (priorités)

| # | Catégorie | Point |
|---|---|---|
| 1 | **BLOQUANT** | wordmark invisible en post-intro (`fill:'both'` sur dernier offset, opacité 0 tenue) → bouton "masq./aff." inopérant |
| 2 | **BLOQUANT** | pic du tressaut dans `widthAt` à t=0.44 alors que le zigzag réel occupe t≈0.47–0.65 (centre ≈0.56) → épaisseur max au mauvais endroit |
| 3 | **MAJEUR** | `currentAnims` jamais rempli (helper `p` mort) → replay empile les animations, `focus` rejoue à chaque regain |
| 4 | **MAJEUR** | paramétrisation non arclength du centre → les pics `widthAt` bougent dès qu'on touche `kx/ky/kt` |
| 5 | **MAJEUR** | IDs SVG globaux dupliqués dans la galerie (résolution par accident) |
| 6 | **MAJEUR** | offset optique du wordmark (trailing letter-spacing) → choisir option A (`x="9"`) |
| 7 | **MAJEUR** | risque pinch aux coudes du tressaut (`ribbonPath`) avec `wKink` élevé (descriptif, implémentation au choix) |
| 8–14 | **MINEUR** | code mort (`sheenIn`, `Bris`, `__geo`), `reduced` non dynamique, `100vh` vs `dvh`, durées K+40, crop dépendant d'overflow par défaut, marge verticale mobile serrée |
