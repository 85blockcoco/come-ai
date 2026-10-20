# LOT D — Modèles, routage, envois

Base : worktree jetable `/tmp/audit_5ef814e` sur `5ef814e`. `HOME=/tmp/audit_home`.

## D.1 Points d'envoi réseau (inventaire AST + grep)

| ID | Fichier:ligne | Hôte / cible | Données envoyées possibles | Garde de consentement avant l'appel |
|---|---|---|---|---|
| D1-1 | `agent.py:28` + `:49` | `generativelanguage.googleapis.com` (Gemini) | prompt utilisateur + données fichier | Non (clé requise à l'import ; crash si absente) |
| D1-2 | `agent_v2.py:25` + `:273` | `generativelanguage.googleapis.com` (Gemini) | prompt utilisateur | Non |
| D1-3 | `workspace_core.py:760` + `:1009` | `generativelanguage.googleapis.com` (Gemini) | message, historique, résultats d'outils (extraits de fichiers, éventuellement secrets) | Partielle : clé + modèle dans allowlist Gemini gratuite ; pas de case de consentement |
| D1-4 | `workspace_core.py:1152` + `:1161` | `127.0.0.1` (Ollama local) | messages utilisateur | URL validée (`validate_local_ollama_url`) ; local uniquement |
| D1-5 | `workspace_core.py:1186` + `:1195` | `127.0.0.1` (Ollama local) | messages + schémas d'outils | idem |
| D1-6 | `hybrid_chat.py:559` `_generate` (branche gemini) | `generativelanguage.googleapis.com` | messages (incl. contexte local issu de fichiers) | `_cloud_model` + allowlist + clé ; pas de case explicite |
| D1-7 | `hybrid_chat.py:559` `_generate` (branche openrouter) | `openrouter.ai` | messages + catalogue GET | `_cloud_model` + suffixe `:free` + clé ; pas de case explicite |
| D1-8 | `hybrid_chat.py:559` `_generate` (branche ollama) | `127.0.0.1` | messages | validation URL ; local |
| D1-9 | `devkit/model_catalog.py:239` + `:256` | `generativelanguage.googleapis.com`, `openrouter.ai` | GET métadonnées modèles (pas de prompt) | `refresh` explicite ; Gemini exige `gemini_free_project_confirmed=True` (`model_catalog.py:244`) ; OpenRouter aucune garde de consentement utilisateur |
| D1-10 | `devkit/evolution_providers.py:420` + `:425` + `:455` | `127.0.0.1` (Ollama) puis Google/OpenRouter | prompt de correction de code | `_settings_guard` : `allow_remote` obligatoire pour cloud ; Gemini projet gratuit confirmé ; OpenRouter suffixe `:free` ; clé |
| D1-11 | `career/discovery.py:221` | `boards-api.greenhouse.io` | GET offres d'un board (lecture) | board configuré par l'utilisateur ; hôte fixe ; pas de redirection |
| D1-12 | `devkit/local_benchmark.py:25` + `:56` | `127.0.0.1:11434` | prompts synthétiques | outil de benchmark explicite |
| D1-13 | `local_ai_runtime.py:22` | `127.0.0.1:11434` | GET version | démarrage local explicite |

Aucun autre module applicatif n'ouvre de connexion réseau (vérifié par `grep` sur `urlopen`, `build_opener`, `generate_content`, `requests`, `httpx`).

## D.2 Ce qui alimente le registre de modèles

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| D2-1 | Registre en mémoire `ModelRegistry` (`free_ai_router.py:395`) alimenté par l'hôte, jamais de catalogue embarqué | `free_ai_router.py:395-434` | LU |
| D2-2 | `build_model_registry` (`intelligence_bridge.py:355`) assemble à partir de `DeclaredModel` + qualité + quotas | `intelligence_bridge.py:355-404` | LU |
| D2-3 | `ModelCatalog` (`devkit/model_catalog.py`) fournit les modèles disponibles via snapshot persistant ; `refresh` seul fait des requêtes | `devkit/model_catalog.py:166-275` | LU |
| D2-4 | `_routable_models` dans `hybrid_chat.py` (appelé à `_route_plan:506`) filtre par catalogue et capacité | `hybrid_chat.py:506` | LU |

## D.3 Décisions du routeur avec horloge factice

Script : `/tmp/audit_lotD_router.py` (sortie `raw/test_lotD_router.txt`). Modèles déclarés : `gemini-3.8-flash` + `qwen/qwen3.5:free`, prix confirmés à zéro.

| ID | Cas | Résultat observé | Sortie brute (extrait) | SHA | Statut |
|---|---|---|---|---|---|
| D3-1 | Quota inconnu | Les deux modèles restent routables ; quota déclaré `unknown` | `primary: gemini-3.8-flash`, `fallbacks: (qwen/...)`, `quota_disclosures: status unknown, known False` | `5ef814e` | EXÉCUTÉ |
| D3-2 | 429 (quota épuisé) sur Gemini | Gemini exclu ; seul OpenRouter reste | `primary: qwen/qwen3.5:free`, `fallbacks: ()` | `5ef814e` | EXÉCUTÉ |
| D3-3 | 5xx / timeout (catégorie `transient`) | **Non pris en compte** par le routeur : Gemini reste sélectionné | `observed quotas transient: {}` / `primary: gemini-3.8-flash` | `5ef814e` | EXÉCUTÉ |
| D3-4 | Tous indisponibles (deux providers bloqués) | Aucune route : `primary: None`, `ordered: ()` | `primary: None`, `fallbacks: ()`, `ordered: ()` | `5ef814e` | EXÉCUTÉ |
| D3-5 | Modèle retiré (`excluded_models`) | Gemini retiré ; OpenRouter seul | `primary: qwen/qwen3.5:free` | `5ef814e` | EXÉCUTÉ |
| D3-6 | Horloge factice | `observe_quotas(..., now=...)` utilise `now` pour calculer `blocked_until` | `blocked_until=2026-10-17T00:01:00+00:00` avec `now` minuit | `5ef814e` | EXÉCUTÉ |

Conclusion : le routeur ne réagit qu'aux observations de quota (`category == "quota"`) et d'authentification ; les erreurs transitoires (5xx, timeout) ne modifient pas l'état de quota.

## D.4 Consent V1 — fichiers et portée réelle

| ID | Affirmation | Preuve (fichier:ligne) | Statut |
|---|---|---|---|
| D4-1 | Case de consentement explicite : `consent_external: bool = False` dans `ApplicationDraftPayload` | `career/router.py:153` | LU |
| D4-2 | Refus si `use_ai and not payload.consent_external` | `career/router.py:410-413` | LU |
| D4-3 | Capacité annoncée avec `explicit_consent_required: True` | `career/router.py:215` | LU |
| D4-4 | Portée : envoi du profil et de l'offre sélectionnés au fournisseur IA configuré pour un brouillon de candidature ; mode local par défaut | `career/router.py:400-420` + `application_studio.py` | LU |
| D4-5 | `AgentService.generate_career_application` est une action séparée, sans outils, partageant le verrou | `workspace_core.py:729-745` | LU |

## D.5 Branche `f1af740` (`feature/v3-consent-guard`)

| ID | Affirmation | Commande / preuve | Sortie brute | SHA | Statut |
|---|---|---|---|---|---|
| D5-1 | 94 fichiers modifiés/ajoutés vs `5ef814e` | `git diff --name-only 5ef814e...f1af740 | wc -l` | `94` | `5ef814e` | EXÉCUTÉ |
| D5-2 | Ajoute `consent_guard/`, `personal_profile/`, `study_coach/`, `profile_chat.py`, `study_web.py`, etc. | liste des fichiers (extrait) | `A consent_guard/guard.py`, `A personal_profile/service.py`, `A study_coach/engine.py`, ... | `f1af740` | EXÉCUTÉ |
| D5-3 | Merge-tree (base `5ef814e`) : aucun conflit automatique | `git merge-tree <base> 5ef814e f1af740` | aucun marqueur `<<<<<<<`, exit 0 | `5ef814e` | EXÉCUTÉ |
| D5-4 | Modifie aussi `come_ai_web.py`, `hybrid_chat.py`, `devkit/exporting.py` | `git diff --name-status` | `M come_ai_web.py`, `M hybrid_chat.py`, `M devkit/exporting.py` | `f1af740` | EXÉCUTÉ |

## D.6 Incohérences trouvées

1. Le routeur ne réagit pas aux erreurs transitoires (5xx, timeout) : seul le quota/auth modifie l'état (D3-3). Un fournisseur instable reste sélectionné.
2. Le consentement V1 est limité au brouillon Career IA ; le chat général (`/api/chat`, `/api/v5/chat`) envoie des données de fichiers aux fournisseurs cloud sans case de consentement explicite (D1-3, D1-6).
3. Le catalogue OpenRouter se rafraîchit sans garde de consentement utilisateur, contrairement à Gemini (D1-9).
4. `agent.py` et `agent_v2.py` créent le client Gemini à l'import (`os.environ["GEMINI_API_KEY"]`) et planteront si la clé manque ; ils ne sont pas alignés avec le reste.
5. La branche `f1af740` touche 94 fichiers et modifie des fichiers centraux (`come_ai_web.py`, `hybrid_chat.py`) ; le merge-tree est propre mais le volume impose une revue.

## D.7 Ce que je n'ai pas pu déterminer

- Comportement réel avec clés API (aucune clé ouverte dans cet audit).
- Effet d'un Retry-After réel sur le cooldown (testé avec valeur synthétique).
- Présence d'autres points d'envoi dans des branches non inspectées.
- Si `consent_guard/` de `f1af740` est intégré ou non dans `main` (il ne l'est pas à `5ef814e`).

Fichiers bruts : `docs/audit_v2/raw/test_lotD_router.txt`, `docs/audit_v2/raw/test_lotD_merge_tree.txt`.
LOT_D.md : ce fichier.
EOF
cp /tmp/audit_lotD_router_out.txt docs/audit_v2/raw/test_lotD_router.txt 2>/dev/null || true
cp /tmp/audit_merge_tree.txt docs/audit_v2/raw/test_lotD_merge_tree.txt
sed -i '' 's#/Users/comedelavenne#~#g; s#/tmp/audit_5ef814e#WORKTREE#g' docs/audit_v2/raw/test_lotD_router.txt docs/audit_v2/raw/test_lotD_merge_tree.txt docs/audit_v2/LOT_D.md
wc -c docs/audit_v2/LOT_D.md