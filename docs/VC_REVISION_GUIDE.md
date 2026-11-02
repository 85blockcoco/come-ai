# Révision Venture Capital — guide utilisateur

NAGE propose un coach de révision VC **100 % local** pour préparer les cours de capital-risque :
rappels actifs, calculs de formules, cas chiffrés, radar de faiblesses et plan de révision borné.
Aucun manuel protégé n'est recopié : le contenu livré est original et les notes personnelles
restent hors du dépôt.

## 1. Environnement vérifié

Versions utilisées pour la recette du 2 novembre 2026 :

| Outil | Version |
| --- | --- |
| Python | 3.12.10 |
| pytest | 9.1.1 |
| ruff | 0.17.1 |
| pypdf | 6.19.0 |

Commandes de contrôle :

```bash
.venv/bin/python --version
.venv/bin/python -m pytest --version
.venv/bin/python -m ruff --version
```

## 2. Données locales et confidentialité

- Les données d'apprentissage sont stockées dans `~/.nage/vc/` (ou dans le dossier absolu
  indiqué par `NAGE_VC_HOME`).
- Le dossier, ses sous-dossiers et les fichiers sont créés avec des permissions privées
  (`700` pour les dossiers, `600` pour les fichiers).
- Un dossier VC qui est un lien symbolique est refusé.
- Aucune donnée personnelle, aucun terme sheet réel et aucune note de cours ne doit être
  ajouté au dépôt. `.nage/` et `vc_data/` sont ignorés par Git.
- L'outil ne fait aucun appel réseau et ne soumet jamais une candidature ou un document.
- La suppression exige la phrase exacte `SUPPRIMER MES DONNEES VC` et ne supprime que le
  dossier VC local.

### Sauvegarde et restauration

Pour une sauvegarde manuelle, copiez le dossier VC avec ses permissions :

```bash
cp -a ~/.nage/vc ~/.nage/vc-backup-$(date +%Y%m%d)
```

Un fichier JSON illisible est conservé automatiquement sous la forme
`<nom>.corrupt-AAAAMMJJHHMMSS` avant d'être remplacé par une valeur vide. Pour restaurer,
arrêtez NAGE, remplacez le fichier courant par la sauvegarde, puis relancez la commande.
Les exports de progression contiennent les cartes et les réglages, jamais le texte des notes.

## 3. Session de rappel active

```bash
.venv/bin/python nage.py vc review --minutes 10
```

Le programme affiche une carte, attend que vous révéliez la réponse, puis demande une note :

- `again` : oubli, la carte revient le jour même ;
- `hard` : réussite difficile, intervalle court ;
- `good` : réussite normale ;
- `easy` : réussite facile, intervalle plus long.

Une session interrompue est conservée. La relancer avec `vc review` reprend au bon curseur.
Modes disponibles : `quick`, `long`, `exam_eve`, `custom`.

Pour une intégration scriptée, ajoutez `--json`. Les commandes `--reveal`, `--grade` et
`--status` permettent de piloter une session existante avec `--session <id>`.

## 4. Drills de formules

```bash
.venv/bin/python nage.py vc drill list --topic VC04
.venv/bin/python nage.py vc drill run VC04-D001 --answer "10 M€"
.venv/bin/python nage.py vc drill random --topic VC09 --seed 7
```

Chaque correction affiche les étapes de calcul et un diagnostic :

| Diagnostic | Signification |
| --- | --- |
| `formula` | formule ou calcul incorrect |
| `order` | ordre des opérations ou priorité incorrecte |
| `unit` | unité absente, ambiguë ou incohérente |
| `missing_data` | énoncé incomplet, calcul impossible |
| `convention` | convention différente de celle du cours |

Unités acceptées : `eur`, `k_eur`, `m_eur`, `percent`, `ratio`, `years`.
Une convention alternative n'est acceptée que si elle est explicitement déclarée dans le
contenu du drill.

## 5. Cas chiffrés

```bash
.venv/bin/python nage.py vc case list
.venv/bin/python nage.py vc case show VC03-CASE01
.venv/bin/python nage.py vc case grade VC03-CASE01 --answers reponses.json
```

Le fichier de réponses est un objet JSON `question -> texte` :

```json
{
  "q1": "Post-money 10 M€, investisseur 20 %.",
  "q2": "2 millions d'actions nouvelles.",
  "q3": "Le runway se raccourcit et un bridge peut diluer."
}
```

