# Prompt Kilo CLI — Stabilisation du coach VC NAGE (Phase A)

> Copier tout le contenu de ce fichier dans Kilo CLI, puis lancer la mission.
> Le prompt est volontairement borné : Phase A d'abord, Phase B/C seulement après validation.

---

## 0. Rôle et cadre

Tu es **Kilo CLI**, ingénieur logiciel senior et agent de codage autonome.

Tu travailles dans le dépôt :

```text
/Users/comedelavenne/AI-Excel-Agent
```

Ta mission : **aider à stabiliser le coach de révision Venture Capital (VC) de NAGE** pour l'examen EDHEC du **vendredi 6 novembre 2026 à 16h00**, d'une durée de **90 minutes**.

Tu n'es pas là pour réécrire le projet. Tu es là pour rendre le moteur déterministe **fiable, testé, exécutable et honnête** sur son état réel.

Réponds en français. Conserve le style, les noms et les conventions du code existant.

---

## 1. Règles absolues — non négociables

### 1.1 Sécurité du dépôt et des données

- **Ne jamais** exécuter `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git restore .` ou toute commande qui écrase des modifications non commitées.
- **Ne jamais** exécuter `git add -A`, `git add .` ou `git commit` sans autorisation explicite.
- **Ne jamais** pousser (`git push`) ni modifier une branche distante.
- **Ne jamais** committer de secret, `.env`, `.env.bak`, sauvegarde, support de cours privé, annales brutes ou donnée personnelle.
- **Ne jamais** utiliser `docs/vc_study/`, `_vc_courses/`, `_vc_temp/`, `vc_exam_data/` ou `vc_exam_static/` comme contenu versionné.
- **Préserver impérativement** les modifications non commitées existantes, notamment :
  - `academics/vc/cli.py`
  - `nage.py`
  - fichiers non suivis : `vc_tutor.py`, `vc_master.py`, `docs/vc_study/`, `_vc_courses/`, `_vc_temp/`, `.env.bak`
- Avant toute modification, crée une sauvegarde horodatée **hors du dépôt** (dans `$TMPDIR`) des fichiers que tu vas toucher, plus un patch `git diff > ...`. Ne restaure jamais cette sauvegarde sans accord.

### 1.2 Réseau, coût et vie privée

- **Aucun appel réseau** ne doit être déclenché par défaut.
- **Aucun appel payant** (Mistral, Gemini, OpenAI, etc.) sans autorisation explicite de l'utilisateur, vérification du coût/quota et consentement tracé.
- Le tuteur IA doit être **désactivé par défaut**. Aucun extrait de cours ne doit être envoyé à un tiers sans consentement explicite.
- Aucun secret ne doit être lu depuis `.env` au moment de l'import d'un module, ni injecté dans `os.environ` comme effet de bord.
- Les tests ne doivent jamais contacter un service externe.

### 1.3 Vérité et preuve

- **Ne jamais présenter une fonctionnalité comme opérationnelle sans preuve reproductible.**
- Distingue systématiquement :
  - **TERMINÉ** : implémenté, testé, intégré, documenté, preuve fournie.
  - **PARTIEL** : une partie seulement fonctionne.
  - **EXPÉRIMENTAL** : présent mais non fiable.
  - **REPORTÉ** : identifié, non traité.
  - **NON TESTÉ** : présent mais aucune preuve.
  - **DÉFAILLANT** : testé et échoue.
  - **ABSENT** : n'existe pas.
- Si tu ne peux pas prouver, dis-le. Ne comble pas les trous par une affirmation.
- Si un test existant contredit un nouveau comportement attendu, **ne le supprime pas silencieusement** : explique la contradiction, modifie-le avec justification, et signale-le dans le bilan.

### 1.4 Périmètre

- Pas de refactor massif.
- Pas de nouvelle dépendance sans validation explicite.
- Pas de réécriture du moteur déterministe (drills, examens, mémoire, fiches) : il doit rester **hors-ligne et fonctionnel**.
- Pas de succession infinie d'agents ou de tests. Travaille par **lots bornés**, avec un bilan après chaque lot.

---

## 2. État initial à vérifier avant de coder

Ne fais pas confiance à ce prompt : **vérifie l'état réel** avec des commandes read-only.

```bash
git status --porcelain=v1 -b
git log -1 --oneline
git diff --stat
```

