# Career — extension vérifiée des sources publiques (vague 2)

Date de vérification : 18 octobre 2026. Branche isolée :
`codex/source-expansion-wave2`, basée sur `ad43cb4858da9576eaf6fd3b5616e2c875e05adb`.
Ce lot n'est pas fusionné dans `main`.

## Résultat livré

Le registre passe de 13 à 21 sources publiques bornées. Huit employeurs ont été
ajoutés après vérification de leur page carrière officielle et de leur ATS
public : Doctolib, Pigment, OakNorth, Monzo, Thought Machine, Alan,
Contentsquare et Dataiku. Les connecteurs existants Greenhouse, Lever et Ashby
sont réutilisés ; aucun nouveau collecteur ad hoc n'a été créé.

Une vérification réseau réelle et bornée a produit :

- 21 sources interrogées, 21 succès, 0 échec ;
- 1 775 annonces évaluées avant limitation ;
- 45 annonces retenues par les critères actifs ;
- 23 annonces portant une preuve explicite de stage ;
- 0 import invalide et 0 doublon dans cette photographie.

Le détail factuel, sans description complète ni donnée personnelle, est dans
`LIVE_SOURCE_CHECK_2026-10-18_WAVE2_FINAL.json`. Il s'agit d'une photographie
temporelle de flux externes, pas d'une promesse de disponibilité future ni
d'une mesure de qualité des candidatures.

## Défauts trouvés et corrigés

1. Les dates Lever/Ashby au format ISO avec heure étaient transmises telles
   quelles alors que l'import Career attend `YYYY-MM-DD`. La normalisation est
   maintenant effectuée dans le connecteur commun. Une date mal formée reste
   inconnue ; elle n'est jamais inventée.
2. L'ancien plafond de 16 sources aurait empêché de consulter les 21 entrées du
   registre. Il est porté à 24, ce qui couvre le registre tout en maintenant une
   borne stricte.
3. Le premier contrôle réel retenait un stage « IT Operations » parce que le
   descriptif employeur contenait du vocabulaire financier. Un test rouge puis
   vert exclut désormais ce faux positif, sans exclure « Investment
   Operations ».
4. Une recette navigateur a montré qu'un profil neuf ne présélectionnait aucun
   domaine : les 150 premières places pouvaient alors être occupées par des
   métiers sans rapport avec la finance. Les huit domaines financiers sont
   désormais cochés par défaut, mais restent tous modifiables. Une nouvelle
   exploration dans l'interface est passée de 150 résultats génériques à 45
   résultats financiers retenus.

La première photographie avant cette correction reste conservée sous
`LIVE_SOURCE_CHECK_2026-10-18_WAVE2.json` afin de rendre l'écart auditable :
46 annonces retenues avant la régression, 45 après.

## Apports observés de la vague 2

- Doctolib : un stage de consolidation et contrôle financier, classé conforme
  selon les faits actuellement disponibles.
- OakNorth : un Industrial Training en finance/réglementaire, conservé « à
  vérifier » car le mois de début et plusieurs faits restent absents.
- Alan : deux postes permanents Sales Planning & Strategy conservés « à
  vérifier » parce que les critères utilisateur autorisent aussi le CDI ; ils
  ne sont pas présentés comme des stages confirmés.
- Les cinq autres sources n'ajoutaient aucune annonce répondant aux critères au
  moment du contrôle. Elles restent utiles pour les rafraîchissements futurs,
  mais ne gonflent pas le résultat.

## Vérifications exécutées

Tests ciblés après correction :

```text
48 passed in 2.73s
```

Non-régression finale sur l'état exact livré :

```text
1092 passed in 101.77s
```

Contrôle réseau final :

```text
Career live source check: 21 succeeded, 0 failed, 0 not queried, 45 retained offers.
```

Recette navigateur réelle sur un espace local isolé : les huit cases de
domaines sont cochées, le bouton `Explorer les stages` interroge 21 sources,
affiche `0 en erreur`, `1775 annonces dans les flux`, `45 offres retenues` et
`45 affichées`. La première carte est le stage Doctolib Consolidation et
Contrôle financier, affiché avec un score déterministe de pertinence et les
faits de période. Aucune candidature n'a été envoyée.

Les deux rapports JSON ont été relus avec un détecteur de formes de clés
Gemini/OpenRouter : aucune forme détectée. Ils ne contiennent que les champs
réduits nécessaires au contrôle (titre, entreprise, type, statut, faits
manquants et URL officielle).

## Limites honnêtes

- La présence d'une source dans le registre ne garantit pas qu'elle publie un
  stage financier à chaque rafraîchissement.
- Les résultats « à vérifier » ne satisfont pas automatiquement les critères :
  les faits absents restent absents.
- Ce lot ne soumet aucune candidature et n'utilise aucune donnée de profil
  personnelle.
- Les sources sont externes et peuvent modifier leur format ou devenir
  indisponibles ; leur santé est donc mesurée à chaque rafraîchissement.

## Retour arrière

Le lot est isolé. Avant intégration, son retour arrière consiste simplement à
ne pas retenir son commit. Après intégration, revenir au commit précédent du
lot restaure le registre de 13 sources et le plafond antérieur sans toucher aux
candidatures existantes.