La correction applique une grille de critères pondérés. Elle signale les nombres non justifiés
et affiche une réponse modèle **après** soumission. Ce n'est pas une note humaine : le score
sert à identifier les critères manquants.

Checklist de relecture d'un cas avant de l'ajouter au contenu :

- les faits sont synthétiques et originaux, sans extrait de manuel protégé ;
- chaque question a au moins un critère et les poids somment à 1.0 ;
- chaque nombre attendu figure dans `allowed_numbers` ;
- la réponse modèle est originale et ne révèle rien avant la soumission ;
- aucune donnée personnelle ou entreprise réelle identifiable n'est présente.

## 6. Notes de cours et citations

```bash
.venv/bin/python nage.py vc notes ingest cours_vc.md --topic VC04
.venv/bin/python nage.py vc notes list
.venv/bin/python nage.py vc notes approve <proposal_id>
.venv/bin/python nage.py vc notes approve <proposal_id> --answer "Réponse rédigée"
.venv/bin/python nage.py vc notes reject <proposal_id>
```

### Formats acceptés

- `.txt` et `.md`/`.markdown` en UTF-8 ;
- `.pdf` contenant du texte extractible via `pypdf` ;
- limite de **2 Mo** par fichier. Les erreurs sont lisibles et ne recopient jamais le
  contenu des notes.

Un PDF scanné sans couche texte est refusé avec un message explicite : il faut fournir une
version texte ou passer le document par un OCR avant l'import.

### Motifs extraits

L'import ne devine rien : une proposition n'est créée que si la réponse figure déjà dans la
note. Les motifs reconnus sont :

```text
Post-money : valorisation après l'entrée du cash.
**Pre-money** : valorisation avant l'entrée du cash.
Liquidation preference — montant récupéré avant les fondateurs.
Q: Qu'est-ce qu'un SAFE ?
R: Un contrat convertible qui donne droit à des actions.
- L'investisseur récupère sa **liquidation preference** avant les fondateurs.
```

Les puces utilisent le titre de section pour transformer le terme en clé à compléter. Sans
titre de section identifiable, la proposition est marquée `a_completer` et ne peut pas être
approuvée sans réponse explicite.

### Citations et approbation

Chaque proposition porte une citation exacte :

```json
{
  "source_id": "sha256 de la source",
  "locator": "ligne 12 ou p. 3, lignes 4-5",
  "quote": "texte exact de la note"
}
```

- Rien n'est actif avant `vc notes approve` : le deck reste vide et la carte n'apparaît pas
  dans `vc review`.
- Une proposition `a_completer` exige `--answer` ; sans réponse, la commande renvoie le
  code 2.
- `vc notes reject` mémorise une signature persistante : la même question n'est plus
  reproposée lors d'un import ultérieur.
- Les doublons sont comptés et ignorés, y compris les doublons internes à un même fichier.
- Un import approuvé ajoute une carte `source_type: user_note` à `deck.json` ; elle est
  fusionnée dans les sessions de rappel sans modifier le contenu livré.
- Un export de progression ne contient jamais le texte brut des notes, seulement les cartes
  approuvées et leurs citations.

### Source modifiée

Le hash SHA-256 de la source est conservé. Si le même nom de fichier est réimporté avec un
contenu différent, l'import est refusé pour éviter un mélange silencieux :

```bash
.venv/bin/python nage.py vc notes ingest cours_vc.md --topic VC04 --replace
```

`--replace` marque l'ancienne source `superseded`, supprime sa copie locale et ses
propositions encore en attente, puis réimporte le nouveau contenu.

### Stockage local

```text
~/.nage/vc/notes/index.json          sources, propositions, rejets
~/.nage/vc/notes/<source_id>.txt     copie locale privée de la note
~/.nage/vc/deck.json                 cartes approuvées
```

Les fichiers sont créés en `600` et les dossiers en `700`. Le texte des notes reste hors du
dépôt Git et n'est jamais inclus dans un message d'erreur.

## 7. Examen blanc et oral

```bash
.venv/bin/python nage.py vc exam start --questions 20 --minutes 30 --seed 7
.venv/bin/python nage.py vc exam submit <exam_id> --answers reponses.json
.venv/bin/python nage.py vc oral VC07 --count 5
```

- `exam start` compose un examen déterministe à partir de la banque originale : QCM,
  calculs numériques et questions ouvertes. Les points somment toujours à 100.
