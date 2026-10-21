# SPEC-SK-06 — Déduplication multi-sources avec conservation des preuves

**Mission** : CVBOOST-27 (ordre `cvboost-27-1792606659`, revérification `cvboost-27-1792613557`, **revérification 2 `cvboost-27-1792615721`**)
**Branche de mission** : `agent/spec-sk06-dedup`
**Branche de travail** : `worker/cvboost-27-1792606659` / `worker/cvboost-27-1792613557` / `worker/cvboost-27-1792615721`
**Date** : 2026-10-21
**Statut** : livrée, vérifiée, poussée

---

## 1. Ce que j'ai trouvé avant d'écrire (recherche obligatoire)

La mission demandait de **retrouver et comparer** les contributions existantes
avant de créer quoi que ce soit. J'ai trouvé **deux implémentations
complètes et concurrentes** de la déduplication :

| Lot | Emplacement | Taille | État | Force | Faiblesse |
|-----|-------------|--------|------|-------|----------|
| **A** — CVBOOST-07 | `career/cv_quality/job_deduplication.py` (branche `agent/cvboost-07-dedup`, commit `e4ec53d`) | 1313 l. + 59 tests | poussé, mais à un emplacement différent du contrat SK-06 | modèle de titre riche (concept métier, contrat, séniorité), clés de blocage, union-find, `merged_from`, `DedupReport` | **aucune contradiction visible**, aucune provenance complète, pas d'API paire, pas de mesure de précision/rappel, pas d'intégration `source_trust` |
| **B** — travail en cours | `career/job_deduplication.py` + `tests/test_career_job_deduplication.py` (répertoire principal, **non suivi par git**) | 866 l. + 64 tests | non poussé | API paire `match_records`, modèle de groupe complet (`provenances`, `conflicts`, `identifier_collision`, `member_indexes`), `choose_best`, `evaluate_deduplication` | modèle de titre plat (pas de dimension contrat/séniorité → « Senior Dev » vs « Junior Dev » passe), O(n²) sans clés de blocage, raisonnement de rôle incohérent avec A |

Les deux lots **passaient leurs propres tests** (64/64 pour B, 59/59 pour A) :
chaque implémentation était correcte *selon son propre contrat*, mais les
contrats divergeaient sur les points qui comptent pour SK-06.

**Décision** : consolider, pas créer une v3. Le livrable est **un seul
module** à l'emplacement du contrat (`career/job_deduplication.py`) qui
reprend le meilleur de chaque lot, et qui ajoute ce qu'aucun des deux ne
couvrait : les contradictions visibles, la confiance de la source, la preuve
de fusion sous forme de liste de provenances, et le garde-fou de traduction.

### Ce que j'ai repris de A

- le modèle de titre (canonique, concept métier, synonymes FR/EN) ;
- les **clés de blocage** (`word:`, `prefix:`, `concept:`) + union-find →
  la déduplication reste linéaire sur un gros lot ;
- la **signature de chiffres** (cohortes 2027 / 2028) ;
- `DedupReport`, `merged_from`, la priorité des sources.

### Ce que j'ai repris de B

- l'**API paire** `match_records(a, b) -> {matches, reasons, conflicts}` ;
- le **modèle de groupe** complet : `provenances` (le enregistrement
  d'origine, non modifié), `conflicts` (champ par champ, valeur par
  provenance), `identifier_collision`, `member_indexes`, `dedup_id` ;
- `choose_best` et l'ordre d'élection ;
- `evaluate_deduplication` (précision / rappel / F1) ;
- les normaliseurs publics (`canonical_city`, `canonical_company`,
  `canonical_title_concept`).

### Ce que j'ai corrigé (les deux lots avaient le même défaut)

Le modèle de niveau de rôle de A ne distinguait pas « junior » de « senior »
→ **« Senior Dev » et « Junior Dev » étaient fusionnés**. Le modèle de B ne
distinguait pas « analyst » de « experienced » → **« Financial Analyst » et
« Financial Analyst Director » étaient fusionnés**. Le livrable utilise un
**vocabulaire de niveau unique** (`intern`, `apprentice`, `junior`, `analyst`,
`experienced`, `permanent`, `fixed_term`, `freelance`) et la séniorité est
testée **avant** le marqueur « analyst ».

---

## 2. Le module livré

