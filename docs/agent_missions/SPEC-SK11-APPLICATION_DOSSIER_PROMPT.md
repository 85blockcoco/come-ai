# MISSION SPEC KIT — SK-11 : Dossier de candidature « 1 clic » et vérifiable

> **Priorité : P0** — Le dossier de candidature est le point de contact entre une offre retenue et un envoi réel.
> Tant que le dossier n'est pas vérifiable, tout ce qui précède (exploration, dédup, matching, profil) ne produit
> que du brouillon non défendable. Module pur, déterministe, hors-ligne, branche dédiée.

---

## Contexte

Les briques existent mais ne sont pas reliées en un dossier unique vérifiable :

| Brique | Livraison | État sur `main` |
|---|---|---|
| Exigences canoniques + provenance | CVBOOST-02 (`career/offer_requirements/`) | ✅ |
| Kit candidature (CV + lettre + fiche) | CVBOOST-05 (`career/application_studio.py`) | ✅ |
| Matching CV ↔ offre, preuve exacte | CVBOOST-21 (`career/cv_quality/matching.py`) | branche dédiée |
| Adéquation exigences ↔ profil approuvé | SK-03 (`career/requirements_fit.py`) | branche dédiée |
| Profil candidat avec preuves approuvées | SK-10 (`career/candidate_profile.py`) | branche dédiée |