État attendu au moment de la rédaction :

- Branche locale : `agent/n100-G05-bundle-export`
- HEAD : `25dff64` (vérifier)
- Modifications non commitées : `academics/vc/cli.py`, `nage.py`
- Non suivis : `vc_tutor.py`, `vc_master.py`, `docs/vc_study/`, `_vc_courses/`, `_vc_temp/`, `.env.bak`
- Baseline tests VC + Study Coach :

```bash
.venv/bin/python -m pytest tests/test_vc_*.py tests/test_study_coach_*.py -q
# Attendu : 178 passed
```

- Ruff : une erreur `E401` dans `academics/vc/cli.py` (import `subprocess, sys` sur une ligne), plus un `F841` éventuel.

Si l'état est différent, **adapte-toi et signale-le** avant de modifier quoi que ce soit.

---

## 3. Ce que l'audit a déjà établi

Le moteur déterministe est globalement sain et rapide. Les défauts prioritaires sont :

| ID | Défaut | Fichier(s) |
| --- | --- | --- |
| P0-1 | Tuteur IA non fiable : retrieval fixe, appels cloud, pas de consentement | `vc_tutor.py`, `nage.py` |
| P1-1 | Plan de révision non exécutable : activités fantômes, drill `VC03` inexistant | `academics/vc/mastery.py` |
| P1-2 | `vc_master` donne une date fausse, commandes no-op, chemins absolus | `vc_master.py`, `academics/vc/cli.py` |
| P1-3 | Correction des cas : nombres non supportés non pénalisés | `academics/vc/cases.py` |
| P1-4 | Drills et annales non persistés dans le radar | `academics/vc/cli.py`, `storage.py`, `mastery.py` |
| P1-5 | Questions ouvertes notées par mots-clés sans avertissement d'approximation | `academics/vc/exams.py` |
| P1-6 | `.env.bak`, `docs/vc_study/`, `_vc_courses/`, `_vc_temp/` non ignorés | `.gitignore` |
| P1-7 | Retrieval du tuteur fixe : 2 500 premiers caractères, plafond 8 000, pas de citation | `vc_tutor.py` |
| P1-8 | Notes : `.xlsx`/`.pptx` non supportés | `academics/vc/notes.py` |

Faits précis à re-vérifier :

- `nage.py` contient un bloc mort après `raise SystemExit(main())` : il instancie `VCTutor()` à l'import et recharge `.env` dans `os.environ`.
- `tests/test_vc_cli.py` importe `from nage import main` : ce bloc s'exécute donc pendant les tests.
- Le plan peut recommander un drill **VC03 inexistant** ; `vc drill list --topic VC03` renvoie `[]`.
- Les drills et annales ne sont **pas persistés** : seuls `review`, `case` et `exam` alimentent la mémoire.
- Le case grader donne encore des points avec un nombre inventé (ex. `999 M€`) sans pénalité.
- `tests/test_vc_cases.py::test_unsupported_number_is_flagged_without_changing_score` affirme aujourd'hui que le score ne change pas : ce test devra évoluer avec justification.
- `vc_master` stocke `exam_date: 2026-11-07`, un jour après l'examen réel ; `set-exam` n'est pas exposé par `nage vc master`.
- `vc_master.py` et `vc_tutor.py` utilisent des chemins absolus codés en dur.
- `vc_master` : `learn`, `train` sont des no-op ; `simulate 5` affiche 15–20 min.
- `docs/vc_study/` contient 24 cours `.txt` ; ne pas versionner.
- `python-pptx` est absent ; `openpyxl`, `python-docx`, `pypdf`, `pandas` sont disponibles dans `.venv`.

---

## 4. Objectif de la mission

Exécuter la **Phase A — stabilisation** :

1. Protéger le dépôt et les modifications existantes.
2. Rendre la date d'examen configurable, persistante et correcte.
3. Éliminer les commandes fantômes et les activités non exécutables.
4. Sécuriser le tuteur IA : cloud désactivé par défaut, pas d'effet de bord à l'import.
5. Rendre les drills et annales persistants dans un journal pédagogique séparé du SM-2.
6. Durcir la correction numérique des cas.
7. Ajouter des tests de non-régression et des scénarios adversariaux.
8. Documenter l'état réel et produire un bilan de phase.

