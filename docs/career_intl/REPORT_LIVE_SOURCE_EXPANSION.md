# Rapport — extension vérifiée des sources Career

Date : 18 octobre 2026

Branche isolée : `codex/live-source-coverage`

Base : `05c0f17497a411922cbebb3ae4b03c1569d7cbae` (`codex/configurable-search-criteria`)

`main` observé et non modifié : `5ef814eb16f3357264624abdf0b8fd746315b7b1`

## Résultat

Le registre actif passe de huit à treize sources publiques. Les cinq ajouts sont :

| Entreprise | Fournisseur | Identifiant | Provenance officielle |
| --- | --- | --- | --- |
| Man Group | Greenhouse | `mangroup` | `https://www.man.com/careers` |
| AQR | Greenhouse | `aqr` | `https://careers.aqr.com/` |
| Robinhood | Greenhouse | `robinhood` | `https://careers.robinhood.com/` |
| General Atlantic | Greenhouse | `generalatlantic` | `https://www.generalatlantic.com/careers/` |
| Qonto | Lever | `qonto` | `https://qonto.com/fr/careers` |

Ces cinq relations employeur–ATS avaient été qualifiées dans le lot documentaire `feature/career-international-sources`. Leurs flux publics ont été relus avec succès le 18 octobre 2026 avant intégration. Les autres propositions LongCat n'ont pas été ajoutées automatiquement : un flux qui répond n'est pas, à lui seul, une preuve suffisante du lien avec la page carrière officielle.

Le plafond d'une exploration explicite passe de huit à seize sources. Il couvre donc le registre entier avec une marge bornée. Lever, Ashby et SmartRecruiters restent désactivés lors d'une construction directe de connecteur ; ils sont activés uniquement dans la carte de l'Explorer, après un clic de l'utilisateur et derrière la validation du registre et du service.

## Contrôle réseau réel par l'application

Commande :

```text
env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY -u COME_AI_MEMORY_DIR HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m scripts.live_source_check --json docs/career_intl/LIVE_SOURCE_CHECK_2026-10-18_FINANCE.json
```

Le script utilise `CareerService`, les connecteurs réels et une base temporaire. Il sélectionne explicitement tous les domaines de la finance, les quatre contrats par défaut, janvier à mars et six mois minimum pour un stage. Il ne lit aucun profil, CV, document, secret ou base utilisateur.

Résultat mesuré :

| Indicateur | Valeur |
| --- | ---: |
| Sources enregistrées | 13 |
| Sources consultées | 13 |
| Sources réussies | 13 |
| Sources en échec | 0 |
| Sources non consultées | 0 |
| Annonces publiques évaluées | 1 195 |
| Offres non conformes aux contrats/périodes | 394 |
| Offres restant incertaines avant filtre métier | 800 |
| Offres écartées par l'admission finance | 767 |
| Offres de finance conservées | 34 |
| Offres strictement conformes | 1 |
| Offres à vérifier | 33 |
| Doublons d'URL conservés | 0 |
| Durée de l'exploration | 18,749 s |

Répartition des 34 offres conservées : 28 stages, 3 CDI, 2 CDD et 1 contrat ambigu. Ces nombres ne sont pas une estimation de recrutement : ils décrivent uniquement les faits présents dans les flux à l'heure du contrôle.

### Offre strictement conforme

- Lincoln International — `Debt Advisory Internship (March 2027)` ; stage ; début mars 2027 ; durée publiée de six mois ; source Greenhouse vérifiée.

### Offres de janvier repérées mais non promues

- Lincoln International — `M&A Internship (January 2027)` : mois explicite, durée absente, donc `to_verify`.
- Lincoln International — `Stockholm - M&A Internship Jan-June 2027` : début janvier explicite, mais le moteur ne transforme pas automatiquement une plage de mois sans jours en durée minimale certaine, donc `to_verify`.

Les titres `Summer 2027`, `Q3 2027` ou une date précédée de `Apply by` ne deviennent jamais un mois de début inventé.

