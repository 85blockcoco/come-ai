# LOT C — Chat et outils

Base : worktree jetable `WORKTREE` sur `5ef814e`. `HOME=/tmp/audit_home`.  
Script exécuté : `/tmp/audit_lotC.py` (sortie `raw/test_lotC.txt`).

## C.1 Trace réelle de la route de chat jusqu'à la boucle d'outils

### Chemin A — `/api/chat` (agent legacy, boucle d'outils Gemini/Ollama)

| Étape | Fichier:ligne | Symbole / action |
|---|---|---|
| 1 | `come_ai_web.py:725` | `@app.post("/api/chat")` |
| 2 | `come_ai_web.py:726` | `async def chat(payload: ChatRequest)` |
| 3 | `come_ai_web.py:738` | `def ask_agent()` (closure) |
| 4a | `come_ai_web.py:744` | si `agent_override is None` : `get_hybrid_chat().ask(...)` → chemin B |
| 4b | `come_ai_web.py:760` | sinon `runtime.agent.ask(message, allow_writes=payload.allow_write)` |
| 5 | `workspace_core.py:822` | `AgentService.ask(...)` |
| 6 | `workspace_core.py:833` | `_ask_gemini(...)` (si clé) ou `_ask_ollama(...)` |
| 7 | `workspace_core.py:899` | `_run_tool_loop(...)` (Gemini) ou `workspace_core.py:1074` (Ollama) |
| 8 | `workspace_core.py:936` | boucle `for turn in range(MAX_TOOL_TURNS + 1)` |
| 9 | `workspace_core.py:938` | `self._with_retries(self._gemini_generate_with_budget(...))` |
| 10 | `workspace_core.py:941` | `calls = list(getattr(response, "function_calls", None) or [])` |
| 11 | `workspace_core.py:968` | `tool_events.append(name)` |
| 12 | `workspace_core.py:970` | `result = self._invoke_tool(name, arguments, allow_writes=allow_writes)` |
| 13 | `workspace_core.py:974` | `result = truncate_tool_result(to_jsonable(result))` |
| 14 | `workspace_core.py:975` | `history.append(types.Content(role="user", parts=response_parts))` |

### Chemin B — `/api/v5/chat` (chat hybride, outils déterministes côté serveur)

| Étape | Fichier:ligne | Symbole / action |
|---|---|---|
| 1 | `come_ai_web.py:465` | `@app.post("/api/v5/chat")` |
| 2 | `come_ai_web.py:466` | `async def hybrid_chat(payload, request)` |
| 3 | `come_ai_web.py:473` | `get_hybrid_chat().ask(...)` |
| 4 | `hybrid_chat.py:631` | `HybridChatService.ask(...)` |
| 5 | `hybrid_chat.py:650` | `events, citations, context = self._local_context(...)` |
| 6 | `hybrid_chat.py:353` | `_local_context(...)` appelle `self.tools.inspect_file/analyze_table/create_analysis_workbook/search_memory` |
| 7 | `workspace_core.py:504` | `LocalTools.inspect_file(...)` etc. |

Note : le chemin B n'utilise **pas** `MAX_TOOL_TURNS` ; les outils sont invoqués de manière déterministe par le serveur, pas choisis par le modèle.

## C.2 Outils exposés au modèle (TOOL_SCHEMAS)

Source : `workspace_core.py:630` (`TOOL_SCHEMAS`, 5 entrées). Exposés au modèle dans `_ask_gemini` via `types.FunctionDeclaration` (`workspace_core.py:878`) et dans `_ask_ollama` via `tools_schema` (`workspace_core.py:1067`).

| Nom | Schéma (paramètres) | Lecture/écriture | Confirmation exigée |
|---|---|---|---|
| `list_workspace_files` | `{}` (aucun) | Lecture | Non |
| `inspect_file` | `file_id: string` (requis) | Lecture | Non |
| `analyze_table` | `file_id: string` (requis), `sheet_name: string` (optionnel) | Lecture | Non |
| `search_documents` | `query: string` (requis), `file_id: string` (optionnel) | Lecture | Non |
| `create_analysis_workbook` | `file_id: string` (requis), `sheet_name: string` (optionnel) | **Écriture** | Oui : `_invoke_tool` (`workspace_core.py:1034`) lève `UserFacingError` si `name == create_analysis_workbook and not allow_writes` ; l'endpoint `/api/actions/report` est le clic de confirmation direct |

## C.3 Module du calcul local et point d'intervention

