# Audit de sécurité applicative

**Date** : 2026-10-18  
**Périmètre** : code, contrats, schémas, API  
**Référence** : commit `5ef814e` (branche `main`, worktree `~/AI-Excel-Agent-sources`)

---

## 1. SSRF (Server-Side Request Forgery)

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 1.1 | **Moyenne** | `workspace_core.py:1212`, `workspace_core.py:1246` | `urllib.request.urlopen(request, timeout=timeout)` sans gestionnaire de redirection. `validate_local_ollama_url` impose l'URL initiale en `http://127.0.0.1:<port>`, mais `urlopen` suit les redirections par défaut. | Un attaquant local (ou un service malveillant sur le port 11434) peut renvoyer une réponse `302 Found` vers une URL interne (ex. `http://169.254.169.254/`, `http://127.0.0.1:6379/`, `http://localhost:8080/`). `urlopen` suivra la redirection et enverra la requête à la cible interne, potentiellement avec le corps JSON de la demande Ollama. | Utiliser `urllib.request.build_opener(ProxyHandler({}), _NoRedirect())` avec une classe `_NoRedirect` qui retourne `None` dans `redirect_request`, comme cela est déjà fait dans `hybrid_chat.py:113` et `devkit/evolution_providers.py:244`. | Test unitaire : mocker une réponse 302 vers une adresse interne et vérifier que `urlopen` ne suit pas la redirection. |

---

## 2. Validation des URLs

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 2.1 | **Faible** | `career/models.py:110-140` (`canonical_url`) | La fonction accepte les schémas `http` et `https` sans restreindre les hôtes aux domaines publics connus. Les adresses IP internes (`http://127.0.0.1`, `http://10.0.0.1`) et `http://` (non chiffré) sont acceptées. | Une URL officielle `http://127.0.0.1:8080/internal` est acceptée et stockée. Si un composant futur utilise cette URL pour une requête serveur, cela constituerait un SSRF. Actuellement, aucune requête serveur n'est effectuée sur `official_url`, mais la validation est permissive. | Restreindre `canonical_url` aux seules URL `https` (ou ajouter une liste blanche de domaines ATS connus). Pour les URLs dites « officielles », imposer `https` et éventuellement une liste de domaines vérifiés (Greenhouse, Lever, Ashby, SmartRecruiters, etc.). | Test unitaire : vérifier que `canonical_url("http://127.0.0.1:8080/x")` lève `UserFacingError`. |
| 2.2 | **Nulle** | `career/models.py:110-140` | `canonical_url` refuse les schémas `javascript:`, `data:`, `file:` et les URLs avec identifiants (`user:pass@host`). La fonction est correctement implémentée pour les usages actuels. | Aucun scénario d'exploitation actuel. | Aucun. | Aucun. |

---

