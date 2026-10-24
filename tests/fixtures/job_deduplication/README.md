# Corpus synthétique — SPEC-SK-06 (déduplication multi-sources)

Ce corpus est **100 % synthétique** : aucune annonce réelle, aucune donnée
personnelle, aucun appel réseau. Il sert de vérité terrain au module
`career/job_deduplication.py` et à ses tests
(`tests/test_job_deduplication.py`).

## Fichiers

| Fichier | Contenu |
|---------|---------|
| `pairs.json` | 112 paires étiquetées à la main (71 fusions, 41 refus) |
| `groups.json` | 14 cas de groupe (provenance, contradictions, élection, collision d'identifiant) |
| `truth_corpus.json` | 59 enregistrements étiquetés dans 36 groupes (précision / rappel) |

## Format d'une paire

```json
{
  "id": "url_utm_source",
  "category": "url_tracking",
  "expect_match": true,
  "expect_reason": "canonical_url_match",
  "a": { "source_name": "greenhouse", "official_url": "...", "title": "...", "city": "..." },
  "b": { "...": "..." }
}
```

`expect_reason` est le **premier** motif renvoyé par `match_records()` :
un motif de fusion (`same_external_id`, `canonical_url_match`,
`apply_url_match`, `same_role_concept`, `company_title_location_cluster`) ou
un motif de refus (`recycled_identifier_conflict`, `company_conflict`,
`role_level_conflict`, `cohort_conflict`, `start_date_conflict`,
`city_conflict`, `no_shared_identity`, `different_role_same_employer`,
`translation_common_words_only`).

## Catégories couvertes

| Catégorie | Cas | Ce qui est vérifié |
|-----------|-----|--------------------|
| `exact_duplicate` | 8 | Même identifiant, même lien, même contenu |
| `url_tracking` | 16 | `utm_*`, `gclid`, `fbclid`, `ref`, `source`, `msclkid`, `trackingid`, port 443, slash final, casse de l'hôte, `www.`, fragment, doubles slash, `http` → `https` |
| `employer_page` | 6 | Même offre sur la page employeur et sur le board |
| `translation` | 12 | Même rôle en français, anglais, italien, allemand ; refus sur quelques mots communs |
| `different_role` | 13 | Dev / PM, senior / junior, M&A / private equity, finance / asset management… |
| `city_conflict` | 12 | Paris / Lyon, remote / Milan, alias de villes, télétravail |
| `company_alias` | 8 | Acme Corp / Acme Inc., J.P. Morgan, Point72, Evercore ISI… |
| `reopening` | 6 | Réouverture : même rôle, date de publication différente |
| `incompatible_dates` | 6 | Débuts janvier 2025 / juin 2025, cohortes 2027 / 2028 |
| `recycled_identifier` | 6 | Identifiant recyclé par le board |
| `role_level` | 8 | Niveaux : intern, apprentice, junior, analyst, experienced, permanent |
| `guard` | 11 | Garde-fous non négociables (voir ci-dessous) |

## Garde-fous non négociables et cas associés

| Garde-fou | Cas |
|-----------|-----|
| Le score de pertinence utilisateur ne décide jamais | `guard_user_score_never_decides` |
| Toutes les provenances sont conservées | `group_three_sources_one_offer`, `group_*` |
| Les contradictions restent visibles | `group_divergent_dates_stay_visible`, `group_city_contradiction_stays_visible` |
| La source officielle reste principale | `group_official_verified_source_stays_primary`, `guard_official_verified_source_wins` |
| Les sources secondaires restent consultables | `group_unknown_feed_is_ranked_between_boards_and_manual` |
| La traduction ne fusionne pas sur quelques mots | `translated_generic_words_only_refused`, `translated_intern_word_only_refused` |
| Les rôles différents ne sont jamais fusionnés | `different_role_*`, `level_junior_vs_senior`, `guard_same_link_different_role_is_refused` |
