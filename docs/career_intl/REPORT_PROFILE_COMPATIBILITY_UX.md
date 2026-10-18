# Lot 2 — Préparation du profil et compatibilité explicable

## État

- Branche : `codex/profile-compatibility-ux`
- Base : `a7815a767010a34794d4079fb4557c12ee8a3edd` (lot sources wave 2)
- `main` n'a pas été modifiée et aucun merge n'a été effectué.
- Livraison : commit à créer après cette revue.

## Livré

### Préparation du profil

`career/profile_readiness.py` fournit une évaluation déterministe sur 20 à partir des seuls faits déjà enregistrés dans le profil local. Les composantes sont : formation (4), expériences (4), compétences (4), langues (2), éligibilité explicitement connue (2), nom affiché (1), contact (1), LinkedIn (1) et entreprises ciblées (1).

La note mesure uniquement la complétude exploitable pour personnaliser une candidature. Elle ne mesure ni la valeur du candidat ni une probabilité d'embauche. Les faits ne sont pas inférés et aucun schéma de base n'est modifié.

### Compatibilité d'une offre

`career/scoring.py` expose maintenant, en plus du classement existant, une note de compatibilité profil sur 20, un niveau de confiance et le nombre de composantes connues/inconnues. La compatibilité reste distincte du score de recherche : elle compare des faits locaux et n'est jamais présentée comme une prédiction de recrutement.

### Interface

L'onglet « Mon profil » affiche immédiatement la préparation du profil, la note sur 20, le libellé et les prochaines actions. Dans Career Explorer, chaque offre peut afficher la compatibilité profil et la confiance à côté du score de classement. Le comportement existant de recherche et de suivi est conservé.

## Preuves exécutées

- `node --check career_static/career.js` : succès.
- Tests ciblés : `107 passed in 16.23s` (profil, garde-fous UI, Stage Hunter, agent Career).
- Suite complète sur cette branche, avec secrets cloud retirés et HOME isolé : `1096 passed in 93.61s`.
- Vérification navigateur locale sur données synthétiques et profil vide, serveur port `8920` : la carte « PRÊT POUR CANDIDATER » est visible, affiche `0/20`, le disclaimer et les quatre premières actions manquantes. Aucun CV réel, aucune clé et aucun appel cloud n'ont été utilisés.

## Limites honnêtes

- Le parcours navigateur a été vérifié avec un profil local vide ; le profil complet synthétique est couvert par les tests Python, mais aucun CV personnel réel n'a été importé.
- La note n'atteste pas de la qualité d'un CV ni de la probabilité d'obtenir un entretien.
- Les offres et les scores de sources publiques restent soumis à la date de collecte et aux informations effectivement publiées par les sources.

## Retour arrière

Dans ce worktree isolé, revenir au lot sources précédent avec `git reset --keep a7815a767010a34794d4079fb4557c12ee8a3edd` ou supprimer uniquement le commit de ce lot après revue. Ne jamais réinitialiser `main` ni les autres worktrees.

