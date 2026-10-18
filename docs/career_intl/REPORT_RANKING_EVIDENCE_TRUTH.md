# Rapport — vérité du classement et lisibilité des preuves

Date : 18 octobre 2026

Branche isolée : `codex/ranking-evidence-truth`

Base : `d5d1c88e0cddd4668f71f307eb6f9394005ece99`

`main` observé et non modifié : `5ef814eb16f3357264624abdf0b8fd746315b7b1`

## Défauts reproduits

1. Une offre très pertinente pour un domaine pouvait afficher `Correspondance stage : 100/100` et `Correspondance forte` alors que sa date de début ou sa durée manquait et que sa qualification factuelle était `to_verify`.
2. Les descriptions HTML doublement encodées de certains flux Greenhouse pouvaient laisser apparaître des balises comme `<li>` dans une preuve académique.
3. Les connecteurs Lever, Ashby et SmartRecruiters partageaient un contrat qui conservait le HTML distant au lieu de réutiliser le normaliseur central.

Les quatre premiers tests de régression ont échoué avant le correctif. Un test Lever supplémentaire a ensuite reproduit la conservation d'un bloc `<script>` synthétique et a également échoué avant correction.

## Correctifs

- Le score numérique reste un score de pertinence sur les critères comparables ; il n'est pas artificiellement plafonné.
- L'API conserve le libellé de pertinence d'origine dans `fit_label`, puis produit un libellé de présentation tenant compte de `qualification_status`.
- `to_verify` devient explicitement `Pertinence élevée — informations obligatoires à vérifier`, `Pertinence possible — informations obligatoires à vérifier` ou `Informations obligatoires à vérifier` selon le score.
- `non_conforming` devient `Hors critères obligatoires sélectionnés` même lorsque le score de pertinence métier est élevé.
- L'interface dit `Pertinence selon tes critères` au lieu de `Correspondance stage`.
- Le ton vert est réservé à une offre à la fois `conforming` et suffisamment pertinente.
- Le normaliseur HTML central décode au maximum deux couches avant l'analyse du document.
- Les connecteurs ATS publics utilisent maintenant le même normaliseur que Greenhouse. Scripts, styles et balises d'affichage disparaissent avant le classement, la preuve et l'interface.

La provenance reste cohérente : les passages académiques sont toujours des sous-chaînes exactes de la `description_original` normalisée et réellement utilisée par l'application.

## Tests

Tests ciblés Career :

```text
158 passed in 16.05s
```

Suite complète finale :

```text
1088 passed in 83.18s (0:01:23)
```

## Vérification navigateur réelle

Une instance jetable a été lancée sur `127.0.0.1:8918` avec stockage temporaire, sans clé cloud ni donnée personnelle. Après sélection des huit domaines financiers et clic sur `Explorer les stages`, les treize sources ont répondu sans erreur et 1 195 annonces ont été évaluées.

Le flux public avait évolué depuis le contrôle précédent et 41 offres ont été affichées. Ce nombre est donc un instantané, non un catalogue garanti.

La première offre strictement conforme affiche :

```text
Pertinence selon tes critères : 100/100
Correspondance forte
Conforme à tes critères contractuels et de période
```

Les offres incomplètes affichent :

```text
Pertinence selon tes critères : 100/100
Pertinence élevée — informations obligatoires à vérifier
À vérifier : informations ou critères incomplets
```

Aucune balise `<li>` n'était visible dans les preuves académiques. Aucun bouton de suivi, préparation ou envoi n'a été activé.

## Sécurité et limites

- Aucun profil, CV, document privé ou base utilisateur n'a été ouvert.
- Aucun fournisseur IA n'a été appelé.
- Aucun message, e-mail ou candidature n'a été envoyé.
- Le texte ATS est normalisé comme donnée non fiable ; il ne devient jamais une instruction.
- Ce lot améliore l'honnêteté et la lisibilité du classement. Il ne prouve pas encore l'adéquation aux données réelles du candidat.

## Retour arrière

Revenir au commit de base `d5d1c88e0cddd4668f71f307eb6f9394005ece99` dans un worktree distinct. Aucun reset destructeur n'est requis.