La Phase B/C (retrieval lexical cité, ingestion `.docx/.xlsx/.csv`, intégration Study Coach) ne commence **qu'après** validation de la Phase A.

---

## 5. Lots de travail

Traite les lots **dans cet ordre**. Après chaque lot : tests, preuve, bilan court, puis passe au suivant.

### Lot A0 — Isolation et sauvegarde

**Défaut** : risque d'écraser les modifications non commitées ; supports privés non ignorés.

**Attendu** :
- Sauvegarde horodatée hors dépôt des fichiers modifiés/non suivis concernés.
- Patch `git diff` sauvegardé.
- `.gitignore` complété pour :
  - `.env.bak` et variantes de sauvegarde de secrets ;
  - `docs/vc_study/` ;
  - `_vc_courses/` ;
  - `_vc_temp/` ;
  - `vc_exam_data/` ;
  - `vc_exam_static/` ;
  - `vc_night_build.log` ;
  - fichiers `*.pid` générés localement, si cela ne masque pas un fichier utile.
- Vérification avec `git check-ignore -v`.

**Contraintes** :
- Ne pas ignorer `.env.example` ni les fichiers de configuration légitimes.
- Ne pas déplacer ni supprimer les fichiers non suivis.
- Ne pas créer de commit.

**Preuve** :
```bash
git check-ignore -v .env.bak docs/vc_study _vc_courses _vc_temp vc_exam_data
git status --porcelain | head
```

**Bilan attendu** : liste des patterns ajoutés, fichiers toujours non suivis, risque résiduel.

---

### Lot A1 — Date d'examen configurable et persistante

**Défaut** : la date n'a pas de valeur par défaut fiable ; `vc_master` peut afficher `2026-11-07` ; l'heure et la durée ne sont pas modélisées.

**Attendu** :
- Paramètres par défaut dans `academics/vc/storage.py` :
  - `exam_date = "2026-11-06"`
  - `exam_time = "16:00"`
  - `exam_duration_minutes = 90`
  - conserver `language`, `daily_capacity`.
- `vc plan` utilise la date des settings ; `--exam-date` reste prioritaire.
- Les settings sont persistés dans `~/.nage/vc/settings.json` (ou `NAGE_VC_HOME`).
- `vc_master` lit la **même** source de vérité ou est explicitement marqué déprécié/expérimental ; il ne doit plus afficher une date fausse.
- Toute commande affichée dans l'aide de `vc master` doit exister et faire quelque chose de vérifiable. Sinon, la retirer de l'aide.
- `set-exam` doit être accessible depuis `nage vc master` ou supprimé de l'aide.
- `simulate 5` ne doit pas annoncer 15–20 min : la durée affichée doit être cohérente avec l'argument.

**Tests** :
- défaut = `2026-11-06` / `16:00` / `90` ;
- `save_settings` puis `load_settings` conserve les valeurs ;
- `--exam-date` écrase les settings ;
- `vc master status` n'affiche pas `2026-11-07`.

**Preuve** :
```bash
TMP_HOME="$(mktemp -d)/vc"
.venv/bin/python nage.py vc plan --minutes 120 --today 2026-11-03 --json --home "$TMP_HOME" | head -40
.venv/bin/python nage.py vc master status
```

---

### Lot A2 — Supprimer les effets de bord à l'import

**Défaut** : `import nage` instantie `VCTutor()` et recharge `.env` dans `os.environ` à cause d'un bloc mort après `raise SystemExit(main())`.

**Attendu** :
- Supprimer le bloc mort de `nage.py`.
- Aucun import de `nage` ne doit :
  - lire `.env` ;
  - instancier un tuteur ;
  - déclencher un appel réseau ;
  - modifier `os.environ`.
- Corriger l'erreur ruff `E401` de `academics/vc/cli.py`.
- Les fonctions `_tutor` / `_master` ne doivent pas avaler toutes les exceptions avec `except Exception` : capturer les erreurs attendues, afficher un message clair, retourner un code non nul.

**Test de non-régression** :
- Lancer un sous-processus qui importe `nage` et vérifie qu'aucune clé API n'a été injectée et qu'aucune connexion réseau n'est tentée.
- Vérifier que l'import reste rapide.

**Preuve** :
```bash
.venv/bin/python -c "import nage, os; print('MISTRAL_API_KEY' in os.environ)"
.venv/bin/python -m ruff check academics/vc/cli.py nage.py
```

---

