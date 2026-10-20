# Explorer les stages — Career Hunter

Le mode Explorer utilise un registre public préparé par l’application : aucun
board personnel, compte ou clé API n’est nécessaire. Le mode Mes entreprises
et les candidatures existantes sont conservés séparément. Ouvrir la page ne
déclenche aucune lecture réseau ; le bouton Explorer déclenche des GET publics.

## Utilisation

1. Ouvrir `/career#career/stagehunter` sur le serveur local Côme AI.
2. Enregistrer les domaines et lieux recherchés à l’étape A.
3. Cliquer **Explorer les stages**, sans configurer d’entreprise.
4. Lire le compte rendu de sources et les résultats de cette exploration.
5. Choisir **Préparer cette candidature**, puis **Créer un suivi**.

La présence d’un stage dans le texte est distinguée de sa pertinence. Un CDI,
un poste senior ou un contrat incertain ne devient pas un stage parce que son
score financier est élevé. Le matching lexical existant est réutilisé ; les
preuves et les données manquantes restent visibles. Les dates non publiées
ne sont pas déduites d’un titre « Summer 2027 » ou de `updated_at`.

## Couverture attestée le 14 octobre 2026 (heure de Paris)

| Employeur | Board public | Provenance officielle |
| --- | --- | --- |
| Lincoln International | https://job-boards.greenhouse.io/lincolninternational | https://www.lincolninternational.com/careers-and-culture/careers/campus-early-careers/ |
| AlixPartners | https://job-boards.greenhouse.io/alixpartners | https://www.alixpartners.com/careers/apply-now/?gh_jid=7810004003 |
| Schonfeld | https://job-boards.greenhouse.io/schonfeld | https://www.schonfeld.com/careers/ |
| Point72 | https://job-boards.greenhouse.io/point72 | https://careers.point72.com/ |
| Qube Research & Technologies | https://job-boards.greenhouse.io/quberesearchandtechnologies | https://www.qube-rt.com/careers/ |
| Flow Traders | https://job-boards.greenhouse.io/flowtraders | https://www.flowtraders.com/careers/job-search/ |
| XTX Markets | https://job-boards.greenhouse.io/xtxmarketstechnologies | https://www.xtxmarkets.com/careers/ |
| Optiver | https://job-boards.greenhouse.io/optiverus | https://www.optiver.com/join-us/jobs/risk-finance-and-legal/singapore/market-risk-internship-2027-singapore/apply |

Les timestamps précis UTC sont enregistrés dans `career/source_registry.py`.
Chaque board a été identifié à partir du site officiel puis interrogé avec le
transport TLS de production. Certains liens de provenance sont dans le JS
officiel : QRT `dist/js/app.js`, Flow Traders `js/job-search.js`, Optiver script
Greenhouse avec `for=optiverus`. Le suffixe `us` d’Optiver n’exclut pas Amsterdam.

Ce registre de huit sources couvre M&A / conseil financier et surtout gestion d’actifs / trading / recherche quantitative.
Il ne couvre pas toutes les banques M&A, les fonds Private Equity ou les offres
FP&A. Un board accessible peut n’avoir aucun stage actuel (XTX lors du contrôle),
ou seulement des stages hors des lieux demandés (Flow lors du contrôle). Ces
sources ne remplissent jamais artificiellement les résultats. Une recherche
avec des critères précis peut légitimement retourner zéro stage.

Adyen, CVX et Trade Republic n’ont pas été ajoutés : absence de preuve complète
du rattachement au board ou flux vide ; les résultats indexés ne constituent
pas une preuve d’accès actuel. Mollie utilise Ashby et reste hors connecteur
Greenhouse. Aucun identifiant de board n’a été deviné pour remplir le registre.

## Architecture et limites

- `source_registry.py` : sources publiques attestées, sans données personnelles.
- `exploration.py` : admission déterministe avec citations source, filtre des
  critères et protocole `InternshipConnector` pour les prochains connecteurs.
- `discovery.py` : adaptateur Greenhouse existant, classification/admission
  avant sélection par source ; TLS vérifié, redirections interdites.
- `service.py` : exploration, import métier existant, cache distinct des boards
  personnels et dernier résultat persistant dans `career_settings` (additif).
- `router.py` : GET et POST `/api/career/stage-search/explore`.
- `career_static/` : bouton, rapport de sources et cartes métier existantes.

Maximum 8 sources par parcours, réponse de 8 Mio par source, délai de socket
de 8 secondes, un retry temporaire maximum, refus d’un flux de plus de 20 000
entrées. Les stages admissibles sont classés avant plafond : top 150 par source
puis top 150 global après dédoublonnage exact d’URL. Aucun nouvel appel ne démarre
après le budget de 60 secondes ; un appel déjà en cours peut le dépasser.

Cache réseau de 10 minutes en mémoire, lié aux sources et critères. Le dernier
rapport et les suivis persistent après redémarrage ; le cache réseau, non.
La page indique séparément lectures réseau, cache, échecs et sources non
consultées. Les compteurs d’un ancien parcours ne sont pas une nouvelle lecture.
Après modification des critères, l’ancien résultat est filtré/reclassé et
signalé comme nécessitant une nouvelle exploration.

Ni CV, ni mémoire, ni critères personnels ne sont envoyés aux boards. Les
requêtes sont uniquement des lectures publiques anonymes, sans modèle IA,
API payante, recherche agressive ou dépôt de candidature. Un contrat indiqué
sur une annonce reste à vérifier avec le recruteur ; aucune embauche garantie.

## Contributions futures : qualification de sources

Un agent de qualification peut travailler indépendamment, **sans modifier le
moteur, le frontend ou le registre accepté**. Il remet une liste de propositions :

```text
company, provider, board_token, public_url, provenance_url, verified_at
preuve du lien site officiel -> board
résultat GET (succès/échec), volume, exemples de stages et localisation
limites, pagination, dates et type de contrat réellement fournis
```

L’intégrateur vérifie les propositions, ajoute les entrées acceptées et rejoue
les tests. Un nouveau fournisseur exige un connecteur borné en lecture seule
derrière `InternshipConnector` ; une entrée sans adaptateur est affichée non
prise en charge, jamais interrogée par une URL arbitraire. Lever, Ashby et les
ATS des grandes banques sont des extensions futures, pas de la couverture
annoncée pour cette livraison. EURES exige une qualification d’accès séparée.

Noveria Lab reste préservé : son moteur de fraîcheur/doublons n’est pas fusionné
tel quel (16 tests réussis, 8 échecs lors de l’inspection). Les dédoublonnages
exacts déjà éprouvés de Career suffisent au MVP ; doublons probabilistes et
relances J+7 avec validation humaine restent des lots distincts.
