# T1 P0 — garde-fous du chat et des sorties d'outils

Date : 18 octobre 2026
Base : `main` `5ef814eb16f3357264624abdf0b8fd746315b7b1` (revérifiée après les tests : inchangée).
Branche isolée : `codex/t1-privacy-guards` — worktree `/Users/comedelavenne/AI-Excel-Agent-t1-privacy-guards`.
`main` n'a pas été modifiée; aucun merge ni push n'a eu lieu.

## Résultat

- Les résultats d'outils sont expurgés récursivement avant d'être remis à un modèle. La fonction centrale réutilise `task_queue.redact_text` et le classificateur de clés sensibles déjà présents. Les motifs existants de cette fonction ont été complétés pour le préfixe OpenRouter `sk-or-v1-`; aucun quatrième moteur de détection n'a été ajouté.
- Les deux endpoints acceptent `allow_cloud_context`, valeur par défaut `false`. Un choix de fichier local est refusé par les routes avant appel du chat si le consentement manque. Le service V5 refuse également avant catalogue, socket ou fournisseur lorsqu'un fichier, souvenir, résultat local ou historique est présent et que la requête demande une route distante sans permission.
- Avec permission, le service consomme une enveloppe `consent_guard` à usage unique, liée au fournisseur, modèle, objectif et empreinte du contexte sérialisé. Le contenu n'est pas enregistré dans la base de consentement. L'accord n'est pas conservé entre requêtes; une requête suivante doit réenvoyer le champ.
- Ollama/hors-ligne ne nécessite pas de consentement cloud; les contenus locaux restent quand même masqués avant le modèle.
- Les contrôles Origin du chat V5 restent présents; un contrôle équivalent a été ajouté à `/api/chat`.
- **API seulement :** pas d'indicateur dans l'interface cette tranche, car `come_ai_web.py` est déjà modifié dans les worktrees `memory`, `profile-integration` et `profile-core`. En conséquence, un envoi cloud avec fichier depuis l'interface actuelle est refusé tant qu'elle ne présente pas de confirmation explicite; le mode Hors ligne reste disponible. L'API accepte la confirmation de la requête courante.

## Décision de réutilisation W0.2

Le préflight complet est dans [T1_PREFLIGHT.md](/Users/comedelavenne/AI-Excel-Agent-t1-privacy-guards/docs/career_intl/T1_PREFLIGHT.md). Les trois worktrees de profil ont été lus en lecture seule et n'ont pas été touchés. Le diff indexé de `profile-core` ne protégeait que le contexte de profil via un booléen; il ne couvrait pas les fichiers et résultats d'outils du chat général. Le paquet exact `consent_guard` de `f1af740` a donc été repris dans ce worktree (commit local `dc2e9ee`), sans fusion de la branche source. La livraison `78ae9f8` contenant `secret_redaction.py` n'a pas été reprise pour éviter un nouveau mécanisme. `task_queue.redact_text` a été retenu pour tout texte/valeur JSON; `usage_ledger.redact_text` reste dédié aux tags et `hybrid_chat.SECRET_PATTERN` conserve son usage antérieur.

## Fichiers et points d'accroche

- `chat_privacy.py` : adaptateur unique vers le `ConsentGuard` réutilisé; stockage local des seules métadonnées/empreintes sous `data_dir/cloud-consent`.
- `task_queue.py:156-218` : extension de motifs existants et parcours récursif `redact_payload` pour chaînes, listes, tuples et valeurs de clés sensibles.
- `workspace_core.py:822-940` et `:941-1020` : booléen par action; refus de tool call local sans accord; résultat masqué avant troncature/réponse Gemini; enveloppe consommée avant le suivi qui transmet le résultat local.
- `hybrid_chat.py:353-400`, `:635-665`, `:750-765` : masquage des événements/citations/contexte, refus avant planification/catalogue en absence de consentement, consommation liée au fournisseur/modèle/messages juste avant génération distante.
- `come_ai_web.py:155-193`, `:465-497`, `:737-787` : champ API refusé par défaut, garde de fichier, Origin sur les deux routes et passage de la permission à la requête de service. Les modifications par hunk dans ce fichier restent limitées à des points d'accroche courts.
- `evals/cases/come_ai_real.json` : scénario `REAL-009` marque `application_verified: true`; l'ancien scénario de génération non mesurée est renuméroté `REAL-010`.
- Tests ajoutés/ajustés : `tests/test_hybrid_chat.py`, `tests/test_hybrid_web.py`, `tests/test_come_ai_v3.py`, `evals/tests/test_come_ai_target.py`, et adaptation du test d'isolation/horloge du garde importé.