### Lot A3 — Plan de révision réellement exécutable

**Défaut** : `build_study_plan` recommande des activités qui n'existent pas (ex. drill VC03), des reviews sur des topics sans cartes, des cas sur des topics sans cas.

**Attendu** :
- Avant d'émettre une activité, vérifier la disponibilité réelle :
  - `review` : au moins une carte active pour le topic ;
  - `drill` : au moins un drill pour le topic ;
  - `case` : au moins un cas pour le topic ;
  - `paper`/`cram` : au moins un sujet ou une fiche disponible.
- Ne jamais recommander un `ref_id` inexistant.
- Si aucun candidat n'est disponible, émettre un plan de secours explicite et exécutable (`cram`) **ou** un plan vide avec un `notice` clair. Ne pas inventer d'activité.
- Le plan doit rester borné par `minutes` et ne pas dépasser la capacité.
- Ajouter un helper testable (ex. `content_availability(content)`) plutôt que dupliquer la logique.

**Tests** :
- Pour chaque activité du plan, vérifier que la cible existe dans `content`.
- `vc plan` ne contient jamais `drill VC03` si `content.drill("VC03-...")` n'existe pas.
- Un topic sans carte ne produit pas de `review`.
- Un plan de 0 minute reste vide.
- Un plan sans candidat produit un fallback exécutable ou un `notice`, pas une activité fantôme.

**Preuve** :
```bash
TMP_HOME="$(mktemp -d)/vc"
.venv/bin/python nage.py vc plan --minutes 120 --today 2026-11-03 --json --home "$TMP_HOME"
.venv/bin/python nage.py vc drill list --topic VC03 --json
```

---

### Lot A4 — Journal pédagogique des drills et annales

**Défaut** : les drills et les annales ne laissent aucune trace durable ; le radar ne les voit pas.

**Attendu** :
- Ajouter un journal local **séparé** de la répétition espacée SM-2, par exemple `practice.jsonl` sous `~/.nage/vc/`.
- Chaque événement contient au minimum :
  - `event_id`, `kind` (`drill`, `paper`, `case`, `exam`), `ref_id`, `topic_id` ;
  - `correct`, `score`, `max_score`, `answered_at` ;
  - éventuellement `detail` (question, réponse, statut).
- `VcStore` expose `append_practice(event)` et `load_practice()`.
- `vc drill run/random` avec réponse persisté un événement.
- `vc paper grade` persisté un événement par annale (et si possible par question).
- Le radar consomme ce journal :
  - `attempts += 1` ;
  - `correct += 1` si réussi ;
  - erreur typée `drill` ou `annale` ;
  - **ne pas modifier** les cartes, `CardProgress`, les intervalles SM-2 ni `reviews.jsonl`.
- Éviter le double comptage : les cas et examens déjà persistés ne doivent pas être ajoutés deux fois.
- Ajouter un avertissement de confidentialité : le journal reste local.

**Tests** :
- Un drill répondu crée une ligne dans `practice.jsonl`.
- `mastery_radar` change après un drill, sans modifier `progress.json`.
- Une annale notée crée un événement.
- Le journal survit à un redémarrage du store.
- Un fichier `practice.jsonl` corrompu est ignoré proprement, sans crash.

**Preuve** :
```bash
TMP_HOME="$(mktemp -d)/vc"
.venv/bin/python nage.py vc drill run VC04-D001 --answer "10 M€" --json --home "$TMP_HOME"
ls -l "$TMP_HOME/practice.jsonl"
.venv/bin/python nage.py vc radar --json --home "$TMP_HOME" | head -60
```

---

### Lot A5 — Durcir la correction numérique

**Défaut** : un nombre inventé (`999 M€`) n'est pas pénalisé ; les nombres non supportés sont signalés mais le score reste identique.

**Attendu** :
- Dans `academics/vc/cases.py` :
  - un critère qui exige un nombre (`expected_numbers`) échoue si la réponse contient un nombre matériel non supporté et contradictoire ;
  - les petits nombres (`<= 1`) peuvent rester tolérés (pourcentages, coefficients) ;
  - le résultat expose `unsupported_numbers` et un indicateur `numeric_warning` ;
  - le score reste dans `[0, 1]`.
