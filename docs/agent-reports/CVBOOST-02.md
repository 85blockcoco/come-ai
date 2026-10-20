# CVBOOST-02 — Exigences de l'offre avec provenance précise

Statut : TERMINÉE (testé sur fixtures ; aucune donnée réelle ; aucun réseau ; aucun envoi).

## 1. Ce qui a été construit

Nouveaux modules uniquement (aucun fichier existant modifié) :

| Fichier | Rôle |
| --- | --- |
| `career/offer_requirements/__init__.py` | API publique : `analyze_offer`, `requirement_provenance`, `resolve_locator`, `split_source_lines`, `load_fixtures` |
| `career/offer_requirements/contracts.py` | schéma documenté + vocabulaire verrouillé (`CATEGORIES`, `MODALITIES`, `SOURCE_FIELDS`, règles d'identifiants) |
| `career/offer_requirements/extract.py` | extraction déterministe : sections, listes, phrases, négations, HTML, échéance, contradictions, doublons |
| `career/offer_requirements/fixtures.py` | chargeur validé du jeu synthétique (nombre, unicité, cinq langues) |
| `career/offer_requirements/fixtures/synthetic_offers.json` | 36 offres FR/EN/DE/IT/ES (aucune donnée réelle, sociétés fictives) |
| `career/offer_requirements/benchmark.py` | `python -m career.offer_requirements.benchmark` — compteurs du contrat + coût de parsing |

## 2. Contrat livré (résumé)

Chaque exigence porte désormais, au lieu d'un « exigence n°N » :

- `id` : `req_` + 16 hex de `sha256("{offer_id}|{source_field}|{texte normalisé}")` — suffixe `_<n>` stable en cas d'occurrence identique (règle documentée dans `contracts.py`) ;
- `text` : texte original citation exacte (jamais de paraphrase comme preuve) ;
- `source_field` : champ source exact (`requirements`, `description_original`, `languages_required`, `eligibility_requirement`, `role_level`, `deadline_date`) ;
- `locator` : référence stable `line:N[.sentence:M]`, résoluble verbatim via `resolve_locator` ;
- `category` {compétence technique | langue | formation | expérience | disponibilité | mobilité | autorisation de travail | autre} ;
- `modality` {required | preferred | contextual | unknown} — **une préférence n'est jamais obligatoire** (garanti par `test_preference_is_never_mandatory_across_all_fixtures`) ;
- `confidence` 0–1 déterministe (plafond 0.40 quand la modalité reste unknown, 0.35 sur passage suspect d'injection) ;
- `negated`, `injection_suspect`, `notes`.

Contrats transverses : `duplicates` (exposés, jamais fusionnés), `contradictions`
(structuré vs description, les deux côtés originaux côte à côte, aucun arbitrage
automatique), `application_deadline` (passage exact + `date_iso` seulement si
AAAA-MM-JJ strictes), `injection_suspects`, `truncated` + avertissement
"honnête", `skipped` (lignes avantages/contexte non transformées en exigences).

Règle de sûreté : le texte d'offre reste une donnée inerte — le package ne
contient pas de `subprocess/socket/urllib/eval/exec` (garde statique testée) et
aucun passage malveillant ne peut devenir `required` ni modifier le comportement.

## 3. Preuves réelles

Dans le worktree dédié `/Users/comedelavenne/AI-Excel-Agent-cvboost-02`,
branche `agent/cvboost-02`, base `7834e45` (contient `fd51bdd`, choix aligné
sur les lots CVBOOST-01/03/04 déjà livrés) :

- Tests ciblés : `62 passed` (`tests/test_offer_requirements_contract.py`,
  `tests/test_offer_requirements_extraction.py`,
  `tests/test_offer_requirements_adversarial.py`).
- Suite complète : `1207 passed, 0 failed` en 263 s
  (`/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python -m pytest -q`).
- `git diff --check` : propre. `ruff check` sur le new périmètre : 0 erreur.
- Benchmark (sortie réelle) :

```
career.offer_requirements benchmark
  offers=36 requirements=86 (required=61, preferred=16, contextual=4, unknown=5)
  duplicates=1 contradictions=4 deadlines=4 injection_suspects=3
  categories used: availability, education, experience, language, mobility, other, technical_skill, work_authorization
  timing: total≈40ms, worst single analysis≈3.3ms (parsing pur local, aucun réseau)
```

Couverture adverse des fixtures : sections et listes (« Prérequis », « Voraussetzungen »),
phrases explicites (« nice to have », « se valoriza », « gradito », « von Vorteil »),
négations FR/EN/ES, exigences contradictoires (OFF-011/012/035), date limite (ISO,
et format non parsable → `date_iso: null` honnête), avantage employeur pris à tort
pour exigence (OFF-016 : jamais requis), prompt injection EN/FR (marqué et inerte),
HTML purgé, doublons traduits conservés (OFF-020), doublons exacts marqués
(OFF-021), texte tronqué (OFF-022 : `truncated: true` + avertissement).

## 4. Adoption par `application_prep.py` sans casser les consommateurs

Aucun consommateur existant n'est touché. Le plan proposé à l'intégrateur :

1. **Adaptateur de compatibilité** : `extract_requirements(job)` reste tel quel.
   Un adaptateur peut la déléguer à
   `career.offer_requirements.analyze_offer` et projeter les champs
   `text`/`source_field` (identiques à la sortie actuelle) vers les
   consommateurs `prepare_application`/`summarize_offer` en ajoutant `id`
   provenant du contrat (additif : les clés existantes ne disparaissent pas).
2. **Remplacement ciblé du libellé générique** : dans `prepare_application`,
   `offer_reference: f"Exigence détectée n°{index}"` devient l'identifiant
   stable + provenance (`source_field`, `locator`, `heading`, `category`,
   `modality`), résolu verbatim via `resolve_locator`. Les écrans qui
   affichent le bloc gagnent la citation exacte ; la clé `requirement`
   reste inchangée, donc `career_static/career.js` n'a rien à deviner.
3. **Prendre la modalité au sérieux** : `cv_action_plan` peut classer
   `preferred` en "amélioration" au lieu de "bloquant" et laisser les exigences
   `negated`/`contextual` hors priorisation ; `unknown` reste affichée à
   vérifier. La répartition ne doit jamais transformer une préférence en
   obligation (invariant testé ici).
4. **Exposition des contradictions** : `contradictions` alimente une bande
   « cette annonce se contredit sur … » ; ni `matched` ni `unverified`
   ne tentent de trancher.
5. **Sécurité** : `injection_suspects` n'entre jamais dans la comparaison
   profil↔exigence ni dans la lettre ; `truncated` propagé dans
   `uncertainty` existant. Les identifiants `req_…` ne servent qu'à la
   provenance d'affichage, jamais comme contenu injecté à un quelconque
   service externe.

Chaque pas peut être fusionné séparément ; tant que (1) n'est pas en place
rien ne change, et la mission CVBOOST-03 (filtres/priorités UI) peut déjà
consommer `analyze_offer` tel quel.

## 5. Limites honnêtes

- L'extraction lexicale est intentionnellement incomplète : une phrase
  descriptive sans marqueur n'est requise nulle part (d'autres exigences
  réelles peuvent rester non repérées ; `unknown` et la bande d'avertissement
  le rappellent).
- `date_iso` n'est extrait que du format `AAAA-MM-JJ` ; « 12 décembre 2026 »
  reste cité sans normalisation (aucune interprétation fausse n'est possible).
- `resolve_locator` est sensible à une divergence stricte entre l'état de
  l'offre analysée et celui utilisé pour la résolution (deux appels doivent
  opérer sur les mêmes champs) ; la fonction renvoie "" plutôt que des
  passages inventés.
- Testé sur fixtures seulement ; aucune vérification navigateur ni réseau
  (hors périmètre de la mission). Non vérifié en charge sur d'immenses
  descriptions hors la génération capée (1000 répétitions testées).

## 6. Rollback

Les modifications sont purement additives sur une branche dédiée :
`git revert` du commit du rapport/code, ou suppression des dossiers listés en
§1 — aucune base, aucune interface consommateur, aucune migration.

Bien noté : `./checklist_codex.sh` (avec `VENV_PY=/Users/comedelavenne/AI-Excel-Agent/.venv/bin/python`)
échoue à son étape 5 « fichiers sensibles trackés » pour une raison préexistante
et hors périmètre : `secret_redaction.py` et `tests/test_secret_redaction_parity.py`
sont déjà trackés à la base `7834e45`. Cette étape n'a jamais vérifié le périmètre
CVBOOST-02 (aucun fichier à nom sensible n'a été ajouté ici).
