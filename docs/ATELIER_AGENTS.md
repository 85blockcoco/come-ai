# Atelier agents — OpenCode + Codex + Gemini + local AI + GitHub

Guide concret pour utiliser les cinq briques ensemble sur ce dépôt. Chaque
brique a un rôle précis ; ne jamais les faire travailler en écrivant tous dans
`main` en même temps (une brique = une branche, revue avant fusion).

## Vue d'ensemble

| Outil | Rôle idéal dans Côme IA | Où il tourne | Coût |
|---|---|---|---|
| **OpenCode** | Chef de projet au quotidien : audit, modifications de code, bancs réels, git | Terminal du Mac | selon modèle |
| **Codex CLI** | Missions délimitées sur une branche (un fichier, un lot de tests) | Terminal du Mac | inclus ChatGPT Pro/Plus |
| **Gemini CLI** | Discussions exploratoires longues, revue de doc ; aussi le moteur cloud de l'app | Terminal du Mac | palier gratuit généreux |
| **Ollama (local)** | Chat 100 % local sans consentement (déjà branché en secours dans l'app) | Mac | gratuit |
| **GitHub** | Sauvegarde distante, CI, revue de PR, Dependabot, Copilot | cloud | inclus Education |

## 1. GitHub (fait en premier — tout le reste en profite)

### a) Installer et connecter GitHub CLI (une seule fois)

```bash
brew install gh                 # déjà fait (gh 2.102.0 installé le 2026-10-20)
gh auth login                   # choisir: GitHub.com → HTTPS → Login with web browser
```

Le terminal affiche un code à 8 caractères ; ouvre
`https://github.com/login/device`, colle le code, autorise. C'est tout.

### b) Créer le dépôt privé et pousser (je peux le faire pour toi ensuite)

```bash
gh repo create come-ai --private --source=. --remote=origin --push
```

Ton `.gitignore` protège déjà toutes les données personnelles
(`data/`, `career_data/`, `memory_data/`, `output/`, `.devkit/`, `.local-ai/`,
`.env`) : seul le code part sur GitHub.

### c) Ce que ta licence Education débloque concrètement

| Avantage | Usage ici |
|---|---|
| ~3 000 min Actions/mois sur dépôt privé | la CI (`tests/evals` complète ≈ 2 min/tour) tourne à chaque push |
| Copilot gratuit (statut étudiant vérifié) | autocomplétion dans VS Code/Xcode, sans consommer mes tours de raisonnement |
| Codespaces (120–180 h·cœur/mois) | atelier de dev cloud pour tester une idée sans toucher ton vrai workspace Mac |
| Dépôts privés illimités | historique distante + bundle de sauvegarde indépendants |

⚠️ Le workflow quotidien sur tes **vraies données** reste sur le Mac :
l'app est local-first. Codespaces sert au développement, pas à tes données.

### d) Après le premier push (je peux le faire, ou toi)

```bash
gh repo edit --enable-private-vulnerability-alerts
gh api repos/{owner}/{repo}/branches/main/protection -X PUT \
  -H "Accept: application/vnd.github+json" \
  -f required_status_checks='["lint","tests"]' -F enforce_admins=false \
  -F required_pull_request_reviews=null -F restrictions=null
# → main n'accepte un push que si CI verte
```

## 2. Codex CLI (missions délimitées)

Le dépôt lui parle déjà : [`CODEX_READY.md`](../CODEX_READY.md) (critères
d'acceptation) et [`checklist_codex.sh`](../checklist_codex.sh) (contrôles).

```bash
npm install -g @openai/codex     # une fois
codex                            # initialiser (connexion ChatGPT)
```

Boucle type pour une mission :

1. À partir d'**OpenCode**, ouvre une branche : `git switch -c agent/mission-XX`
2. Dans le terminal Codex : « Implémente la mission décrite dans
   CODEX_READY.md §X sur cette branche. Donne-moi le diff. »
3. Contrôle : `./checklist_codex.sh && .venv/bin/python -m pytest -q`
4. Revue du diff par **OpenCode** avant merge — Codex écrit, OpenCode relit.
5. Push → la CI tranchera.

## 3. Gemini CLI + clé de l'app

```bash
npm install -g @google/gemini-cli
gemini                           # connexion compte Google, palier gratuit
```

- **Gemini CLI** : utile pour « lis ces 8 fichiers et propose une restructuration »
  (lecture seule, puis tu redonnes la consigne à l'outil qui écrit).
- **Clé `GEMINI_API_KEY`** (celle de l'app) : dans `.env` local uniquement,
  jamais dans Git ; le consentement cloud signé reste obligatoire à chaque
  départ de données (le guard l'exige déjà dans le code).

## 4. Ollama (100 % local, zéro envoi)

```bash
brew install ollama              # si absent
ollama pull qwen2.5-coder:7b     # bon compromis code/raisonnement local
```

L'app l'utilise déjà comme secours (`OLLAMA_MODEL` dans `.env.example`) :
tout le flux V3/Career peut tourner sans une seule requête sortante.

## 5. OpenCode (orchestrateur ta référence)

Ce que je fais de mieux pour toi ici, et tu peux le redemander tel quel :

- **Audit/merge/purge git prudente** (déjà démontré sur ce dépôt : 247→10 branches,
  bundle de sauvegarde avant toute suppression).
- **Bancs réels** : trouver des bugs impossibles à voir en tests unitaires
  (ex. le schéma Career v7 découvert ce jour sur ta vraie base).
- **Revue des diffs des autres agents** (Codex) avant fusion dans `main`.
- **Sessions worktrees** : je peux créer un worktree par chantier et y ouvrir
  une session dédiée, chacun sur sa branche.

## Règle d'or de l'atelier

> Un agent qui **écrit** sur une branche dédiée ; un agent qui **relit** avant
> fusion ; la **CI** comme arbitre ; et jamais deux writers sur `main`.

## Check-list d'une session multi-agents

```bash
git switch -c agent/<mission>          # 1. branche
# (Codex ou OpenCode implémente)       # 2. travail assisté
./checklist_codex.sh                   # 3. lint + tests
git push origin agent/<mission>        # 4. push
gh pr create --fill                    # 5. PR → CI
gh pr merge --merge                    # 6. fusion après CI verte
```

## Check-list de relecture d'un lot « Career » (rôle du relecteur)

Avant d'accepter un lot qui touche `career/` ou `career_static/`, le
relecteur vérifie, dans l'ordre :

1. **Périmètre** : le diff ne touche que les fichiers annoncés par la mission
   (`git diff main...<branche> --stat`) ; tout fichier hors périmètre = refus.
2. **Interdits fonctionnels** (grep sur le diff ajouté) :
   - `SCHEMA_VERSION` non modifié (aucune migration de schéma sauf mission dédiée) ;
   - aucune chaîne `window.prompt` ajoutée (garde statique
     `tests/test_career_v5_ux_guards.py`) ;
   - aucun appel réseau ajouté (`requests`, `httpx`, `urllib`, sockets)
     hors mission connecteur bornée ;
   - aucune chaîne ressemblant à un secret (`sk-`, `AIza`,
     `BEGIN PRIVATE KEY`) ;
   - **aucun envoi automatique** à un employeur (`automated_submission = false`
     maintenu, pas d'envoi d'e-mail, pas de clic robotisé) ;
   - aucune donnée personnelle réelle dans les fixtures (tout est synthétique).
3. **Comportement** : les nouvelles routes sont en GET quand elles ne font
   que lire ; les écritures restent derrière confirmation ; suppression =
   confirmation typée unique.
4. **Validation locale sur un worktree jetable** (dans le worktree de la
   branche, jamais sur le dossier principal) :
   `.venv/bin/python -m pytest -q` vert total (baseline 1147 + tests du lot),
   `.venv/bin/ruff check .` zéro erreur, `git diff --check` propre.
5. **Fusion** : uniquement après CI GitHub verte sur la PR ; fusion `--no-ff`
   avec un message qui résume le lot ; tag de jalon pour un lot majeur.
6. **Après fusion** : relancer la suite sur `main` et noter le nouveau
   baseline dans les handoffs restants.

Un tool d'audit automatisant ces contrôles est en préparation par l'agent
intégrateur (Mission 10, phase 1) : `scripts/audit_integration.py`.

Historique des décisions produit : `docs/audits/`, `docs/agent-reports/`,
`docs/archive/` (anciens handoffs).