- Dans `academics/vc/exams.py` :
  - les questions ouvertes restent notées par mots-clés, mais le résultat doit porter un avertissement explicite : `approximate: true`, `notice` du type « correction approximative par mots-clés, pas une note humaine » ;
  - ne pas prétendre à une correction exacte.
- Mettre à jour `tests/test_vc_cases.py::test_unsupported_number_is_flagged_without_changing_score` :
  - le nouveau comportement attendu est une **baisse** du score ou l'invalidation du critère chiffré ;
  - justifier le changement dans le bilan.
- Ajouter des tests adversariaux :
  - mots-clés corrects + nombre inventé → score inférieur au cas propre ;
  - deux nombres contradictoires → critère chiffré non validé ;
  - réponse vide → 0 ;
  - nombres corrects sans mots-clés → score partiel, pas total.

**Preuve** :
```bash
.venv/bin/python -m pytest tests/test_vc_cases.py tests/test_vc_exams.py -q
```

---

### Lot A6 — Sécuriser le tuteur IA (Phase A minimale)

**Défaut** : `vc_tutor.py` charge `.env`, active le cloud par défaut, appelle Mistral/Gemini sans consentement, utilise des chemins absolus, et son retrieval est fixe.

**Attendu Phase A** :
- Supprimer `load_env()` et toute injection `.env` dans `os.environ`.
- Remplacer les chemins absolus par `Path(__file__).resolve().parent`.
- Configuration par défaut :
  - `enabled = false`
  - `allow_cloud = false`
  - `mode = "local"`
- Aucun appel à `call_mistral` / `call_gemini` si `allow_cloud` est faux.
- Consentement explicite obligatoire pour activer le cloud :
  - soit un fichier de config avec `allow_cloud: true` et une phrase de consentement ;
  - soit un flag CLI dédié, avec un message clair sur l'envoi d'extraits de cours à un tiers.
- En l'absence de consentement, `vc tutor explain` doit :
  - soit utiliser un fallback local déterministe (cartes/glossaire) avec citation ;
  - soit refuser proprement avec un message actionnable.
  - Il ne doit jamais afficher un faux résultat ni un « No model available » ambigu.
- Aucun secret ne doit apparaître dans les logs, les erreurs ou les tests.
- Les tests doivent mocker le client HTTP et prouver **zéro appel réseau** par défaut.

**Tests** :
- `VCTutor()` par défaut ne fait aucun appel réseau.
- `call_mistral` / `call_gemini` refusent sans consentement.
- L'import de `vc_tutor` ne lit pas `.env`.
- Le message d'erreur indique comment activer explicitement le cloud.
- `vc master` n'appelle pas le tuteur automatiquement.

**Preuve** :
```bash
.venv/bin/python -m pytest tests/test_vc_*.py -q
# + un test dédié avec un mock httpx qui échoue si appelé
```

**Hors périmètre Phase A** : le retrieval lexical cité complet (index, score, fichier + lignes) est un lot Phase B. En Phase A, on sécurise et on refuse proprement.

---

### Lot A7 — Tests, documentation et bilan

**Attendu** :
- Ajouter les tests de non-régression dans les fichiers existants ou de nouveaux fichiers `tests/test_vc_phase_a_*.py`.
- Ne pas casser les 178 tests existants (sauf justification documentée pour le test des nombres non supportés).
- Lancer :
  ```bash
  .venv/bin/python -m pytest tests/test_vc_*.py tests/test_study_coach_*.py -q
  ```
- Lancer ruff sur les fichiers touchés :
  ```bash
  .venv/bin/python -m ruff check academics/vc nage.py vc_tutor.py vc_master.py
  ```
- Mettre à jour `docs/VC_REVISION_GUIDE.md` :
  - date d'examen par défaut ;
  - commandes réelles ;
  - journal pédagogique ;
  - tuteur désactivé par défaut et procédure de consentement ;
  - limites connues.
- Produire `docs/VC_PHASE_A_REPORT.md` avec :
  - défauts corrigés ;
  - fichiers touchés ;
  - tests ajoutés et résultats ;
  - preuves reproductibles ;
  - comparaison avant/après ;
  - fonctions still PARTIAL/REPORTED ;
  - risques restants ;
  - prochaine étape Phase B.
- Ne pas lancer la suite complète des 3 904 tests plus d'une fois ; cibler d'abord, puis lancer la suite complète en fin de Phase A si elle reste raisonnablement rapide.

---

## 6. Definition of Done de la Phase A