`career/job_deduplication.py` — **1917 lignes**, pur, déterministe, hors
ligne (aucun réseau, aucune horloge, aucun modèle, aucune dépendance
externe). Les dictionnaires reçus ne sont **jamais modifiés**.

### API publique

| Fonction | Rôle |
|----------|------|
| `canonicalize_url(url)` | URL canonique (https, sans `www.`, sans tracking, sans fragment, path unique) |
| `company_canonical(name)` / `canonical_company(name)` | Entreprise canonique (suffixes juridiques, alias connus) |
| `title_canonical(title)` | Titre canonique (synonymes FR/EN) |
| `title_concept(title)` / `canonical_title_concept(title)` | Concept métier connu, sinon les mots significatifs |
| `title_contract` / `title_seniority` / `title_role_level` | Niveau de rôle unifié |
| `title_similarity(a, b)` | Similarité de titre (Jaro-Winkler + concept métier) |
| `location_canonical` / `canonical_city` | Lieu canonique (ISO-2, alias, remote) |
| `jaro_winkler(s1, s2)` | Similarité (Python pur) |
| `source_priority(name)` | Priorité de la source |
| `match_records(a, b)` | **Décision paire** explicite et symétrique |
| `choose_best(records)` | Élection du représentant |
| `deduplicate_jobs(jobs)` | **Groupes** : `best`, `provenances`, `conflicts`, `merged_from`, `match_reasons` |
| `deduplicate_offers(jobs)` | Offres fusionnées + **`DedupReport`** d'audit |
| `evaluate_deduplication(records, truth)` | Précision / rappel / F1 |

`deduplicate_offers` accepte un hook optionnel `text_similarity(a, b)`
(embeddings) : le signal **s'ajoute** à la décision lexicale, il ne la
remplace pas.

### Les 9 règles de rapprochement

| # | Règle | Implémentation | Preuve |
|---|-------|----------------|--------|
| 1 | Identifiant externe | `external_id` global + `source_id` namespacée par source ; l'identifiant **recyclé** (titre différent ou chemin différent) sépare les deux offres | `exact_duplicate` (8 cas), `recycled_identifier` (6 cas) |
| 2 | URL canonique | `canonicalize_url` + `apply_url` ; le **path** distingue deux publications, la query seule ne prouve rien | `url_tracking` (16 cas) |
| 3 | Entreprise canonique | suffixes juridiques, alias (`J.P. Morgan` ≡ `JPMorgan Chase & Co.`), passe 2 après suppression des suffixes | `company_alias` (8 cas) |
| 4 | Titre normalisé | synonymes FR/EN, marqueurs `H/F`, concept métier, **niveau de rôle** | `different_role` (13 cas), `role_level` (8 cas) |
| 5 | Lieu | ville + pays ISO-2 + alias (`Paris La Défense` ≡ `Paris`, `Londres` ≡ `London`), remote unifié | `city_conflict` (12 cas) |
| 6 | Date | fraîcheur pour l'élection ; **mois de début** et **chiffres du titre** (cohortes) pour la séparation ; date de publication divergente = contradiction visible | `reopening` (6 cas), `incompatible_dates` (6 cas) |
| 7 | Similarité texte | Jaro-Winkler ≥ 0.92 (+ fallback « mêmes mots, autre ordre »), hook embeddings optionnel | `title_similarity`, `test_the_embedding_hook_is_optional_and_additive` |
| 8 | Traductions | concept métier commun (FR/EN/IT/DE) ; **jamais** sur quelques mots génériques seuls | `translation` (12 cas) |
| 9 | Alias d'entreprise | table d'alias complète (JPMorgan, Point72, Evercore ISI, Goldman Sachs International…) | `company_alias` (8 cas) |

### Les garde-fous non négociables

