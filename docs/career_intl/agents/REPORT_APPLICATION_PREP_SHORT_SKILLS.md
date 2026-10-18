# Rapport — correction de vérification des compétences courtes

**Statut : TERMINÉE**  
**Branche :** `codex/application-prep-short-skills`  
**Base :** `main` @ `e1552b1cf97c6b70410b74b07f5c41f4cbf3a0ee`

## Défaut reproduit

`career/application_prep.py` ignorait tout token normalisé de moins de quatre
caractères. Une exigence synthétique `SQL is required.` et un profil contenant
`SQL and financial modelling` étaient donc classés sans élément correspondant,
alors que `SQL` est une compétence vérifiable et explicitement présente dans le
profil.

Le défaut pouvait dégrader les candidatures finance/data (SQL, CFA, VBA, etc.)
sans inventer de faits : il produisait un faux négatif dans le rapprochement.

## Correctif

Deux commits isolés, sans modification de `main` :

- `5b5f4ee` — test de régression écrit en premier ;
- `959df11` — allowlist conservatrice de compétences courtes (`api`, `aws`,
  `cfa`, `erp`, `git`, `sas`, `sap`, `sql`, `vba`).

Tous les autres tokens courts restent ignorés afin de ne pas transformer des
articles ou prépositions en preuves de compétence.

## Tests exécutés

- Test rouge avant le correctif : 1 échec reproduisant le faux négatif SQL.
- Après correctif : `68 passed` pour la régression, les garde-fous UI et le
  Stage Hunter.
- Tests Career complémentaires : `59 passed` (`test_career_agent.py` et
  `test_hybrid_web.py`).
- `git diff --check` : propre.

Les données sont entièrement synthétiques ; aucun CV, secret, appel réseau ou
fournisseur IA n'a été utilisé.

## Limites

La correction ne déduit pas de compétence nouvelle : elle permet seulement à
des acronymes explicitement autorisés et présents dans le profil de servir de
preuve lexicale. La détection de la langue de l'offre et la génération de
documents restent contrôlées par le choix de langue de l'utilisateur.

## Intégration

La branche est prête à être revue/cherry-pickée. Aucun merge, push ou écriture
dans le worktree principal n'a été effectué.
