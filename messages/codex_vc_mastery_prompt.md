# Mega Prompt Codex — Parcours d'apprentissage VC (de 0 → examen)

## Objectif
Rendre NAGe le meilleur coach possible pour apprendre le cours VC à 100% d'ici vendredi : progression visible, UI soignée, couverture exhaustive des notions et exercices.

## Scope
1. **Couverture exhaustive** : ingérer tous les PDFs/XLSX de `~/Desktop/EDHEC COURS/VENTURE CAPITAL` (28 fichiers, 1480 pages). Extraire toutes les notions, définitions, formules, exemples, cas, exercices. Aucune notion oubliée.
2. **Progression** : dashboard par chapitre (%, cartes dues, score moyen), alertes points faibles, plan jour par jour jusqu'à vendredi.
3. **UI/UX** : interface propre, navigation par chapitre, thème sombre/clair, responsive, accessibilité, recherche full-text, raccourcis clavier, animations légères, skeleton loading.
4. **Tuteur IA sourcé** : réponses uniquement depuis les docs, citations page/extrait, modes (explication, reformulation, exemple, "comme à un débutant"), refus si hors corpus.
5. **Flashcards SRS** : cartes auto-générées, révision espacée SM-2, notation again/hard/good/easy, cartes dues.
6. **Quiz progressif** : questions adaptatives, feedback immédiat, pas d'examen blanc avant maîtrise ≥80%.
7. **Simulateur d'examen** : cas chiffrés type examen, timer, correction détaillée, score, remédiation.
8. **Export PDF** : fiches de synthèse + plan de révision.
9. **Offline** : service worker pour cacher les fiches (pas les données perso).

## Contraintes
- Backend `career/**`, UI `desktop_static/**` / `v5_static/**` → coordination.
- Tests ciblés, ruff clean, pas de force-push, pas de modification de `main` distante.
- Modèles coût nul uniquement.
- Ne pas toucher `/Users/comedelavenne/NAGE-release`.

## Livrable
- Branche `codex/vc-mastery-20261103`, tests verts, rapport `docs/agent-reports/NAGE-VC-MASTERY.md`.
- Vérification navigateur réelle du parcours complet.