| ID | Affirmation | Preuve | Statut |
|---|---|---|---|
| C3-1 | Calcul local = `calculate_expression` dans `hybrid_chat.py:125` (AST restreint, pas d'eval arbitraire) | `hybrid_chat.py:125-175` | LU |
| C3-2 | Point d'intervention : branche arithmétique de `HybridChatService.ask`, `hybrid_chat.py:681` (`value = calculate_expression(...)`) | `hybrid_chat.py:681` | LU |
| C3-3 | L'agent legacy (`AgentService`) n'expose **aucun** outil de calcul au modèle (5 outils, aucun calcul) | `workspace_core.py:630-660` | LU |

## C.4 Sessions scriptées (modèle factice, hors réseau)

Script : `/tmp/audit_lotC.py`, `AgentService._run_tool_loop` directement, `_with_retries` remplacé par des réponses scriptées. `MAX_TOOL_TURNS = 5` (`workspace_core.py:52`).

| ID | Cas | Comportement observé | Sortie brute (extrait) | SHA | Statut |
|---|---|---|---|---|---|
| C4-1 | 1 outil | Succès : 1 invocation, puis réponse finale | `EVENT: Outil local appelé: inspect_file` / `RESULT: {"answer": "Réponse après 1 outil.", "tool_events": ["inspect_file"]}` | `5ef814e` | EXÉCUTÉ |
| C4-2 | 5 outils d'un coup | Rejeté **avant** invocation : `len(calls) > 4` | `EXCEPTION: UserFacingError : Le modèle a demandé trop d’outils simultanément. Reformule la demande en une action plus ciblée.` | `5ef814e` | EXÉCUTÉ |
| C4-3 | Dépassement de `MAX_TOOL_TURNS` | 5 invocations successives, puis exception | `EVENT: ... ×5` / `EXCEPTION: UserFacingError : La demande nécessite trop d’étapes automatiques. Reformule-la en une action plus ciblée.` | `5ef814e` | EXÉCUTÉ |
| C4-4 | Outil qui lève une exception | Exception capturée, résultat `{"error": ...}` envoyé au modèle ; boucle continue | `INVOKE_RESULT: inspect_file EXCEPTION: UserFacingError Ce fichier n’est pas disponible...` / `RESULT: {"answer": "Après erreur outil.", "tool_events": ["inspect_file"]}` | `5ef814e` | EXÉCUTÉ |
| C4-5 | Chemin `../` | Rejeté par `Workspace.get_path` : fichier non disponible ; aucune traversée | `INVOKE_RESULT: inspect_file EXCEPTION: UserFacingError Ce fichier n’est pas disponible dans l’espace de travail.` / `DIRECT get_path("../x")` → même erreur | `5ef814e` | EXÉCUTÉ |
| C4-6 | Secret dans un résultat d'outil | **Le secret est renvoyé tel quel** au modèle (aucune rédaction dans `truncate_tool_result`) | `INVOKE_RESULT: inspect_file {"excerpt": "token = sk-AAAA... (52 chars)", "truncated": false}` | `5ef814e` | EXÉCUTÉ |

## C.5 Détails observés

- `truncate_tool_result` (`workspace_core.py:1274`) ne tronque que par taille (`MAX_RESULT_CHARS`), **pas** de rédaction de secret/chemin. La rédaction de chemins existe dans `safe_error` (`workspace_core.py:1254`) mais s'applique aux erreurs, pas aux résultats d'outils.
- `Workspace.get_path` (`workspace_core.py:309`) refuse tout `file_id` absent du registre ou dont le parent ≠ `data_dir` → protection contre `../` et chemins absolus.
- `_invoke_tool` (`workspace_core.py:1026`) : outil inconnu → `UserFacingError("Action IA non autorisée.")` ; écriture sans `allow_writes` → refus explicite.
- `MAX_TOOL_TURNS = 5` (`workspace_core.py:52`) ; boucle `range(6)` ; exception au 6ᵉ tour (index 5).
- Limite simultanée : 4 outils max (`len(calls) > 4`).

## C.6 Incohérences trouvées

1. La boucle d'outils (`AgentService`) et le chat hybride (`HybridChatService`) sont **deux chemins distincts** : seul le premier expose des outils au modèle et respecte `MAX_TOOL_TURNS`. Le second appelle les outils côté serveur sans boucle ni limite de tours.
2. Un secret présent dans un fichier est **exposé au modèle** via le résultat d'outil (C4-6), alors que `safe_error` rédige les chemins. Asymétrie.
3. `create_analysis_workbook` est le seul outil d'écriture, mais sa confirmation dépend du flag `allow_writes` passé par l'UI ; il n'y a pas de confirmation interactive dans la boucle d'outils elle-même.
4. `_local_context` (chemin B) invoque `create_analysis_workbook` directement si `allow_write=True` (`hybrid_chat.py:366`), sans passer par le flag de confirmation de la boucle.

## C.7 Ce que je n'ai pas pu déterminer

- Comportement réel avec un fournisseur Gemini/Ollama live (pas de réseau/clé dans cet audit) ; seul le chemin `_run_tool_loop` a été exercé avec un modèle factice.
- Effet de `truncate_tool_result` sur des résultats > `MAX_RESULT_CHARS` (non testé ici).
- Présence éventuelle d'autres outils exposés par d'autres modules (ex. Career, DevKit) — non inspectés dans ce lot.

Fichiers bruts : `docs/audit_v2/raw/test_lotC.txt`.
LOT_C.md : ce fichier.
EOF
wc -c docs/audit_v2/LOT_C.md