## Défauts corrigés avec tests rouges puis verts

1. Le registre n'incluait pas les cinq sources revues.
2. Lever était encore désactivé même pour une source curée et après le clic Explorer.
3. La limite de huit sources empêchait de consulter un registre élargi.
4. Les mois et années publiés dans les titres n'étaient pas utilisés comme faits de début.
5. Le texte institutionnel des employeurs pouvait faire remonter des fonctions support sans rapport suffisant avec la finance (`Receptionist`, `Staff Product Designer`, `Datacentre Operations`, `Talent Community`). Un test synthétique a d'abord reproduit l'erreur, puis le filtre a été corrigé sans exclure `Investment Operations`.

Première régression du lot registre : `2 failed, 2 passed`.

Régression du parsing des titres avant correction : `2 failed, 3 passed`.

Après corrections :

```text
142 passed in 10.24s
```

Suite complète avant la dernière régression métier :

```text
1082 passed in 104.33s (0:01:44)
```

Le décompte de la suite complète finale, relancée après ce correctif, figure dans la section de validation finale ci-dessous.

Validation finale sur l'état exact du lot :

```text
1083 passed in 66.01s (0:01:06)
```

Évaluation applicative finale exécutée sur cet état : run `88cc0c79b087`, 14 cas, 13 exécutés et réussis, zéro échec, un cas non pris en charge (`local_model_generation`), zéro appel API déclaré par la cible, durée 1,464 s et pic mémoire 112,5 MiB.

## Vérification dans le navigateur

Une instance locale jetable a été lancée sur le port `8917`, avec stockage temporaire, clés cloud retirées et les connecteurs publics réels. Dans Stage Hunter, les huit domaines de finance ont été cochés puis enregistrés avant de cliquer sur « Explorer les stages ».

L'interface a affiché :

```text
13 sources consultées sur le réseau · 0 en cache · 0 en erreur ·
1195 annonces dans les flux · 34 offres retenues · 34 affichées.
```

La première carte est le stage Lincoln strictement conforme, avec mars 2027, six mois, provenance Greenhouse et lien officiel. Les fonctions support reproduites lors de la première vérification ne figurent plus dans les résultats. Les offres dont la date ou la durée manque restent visiblement marquées « À vérifier ». Aucun bouton de candidature, de suivi ou de message n'a été actionné.

## Artefacts

- `docs/career_intl/LIVE_SOURCE_CHECK_2026-10-18_FINANCE.json` : faits publics et compteurs du dernier contrôle, sans corps complet des annonces.
- `scripts/live_source_check.py` : contrôle reproductible, stockage temporaire et refus d'écraser un rapport existant.
- `tests/test_career_verified_source_expansion.py` : contrat du registre, activation bornée et réduction des données exportées.

## Confidentialité et limites

- Aucun fournisseur IA n'a été appelé.
- Aucun profil, CV, dossier `internships`, historique de candidature ou document personnel n'a été lu.
- Aucun formulaire, candidature, message ou e-mail n'a été envoyé.
- Les flux ATS sont des instantanés publics : une offre peut être modifiée ou supprimée après le contrôle.
- Les 33 offres à vérifier ne sont pas annoncées comme conformes. La plupart manquent encore d'une date de début suffisamment précise, d'une durée de stage ou des deux.
- Certaines citations académiques provenant des descriptions Greenhouse affichent encore des balises HTML brutes dans l'interface. Le fait cité reste traçable, mais sa présentation doit être nettoyée dans un lot UI distinct sans affaiblir la provenance.
- Ce lot augmente la couverture des sources et améliore l'extraction factuelle ; il ne mesure pas encore l'adéquation au véritable profil de l'utilisateur.

## Retour arrière

Le lot est isolé dans son propre worktree. Pour revenir à l'état précédent sans supprimer aucun travail, utiliser le commit `05c0f17497a411922cbebb3ae4b03c1569d7cbae` ou créer un autre worktree depuis ce commit. Aucun reset destructeur n'est nécessaire.
