# HANDOFF CODEX — Mission : radar de relances des candidatures

> **⚠️ MISSION ABSORBÉE (2026-10-20, fin de journée)** — cette mission fait
> désormais partie du pack des dix missions en cours d'exécution par les
> agents : voir `docs/agent_missions/CAREER_CV_BOOST_10_BUILD_PROMPTS_2026-10-20.md`,
> **Mission 09** (« Tableau de bord des candidatures et relances ») qui
> englobe bandes de compteurs, staleness et brouillons de relance (jamais
> d'envoi). Ne pas lancer cette mission en doublon : les modifications
> simultanées de `career/service.py` et `career_static/career.js` créeraient
> des conflits. Le présent document reste valable comme **cadrage
> fonctionnel détaillé** de la partie relances.

Date : 2026-10-20 · Branche de travail demandée : `agent/career-followup-radar`
Dépôt : `/Users/comedelavenne/AI-Excel-Agent` (branche `main` à jour, 1141 tests verts, ruff zéro erreur)

## Contexte du produit (à lire AVANT tout code)

- App **100 % locale** FastAPI (`come_ai_web.create_app`), aucune donnée ne
  sort sans consentement signé (`consent_guard/`). Career 4.1 vit dans
  `career/service.py` (SQLite schéma 7, **ne pas changer `SCHEMA_VERSION`**).
- Le pipeline de candidatures existe : table `applications`
  (`stage`, `receipt_status`, `updated_at`, 12 étapes dans
  `career/models.py::GENERIC_APPLICATION_STAGES`) et historique
  `application_events` (`event_type`, `detail`, `created_at`,
  index `(job_id, created_at DESC)`).
- L'UI est `career_static/career.js` (vue `applications` via
  `loadApplications()` → `/api/career/applications`) et
  `career_static/career.css` (tokens `--ink/--muted/--border/--accent/…`).
- Tests existants à ne pas casser : `tests/test_career_agent.py` (39),
  `tests/test_career_exploration.py`, gardes statiques
  `tests/test_career_v5_ux_guards.py`.

## Ce qui manque (la mission)

L'utilisateur ne voit **aucun signe** qu'une candidature attend une relance
depuis X jours, et aucun compteur par étape. Il faut :

### 1. Backend — `career/service.py` (ou nouveau module `career/followup.py`)

Nouvelle méthode publique `application_followup_digest(*, stale_after_days: int = 7) -> dict` :

- **Compteurs par étape** : `{stage: count}` sur les applications actives
  (hors `rejected/refused/withdrawn`).
- **Candidatures en attente** : pour chaque application dont
  `stage ∈ {submitted, receipt_unknown, response_received, interview}` et
  dont le **dernier** `application_events.created_at` date de plus de
  `stale_after_days` jours (plancher : 3, plafond : 30, borné, sinon
  `UserFacingError` en français), renvoyer :
  `job_id, job_title, company, application_id, stage, last_event_at,
  days_since_last_event, suggested_followup` (texte prêt en français,
  court, factuel — voir contrainte de ton en bas).
- Ne **jamais** envoyer un e-mail ni appeler le réseau. Le « suivi » proposé
  est un **brouillon local** : l'envoi reste manuel (règle produit :
  `automated_submission = false` déjà affiché par `/api/career/health`).
- Montée en charge : requêtes SQL paginées/limitées (≤ 200 applications),
  réutiliser le pattern `_connection()` (WAL, secure_delete déjà en place)
  et le verrou `_lock` existant. Pas de nouvelle migration : tout se lit
  dans les tables existantes.
- Brancher dans `career/router.py` : `GET /api/career/applications/followup`
  (GET = lecture sûre, protégée par le CSRF middleware existant sans effort).

### 2. Frontend — `career_static/career.js` + `career.css`

- Dans la vue Candidatures, en tête : bandeau « Radar de relances » :
  compteurs par étape + liste des candidatures en attente avec
  « N jours sans réponse » et un bouton « Copier le brouillon de relance »
  (copie presse-papiers locale via `navigator.clipboard`, **jamais d'envoi**).
- Pas de `window.prompt` (interdit désormais : il ne reste que la confirmation
  typée de suppression dans tout le fichier — garde statique
  `tests/test_career_v5_ux_guards.py`).
- Accessibilité : `aria-live` sur le bandeau, focus visible, labels.
- Style : uniquement les tokens CSS existants (voir `.job-note-editor`
  comme exemple récent de bloc intégré).

### 3. Tests (obligatoire, style du dépôt)

- `tests/test_career_followup_digest.py` : compteurs exacts, seuil
  `stale_after_days` borné (erreur utilisateur au-delà), candidatures
  fermées exclues, brouillon factuel (contient société + titre), aucune
  écriture réseau. Fixtures **synthétiques** uniquement (jamais de données
  personnelles réelles — règle du dépôt).
- Gardes statiques à étendre dans `tests/test_career_v5_ux_guards.py` :
  `navigator.clipboard` présent, aucun `window.prompt` ajouté.

## Contrôles avant de dire « terminé »

```bash
./checklist_codex.sh                 # lint + contrôles portables
.venv/bin/python -m pytest -q        # DOIT être 1141 + tes tests = vert total
```

## Interdits (rappel du projet)

1. Aucun `git reset --hard`, `git clean`, force-push, ni écriture directe sur
   `main` (branche dédiée + push, la CI GitHub arbitre).
2. Aucune clé/API/secret dans le code ou les fixtures.
3. Pas de données personnelles réelles nulle part.
4. Pas de changement de `SCHEMA_VERSION` ni de schéma.
5. Pas d'appel réseau nouveau (aucun connecteur dans cette mission).
6. Diffs petits et revus : une mission = une branche = une PR.

## Livrables

1. Branche `agent/career-followup-radar` avec le code + tests.
2. `git push` (si remote absent, laisser la branche locale et le signaler).
3. Compte-rendu dans `docs/agent-reports/C50-FOLLOWUP.md` : ce qui a changé,
   résultats de tests, limites restantes.
