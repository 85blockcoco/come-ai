# Utilisation

Ouvrir NAGE → **Atelier** → **Construire mon NAGE**.

1. Choisir une priorité, par exemple « Un CV et une lettre convaincants et exacts ».
2. Décrire le résultat souhaité et ajuster les critères, un par ligne.
3. Dans le périmètre technique, conserver des fichiers existants, différents
   des tests d’acceptation. La limite est huit sources et huit tests.
4. Cliquer sur **Préparer la mission** puis **Lire le brief**.
5. Cliquer sur **Télécharger pour OpenCode** et transmettre le ZIP dans la
   session de coordination OpenCode. Les fichiers du dépôt ne sont pas inclus.
6. Pour le moteur local existant, cliquer sur **Ajouter au backlog local**,
   puis utiliser le cycle borné dans l’Atelier avancé. La mise en file seule ne
   consomme aucun quota.

Une réponse OpenCode doit fournir le SHA complet, le diff, les commandes de tests
et la recette observée. Le champ `status` du modèle de résultat commence à
`needs_review`; un compteur ou une déclaration `done` n’est pas une recette.

## Commandes de validation ciblées

```sh
python -m pytest -q tests/test_devkit_specifications.py
python -m pytest -q tests/test_devkit_diagnostics.py tests/test_evolution.py tests/test_evolution_store.py
python -m pytest -q tests/test_evolution_web.py tests/test_devkit_integration.py tests/test_desktop_app.py
python -m ruff check devkit/
node --check desktop_static/app.js
```

## Migration et retour arrière

La première ouverture d’une base d’évolution v1 crée une sauvegarde privée
cohérente `evolution-v1-before-v2.sqlite3` dans `.devkit/evolution/` avant l’ajout
de la colonne des tests ciblés. Les anciennes tâches gardent leur comportement.
Pour restaurer cette sauvegarde, arrêter l’Atelier, conserver la base v2 et ses
journaux à part, puis remettre la sauvegarde v1 sous le nom `evolution.sqlite3`
avec la version de code précédente. Ne pas remplacer une base ouverte.
