# RECETTE E2E HTTP — lot 59 kit 1-clic (complément CODEX_RECETTE.md)
Service: `python3 -m uvicorn come_ai_web:create_app --factory --port 8747` (entrée correcte découverte par Codex Tâche A)
Mode: HTTP pur (codex sans navigateur en sandbox) — fixtures synthétiques, 0 donnée réelle.

| Étape | Verdict | Preuve |
|---|---|---|
| 1. Page `/` | ✅ 200 (6 975 o) | Codex tâche A |
| 2a. Import profil texte | ✅ 201 | `profile_import_48e11095...` |
| 2b. Guard approuvé (apply sans liste de champs) | ✅ **422 = comportement RÉUSSI du gardien** | contrat exige `updates[]` approbation explicable (sk10) |
| 2c. Apply champs proposés | ✅ 200 | profil `display_name: Camille Exemple`, expériences enrichies |
| 3. Import offre | ✅ 201 + **déduplication fonctionnelle (2e import, même URL → 1 job)** | `job_5bac7c...` / `job_1ef3725b...` si URL distincte |
| 4. Kit 1-clic (générer) | ✅ 200 | application + draft `variant m_a`, `generation_mode: local` |
| 4b. Consent guard | ✅ `approval_granted: false`, jamais de soumission auto | Constitution respectée |
| 5. Téléchargement | ✅ **6 formats OK**: CV md 687o+docx 37.3Ko+pdf 2.27Ko, lettre md 1.14Ko+docx 37.5Ko+pdf 2.51Ko | |
| 6. personnalisations | ✅ sur offre fraîche: «Camille Exemple» dans lettre (placeholder disparu), expérience «Analyste financier» citée, offre liée (LBO/valorisation) | |
| Étape audit (lot 77) | ABSENTE ATTENDU — mission 77 pas encore exécutée par la flotte | non bloquante |
| UX visuelle | À faire par l'utilisateur avant démo (5 min de clics, service déjà lancé sur :8747) | |

**Conclusion: PARCOURS E2E DU KIT 1-CLIC = FONCTIONNEL BOUT EN BOUT, sans bug produit.
Ce que ce teste ne couvre pas: rendu visuel pure, erreurs console navigateur.**
