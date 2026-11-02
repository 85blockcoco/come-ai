# NAGE — guide utilisateur v2 (02/11/2026)

NAGE tourne **entièrement sur ton Mac**. Aucune candidature n'est envoyée à ta
place, aucune donnée personnelle n'est publiée, et les calculs de devoirs ne
sortent jamais de la machine.

## 1. Démarrer l'application

```bash
cd $HOME/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py --no-browser --port 8765
```

Ouvre ensuite **http://127.0.0.1:8765/career** (candidatures) ou
**http://127.0.0.1:8765/v5** (espace unifié).

NAGE Bureau (version séparée) : `http://127.0.0.1:8766`.

## 2. Candidatures en 3 clics (Career)

1. **Profil** → importe ton CV (PDF/DOCX/TXT). Chaque fait extrait doit être
   approuvé par toi avant d'entrer dans le profil.
2. **Offres** → colle une offre réelle, choisis sa famille métier, puis
   **Générer le kit** (CV adapté + lettre + checklist).
3. **Candidatures** → relis, approuve, exporte.

### Shortlist et urgence

- `POST /api/career/offers/rank` classe les offres : urgent 72 h d'abord,
  deadlines proches ensuite, **offre sans deadline en dernier**.
- `GET /api/career/shortlist?fmt=text` affiche le tableau de bord texte.
- `POST /api/career/shortlist/export` écrit `career_data/exports/shortlist.csv`
  ou `.json` — le chemin est imposé par le serveur, jamais par le client.

### Atelier lettre (`/app#applications`)

- Choix de l'offre, langue (FR/EN/DE/ES), ton (formel/dynamique/concis).
- Aperçu modifiable, contrôle factuel, puis **approbation humaine explicite**.
- L'export local (TXT/MD/DOCX/PDF) est refusé tant que la lettre n'est pas
  approuvée **dans le registre serveur**. Le booléen `approved` envoyé par le
  navigateur ne suffit jamais.
- Aucun envoi automatique : pas de SMTP, pas de formulaire soumis à ta place.

### Dossier et ATS

- `GET /api/career/ats/fields?platform=greenhouse` préremplit les champs connus
  et liste les champs obligatoires manquants.
- `POST /api/career/dossier/checklist` renvoie les documents manquants en
  `blockers` (un dossier incomplet n'est jamais déclaré complet).
- `POST /api/career/dossier/preview` donne un aperçu **en lecture seule**.

## 3. Devoirs et quotidien — CLI `nage.py`

Le CLI est local, sans réseau, et n'écrit aucune donnée dans le dépôt.

```bash
# Finance : valeur future, NPV, TRI, ratios, obligations…
.venv/bin/python nage.py finance future_value pv=100 rate=0.1 periods=2
.venv/bin/python nage.py finance npv cashflows=-100,30,40,50 rate=0.08

# Maths / statistiques
.venv/bin/python nage.py math mean values=1,2,3,4
.venv/bin/python nage.py math confidence_interval values=10,12,13,15

# Plan du jour (capacité bornée, tâches triées par urgence)
.venv/bin/python nage.py plan --minutes 120 \
  --task "NPV|2026-11-03|45|1" --task "Révisions|2026-11-04|30|2"

# Budget mensuel (fichier local ~/.nage/ledger.jsonl)
.venv/bin/python nage.py budget add income 1200 "Stage" --category job
.venv/bin/python nage.py budget add expense 12.5 "Cantine" --category repas
.venv/bin/python nage.py budget report --month 2026-11

# Brief quotidien : tâches urgentes + écart budget + révisions
.venv/bin/python nage.py brief --task "NPV|2026-11-02|45|1" --cards-due 5

# Plan de recherche : les sections vides restent [À COMPLÉTER]
.venv/bin/python nage.py research --topic "Finance durable" \
  --section "Introduction" --section "Données" \
  --fact "La BCE publie un rapport annuel"

# Méthode de devoir pas-à-pas (jamais la réponse finale)
.venv/bin/python nage.py homework --type npv --level master
```

Ajoute `--json` avant la commande pour une sortie machine :

```bash
.venv/bin/python nage.py --json math mean values=1,2,3
```

### Opérations autorisées

- **Finance** : `future_value`, `present_value`, `annuity_pv`, `annuity_fv`,
  `npv`, `irr`, `bond_price`, `current_ratio`, `quick_ratio`,
  `debt_to_equity`, `net_margin`, `roe`, `compound_rate`.
- **Maths** : `mean`, `median`, `mode`, `percentile`, `variance_sample`,
  `values_std`, `zscore`, `outliers_iqr`, `binomial_pmf`, `normal_cdf`,
  `normal_inv`, `confidence_interval`, `linear_fit`, `solve_linear_system`,
  `roots_quadratic`.

Toute autre opération est refusée : pas de dispatch Python arbitraire.

## 4. API académique locale

| Route | Rôle |
|---|---|
| `POST /api/academics/finance/calculate` | Calcul finance whitelisté |
| `POST /api/academics/math/calculate` | Calcul maths whitelisté |
| `POST /api/academics/daily/plan` | Plan du jour borné |
| `POST /api/academics/research/outline` | Plan de recherche sans invention |

Exemple :

```bash
curl -s -X POST http://127.0.0.1:8765/api/academics/finance/calculate \
  -H 'Content-Type: application/json' \
  -d '{"operation":"future_value","arguments":{"pv":100,"rate":0.1,"periods":2}}'
```

## 5. Sécurité et vie privée

- Aucune soumission automatique de candidature.
- Aucune clé API ni `.env` lue par le CLI.
- Les exports restent sous `career_data/exports/` (ou `~/.nage/` pour le budget).
- Les faits manquants restent des placeholders : NAGE n'invente pas.
- Le serveur écoute uniquement sur `127.0.0.1`.

## 6. Si quelque chose ne marche pas

```bash
# Vérifier que le serveur répond
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/

# Rejouer les tests ciblés
.venv/bin/python -m pytest -q tests/test_nage_cli.py tests/test_academics_routes.py \
  tests/test_career_letter_routes.py tests/test_career_shortlist_routes.py \
  tests/test_career_dossier_routes.py

# Lint
.venv/bin/python -m ruff check nage.py tests/test_nage_cli.py
```

Si le port 8765 est occupé : arrête l'ancien processus ou choisis `--port 8767`.