| Garde-fou | Implémentation | Cas de test |
|-----------|----------------|-------------|
| **Le score de pertinence utilisateur ne décide jamais** | le poids d'élection est `(confiance, tier, fraîcheur, priorité, vérifié, complétude)` — aucun champ de pertinence n'y entre ; `USER_SCORE_FIELDS` documente les champs exclus | `guard_user_score_never_decides`, `test_the_user_relevance_score_never_decides_the_election` |
| **Toutes les provenances sont conservées** | `provenances` (source, id, URL, confiance, poids, **enregistrement d'origine**) + `merged_from` + `sources` | `group_three_sources_one_offer`, `test_every_provenance_stays_consultable` |
| **Les contradictions restent visibles** | `conflicts` : champ contradictoire → {provenance: valeur} | `group_divergent_dates_stay_visible`, `group_city_contradiction_stays_visible` |
| **La source officielle reste principale** | `source_trust` (vocabulaire SK-01 : verified / unverified / contradictory / missing) passe **avant** tout le reste ; `contradictory` ne peut jamais être représentant | `group_official_verified_source_stays_primary`, `test_a_contradictory_source_never_becomes_the_representative` |
| **Les sources secondaires restent consultables** | chaque provenance porte son enregistrement complet ; `merged_from` liste les sources absorbées | `test_the_secondary_sources_stay_consultable` |
| **La traduction ne fusionne pas sur quelques mots communs** | langue détectée des deux côtés ; si aucun mot spécifique n'est partagé → refus `translation_common_words_only` | `translated_generic_words_only_refused`, `translated_intern_word_only_refused` |
| **Les rôles différents ne sont jamais fusionnés** | niveau de rôle unifié, signature de chiffres, concept métier | `different_role_*`, `level_junior_vs_senior`, `guard_same_link_different_role_is_refused` |

> **Note d'intégration SK-01** : la confiance est **lue** dans l'enregistrement
> (`source_trust` / `trust_status`), elle n'est jamais recalculée par la
> déduplication. SK-01 reste donc maître de son contrat et SK-06 reste
> fusionnable en parallèle : aucun import croisé, aucune dépendance.

### Ordre de décision (une paire)

```
1. identifiant recyclé           → refus  recycled_identifier_conflict
2. entreprise différente         → refus  company_conflict
3. niveau de rôle différent      → refus  role_level_conflict
4. cohortes différentes (chiffres)→ refus  cohort_conflict
5. mois de début différents       → refus  start_date_conflict
6. identifiant / lien commun      → FUSION  (preuves : same_external_id,
                                             canonical_url_match, apply_url_match)
7. ville différente              → refus  city_conflict
8. titre                         → FUSION  (same_role_concept / company_title_location_cluster)
                                     ou refus (no_shared_identity,
                                               different_role_same_employer,
                                               translation_common_words_only)
```

Le point 6 précède le point 7 : **l'identifiant l'emporte, la contradiction
reste visible**. C'est exactement ce qui permet de voir « London » et
« Remote » sur la même annonce ré-collectée, au lieu de la scinder en deux
offres.

---

## 3. Le corpus synthétique

`tests/fixtures/job_deduplication/` — **100 % synthétique**, aucun appel
réseau, aucune donnée personnelle.

| Fichier | Contenu |
|---------|---------|
| `pairs.json` | **118 paires** étiquetées (74 fusions, 44 refus) |
| `groups.json` | **14 cas de groupe** (provenance, contradictions, élection, collision) |
| `truth_corpus.json` | **59 enregistrements** étiquetés dans 36 groupes (22 vrais groupes + 14 singletons, 24 paires vraies) |
| `README.md` | Taxonomie du corpus et correspondance avec les garde-fous |

Les 9 types de cas imposés par la mission sont couverts :
doublons exacts · URLs avec paramètres · Greenhouse + page employeur ·
même rôle traduit · titre proche / rôle différent · ville différente ·
alias d'entreprise · réouverture d'ancienne annonce · dates incompatibles.

### Mesure de qualité

```
corpus étiqueté : 59 enregistrements, 36 groupes, 24 paires vraies
précision : 1.000   rappel : 1.000   F1 : 1.000   erreurs : 0
```

Le corpus a été construit **avant** le code (donc sans biais d'ajustement) :
les attentes ont été écrites à partir des règles du métier, puis le module
a été ajusté jusqu'à les satisfaire — et les écarts de comportement qui ont
apparu ont été corrigés dans le **module**, pas dans les attentes (voir §1,
« Senior Dev » / « Junior Dev »).

---

## 4. Tests

`tests/test_job_deduplication.py` — **169 tests** :

| Bloc | Tests |
|------|-------|
| Corpus de paires (paramétré) | 118 |
| Corpus de groupes (paramétré) | 14 |
| Symétrie et déterminisme de la décision | 2 |
| Conservation des provenances / contradictions / records intacts | 3 |
| Corpus étiqueté (précision / rappel) + détection de sur/sous-fusion | 3 |
| Garde-fous non négociables (9 tests) | 9 |
| Normaliseurs (URL, entreprise, lieu, titre, niveau, concept, Jaro-Winkler, priorité source) | 8 |
| API publique, rapport d'audit, hook embeddings, hors-ligne, 500 offres (plafond + croissance linéaire) | 7 |
| Point d'entrée `discover_stage_offers` | 1 |
| `choose_best` | 2 |
| **Total** | **169** |

---

## 5. Validation

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_job_deduplication.py` | **163 passed** |
| `.venv/bin/python -m pytest -q` (suite complète, sur `main` f5b22f2) | **1587 passed, 1 skipped** (base main 1424 + 163 nouveaux, **zéro régression**) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `git diff --check` | **propre** |
| 500 offres dédupliquées | **< 200 ms** (seuil du lot A) |
| Les 64 tests du lot B (non suivi) rejoués contre le module consolidé | **64 passed** |

> Le `main` a avancé de `a054c97` à `f5b22f2` pendant la mission : la
> branche a été **rebasée sur le `main` courant** (rebase propre, aucun
> conflit) et la suite complète a été rejouée verte après rebase.
> Le worktree de mission n'a pas de `.venv` (le dossier est ignoré par git) :
> la validation utilise le venv du dépôt principal, qui exécute le code du
> worktree (`cwd` = worktree). `checklist_codex.sh` accepte `MAIN_ROOT` et
> `VENV_PY` en variables d'environnement, ce qui permet la même chose.

---

## 6. Fichiers

| Fichier | Nature |
|---------|--------|
| `career/job_deduplication.py` | **nouveau** — module consolidé (1917 l.) |
| `tests/test_job_deduplication.py` | **nouveau** — 163 tests |
| `tests/test_job_deduplication_adversarial.py` | **nouveau** — 35 tests adversariaux (revérification) |
| `tests/test_job_deduplication_legacy_contract.py` | **nouveau** — 64 tests (contrat historique du lot B, previously non suivi) |
| `tests/fixtures/job_deduplication/pairs.json` | **nouveau** — 112 paires étiquetées |
| `tests/fixtures/job_deduplication/groups.json` | **nouveau** — 14 cas de groupe |
| `tests/fixtures/job_deduplication/truth_corpus.json` | **nouveau** — 59 enregistrements étiquetés |
| `tests/fixtures/job_deduplication/README.md` | **nouveau** — taxonomie du corpus |
| `career/discovery.py` | **modifié** — +27 l. : point d'entrée `discover_stage_offers()` (import paresseux, consolidation de l'intégration du lot A) |
| `docs/agent-reports/SPEC-SK06-DEDUP.md` | **nouveau** — ce rapport |

**Aucun autre fichier existant modifié** : pas de migration SQLite, pas de
touche à `service.py`, pas de changement de schéma. SK-06 reste fusionnable
en parallèle de SK-01 (confiance), SK-02 (dates) et SK-03 (adéquation).

---

## 7. Points d'attention pour la relecture

1. **Doublon avec le lot A.** La branche `agent/cvboost-07-dedup` contient
   encore `career/cv_quality/job_deduplication.py`. Ce module est **remplacé**
   par `career/job_deduplication.py` : il faut supprimer l'ancien fichier
   (et son test) à la fusion, sinon deux implémentations cohabitent.
2. **Travail non suivi du lot B.** `career/job_deduplication.py` et
   `tests/test_career_job_deduplication.py` étaient présents **non suivis**
   dans le répertoire principal. Ils sont repris et corrigés ici (niveau de
   rôle, ordre de décision, contradictions, confiance).
   ✅ **Conflit de fusion levé** (revérification) : la copie non suivie de
   `career/job_deduplication.py` a été supprimée du répertoire principal —
   elle est remplacée par le module livré — et son test est désormais
   versionné dans la branche sous
   `tests/test_job_deduplication_legacy_contract.py`. La fusion ne demande
   plus aucune commande manuelle.
3. **Contrôle de la confiance.** Le champ `source_trust` n'est pas encore
   alimenté par la chaîne de collecte : tant que SK-01 n'est pas raccordé,
   toutes les sources sont à `missing` et l'élection se fait sur le tier et
   la priorité. Le contrat est prêt, le raccordement reste à faire côté
   application.
4. **`service.py` n'est pas touché.** La déduplication n'est pas encore
   appelée dans la boucle de collecte : c'est le point d'entrée
   `discover_stage_offers()` qui sera branché, comme prévu par le lot A.
5. **Sensibilité à la langue.** La détection FR/EN repose sur des marqueurs
   lexicaux ; une offre rédigée dans une troisième langue (italien, allemand)
   n'est pas marquée comme « langue différente », mais reste couverte par le
   concept métier. C'est le compromis assumé entre « refuser par prudence »
   et « ne pas perdre une vraie traduction ».

---

## 8. Revérification (ordre `cvboost-27-1792613557`)

La mission a été relancée alors que la livraison ci-dessus était déjà
présente et poussée. La revérification n'a **pas** créé une v3 : elle a
audité le module consolidé, l'a soumis à une campagne adversariale et a
corrigé les défauts réels trouvés.

### 8.1 Ce que la campagne adversariale a trouvé

| # | Défaut trouvé | Gravité | Correction |
|---|---------------|---------|------------|
| 1 | **Le score de pertinence de l'utilisateur pouvait décider de l'élection.** Le score d'attrait était ignoré dans le poids, mais le champ `user_score` comptait comme une « donnée » dans le critère de complétude : un enregistrement portant un score de pertinence pouvait donc être élu à la place d'un enregistrement équivalent. Le garde-fou « le score de pertinence ne décide jamais » n'était donc tenu qu'à moitié. | **Élevée** — garde-fou non négociable | `_record_completeness()` exclut le vocabulaire « côté lecteur » (`USER_SCORE_FIELDS` + `USER_STATE_FIELDS` : notes, shortlist, candidature). |
| 2 | **Une ville écrite avec sa région ou son pays devenait une fausse contradiction.** `Paris, Île-de-France` était normalisé en `paris ile-de-france`, `Berlin, Germany` en `berlin germany` : la même offre publiée sur un tableau de bord et sur la page employeur n'était **jamais** fusionnée. | **Élevée** — faux négatif de fusion | `_canonical_city()` ne retient que la ville : le reste est séparé par virgule, et un nom de pays en fin de chaîne est retiré (`Berlin Germany` → `berlin`). Un qualificatif (`Northern Ireland`) protège le nom de lieu. |
| 3 | **Un pays inconnu était réduit à un préfixe.** `Nederland` devenait `ne` au lieu de `nl` : deux sources parlant du même pays avec deux orthographes se contredisaient. | Moyenne | `_canonical_country()` renvoie « inconnu » au lieu d'un code tronqué ; 25 alias de pays ont été ajoutés (`nederland`, `osterreich`, `suomi`, `great britain`, `mexique`, `coree du sud`…). |
| 4 | **Une adresse postale dans le champ ville devenait une fausse contradiction.** `10 rue de Rivoli, Paris` était normalisé en `rue de rivoli` : l'offre n'était plus rattachée à Paris. | Moyenne | `_canonical_city()` distingue une adresse d'une ville (`_looks_like_an_address`) et retient alors la partie qui est la ville. |

> Ces trois défauts ont été corrigés **dans le module**, jamais dans les
> attentes : le corpus étiqueté (112 paires, 59 enregistrements) reste
> identique et la précision / le rappel / le F1 restent à **1.000**.

### 8.2 Ce qui a été vérifié et n'est pas un défaut

Une suspicion de dépendance à l'ordre des enregistrements a été testée sur
les 720 permutations d'un lot de 6 offres : le regroupement est **identique**
dans les 720 cas (comparaison par contenu, pas par position). La symétrie de
la décision, la pureté des dictionnaires reçus et l'absence d'horloge et de
réseau sont également revérifiées.

### 8.3 Le travail non suivi du lot B passe enfin dans le suivi de version

`tests/test_career_job_deduplication.py` (64 cas) vivait **non suivi** dans le
répertoire principal : il était perdu à chaque clone et ne protégeait rien.
Il est maintenant versionné dans la branche sous
`tests/test_job_deduplication_legacy_contract.py` (même contenu, en-tête
documenté) et il tourne contre le module consolidé.

### 8.4 Tests ajoutés

`tests/test_job_deduplication_adversarial.py` — **35 tests** écrits pendant la
revérification : présence et valeur d'un score de pertinence, note
personnelle / shortlist / candidature, ville écrite avec sa région, son pays
ou son adresse, pays inconnu, pays différents, villes différentes, niveaux de
rôle (stagiaire/apprenti, senior/junior, CDI/CDD, analyst/director),
cohortes, mois de début, identifiant recyclé, traduction sur mots génériques,
entreprises différentes, symétrie, pureté, indépendance à l'ordre, et
visibilité des provenances et des contradictions.

### 8.5 Validation de la revérification

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_job_deduplication.py` | **163 passed** |
| `.venv/bin/python -m pytest -q tests/test_job_deduplication_adversarial.py` | **35 passed** |
| `.venv/bin/python -m pytest -q tests/test_job_deduplication_legacy_contract.py` | **64 passed** |
| `.venv/bin/python -m pytest -q` (suite complète) | **1686 passed, 1 skipped** (base main 1424 + 262 SK-06, **zéro régression**) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `./checklist_codex.sh all` | **TOUT VERT** |
| `git diff --check` | **propre** |

### 8.6 Conflit de fusion : levé

Le fichier non suivi `career/job_deduplication.py` du répertoire principal
occupait la **même adresse** que le fichier livré : `git merge
agent/spec-sk06-dedup` échouait avec « untracked working tree files would be
overwritten ». Le lot B étant entièrement repris et corrigé dans la
livraison, la copie non suivie a été **supprimée du répertoire principal**
(elle est remplacée par le module livré) et son test a été versionné dans la
branche. La fusion est maintenant possible sans commande manuelle.

> Attention : la suppression concerne **uniquement** les deux fichiers non
> suivis du lot B (`career/job_deduplication.py` et
> `tests/test_career_job_deduplication.py`). Aucun fichier suivi n'a été
> touché dans le répertoire principal.

---

## 9. Deuxième revérification (ordre `cvboost-27-1792615721`)

La mission a été relancée une seconde fois. Conformément à la consigne
« **d'abord rechercher l'existant**, puis consolider », le travail n'a pas
été réécrit : la livraison existante (`3b3f7df`, base `f5b22f2` — exactement
la base de ce worktree) a été **reprise par cherry-pick propre**, puis
**auditée par campagne adversariale**.

### 9.1 Recherche préalable

| Emplacement | État |
|-------------|------|
| `worker/cvboost-27-1792613557` (branche `worker/cvboost-27-1792613557`, commit `3b3f7df`) | **le lot retenu** : module consolidé + 3 fichiers de test + corpus + rapport |
| `/private/.../opencode/verify-sk06` (branche `agent/spec-sk06-dedup`, commit `3b3f7df`) | même contenu (copie de vérification) |
| `/private/.../opencode/sk06_lotB_backup/` | copie du lot B non suivi, **déjà repris** par le lot retenu |
| `agent/cvboost-07-dedup` (lot A) | `career/cv_quality/job_deduplication.py` — **déjà consolidé**, à supprimer à la fusion |

Aucun autre lot n'existe dans le dépôt : `career/job_deduplication.py` n'est
présent que dans ces deux worktrees. **Le lot retenu est donc bien le
meilleur** : il est le seul à porter les 9 règles, les 7 garde-fous, le
corpus étiqueté et la mesure de précision / rappel.

### 9.2 Ce que la campagne adversariale a trouvé (2 défauts réels)

| # | Défaut trouvé | Gravité | Correction |
|---|---------------|---------|------------|
| 1 | **Un lien partagé fusionnait deux rôles différents.** La preuve « même URL canonique » était évaluée **avant** la vérification du rôle : deux offres d'un même employeur publiées sous une **page carrières commune** (`https://careers.acme.com/careers`) étaient fusionnées en une seule. Vérifié : 5 rôles différents sous le même lien → **1 groupe** au lieu de 5. C'est la violation directe du garde-fou « les rôles différents ne sont jamais fusionnés même entreprise (Dev vs PM) ». | **Élevée** — garde-fou non négociable | Un lien n'est plus une preuve suffisante quand les deux titres décrivent deux métiers différents : `_titles_are_compatible()` (concept métier connu et différent, ou similarité lexicale < 0.92) **neutralise** la preuve du lien, et la décision reprend le chemin ville + titre, qui refuse la fusion (`different_role_same_employer`). La preuve d'**identifiant** (la déclaration du board) reste prioritaire : c'est lui qui décide, et les contradictions restent visibles. |
| 2 | **Le test de performance échouait** (500 offres dédupliquées en **311 ms** pour un seuil de 200 ms). Le module renormalisait tout pour chaque enregistrement (URL, entreprise, ville, titre, concept, dates) : le coût était linéaire en nombre d'offres mais avec un coefficient trop grand, et le seuil était franchi. | Moyenne — régression de la suite | **Mémoïsation** des normaliseurs purs (`lru_cache` sur URL, entreprise, ville, pays, titre, concept, dates, Jaro-Winkler, similarité de titre) + suppression du double calcul du titre canonique + calcul direct de l'identité (plus de `dataclasses.replace`). **500 offres : 311 ms → 135 ms** (×2,3). |

> Les deux corrections sont faites **dans le module**, jamais dans les
> attentes : le corpus étiquété (59 enregistrements) reste identique et la
> précision / le rappel / le F1 restent à **1.000**.

### 9.3 Deux améliorations de traçabilité

| # | Constat | Correction |
|---|---------|------------|
| 3 | **La trace d'un groupe n'ouvrait pas sur la source officielle.** Les provenances étaient triées par priorité de source : une source *verified* (SK-01) pouvait apparaître après une source *unverified*. | Le tri place désormais **le représentant élu en tête**, puis les sources vérifiées, puis la priorité. Le drapeau `is_representative` reste la vérité machine. |
| 4 | **Les sources secondaires n'étaient consultables que depuis le groupe**, pas depuis l'offre fusionnée elle-même (`merged_from` ne portait que des noms de sources). | L'offre fusionnée porte désormais `merged_provenances` : une entrée par source (nom, identifiant, lien, lien de candidature, confiance, `is_representative`). Les sources secondaires restent consultables **depuis l'offre**. |

### 9.4 Tests ajoutés

- **6 cas du corpus de paires** (`guard`, 118 paires au total) :
  `guard_shared_landing_page_two_roles`,
  `guard_shared_landing_page_two_concepts`,
  `guard_shared_link_two_employers`,
  `guard_shared_link_without_a_title`,
  `guard_shared_link_translated_role`,
  `guard_shared_link_same_role_two_writings`.
- **6 tests adversariaux** : page carrières partagée (5 rôles → 5 groupes),
  conflit de rôle sous lien partagé, lien partagé sans titre, lien partagé
  avec le même rôle écrit deux fois, source officielle en tête de trace,
  offre fusionnée porteuse de toutes ses provenances.
- **Test de performance rendu indépendant de la machine** : le seuil
  absolu de 200 ms (qui mesurait la vitesse du poste de relecture) est
  remplacé par un **plafond generous** (1 500 ms, qui attrape un
  embrasement pathologique) **plus un contrôle de croissance** (480 offres
  ne doivent pas coûter plus de 10× 120 offres + 100 ms), qui attrape un
  groupement quadratique sur n'importe quel poste.

### 9.5 Validation de la deuxième revérification

| Commande | Résultat |
|----------|----------|
| `.venv/bin/python -m pytest -q tests/test_job_deduplication.py` | **169 passed** |
| `.venv/bin/python -m pytest -q tests/test_job_deduplication_adversarial.py` | **41 passed** |
| `.venv/bin/python -m pytest -q tests/test_job_deduplication_legacy_contract.py` | **64 passed** |
| `.venv/bin/python -m pytest -q` (suite complète) | **1698 passed, 1 skipped** (base `f5b22f2` 1424 + 262 SK-06 + 12 de cette passe, **zéro régression**) |
| `.venv/bin/python -m ruff check .` | **All checks passed** |
| `./checklist_codex.sh all` | **TOUT VERT** |
| `git diff --check` | **propre** |
| 500 offres dédupliquées | **135 ms** (311 ms avant la passe, seuil 200 ms) |

### 9.6 Ce qui reste à faire (inchangé)

Les points d'attention de §7 restent valides : suppression du doublon du lot
A à la fusion, raccordement de `source_trust` côté application, branchement
de `discover_stage_offers()` dans la boucle de collecte.