## 3. Injection HTML

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 3.1 | **Nulle** | `career/application_studio.py:577-624` (`markdown_to_safe_html`) | Tout le contenu markdown est échappé avec `html.escape()` avant d'être inséré dans les balises HTML. Les balises `<script>` et `<style>` ne sont pas interprétées. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 3.2 | **Nulle** | `career/application_studio.py:627-642` (`render_application_html`) | Le titre est échappé avec `html.escape()`, la langue est normalisée via `normalize_language` (alphabet restreint). | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 3.3 | **Nulle** | `career/calendar_export.py:280-289` (`_escape_text`) | Le texte des événements iCalendar est échappé selon RFC 5545 (backslash, point-virgule, virgule, nouvelle ligne). Les caractères de contrôle sont supprimés par `_bounded_text`. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 4. XSS (Cross-Site Scripting)

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 4.1 | **Nulle** | `career_static/career.js`, `web_static/app.js`, `v5_static/v5.js` | Le frontend utilise exclusivement `textContent`, `createElement` et `append` pour insérer des données dans le DOM. Aucun usage de `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` ou `eval`. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 4.2 | **Nulle** | `career_static/career.js:930-932` | Les liens `href` sont définis avec `job.official_url`, qui est validé par `canonical_url` (schéma `http/https` uniquement). Le schéma `javascript:` est impossible. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 4.3 | **Nulle** | `web_static/app.js:101` | Les liens de téléchargement utilisent `encodeURIComponent(output.name)` dans l'URL, empêchant l'injection de caractères spéciaux. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 5. Contenu d'annonce rendu dans l'interface

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 5.1 | **Nulle** | `career_static/career.js` (fonction `make`) | La fonction `make(tag, text, className)` crée un élément DOM et assigne le texte via `textContent`. Les champs d'annonce (titre, entreprise, description, exigences) sont rendus de manière sécurisée. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 5.2 | **Nulle** | `career_static/career.js:890-893` | La description originale de l'annonce est rendue via `make("p", job.description_original)`, ce qui échappe automatiquement le contenu HTML. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 5.3 | **Nulle** | `career/stage_search.py:407`, `career/application_prep.py:185` | Les champs de description sont nettoyés par `clean_text()` avant d'être stockés ou affichés. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 6. Host et Origin

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 6.1 | **Moyenne** | `come_ai_web.py:679-703` (`upload_files`), `career/router.py:249-271` (`import_profile_document`) | Les endpoints d'upload `/api/files/upload` et `/api/career/profile-imports` ne vérifient pas l'en-tête `Origin`. Seuls `/api/v5/chat` et `/api/chat` (lignes 469-471, 743-745) et les routes DevKit (`devkit/router.py:69-72`) valident l'Origin. | Une page web malveillée hébergée sur `http://attacker.local:8080` peut soumettre un formulaire `multipart/form-data` vers `http://127.0.0.1:8765/api/files/upload`. Si la victime clique sur un lien ou visite la page malveillante pendant que l'application locale est ouverte, le navigateur enverra la requête avec l'en-tête `Origin: http://attacker.local:8080`. Le serveur accepte la requête (200 OK) car il ne vérifie pas l'Origin. Un fichier arbitraire peut être importé dans l'espace de travail local. | Ajouter une vérification de l'en-tête `Origin` sur tous les endpoints d'upload, similaire à celle de `/api/v5/chat`. Alternativement, ajouter un jeton CSRF par session. | Test d'intégration : POST `/api/files/upload` avec `Origin: http://malicious.test` et vérifier que la réponse est `403 Forbidden`. |
| 6.2 | **Faible** | `come_ai_web.py:340-343` | `TrustedHostMiddleware` inclut `"testserver"` dans `allowed_hosts`, même en production. Cela est nécessaire pour les tests (`TestClient`), mais pourrait permettre un contournement si le middleware était mal configuré. | Un attaquant envoie `Host: testserver:8765`. Le middleware accepte l'en-tête. Cependant, l'application est liée à `127.0.0.1` uniquement, donc l'exploitation depuis l'extérieur est impossible. | En production, restreindre `allowed_hosts` à `["127.0.0.1", "localhost", "[::1]"]`. Conserver `"testserver"` uniquement dans l'environnement de test. | Test d'intégration : POST `/api/health` avec `Host: testserver:8765` et vérifier que la réponse est `400 Bad Request` en production. |
| 6.3 | **Nulle** | `devkit/router.py:69-72` | La vérification de l'Origin et du token DevKit est correctement implémentée sur toutes les routes sensibles (`/api/devkit/*`). | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 7. Uploads

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 7.1 | **Nulle** | `come_ai_web.py:76-66, 1160-1192` | Les uploads sont limités par `UploadBodyLimitMiddleware` (100 Mo pour `/api/files/upload`, 10 Mo pour `/api/career/profile-imports`). Le streaming est borné par `MAX_IMPORT_BYTES` (50 Mo). Le nom de fichier est nettoyé par `_safe_upload_name`. Le chemin temporaire utilise un UUID unique. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 7.2 | **Nulle** | `come_ai_web.py:1195-1200` (`_safe_upload_name`) | `Path(raw_name or "fichier").name` supprime les composants de chemin. Les caractères de contrôle (`\x00-\x1f`) sont supprimés. Les noms `.` et `..` sont refusés. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 7.3 | **Nulle** | `career/service.py:808-813` (`_safe_profile_source_name`) | `Path(raw_name or fallback).name` supprime les composants de chemin. Les caractères de contrôle sont supprimés. Les noms `.` et `..` sont remplacés par `fallback`. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 7.4 | **Nulle** | `come_ai_web.py:1175-1177` | L'écriture utilise `open("xb")` (création exclusive, échec si le fichier existe), empêchant l'écrasement d'un fichier existant. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 7.5 | **Nulle** | `career/router.py:582-617` (`_store_profile_document`) | Le fichier temporaire est créé avec `open("xb")` et `chmod 0600`. Le contenu est haché (SHA-256) avant d'être transmis au service. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 8. Chemins de fichiers

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 8.1 | **Nulle** | `come_ai_web.py:1213-1219` (`_safe_output_path`) | Le nom de fichier est validé (`Path(filename).name`), la résolution du chemin est vérifiée (`candidate.parent == output_dir.resolve()`), l'existence et l'extension `.xlsx` sont contrôlées. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 8.2 | **Nulle** | `workspace_core.py:312-316` (`get_path`) | Le `file_id` doit exister dans le registre, le chemin doit être un fichier, et le parent doit correspondre à `data_dir.resolve()`. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 8.3 | **Nulle** | `workspace_core.py:288-295` (`unique_destination`) | `Path(name).name` est utilisé, empêchant la traversée de chemin. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 8.4 | **Nulle** | `devkit/patching.py:62-85` (`_safe_relative`, `_target`) | Les chemins relatifs sont validés (`PurePosixPath`, refus de `..`, `.`, chemins absolus). Les liens symboliques sont vérifiés à chaque niveau. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 8.5 | **Nulle** | `devkit/patching.py:301-304` (`candidate_path`) | L'ID du candidat est validé par `_ID` et le chemin est vérifié (pas de lien symbolique, est un dossier). | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 8.6 | **Nulle** | `career/service.py:174-177` (`re_sub_filename`) | Les caractères non autorisés sont remplacés par `-`, empêchant l'injection de composants de chemin. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 9. Logs

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 9.1 | **Nulle** | `come_ai_web.py:1234-1242` (`_build_logger`) | Les messages de log sont formatés avec `safe_error()` (pour les erreurs) ou des messages statiques. `safe_error` masque les clés API, les chemins locaux et les secrets. Les nouvelles lignes sont remplacées par des espaces (`compact`). | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 9.2 | **Faible** | `logs/come-ai-web.log`, `logs/ai-workspace.log` | Les fichiers de log ont les permissions `644` (lisibles par tous les utilisateurs du système). Sur un Mac partagé ou multi-utilisateur, cela pourrait exposer des informations internes (messages d'erreur, ID de tâche). | Un utilisateur non privilégié sur le même Mac peut lire les logs et obtenir des informations sur l'activité de l'application. | Appliquer `chmod 600` sur les fichiers de log lors de la création, ou utiliser `os.open()` avec `mode=0o600`. | Vérifier que les fichiers de log nouvellement créés ont les permissions `-rw-------`. |
| 9.3 | **Nulle** | `workspace_core.py:1304-1322` (`safe_error`) | Les clés API (`AIza`, `AQ.`, `sk-or-v1-`, etc.) et les chemins locaux (`/Users/...`, `/private/var/...`) sont masqués par des expressions régulières avant d'être journalisés. | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 10. Secrets

| # | Gravité | Fichier:Ligne | Preuve | Scénario d'exploitation | Correctif proposé | Test recommandé |
|---|---------|---------------|--------|--------------------------|-------------------|-----------------|
| 10.1 | **Haute** | `workspace_core.py:1235-1230` (`truncate_tool_result`) | La fonction tronque les résultats par taille (`MAX_RESULT_CHARS`) mais **ne masque pas les secrets** présents dans le contenu. Un fichier contenant `sk-AAAA...` ou `AIza...` sera transmis tel quel au modèle cloud si `allow_cloud_context=True`. | L'utilisateur sélectionne un fichier contenant des secrets (ex. un `.env` ou un fichier de configuration) et autorise la transmission cloud. Le contenu du fichier (incluant les secrets) est transmis au fournisseur IA (Gemini, OpenRouter) via le résultat de l'outil `inspect_file`. | Ajouter une passe de rédaction dans `truncate_tool_result` en utilisant `SECRET_PATTERN` de `hybrid_chat.py:67-70` ou une fonction équivalente. Alternativement, refuser la transmission cloud si le contenu du fichier correspond à un pattern de secret. | Test unitaire : créer un fichier contenant `sk-AAAA...`, appeler `inspect_file`, vérifier que le secret est masqué dans le résultat sérialisé. |
| 10.2 | **Moyenne** | `docs/audit_v2/LOT_F.md:50` (connu) | Les trois implémentations de `redact_text` (`task_queue`, `usage_ledger`, `devkit.exporting`) ne masquent pas le même ensemble de secrets. `task_queue` ne masque pas `sk-or-v1-` et `AQ.`. `devkit.exporting` ne masque pas `sk_`, `rk_`, `pk_` et les `key = value` sans guillemets. | Un secret masqué par un module peut être transmis en clair par un autre module. Par exemple, `task_queue.redact_text` laisse passer `sk-or-v1-...` qui serait masqué par `usage_ledger.redact_text`. | Unifier les patterns de rédaction dans un module partagé (ex. `secrets_redaction.py`) et l'utiliser dans tous les modules. | Test unitaire : vérifier que tous les patterns de secrets sont masqués par toutes les implémentations de `redact_text`. |
| 10.3 | **Nulle** | `workspace_core.py:152-156` (`has_gemini_key`) | La présence de la clé est vérifiée sans afficher la valeur. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 10.4 | **Nulle** | `.env` (permissions `600`) | Le fichier `.env` contenant les clés API a les permissions `-rw-------`, limitant l'accès au propriétaire. | Aucun scénario d'exploitation. | Aucun. | Aucun. |
| 10.5 | **Nulle** | `hybrid_chat.py:67-70` (`SECRET_PATTERN`) | Le pattern couvre les clés Gemini (`AIza`), OpenRouter (`sk-or-v1-`), Anthropic (`sk-`), et les clés génériques (`api_key`, `access_token`, `password`). | Aucun scénario d'exploitation. | Aucun. | Aucun. |

---

## 11. Synthèse des défauts critiques

| # | Gravité | Titre | Statut |
|---|---------|-------|--------|
| 1.1 | Moyenne | SSRF via redirection Ollama | À corriger |
| 6.1 | Moyenne | Origin non vérifié sur uploads | À corriger |
| 10.1 | Haute | Secrets non masqués dans les résultats d'outils | À corriger |
| 10.2 | Moyenne | Rédaction de secrets incohérente | À corriger |
| 9.2 | Faible | Permissions des fichiers de log | À corriger |
| 2.1 | Faible | Validation d'URL permissive | À corriger |
| 6.2 | Faible | `testserver` dans `allowed_hosts` | À corriger |

---

## 12. Preuves d'absence de défauts

| Domaine | Preuve |
|---------|--------|
| XSS | Frontend utilise `textContent` exclusivement. Aucun `innerHTML` ou équivalent. |
| Injection HTML | `markdown_to_safe_html` échappe tout le contenu avec `html.escape()`. |
| Chemins de fichiers | `get_path`, `_safe_output_path`, `_safe_relative`, `unique_destination` empêchent la traversée de chemin. |
| Uploads | Noms de fichiers nettoyés, taille bornée, création exclusive (`open("xb")`). |
| Logs | `safe_error` masque les secrets et les chemins locaux. |
| Host | `TrustedHostMiddleware` limite les en-têtes `Host` autorisés. |
| Origin (chat) | `/api/v5/chat` et `/api/chat` vérifient l'Origin. |
| Origin (DevKit) | `/api/devkit/*` vérifient l'Origin et un token de session. |
