# Banc réel du workspace — « devoir tutorial » (2026-10-20)

Validation du workspace Côme IA 5.0/Career contre un dossier réel de devoirs
(`~/Desktop/devoir tutorial/`) : 13 fichiers, 5 formats (xlsx, docx, pdf, pptx,
deux corrigés et deux rendus). Aucune donnée ne quitte le Mac ; aucun fichier
réel n'entre dans les fixtures ou le dépôt (règle « pas de données personnelles
réelles »).

## Résultats

| Fonction | Verdict | Détails |
|---|---|---|
| Démarrage du vrai workspace | **corrigé pendant le banc** | La base Career réelle est en schéma 7 (`quality_json`, livré par la mission 39 jamais fusionnée) alors que le code était en 6 : l'app refusait de démarrer (fail-closed correct). Correctif v7 re-appliqué depuis l'archive (`b95ca72` → commit `4a89ac6`). |
| Upload des formats pris en charge | ✅ | (Correction du compte-rendu initial : le « pptx accepté » venait d'un artefact d'analyse des réponses, pas de l'app.) Les formats hors liste reçoivent un refus honnête « Format non pris en charge. » et ne sont **pas** stockés ni listés — comportement vérifié de façon ciblée sur le `.pptx`. |
| Liste des fichiers | ✅ | Le `.pptx` était en réalité refusé à l'upload avec un message honnête : l'app est correcte, mon parsing du banc était faux (voir ligne du dessus). |
| Inspection orchestrée V5 | ✅ | `inspect_file` sur `Fund data 2026 (1).xlsx` (356 lignes × 10 colonnes, 1 feuille). |
| Analyse financière + rapport | ✅ | Plan `inspect → analyze → create_analysis_workbook` exécuté, écriture confirmée en `output/analyse_….xlsx` (5,9 Ko), fichier source intact. |
| Qualité d'analyse | ⚠️ | « 0 colonnes numériques » sur un classeur **transposé** (dates en colonne A, en-tête à la ligne 5) : l'en-tête par défaut passe à côté des données. Généraliser la détection d'en-tête/feuille transposée pour les devoirs réels. |
| Mémoire : indexation asynchrone | ✅ | docx de l'énoncé + PDF théorisé indexés par file persistante, reprise idempotente. |
| Mémoire : recherche citée | ✅ | Requêtes pluriels/multi-terms OK ; les zéros restants correspondent à des termes absents du corpus (vérifié un à un). |
| Mémoire : fuite de chemin | ✅ | `/api/v5/memory/storage` ne contient aucun chemin absolu. |
| Career sur la vraie base | ✅ | `/api/career/health` + `/api/career/jobs` (121 offres réelles locales) verts après le correctif v7. |
| Chat cloud non testé | n/a | `allow_cloud_context` jamais coché pendant le banc : aucune donnée de devoir n'a été transmise à un fournisseur. |

## Actions déroulées le jour même (tests verts)

1. **Analyse de classeurs transposés** ✅ commit `d29ea74` : quand l'analyse
   par défaut ne voit aucune colonne numérique (symptôme exact du banc),
   `read_table` cherche une ligne d'en-têtes plausible jusqu'à 10 lignes,
   reconstruit le tableau (conversion numérique uniquement sans perte) et
   ajoute « En-têtes détectés à la ligne N… ». Vérifié sur le vrai fichier
   du devoir : en-têtes ligne 5, 116 lignes, facteurs numériques analysés.
2. **Requêtes multi-termes FTS à repli OR** ✅ commit `db3483e` : zéro résultat
   strict multi-termes → tentative « au moins un terme » (termes tous cités,
   aucune injection FTS possible) + note « correspondance élargie », transmise
   par l'endpoint `/api/v5/memory/search`. Les requêtes à 0 du banc renvoient
   désormais des résultats explicites quand le corpus contient au moins un terme.

## Changements apportés par ce banc

- Commit `4a89ac6` : `SCHEMA_VERSION` 6→7 + migration `quality_json`
  (bases de données v7 opensafely → v6 d'applis plus anciennes toujours migrées).
- Lot d'amélioration direct (commits `d29ea74`, `db3483e`, 4 tests ajoutés,
  suite : 1137 passed à l'époque ; 1141 passed le soir, ruff zéro erreur).
- **Round 2 du banc (fin de journée, après tous les changements) : 6/6 vert**
  sur le vrai workspace — refus pptx propre, analyse transposée (3 colonnes
  numériques + note d'en-têtes), note « correspondance élargie » transmise,
  Career v7 en santé, formats annoncés sans pptx. Vérifié sur l'app réelle
  (`create_app` + TestClient), sans serveur, sans réseau sortant.
- Le banc a servi l'app réelle (uvicorn non lancé, TestClient create_app) :
  imports dans `data/`, rapport dans `output/`, index dans `memory_data/` —
  tous dossiers gitignorés ; rien n'a été committé de personnel.