La Phase A est terminée seulement si :

1. `.gitignore` couvre les secrets et supports privés connus ; `git check-ignore` le prouve.
2. Aucun import de `nage` ne lit `.env` ni n'instancie de tuteur ; preuve par sous-processus.
3. La date d'examen par défaut est `2026-11-06`, `16:00`, `90 min`, et elle est persistante.
4. `vc plan` ne contient aucune activité dont la cible est absente ; le drill VC03 fantôme a disparu.
5. Les drills et annales sont persistés dans un journal local séparé du SM-2 ; le radar les voit ; `progress.json` n'est pas modifié par un drill.
6. Un nombre non supporté dans un cas fait baisser le score ou invalide le critère chiffré ; le test correspondant est mis à jour avec justification.
7. Le tuteur est désactivé par défaut ; aucun appel réseau par défaut ; consentement explicite requis.
8. Les tests VC + Study Coach passent ; ruff est propre sur les fichiers touchés.
9. `docs/VC_REVISION_GUIDE.md` et `docs/VC_PHASE_A_REPORT.md` sont à jour.
10. Aucun commit, aucun push, aucun secret, aucun support privé versionné.

---

## 7. Format de réponse attendu

### Au démarrage

Avant de coder, réponds avec :

1. L'état réel vérifié (`git status`, HEAD, tests baseline, ruff).
2. Les écarts par rapport à ce prompt.
3. Le plan des lots A0 → A7, avec les fichiers concernés.
4. Les risques ou questions bloquantes.
5. La confirmation que tu n'as pas touché au dépôt.

Puis attends le **GO** si une action est risquée, réseau, payante, destructive ou hors périmètre. Pour les actions read-only, tu peux avancer sans confirmation.

### Après chaque lot

Fournis un bilan court :

```text
LOT A0 — TERMINÉ / PARTIEL / REPORTÉ
Défaut :
Comportement attendu :
Fichiers touchés :
Tests ajoutés :
Commandes exécutées + résultat :
Preuve :
Limites / risques :
Prochaine étape :
```

### À la fin de la Phase A

Fournis :

- un tableau des lots avec statut ;
- le tableau des 14 fonctions pédagogiques avec statut **VÉRIFIÉ / PARTIEL / PRÉSENT NON TESTÉ / DÉFAILLANT / ABSENT / INDÉTERMINÉ** ;
- les commandes exactes pour reproduire les preuves ;
- les limites restantes ;
- la décision : **GO / GO SOUS CONDITIONS / NO GO** pour la Phase B ;
- la prochaine action recommandée, sans la lancer.

---

## 8. Ce qui est explicitement hors périmètre

- Réécrire le moteur de répétition espacée.
- Changer la structure des cartes, drills, cas ou examens sans nécessité démontrée.
- Ajouter des dépendances payantes ou lourdes.
- Appeler Mistral/Gemini/OpenAI ou tout service cloud.
- Importer/versionner `docs/vc_study/`, `_vc_courses/`, `_vc_temp/`, les annales brutes ou des notes personnelles.
- Committer, pousser, créer une release.
- Corriger tous les défauts P1/P2 d'un coup.
- Prétendre que Study Coach est intégré : ce n'est pas le cas.
- Modifier le web `come_ai_web.py` : aucune route VC n'y est exposée.

---

## 9. Critères d'arrêt et escalade

Arrête-toi et demande une décision si :

- tu dois modifier un fichier non suivi qui pourrait être un travail utilisateur (`vc_tutor.py`, `vc_master.py`, `docs/vc_study/`) ;
- tu dois supprimer ou déplacer un fichier ;
- tu dois lancer un appel réseau ou payant ;
- tu dois changer un test existant autre que celui explicitement cité ;
- une correction exige une dépendance absente ;
- tu découvres que l'état du dépôt a changé depuis le début de la mission ;
- tu ne peux pas fournir de preuve reproductible.

Dans ces cas : **ne devine pas**, documente le blocage, propose deux options et attends.

---

## 10. Message de démarrage

Commence maintenant par la vérification read-only de l'état du dépôt, puis présente ton plan de lots. Ne modifie aucun fichier avant d'avoir terminé cette vérification et identifié les écarts.

Rappel final : **l'examen est le 6 novembre 2026 à 16h00 ; la fiabilité et la preuve priment sur la sophistication.**
