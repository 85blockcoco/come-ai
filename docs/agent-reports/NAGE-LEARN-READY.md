# NAGE-LEARN — rapport de lot backend

## Livraison

- Branche : `agent/nage-learn-pipeline`
- Commits de livraison précédents : `ecc11507f9489e3130ce93d1507ad510de03605b` (pipeline) et `4c0d18efb05fc98dc9e8fef9dcac29ae3b8b77ff` (canonicalisation des notions) ; le SHA final de cette branche est transmis dans le handoff.
- Périmètre : `career/**` (pipeline hors ligne) et intégration minimale du routeur dans `come_ai_web.py`.
- Aucun PDF, classeur, document personnel ou corpus privé n’est ajouté à Git.

## Fonctionnalités livrées

1. `career/ingest.py` : extraction PDF locale avec pages/sections, hash de source, manifeste et index lexical/vectoriel SQLite local. Les miroirs texte page-marqués `.pdf.txt` du corpus autorisé sont acceptés sans recopier les documents.
2. `career/tutor.py` : tutorat sourcé (explication, reformulation, exemple, débutant, pas-à-pas, « je n’ai pas compris ») ; refus explicite si aucune preuve locale suffisante ; citations fichier/page/section/extrait.
3. `career/summary.py` : fiches définitions/formules/points clés avec export PDF local.
4. `career/srs.py` : flashcards locales et ordonnancement SM-2.
5. `career/quiz.py` : questions déterministes issues des extraits, difficulté progressive, correction immédiate, maîtrise par notion et points faibles.
6. `career/plan.py` : plan jour par jour priorisant les chapitres dont la maîtrise observée est insuffisante.
7. `career/exam.py` : verrou d’examen blanc à 80 %, timer, questions de consolidation finale et correction détaillée sourcée.
8. `career/learning_router.py` : routes d’ingestion, chapitres, recherche full-text, tuteur, fiches/PDF, SRS, quiz, dashboard, plan et examen sous `/career/...` et alias `/api/career/learning/...` lorsque compatible avec les routes Career existantes.

## Vérifications exécutées

```text
PYTHONPATH=. pytest -q tests/test_nage_learning.py  # 4 passed
ruff check career/ingest.py career/tutor.py career/summary.py career/srs.py career/quiz.py career/plan.py career/exam.py career/learning_router.py come_ai_web.py tests/test_nage_learning.py  # All checks passed
git diff --check  # clean
```

Contrôle local du corpus autorisé (hors dépôt) : 25 PDF et 1 480 pages extraits depuis les miroirs locaux `.pdf.txt`, 1 470 chunks, 2 410 990 caractères ; aucun accès réseau et aucun envoi cloud.

## Gaps connus / coordination UI

- Ce lot ne modifie pas `desktop_static/**` : navigation visuelle des chapitres, thème clair/sombre, responsive/ARIA, skeleton, focus clavier, feedback visuel et service worker offline restent à intégrer par le lot UI Codex.
- Les trois fichiers XLSX du corpus privé ne sont pas ingérés par ce pipeline PDF ; ils restent hors corpus tutoriel tant qu’un adaptateur source et une provenance par cellule ne sont pas spécifiés.
- La validation ci-dessus est ciblée ; elle ne constitue pas une validation de la suite complète ni une preuve de publication/merge.

## Suivi d’intégration — candidate `codex/nage-learning-integration-20261103`

Le lot est maintenant raccordé à l’expérience desktop et au corpus complet autorisé, sans copier les supports privés dans Git.

- `career/ingest.py` accepte les PDF et XLSX locaux (et leurs miroirs texte privés), avec provenance par page ou feuille. Le corpus contrôlé contient 28 sources : 25 PDF et 3 XLSX, 1 494 unités pages/feuilles, 1 492 passages indexés.
- Les chapitres `TOPIC 1` à `TOPIC 5` sont normalisés à partir des noms de fichiers, y compris lorsque l’extraction PDF ne répète que le titre de la diapositive. Le quiz et le SRS utilisent désormais le filtre de section sans exiger que le libellé apparaisse dans le texte.
- `desktop_static/**` expose `Réviser VC` : navigation par chapitre, fiche et export PDF, tuteur sourcé, recherche plein texte, quiz progressif, progression observée et plan des sessions. Le service worker met en cache uniquement les fiches `/career/summary/...`, jamais les données personnelles.

### Preuves rejouées le 2026-11-03

```text
pytest -q tests/test_nage_ingest.py tests/test_nage_learning.py tests/test_nage_learning_ui.py \
  tests/test_vc_http_user_flow.py tests/test_vc_ui.py tests/test_vc_*.py \
  tests/test_academics_routes.py tests/test_academics_integration.py tests/test_nage_cli.py
196 passed in 11.58s
ruff check ...  # All checks passed
node --check desktop_static/app.js  # OK
node --check desktop_static/sw.js   # OK
git diff --check                      # clean
```

Parcours navigateur réel vérifié sur `http://127.0.0.1:8765/app#learning` : fiche TOPIC 3, question de quiz puis correction, question tuteur « post-money » avec citations, et recherche « liquidation preference » avec résultats PDF/XLSX. Une ingestion fraîche a observé `28 documents / 1 494 pages-feuilles / 1 492 chunks`, dont `3` XLSX.

Gaps restants : la suite complète n’a pas été lancée, l’examen blanc reste volontairement verrouillé jusqu’à 80 % de maîtrise observée, et l’intégration dans `main` attend toujours une validation humaine explicite.
