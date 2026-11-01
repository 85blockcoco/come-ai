# Note OpenCode → Codex — NAGE NEXT 100 (31/10)

## Contexte
Côme autorise 100 missions pour faire évoluer NAGE (sources internationales, qualification,
classement, profil, CV, lettres, dossier, entretiens, fiabilité IA, recettes).

## Coordination
- Codex développe le nouveau Spec Kit dans :
  `/Users/comedelavenne/Documents/Codex/2026-10-25/codex-op-ration-v3-stable-consolidation/candidate`
  Branche : `codex/nage-consolidation-20261030`
- **Ne modifie jamais ce worktree, ni /Users/comedelavenne/NAGE-release.**
- Réservé à Codex pendant l'intégration : `devkit/**`, `desktop_static/**` et leurs tests.
- OpenCode prend le backend `career/**` et l'orchestration.
- Ne pas modifier `main`. Ne pas remplacer de travail non commité.

## Backlog
Voir `docs/NAGE_NEXT_100_BACKLOG.md` (10 lots × 10 missions) et `missions_next100.json`.

## Lots réservés (I, J)
Pour les lots I et J, OpenCode reste hors des fichiers réservés à Codex. Les missions qui
nécessitent ces fichiers sont marquées « attente coordination ».

## 4 premières missions lancées (indépendantes, haute valeur)
1. A01 — Connecteur UK (sources internationales finance)
2. B05 — Niveau diplôme requis (BBA/Bac+4/M2/MBA) — filtre clé utilisateur
3. C07 — Filtre par type de stage finance (M&A, CIB, corp fin)
4. D04 — Registre de preuves (fondation pour CV factuel)

Branches : `agent/n100-A01-uk-sources`, `agent/n100-B05-degree-level`,
`agent/n100-C07-finance-family`, `agent/n100-D04-evidence-registry`.

## Règles rappelées
- Modèles coût nul vérifié uniquement (beam-free, mimo-v2.6-flash-free, deepseek-v4.1-flash-free).
- Max 2 tentatives par mission, puis consigner la cause et avancer.
- Pas de suite complète en parallèle. Tests ciblés uniquement.
- Preuve obligatoire : branche sur origin + tests verts avant "done".
- SHA, tests et conflits transmis à Codex à chaque lot validé.

## Livraisons OpenCode au 01/11 (mise à jour)

Branche principale backend : `agent/spec-033-translation-variants`.
Tous les modules sous `career/` avec tests ciblés verts (ruff clean) :

| Lot | Missions | SHA dernier commit |
|---|---|---|
| I (fiabilité IA) | I01, I02, I03, I04, I06, **I07, I08, I09** (nouveau) | `cb7915c` |
| F (lettres) | **F02–F06** multilingue/ton/personnalisation/vérif/score | `0abdf12` |
| F (lettres) | **F07–F10** export/templates/approu humaine/rapport | `b8e18ef` |
| J | J08 profiling, J09 error monitoring | `1e9f51d`, `e5381f4` |
| C/A/B/D | C05 rationale, H02 STAR, H05 relances, UK/DE/ES/US, durée, géo, contrat, VC parser, profil | `9a075b3` et antérieurs |

Restes côté OpenCode : E07–E10, C03/C08/C09, I10, D05/D06/D08/D09.
Restes côté Codex (fichiers UI) : J02–J05, J10. Voir prompt reçu séparément.
Total : 87/87 v1 done, 61→ **70/100** N100 done après ce lot F.

## ➡️ PROMPT CODEX PRÊT À LANCER (01/11)

**Lire impérativement `docs/agent_missions/N100_UI_CODEX_PROMPT.md`** (mission N100-UI-CX1) :
6 missions U1–U6 = câblage REST des 24 modules OpenCode (lettres, shortlist, dossier)
+ UI lot J. C'est LÀ que se trouve le travail — pas dans missions_next100.json.

Mise à jour du total backend : passe 5 livrée (A06, D06, D09, G06, G07, G08, H10, J06, J07,
C10) → SHA `90ccadf`. **80/100 N100 done** côté backend. Restantes : U1–U6 (Codex) + I10,
G09/G10 (vérifier), E2E recette jointe OpenCode.