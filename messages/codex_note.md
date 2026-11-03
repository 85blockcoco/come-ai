# RAPPORT CODEX — 2026-10-27 21:25 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| `eff542c` | Préserve les pages d’un CV texte court et les preuves temporelles/provenances lors de la déduplication | `career/service.py`, `career/exploration_service.py`, 2 tests | gate officiel : **6 437 passed, 12 skipped, 0 failed** | **466,46 s** suite complète |
| `741b9ba` | Priorise BBA/Bachelor/Bac+4 sans masquer M2/MBA | Career backend, interface Career et tests | inclus dans la campagne complète | inclus ci-dessous |
| `94dd041` | Sélecteur persistant NAGE Terminal / NAGE Studio et thème professionnel clair | desktop et test UI | inclus dans la campagne complète | inclus ci-dessous |
| `48ca9eb` | Parcours candidature en trois interactions, sans envoi automatique | Career, desktop, rapport P0 | inclus dans la campagne complète | inclus ci-dessous |
| `2a00644` + `f7682ed` | Alignement isolé avec `origin/main`, puis réintégration du P0 et de NAGE Studio | candidate consolidée | inclus dans la campagne complète | inclus ci-dessous |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---|---|---|
| Candidate isolée alignée sur `origin/main` | 100 % techniquement | alignement, corrections et campagne complète | publication et vérification SHA | aucun; `main` reste intacte |
| P0 candidature en trois interactions | 100 % du scénario synthétique défini | HTTP, navigateur, persistance et tests | recette employeur réelle volontairement exclue | aucune soumission automatique autorisée |
| Priorité d’études BBA/Bac+4 | 100 % | classement backend/client + libellés + tests | terminé | M2/MBA restent visibles |
| Édition CV NAGE | 100 % du périmètre local | génération, modification, sauvegarde, revue invalidée et export | terminé | validation humaine requise avant usage externe |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` | 9 990 ms, ancien serveur partagé du 26/10 | **11,646 ms à froid; 10,916 et 8,359 ms à chaud** | `curl` sur serveur Uvicorn isolé, base synthétique vide, port 18929, 27/10 à 21:09 CET |
| Routes applicatives locales | non apparié | `/app` 7,517 ms; `/career` 4,960 ms; HTTP 200 | même serveur isolé |
| Campagne complète actuelle | précédent passage : 6 435 passed, 2 failed, 12 skipped | **6 437 passed, 0 failed, 12 skipped** | gate officiel monolithique, 6 449 cas collectés, 466,46 s |

## 4. État 24 h de ta prod
- commits aujourd’hui avant la mise à jour de ce rapport : 10.
- diff candidate contre `origin/main` après `eff542c` : 154 fichiers, 20 240 ajouts, 397 suppressions (`git diff --shortstat origin/main...HEAD`).
- ascendance : `origin/main...HEAD` = `0 109`; la candidate contient donc le `main` distant observé, sans le modifier.
- tests verts : fichiers racine `744 + 2 095 + 1 266 + 2 206`, contrats/intégration `26`, évaluations `100` = **6 437 passed**. Les **12 skips** sont 9 contrôles connecteurs live désactivés, 2 contrôles géographiques live désactivés et 1 exhaustivité sans script/base disponible.
- gate officiel `scripts/career_release_gate.py` : **PASS** au SHA `7611490`; worktree propre, `compileall`, 1 232 tests matching, 209 contrats de release, Ruff global et suite complète tous verts. Preuve locale : `artifacts/career-release-gate.json`.
- contrôles statiques : `ruff check career tests scripts/career_release_gate.py`, `git diff --check` verts.
- navigateur déjà validé sur la candidate : parcours P0, persistance du style NAGE Studio et zéro avertissement/erreur console après correction du script Constitution.

## 5. Ce que j’attends d’OpenCode
- Aucun travail requis pour cette livraison; éviter toute modification concurrente de la candidate pendant le push et la vérification distante.

## 6. Risques / blocages
- Le contrat de performance `< 3 s` est **PAS ATTEINT** sur `127.0.0.1:8765`: 3,378 s au test de référence obligatoire. Ce serveur vient du checkout partagé `agent/spec-033-translation-variants`, dont l'état local est concurrent; il n'a pas été modifié ni redémarré.
- La candidate isolée respecte le seuil dans le scénario mesuré (1 000 offres synthétiques, médiane 1,336 s), mais ce résultat ne remplace pas le test sur le serveur partagé et les environnements ne sont pas identiques.
- Au fetch de 2026-10-26 16:58 CET, `origin` expose SPEC-045 (`226dd78bd7a13f032435d240f7526acb476156f8`) et SPEC-047 (`5b35e8a9b7046fa364b6ed5c8edec5fc6bfbaa38`); SPEC-044 et SPEC-046 sont absentes. `worker/cvboost-81-1793029972324` pointe exactement sur `origin/main` (`2e52575e0011a14825559f3037a794a6659f5465`) et n'a aucun delta à intégrer.
- La branche SPEC-045 distante remplace les motivations à compléter par des affirmations non étayées et supprime les assertions de test correspondantes; la candidate conserve les formulations à compléter. Les fichiers `career/send_confirmation.py` et `tests/test_send_confirmation.py` de SPEC-047 sont identiques à ceux de la candidate. Le test ciblé combiné passe (55 tests). SPEC-047 fournit actuellement le backend; son flux UI n'est pas intégré ici.
- Le contrôle `git diff --check origin/main...HEAD` avait détecté six espaces finaux dans les retours forcés Markdown du rapport SPEC-SK02. Ils ont été remplacés par des retours forcés avec antislash, sans changer les mots; le diff complet après commit passe `git diff --check`.
- Pré-revue des consignes locales SPEC-044/046 : le candidat possède déjà `career/cv_variants.py`, `career/application_studio.py` et `career/document_export.py`, mais aucun `career/apply_kit.py`, `career/ats_guide.py` ni leurs routes. Je n'ai pas dupliqué le travail des agents dont les branches ne sont pas publiées. SPEC-044-E2E_METRICS demande des offres réelles locales; aucune offre réelle n'a été lue ni copiée, et cette évaluation n'a pas été exécutée.
- Le worktree non commité `/Users/comedelavenne/AI-Excel-Agent-worker-cvboost-84-1793029873023` ajoute une variante de SPEC-047 dans `career/router.py` et `career/service.py`, et un `career/send_confirmation.py`. Elle fixe `approval_granted = 1` à la déclaration d'envoi et utilise `_LAST_SERVICE` global. La candidate exige l'approbation préalable et son test dédié plus le test exigeant un suivi existant passent (2/2, 3,14 s); la variante du worktree n'a pas été intégrée ni validée par Codex. Un pytest ciblé a été observé en cours dans ce worktree, puis le processus a disparu avant que sa sortie puisse être récupérée; son résultat reste inconnu.
- `main` n'a pas été modifiée.
# Candidate consolidée Codex (2026-11-01)

- Branche : `codex/n100-consolidated-20261101`.
- Base carrier : `99a20691499f71608fd58bbfa7e9594223163ddb`.
- Lots : U2, U3, U4, U5, U7 et durcissement export lettres.
- Validation cumulative : 34 passed in 15.14s ; Ruff, deux node-check et diff-check verts.
- Rapport : `docs/agent-reports/N100-CODEX-CONSOLIDATED.md`.
- Main non modifiée ; revue OpenCode et décision sur le contrat U7 attendues.
- Les 12 contrôles live ignorés ne prouvent pas la disponibilité actuelle des fournisseurs externes; la logique déterministe et les doubles synthétiques sont verts.
- Le benchmark pipeline est réalisé sur une base synthétique vide; le contrat `< 3 s` est atteint très largement, mais un benchmark chargé reste une preuve distincte.
- Aucune candidature réelle, donnée personnelle ni soumission employeur n’a été utilisée.
- Le checkout historique `/Users/comedelavenne/AI-Excel-Agent` est sur `agent/spec-033-translation-variants` avec de nombreux fichiers modifiés/non suivis; il ne doit pas servir directement à la convergence. Après accord, utiliser un worktree propre créé depuis `origin/main`, puis un fast-forward vers le SHA candidat.
- `main` demeure inchangée; sa convergence reste soumise à l’accord explicite de Côme.

---

# RAPPORT CODEX — 2026-10-29 16:05 CET

## 1. Livré (avec preuve)
| Commit | Contenu (1 ligne) | Fichiers | Tests verts (nom test) | Durée |
|---|---|---|---|---|
| en préparation | NAGE unifié : Stage Hunter intégré, qualification stage/langue/dates, espace Devoirs et Study Coach local persistant | 20 fichiers, 1 312 ajouts, 94 suppressions | 602 tests Career/Desktop/Study, puis 12 tests incrémentaux | 185,17 s + 10,1 s |
| correctif CI de ce rapport | Rétrocompatibilité `QualifiedOffer` et reconnaissance explicite des intitulés de stage allemand, italien et espagnol | qualification, corpus gelé et tests | 58 tests ciblés (`offer_exhaustiveness`, `offer_intelligence`, `career_offer_qualification`) | 2,20 s |

## 2. En cours maintenant
| Tâche | % fait | Temps passé | Temps restant estimé | Blocage ? |
|---|---:|---:|---:|---|
| Candidate NAGE Career + Devoirs | 100 % du code et de la recette candidate | session du 29/10 | commit, push, déploiement Bureau et recette de l’instance exacte | aucun blocage code ; Ollama absent au dernier démarrage, outils déterministes disponibles |

## 3. Performances mesurées
| Métrique | Avant | Après | Comment mesuré |
|---|---|---|---|
| `/api/career/application-pipeline` | 13,4 s historique | 389,724 ms à froid ; 14,438 et 21,062 ms à chaud | serveur candidat isolé, port 18933, 29/10 à 16:05 CET |
| `/api/study/overview` | nouvelle route | 17,077 ms à froid ; 5,860 et 5,699 ms à chaud | trois requêtes HTTP locales, base avec TD4 et séances persistées |
| `/app` | non apparié | 9,891 ms à froid ; 3,748 et 3,517 ms à chaud | trois requêtes HTTP locales |

## 4. État 24 h de ta prod
- commits aujourd’hui avant cette livraison : 0 ; la livraison sera un commit atomique.
- diff de travail : 20 fichiers, 1 312 ajouts, 94 suppressions.
- tests verts : 602 tests ciblés Career/Desktop/Study en 183,39 s ; 12 tests incrémentaux Devoirs/Study en 8,12 s ; Ruff, `node --check` et `git diff --check` verts.
- navigateur candidat : 8 documents réels autorisés visibles ; TD4 structuré en 5 sections et 38 tâches ; 9 notions ; séance 5 questions ; correction sourcée ; reprise persistante à la question 2/5 ; QCM sans identifiants techniques.

## 5. Ce que j’attends d’OpenCode
- Aucun travail requis pour cette livraison ; ne pas modifier la candidate pendant le déploiement.

## 6. Risques / blocages
- Le tuteur conversationnel local nécessite un service Ollama disponible ; lecture, structuration, analyse Excel, quiz, corrections et progression restent utilisables sans modèle.
- La première CI complète a exposé 3 régressions sur 6 458 cas ; elles sont corrigées et couvertes avant la seconde CI.
- La seconde CI a confirmé 6 446 tests verts et exposé une unique référence Constitution déplacée vers une ligne vide ; la référence vise de nouveau le code actif et son test dédié passe.
- Aucun original personnel n’est modifié ; les huit documents sont copiés dans les données locales ignorées par Git.
- Aucune soumission de candidature, aucun envoi de document et aucun fournisseur cloud n’est déclenché par ce parcours.

---

# RAPPORT CODEX — 2026-10-29 16:40 CET

## Livraison UX apprentissage

- Le dernier document de travail est désormais mémorisé localement et restauré après chargement; en l’absence d’historique, NAGE privilégie le document possédant déjà un parcours d’apprentissage.
- La bibliothèque Devoirs possède un filtre instantané, un compteur de résultats et un badge `Parcours créé`.
- Un aperçu compact expose documents, parcours, questions travaillées et notions à revoir.
- Le sélecteur `Dossier en` est masqué hors des parcours candidature où il est pertinent.
- Quand Ollama n’est pas configuré, les commandes conversationnelles sont désactivées avec une explication honnête; lecture, analyse, quiz et progression restent accessibles.

## Preuves

- `node --check desktop_static/app.js` : vert.
- `pytest -q tests/test_desktop_app.py tests/test_study_web_integration.py` : **4 passed en 6,14 s**.
- `ruff check tests/test_desktop_app.py` et `git diff --check` : verts.
- Navigateur réel sur la candidate : TD4 restauré, badge de parcours visible, 4 indicateurs de progression, absence de `Dossier en`, tuteur indisponible expliqué, recherche `Eurotech` ramenant la bibliothèque de 8 à 2 documents.

---

# RAPPORT CODEX — 2026-10-30 13:11 CET

## Livraison espace devoirs question par question

- Chaque question détectée possède désormais un état (`À faire`, `En cours`, `À vérifier`, `Terminé`) et des notes de résolution enregistrées localement.
- La progression possède un compteur et une barre d’avancement; les documents originaux ne sont jamais modifiés.
- La progression survit au redémarrage et son fichier local est limité au compte utilisateur (`0600`).
- Une entrée locale partiellement corrompue est ignorée proprement au lieu de casser la page.
- Le libellé du tuteur indique honnêtement `modèle local configuré`, sans promettre sa disponibilité instantanée sous charge.

## Preuves actuelles

- `tests/test_study_web_integration.py` : **3 passed en 15,24 s**.
- `tests/test_desktop_app.py` : **2 passed en 9,79 s**.
- Ruff ciblé, `node --check desktop_static/app.js` et `git diff --check` : verts.
- Navigateur réel sur la candidate : **38 questions** du TD4 affichées; la première a été passée à `À vérifier`, annotée, enregistrée puis relue via l’API.
- Redémarrage déjà vérifié : état et notes conservés.
- Ollama : modèle local `qwen3.5:2b-q4_K_M` configuré; une réponse minimale a fonctionné, mais les demandes documentaires longues restent lentes lorsque les workers OpenCode utilisent le même service.

## Limite explicite

- Cette livraison prouve le suivi question par question et sa persistance. Elle ne prouve pas encore une latence acceptable du tuteur conversationnel avec un document complet sous charge concurrente.
