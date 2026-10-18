# T1 P0 — préflight de confidentialité

Base : `main` `5ef814eb16f3357264624abdf0b8fd746315b7b1`, revérifiée avant création du worktree.
Worktree isolé : `/Users/comedelavenne/AI-Excel-Agent-t1-privacy-guards`, branche `codex/t1-privacy-guards`, initialement propre à cette base. Aucune fusion automatique.

## W0.2 — propriété et changements préexistants

Lecture effectuée avec `git status --short`, `git diff --stat`, `git diff --cached --stat` et inspection des hunks précis. Aucun changement préexistant n'a été modifié.

| Worktree | Branche | État ciblé relevé | Portée du diff local |
|---|---|---|---|
| `/Users/comedelavenne/AI-Excel-Agent-memory` | `feature/nemotron-memory` | `come_ai_web.py` modifié | +264/−2 lignes, endpoints CRUD `/api/v5/profile/*`; aucun changement de `hybrid_chat.py`, aucun mécanisme générique de consentement ni de masquage dans les hunks. |
| `/Users/comedelavenne/AI-Excel-Agent-profile-integration` | `feature/profile-integration-v1` | `come_ai_web.py` modifié | +153/−2 lignes, routes et intégration profil; aucun changement du chemin général de chat ou de masquage. |
| `/Users/comedelavenne/AI-Excel-Agent/.devkit/integration/profile-core` | `integration/profile-core` | modifications indexées de `come_ai_web.py` et `hybrid_chat.py` | +49/−4 lignes. Ajoute `use_profile` / `allow_profile_cloud`, charge un contexte Personal Context Engine et refuse certains envois de profil non autorisés. Cela ne couvre pas les fichiers sélectionnés, mémoire documentaire ou résultats d'outils du chat général. |

Les trois worktrees sont conservés tels quels. Le périmètre T1 peut être développé uniquement dans ce worktree conformément à la règle de chevauchement révisée; les raccordements dans `come_ai_web.py` resteront limités au schéma/contrôle API. Aucun fichier d'interface statique ne sera modifié : l'API seule est retenue, les worktrees `memory`, `profile-integration` et `profile-core` touchant déjà `come_ai_web.py`.

Les journaux `git log --all --since='3 weeks ago' -- <fichier>` montrent des commits récents touchant notamment `come_ai_web.py`, `hybrid_chat.py` et `workspace_core.py`, dont les lots de consentement et de sécurité listés ci-dessous. Un journal Git ne détermine pas si un agent est actif; les modifications locales des trois worktrees ci-dessus sont donc protégées.

## Réutilisation et décision

- **Consentement :** réutiliser `consent_guard` de `f1af740` (porté dans ce worktree par le commit `dc2e9ee`). Son enveloppe lie consentement à fournisseur, modèle, objectif et empreinte de contenu; consommation atomique unique; aucun transport ni secret. L'option `allow_cloud_context` restera booléenne, par défaut `false`, uniquement comme confirmation ponctuelle de l'action API courante. Le garde serveur réutilisé vérifie et consomme une enveloppe exacte pour chaque corps qui inclut du contenu local. Il n'y aura pas de second magasin/garde parallèle.
- **Masquage :** retenir `task_queue.redact_text` (dans `task_queue.py:156-190`) et lui ajouter un parcours récursif de valeurs JSON, sans nouvel ensemble de motifs. Le même helper sera appelé dans les deux chemins avant passage au modèle. Ne pas importer le masque de `usage_ledger.py`, qui est destiné aux tags, ni créer un quatrième regex. `hybrid_chat.SECRET_PATTERN` (`hybrid_chat.py:65-90`) reste un contrôle d'identifiants de modèles/texte final, pas le masque partagé de payload.
- **Erreurs :** réutiliser `workspace_core.safe_error` (`workspace_core.py:1253-1272`) pour les erreurs d'outils, puis le masque partagé sur leur payload structuré.
- **Alternatives inspectées :** commit `78ae9f8` de la branche candidate introduit `secret_redaction.py`, masque générique récursif mais nouveau mécanisme distinct; il n'est pas repris afin de ne pas créer un quatrième système. Le garde `consent_guard` du candidat est présent, mais la différence locale de `profile-core` n'est qu'un booléen limité au profil; le paquet exact de `f1af740` est la source retenue.

## Cartographie des transmissions

1. **`POST /api/chat` → `AgentService`** : schéma `come_ai_web.py:155-159`; route `come_ai_web.py:725+`; appels Gemini dans `workspace_core.py:822-920` et boucle manuelle `workspace_core.py:925-980`. Les résultats de chaque outil sont convertis/tronqués puis renvoyés à Gemini dans `workspace_core.py:965-979`; c'est le point de masquage et le point d'exigence de consentement avant l'appel suivant. Les IDs sélectionnés et noms deviennent le message distant dans `come_ai_web.py:728+`; ils seront refusés avant génération sans consentement explicite.
2. **`POST /api/v5/chat` → `HybridChatService`** : schéma `come_ai_web.py:182-191`; garde Origin et transfert `come_ai_web.py:465-489`; lecture locale dans `hybrid_chat.py:353+` (`_local_context`: inspection fichier, analyse tabulaire, recherche mémoire, événements/citations); planification `hybrid_chat.py:640+`; génération distante `hybrid_chat.py:559+` dans branches Gemini (`:582+`) et OpenRouter (`:608+`). Le refus sans consentement doit précéder catalogue/transport; avec consentement, enveloppe consommée pour fournisseur/modèle et texte contextualisé exact avant `_generate`.

## Plan T1

Fichiers prévus : `task_queue.py` (parcours récursif via le masque existant), `workspace_core.py` (outils AgentService), `hybrid_chat.py` (contexte déterministe, route cloud et consentement), `come_ai_web.py` (champ API `allow_cloud_context=False`, contrôle/passation sur les deux routes), tests ciblés, un cas dans `evals`, et `docs/career_intl/REPORT_T1.md`. Aucun fichier statique/UI ne sera changé dans ce lot. Une commande de test sera lancée avec HOME factice et aucune clé réelle lue.

Critères de preuve : secrets fictifs absents des corps outils transmis; Gemini/OpenRouter refusés avant tout socket lorsque données locales et consentement absent; envoi simulé accepté avec consentement; Ollama sans régression; champ omis lors d'une requête ultérieure = refus par défaut; cross-origin toujours refusé. Suite de base attendue : 749 tests; compteur réel reporté, jamais prérempli comme résultat.