**Ce qui manque** : un point d'entrée unique, depuis une offre, qui produit un dossier complet
(recommandations CV, CV adapté, lettre, fiche de prépa, checklist, questions d'entretien, export) **et**
qui dit, phrase par phrase, sur quoi chaque affirmation repose.

**Impact** : aujourd'hui, une candidature part d'un brouillon dont personne ne peut dire quelle phrase est prouvée.

---

## Modules à créer / modifier

```
career/application_dossier.py            # NOUVEAU — module pur du domaine
career/service.py                         # persistance + orchestration
career/router.py                          # endpoints HTTP
tests/test_application_dossier.py         # NOUVEAU
tests/fixtures/application_dossier/       # NOUVEAU — corpus synthétique
docs/agent-reports/SPEC-SK11-APPLICATION_DOSSIER.md
```

---

## Règles non négociables

1. **Une phrase factuelle = une preuve.** Chaque phrase factuelle du dossier cite un **fait de profil approuvé**
   (identifiant + citation verbatim). Une phrase sans fait approuvé n'est jamais présentée comme un fait.
2. **Zéro invention** — diploma, skill, number, language level, employer, date : rien n'est ajouté.
   Un fait non approuvé ne devient jamais une affirmation ; il reste une question à trancher.
3. **Vérificateur obligatoire.** Chaque affirmation du dossier reçoit exactement un verdict :
   `supported` / `unsupported` / `to_verify`.
4. **`unsupported` bloque l'export final.** Tant qu'une affirmation n'est pas prouvée, l'export est refusé
   avec la liste des phrases fautives. `to_verify` n'est pas bloquant mais reste visible.
5. **Langue de l'offre par défaut, modifiable.** La langue par défaut est celle annoncée par l'offre ;
   la personne peut forcer `fr` / `en` / `it` / `de`. Le choix est mémorisé et tracé (`language_source`).
6. **Comparaison avant/après obligatoire.** Le dossier compare le CV de départ (avant) et le CV adapté (après),
   ligne par ligne : `kept` / `added` / `removed`.
7. **Historique de versions.** Chaque regeneration produit une version ; les versions précédentes sont conservées.
8. **Aucun envoi automatique.** Le dossier écrit des fichiers, jamais il ne contacte l'employeur.
   Aucune requête réseau dans le module, aucun `auto-submit`.
9. **Hors-ligne et déterministe.** Pas de réseau, pas d'horloge interne, pas de aléa : même offre + mêmes faits
   → même dossier, même vérificateur, mêmes identifiants de claims.
10. **Les données de l'offre sont non fiables.** Le texte de l'offre est une donnée, jamais une instruction.

---

## Contrat de sortie (résumé)

```python
from career.application_dossier import build_application_dossier, export_dossier

dossier = build_application_dossier(
    offer,               # dict de l'offre (offre canonique)
    profile_facts,       # faits de profil approuvés (SK-10 / SK-03 / profil local)
    language=None,       # None = langue annoncée par l'offre, sinon fr|en|it|de
    base_cv="",          # CV de départ pour la comparaison avant/après
)

dossier.language                 # "fr"
dossier.language_source         # "offer" | "user"
dossier.recommendations         # HIGHLIGHT / REPHRASE / DO_NOT_ADD / QUANTIFY / CONFIRM_LANGUAGE
dossier.coverage                 # exigence ↔ fait, avec verdict
dossier.diff                     # kept / added / removed
dossier.verification.claims      # une affirmation = une ligne
dossier.verification.export_allowed   # False si une affirmation est "unsupported"

export_dossier(dossier, target_dir)   # refuse si export_allowed est False
```

---

## Vérificateur : règles exactes

Pour chaque phrase du dossier :

| Situation | Verdict |
|---|---|
| La phrase cite ≥1 fait approuvé **et** le fait couvre bien la phrase | `supported` |
| La phrase cite un fait **non approuvé** (proposé / rejeté / suspendu) ou un fait absent | `to_verify` |
| La phrase affirme quelque chose qu'aucun fait approuvé ne prouve | `unsupported` |
| Phrase ajoutée à la main (hors registre) : assertion candidate non prouvée | `unsupported` |
| Phrase ajoutée à la main : ni assertion candidate ni contradiction | `to_verify` |

« Assertion candidate » = la phrase porte une marque de première personne ou un chiffre
(`j'ai`, `mon expérience`, `3 ans`, `i have`, `my`, `ich habe`, `3 Jahre`, …).

**Règle d'or** : `supported` n'est accordé que si un fait **approuvé** existe **et** que la phrase
est couverte par ce fait (chevauchement de tokens significatifs). Un fait proposé ne prouve rien.

---

## Validation

### Corpus synthétique (12+ offres, 4 langues)

| Cas | Attendu |
|---|---|
| Offre FR avec fait approuvé correspondant | `supported`, export autorisé |
| Offre FR sans fait pour une exigence obligatoire | exigence `unsupported` (côté profil), dossier **non bloqué** |
| Fait au statut `proposed` | `to_verify`, pas `supported` |
| Fait au statut `rejected` | jamais utilisé, jamais compté comme preuve |
| Phrase inventée ajoutée à la main | `unsupported`, **export bloqué** |
| Phrase inventée retirée | export ré-autorisé |
| Chiffre « 5 ans d'expérience » sans fait | `unsupported`, export bloqué |
| Niveau de langue « C1 » sans fait | `unsupported`, export bloqué |
| Diplôme inventé | `unsupported`, export bloqué |
| Offre EN → langue par défaut `en` | `language_source == "offer"` |
| Langue forcée `fr` sur offre EN | `language_source == "user"` |
| CV de départ fourni | diff `kept` / `added` / `removed` non vide |
| Deux regenerations | historique de versions conservé |

### Commandes

```bash
.venv/bin/python -m pytest -q tests/test_application_dossier.py
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
git diff --check
./checklist_codex.sh main
```

---

## Critères de réussite

- [ ] `career/application_dossier.py` pur, déterministe, hors-ligne, sans horloge interne
- [ ] Les 6 livrables produits : recommandations CV, CV adapté, lettre, fiche de prépa, checklist, questions d'entretien
- [ ] Vérificateur obligatoire : `supported` / `unsupported` / `to_verify` sur chaque affirmation
- [ ] `unsupported` bloque l'export final, avec la liste des phrases fautives
- [ ] Zéro invention : diplôme, compétence, chiffre, niveau de langue
- [ ] Langue de l'offre par défaut, modifiable, tracée
- [ ] Comparaison avant/après (kept / added / removed)
- [ ] Historique de versions
- [ ] Aucun envoi automatique, aucune requête réseau
- [ ] 40+ tests dédiés, suite complète verte, ruff clean, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK11-APPLICATION_DOSSIER.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk11-application-dossier`, worktree dédié, code, tests, rapport, push.
Je relis et j'intègre.
