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
| Upload 12/12 | ✅ | Tous les formats présents importés (y compris `.pptx`). |
| Liste des fichiers | ⚠️ bug UX | Le `.pptx` est **accepté (200) puis invisible** : absent de `/api/files`. Soit le refuser à l'upload, soit l'extraction supportée. |
| Inspection orchestrée V5 | ✅ | `inspect_file` sur `Fund data 2026 (1).xlsx` (356 lignes × 10 colonnes, 1 feuille). |
| Analyse financière + rapport | ✅ | Plan `inspect → analyze → create_analysis_workbook` exécuté, écriture confirmée en `output/analyse_….xlsx` (5,9 Ko), fichier source intact. |
| Qualité d'analyse | ⚠️ | « 0 colonnes numériques » sur un classeur **transposé** (dates en colonne A, en-tête à la ligne 5) : l'en-tête par défaut passe à côté des données. Généraliser la détection d'en-tête/feuille transposée pour les devoirs réels. |
| Mémoire : indexation asynchrone | ✅ | docx de l'énoncé + PDF théorisé indexés par file persistante, reprise idempotente. |
| Mémoire : recherche citée | ✅ | Requêtes pluriels/multi-terms OK ; les zéros restants correspondent à des termes absents du corpus (vérifié un à un). |
| Mémoire : fuite de chemin | ✅ | `/api/v5/memory/storage` ne contient aucun chemin absolu. |
| Career sur la vraie base | ✅ | `/api/career/health` + `/api/career/jobs` (121 offres réelles locales) verts après le correctif v7. |
| Chat cloud non testé | n/a | `allow_cloud_context` jamais coché pendant le banc : aucune donnée de devoir n'a été transmise à un fournisseur. |

## Actions à dérouler (prochaine lotifié)

1. **`.pptx`** : refuser proprement à l'upload OU ajouter l'extracteur texte
   (bilingue : préférer refuser avec message honnête tant que l'extract n'existe pas).
2. **Analyse de classeurs transposés** : essayer plusieurs lignes d'en-tête,
   détecter « première ligne d'entêtes réelle » (colonne `datetime` + messages
   numériques dedans), ou exposer une option « données transposées ».
3. **Réessayer FTS avec repli OR** : quand une requête multi-termes renvoie 0,
   tenter un match affaibli et le signaler honnêtement (« correspondance élargie »).

## Changements apportés par ce banc

- Commit `4a89ac6` : `SCHEMA_VERSION` 6→7 + migration `quality_json`
  (bases de données v7 opensafely → v6 d'applis plus anciennes toujours migrées).
- Le banc a servi l'app réelle (uvicorn non lancé, TestClient create_app) :
  imports dans `data/`, rapport dans `output/`, index dans `memory_data/` —
  tous dossiers gitignorés ; rien n'a été committé de personnel.
