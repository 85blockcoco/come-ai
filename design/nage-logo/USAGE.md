# Guide d’usage du logo NAGe

Les fichiers prêts à intégrer sont dans [`career_static/nage_assets/`](../../career_static/nage_assets/). La nouvelle direction demandée le 4 novembre 2026 reprend l'emblème symétrique de la [planche de référence](https://chatgpt.com/s/m_6aeb412032d0819188467a4e53cf0451) : vert néon et motif sur fond vert profond. Le prototype historique reste préservé ; il n'a pas été modifié par cette évolution. Le tracé source d’une moitié est défini une seule fois ; l’autre moitié utilise ce même tracé dans un groupe `scale(-1,1)`.

## Versions

- **Dégradé — `nage-logo.svg`** : emblème et nom verts, lueur douce, à privilégier sur fond sombre. Aucun reflet animé.
- **Monochrome — `nage-logo-mono.svg`** : variante durable et sobre en `#00d47a`, à privilégier pour les interfaces, documents et impressions simples.
- **Contour — `nage-logo-stencil.svg`** : contour émeraude pour gravure, gaufrage ou usage où une forme évidée est préférable. Vérifier le contraste et l’épaisseur sur le support final.
- **Symbole seul — `favicon.svg`** : emblème néon, fond vert profond, motif de lignes, sans mot-symbole. Utiliser les PNG fournis pour les environnements qui ne prennent pas en charge SVG. Le motif est masqué aux petites tailles pour garder le symbole lisible.

## Tailles minimales

- Logo complet avec mot-symbole : **120 px de large** à l’écran ou **30 mm** en impression.
- Symbole seul : **24 px** à l’écran ou **8 mm** en impression.
- Favicon : fichiers fournis en **32, 64, 180 et 512 px**. À 16 px, préférer le SVG comme favicon navigateur afin de bénéficier du rendu vectoriel.
- Éviter la version contour sous **96 px** de large ; son trait peut perdre en netteté à l’impression ou sur écran basse résolution.

## Zone de protection

Garder libre autour du logo une marge minimale égale à la hauteur du « e » du mot-symbole. Pour le symbole seul, garder une marge équivalente à **un huitième de la hauteur du symbole**. Aucun texte, bord, icône ou élément de mise en page ne doit entrer dans cette zone.

## À faire

- Conserver les proportions et le centrage d’origine.
- Choisir la finition qui conserve le meilleur contraste sur le fond.
- Utiliser les fichiers SVG pour les interfaces et les supports vectoriels ; réserver les PNG fournis aux usages qui l’exigent.
- Garder le symbole sans mot-symbole pour les petits emplacements carrés.

## À éviter

- Ne pas étirer, incliner, tourner, recadrer ni séparer les rubans.
- Ne pas redessiner ni substituer une moitié : la symétrie dépend du miroir du tracé source.
- Ne pas amplifier la lueur ni superposer d'effets aux exports : utiliser la finition adaptée à la taille. Garder les pages d'apprentissage sobres.
- Ne pas remplacer la palette officielle, ni placer le logo sur un fond dont le contraste rend les rubans difficiles à distinguer.
- Ne pas ajouter le mot-symbole au favicon.