- Relancer `exam start` reprend l'examen actif. `--new` remplace explicitement l'examen
  en cours.
- `--topic VC04` (répétable) limite la composition à un ou plusieurs topics.
- Le chronomètre part de `started_at`. À l'échéance, les réponses déjà saisies sont
  conservées et l'examen est noté avec le statut `expired`.
- `reponses.json` associe l'identifiant de chaque question à une réponse texte :

```json
{
  "VC04-E001": "15 M€",
  "VC04-E003": "B",
  "VC04-E005": "Le pre-money fixe la valeur avant le cash, le post-money ajoute l'investissement."
}
```

- La correction affiche le score global, le score par topic, les topics faibles et une
  séance de rattrapage avec cartes, drills et cas. Le score est recalculable depuis les
  réponses et les points stockés.
- Les QCM acceptent la lettre (`A`, `B`, `C`, `D`) ou le texte exact du choix. Les réponses
  numériques acceptent une unité explicite (`15 M€`, `15 000 k€`, `33,33 %`, `3x`).
- Les questions ouvertes sont évaluées par mots-clés attendus, jamais par une IA distante.
- `vc oral` propose des questions et des relances ciblées. La réponse modèle et
  l'explication de la carte ne sont jamais affichées : l'oral sert à s'entraîner, pas à lire
  le corrigé.
- L'historique est écrit dans `exams/history.jsonl` et alimente le radar, le plan et le
  rapport. L'examen actif est stocké dans `exams/active.json` et supprimé après soumission.

## 8. Radar, plan et rapport

```bash
.venv/bin/python nage.py vc radar --today 2026-11-02
.venv/bin/python nage.py vc plan --minutes 30 --exam-date 2026-11-15
.venv/bin/python nage.py vc report --days 30
```

- Le radar indique les topics non testés, fragiles, en progression ou solides.
- Le plan respecte strictement la capacité en minutes et cite la raison de chaque activité.
- Si `--exam-date` est absent, le plan utilise la date enregistrée dans `settings.json`.
- Le rapport calcule couverture, rétention à 1/7/30 jours, cartes dues et prochaines actions.
  Chaque nombre peut être recalculé depuis les événements locaux.
- Pour lire la préparation d'examen : une couverture faible signale les topics jamais testés,
  une rétention 7 j basse signale les notions oubliées, et les prochaines actions donnent le
  temps à investir par activité.

## 9. Lexique et term sheet

```bash
.venv/bin/python nage.py vc glossary search "liquidation preference"
.venv/bin/python nage.py vc term-sheet decode term_sheet.txt
```

Le lexique est bilingue FR/EN et insensible aux accents. Le décodeur de term sheet reconnaît
les clauses documentées et explique leur effet économique ; une clause inconnue est listée
dans `unknown_clauses` et marquée `non documenté` plutôt que devinée.

## 10. Suppression des données VC

```bash
.venv/bin/python nage.py vc delete --confirm "SUPPRIMER MES DONNEES VC"
```

Une phrase incorrecte renvoie le code 2 et ne supprime rien. La commande ne touche jamais aux
données Career ni au reste du dépôt.

## 11. Tests et qualité

```bash
.venv/bin/python -m pytest -q tests/test_vc_*.py
.venv/bin/python -m ruff check academics/vc nage.py tests/test_vc_*.py
```

La recette du MVP P1 et P2 couvre le stockage, le scheduler, les drills, les cas, l'import
de notes citées avec approbation, l'examen blanc chronométré, l'oral, le radar, le plan, le
rapport, le lexique, le term sheet et le parcours CLI complet.

## 12. Périmètre livré et limites

Livré et prouvé :

- US1 rappel actif quotidien ;
- US2 drills de formules avec diagnostic ;
- US3 cas chiffrés avec grille de critères ;
- US4 examen blanc chronométré, notation multi-format, topics faibles et oral simulé ;
- US5 radar et plan de révision ;
- US6 ingestion de notes de cours avec citations exactes, approbation explicite et rejet
  persistant ;
- US7 lexique et décodeur de term sheet ;
- US8 rapport de progression.

Non encore livré :

- façade HTTP et page statique ;
- extension du contenu aux objectifs 200 cartes, 100 drills, 20 cas, 100 questions et
  120 termes.

Le MVP reste utilisable en l'état avec 20 topics, 50 cartes, 24 drills, 4 cas, 20 questions
d'examen et 42 termes.