## Preuves rouge → vert

1. **Reproduction rouge sur la base `main` :** avec un fichier Markdown synthétique contenant uniquement un jeton fictif `Authorization: Bearer …` et un transport OpenRouter simulé, le code de base envoyait le jeton (`baseline_bearer_value_sent_without_consent=True`). Aucun réseau n'était utilisé.
2. **Vert ciblé :**
   `env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q tests/test_hybrid_chat.py::test_consented_cloud_receives_redacted_local_context_and_permission_is_per_request tests/test_hybrid_chat.py::test_local_context_cloud_is_refused_before_any_network_without_request_consent tests/test_come_ai_v3.py::test_agent_tool_result_is_redacted_before_gemini_followup tests/test_hybrid_web.py::test_v5_selected_file_cloud_request_requires_per_request_consent tests/test_hybrid_web.py::test_legacy_chat_selected_local_file_requires_cloud_consent_before_agent`

   Sortie : `7 passed in 4.71s`. Ces cas couvrent Gemini/OpenRouter simulés avec sockets bloqués, consentement accepté, non-réutilisation, résultats d'outils Gemini masqués, mode local et garde Origin.

## Vérifications finales

Suite complète, clés absentes du sous-processus, HOME factice :

`env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q`

Résultat réel sur cette branche : **945 passed en 57,31 s**, aucun échec ni test ignoré. Ce total comprend la suite préexistante de 749 tests ainsi que les tests du garde réutilisé et les régressions T1.

Évaluation réelle locale, sans persistance, secrets retirés et réseau bloqué par la cible :

`env -u GEMINI_API_KEY -u GOOGLE_API_KEY -u OPENROUTER_API_KEY HOME=/tmp/codex_home PYTHONDONTWRITEBYTECODE=1 /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m evals run --target come-ai --strict --no-persist`

Résultat : **9 exécutés, 9 réussis, 0 échec, 1 non pris en charge** (`REAL-010 local_model_generation`), zéro simulation, zéro tentative réseau/API, 0,128 s, pic 77,8 MiB. `REAL-009` exerce le refus réel du `HybridChatService` avec fixture fichier synthétique; ce résultat n'évalue aucune qualité de modèle.

`git diff --check` : succès, aucune erreur d'espacement.

## Limites résiduelles

- Aucun indicateur UI n'a été ajouté par choix de propriété des fichiers. L'interface actuelle ne peut pas encore consentir au partage de fichier; elle doit rester en mode Hors ligne pour ces demandes, jusqu'à une tranche UI isolée.
- `/api/chat` utilise Gemini dans son chemin historique; si le modèle demande un outil local sans accord, l'outil est refusé avant lecture/exécution. Le premier appel ne contient alors que la demande utilisateur, pas de résultat local.
- Les détecteurs sont des garde-fous de formats connus et de champs sensibles, pas un classificateur de toutes les données confidentielles arbitraires. Le consentement explicite reste nécessaire pour tout contexte local envoyé au cloud.
- Aucun vrai fournisseur cloud, profil réel, document privé, serveur ou navigateur n'a été utilisé. Les tests cloud sont des transports simulés; les secrets sont fictifs.

## Retour arrière

Aucun retour arrière n'est nécessaire sur `main`, qui n'a reçu aucune modification. Pour annuler plus tard le lot fonctionnel après intégration, utiliser `git revert <commit-T1>` sur la branche d'intégration. Le commit de réutilisation autonome `dc2e9ee` (`consent_guard`) est séparé; il ne doit être reverti que si aucun autre lot ne l'utilise. Ne pas faire de reset/clean ni toucher aux worktrees concurrents.
