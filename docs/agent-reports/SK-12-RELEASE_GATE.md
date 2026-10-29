# SK-12 — Recette Career complète et barrière release

## Contexte et limite de mission

La fiche de mission `docs/agent_missions/SPEC-SK12-RELEASE_GATE_PROMPT.md`
n'existe dans aucune branche ni commit du dépôt : le worker a reçu
`[ERREUR: fichier introuvable]`. Le travail suit donc la description du
registre (`missions_registry.json`, mission 33) et les contrats d'acceptation
déjà présents dans le dépôt.

La branche de travail ne contient pas les endpoints d'approbation par preuve
de SK-10. Le chemin « profil approuvé » utilisé ici est donc l'import de profil
existant : import → relecture (`preview`, suggestions) → application explicite
champ par champ. Ce n'est pas présenté comme une approbation par preuve SK-10.

## Livré

| Fichier | Rôle |
| --- | --- |
| `career/release_gate.py` | Gate réutilisable : rapport, checks, classes de mesure, serveur loopback réel, connecteurs synthétiques, rendu JSON/Markdown |
| `scripts/release_gate.py` | CLI `--base-dir`, `--no-browser`, `--live`, `--json`, `--output` ; code de sortie 1 si un check échoue |
| `tests/test_release_gate.py` | Recette HTTP complète, non-fuite de données privées, déterminisme des verdicts, réexécution sur base existante |

## Parcours couvert (client HTTP réel, serveur loopback éphémère)

1. Santé : `automated_submission=false`, import de profil avec relecture obligatoire.
2. Profil : import texte → relecture → application explicite → éligibilité déclarée.
3. Critères d'exploration enregistrés localement.
4. Exploration avec quatre comportements de source : succès, partiel, indisponible, non supporté ; les offres existantes sont conservées.
5. Matching local et source officielle vérifiée.
6. Déduplication : réimport idempotent, shortlist et note utilisateur conservées.
7. Offres adverses : contradictoire (stage + permanent), expirée, sans date ; aucune n'est surévaluée.
8. Fiche : variante recommandée, couverture, écarts.
9. Kit : lettre, checklist avec action manuelle non cochée, trois téléchargements validés (PDF `%PDF`, DOCX `PK`).
10. Pipeline local sans envoi.
11. Suivi, approbation manuelle explicite, checklist locale.
12. Réception confirmée par référence, radar de relance local (`is_email=false`), note d'honnêteté.
13. Entretien : question, réponse, retour, clôture.
14. Barrière anti-envoi : aucun envoi automatique, seul un dépôt déclaré existe.
15. Redémarrage : offre, candidature et entretien retrouvés.
16. Lectures hors ligne complètes.
17. Navigateur réel : Chromium ouvre `/career`, rend l'en-tête puis ouvre le panneau Stage Hunter par une action utilisateur, sans erreur JavaScript.
18. Rapport : aucune coordonnée, référence privée ou erreur brute.

## Classes de mesure (jamais mélangées)

- `synthetic` : entrées de fixture déterministes.
- `app-verified` : comportement observé de l'application et de son API HTTP.
- `live` : source publique réelle, **uniquement** avec `--live`. Par défaut le check est `SKIP`, jamais vert silencieusement.
- `unmeasured` : qualité réelle d'un recruteur / d'une embauche. Aucun score n'est produit ni présenté comme mesure réelle.

Le rapport sépare aussi `submission` (`automatic=false`, `sent=0`) et `network`
(offline par défaut).

## Exécution

```bash
# Recette locale, navigateur réel inclus
.venv/bin/python scripts/release_gate.py

# Sans navigateur : le check est explicitement SKIP
.venv/bin/python scripts/release_gate.py --no-browser

# Mesure live facultative (une seule source publique, aucune offre importée)
.venv/bin/python scripts/release_gate.py --live

# Tests ciblés
.venv/bin/python -m pytest -q tests/test_release_gate.py
```

## Résultat de la recette du 2026-10-29

- `scripts/release_gate.py` (navigateur réel activé) : **PASS — 19 pass, 0 fail, 1 skip**.
- Le skip est `live_public_source`, non demandé.
- `pytest` ciblé : `18 passed` (gate + régressions US1/US2/US3 + apply kit).
- `ruff check` sur les fichiers modifiés : vert.
- `./checklist_codex.sh secrets` : vert.
- `./checklist_codex.sh lint` global reste rouge sur **9 erreurs préexistantes**
  dans `career/connectors/{apec,jobteaser,public_ats}.py`, fichiers hors
  périmètre de cette mission et non modifiés.

## Ce que le gate ne prouve pas

- Aucune couverture live des sources publiques par défaut.
- Aucune qualité réelle de candidature, de lettre ou d'entretien.
- Aucun envoi, aucune relance envoyée, aucun appel cloud.
- Aucune approbation par preuve SK-10 (indisponible sur cette branche).
