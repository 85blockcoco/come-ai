# Checklist d'intégration — intro NAGe dans une app HTML existante

- [ ] **Copier les blocs autonomes** : `#stage` (markup), le CSS sectionné « Zone d'animation » + styles du logo, et le `<script>` géométrie/séquence — rien d'autre (header/panel/gallery = prototype only).
- [ ] **Renommer/ranger les IDs globaux** (`#logoSvg`, `#ribbonGeo`, `gEm`, `gSheen`, `fGlow`, `gSheen`…) pour éviter toute collision avec les IDs existants de l'app — surtout si plusieurs `<svg>` coexistent.
- [ ] **Fixer les IDs** : préfixer chaque instance (`ribbonGeo-hero`, `gEm-hero`…) pour empêcher la résolution accidentelle d'IDs dupliqués dans le document.
- [ ] **z-index du stage** : `#stage` doit recouvrir l'app initialement (le `opacity:0` de l'app n'évite pas le clic fantôme) → poser `z-index` élevé sur `#stage` + verrouille `pointer-events:none` sur le contenu d'app tant que l'intro tourne.
- [ ] **Garde de session** : conserver `sessionStorage['nage_intro_played']` et jouet l'intro uniquement si absent — **neutraliser le listener `focus`** (rejouer sur tout regain = anti-pattern).
- [ ] **Ne pas re-render pendant l'intro** : si l'app est en framework réactif (React/Vue), injecter le markup une seule fois ; tout `render()`/reconciliation doit préserver `#defsHost`, `#halfL/#halfR`, `#wordmark` avec leurs références (sinon les animations `fill:'both'` pointent des nœuds morts).
- [ ] `prefers-reduced-motion` : le skip inline est déjà géré — en intégration, ajouter aussi `scroll-behavior`/autofocus exemptés, et vérifier que le faux-UI est remplacé par le vrai contenu (pas de double masquage).
- [ ] Remplacer `#fakeui` par le vrai contenu de l'app (la phase C anime son `opacity/scale`) — l'animée `ui.animate` doit cibler l'identité réelle (id/config  à adapter).
- [ ] Nettoyer le code mort avant intégration : `sheenIn`, variable `Bris`, `window.__geo`, helper `p` (ou le brancher réellement pour alimenter `currentAnims`).
- [ ] Corriger le `fill:'both'` final du wordmark (dernière keyframe à l'opacité cible + `onfinish=cancel` + inline sync) **avant** intégration, sinon le texte reste masqué.
- [ ] `currentAnims` doit être rempli (cancel au replay) — sinon empilement des runs au rejouer / changement de page.
- [ ] Fix du centrage : `text x="9"` (ou `dx="-9"` sur le tspan `e`) compensant le trailing `letter-spacing:18`.
- [ ] Fix du pic tressaut dans `widthAt` (t≈0.44 → ≈0.56, σ plus serré) + idéalement re-paramétrage par longueur d'arc.
- [ ] Vérifier `overflow="hidden"` sur l'`<svg>` racine si le logo est affiché dans une surface non-clippée.
- [ ] Tester : iPhone portrait ≤460px (logo vs contrôles), `reduced-motion` OS activé, double à triple clic "Rejouer", et le bouton exporter si conservé.
