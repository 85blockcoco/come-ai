# NAGe — état préparation examen VC

Date : 2026-11-03

## Ce qui est réellement utilisable

Dans la V5 locale (`/v5`), l'espace **Réviser VC** propose désormais :

- un plan de bataille calculé à partir de la couverture et des topics non testés ;
- une session de rappel espacée : question affichée seule, révélation explicite, puis grade `À revoir / Difficile / Bien / Facile` ;
- un radar par chapitre avec tentatives, exactitude, statut et cartes dues ;
- un examen blanc local (5, 10 ou 20 questions), avec minuteur, QCM/exercices, sauvegarde locale des réponses, correction déterministe et topics de remédiation.

Les routes sont sous `/api/academics/vc/*`. Elles utilisent le contenu VC versionné du dépôt et le stockage privé `NAGE_VC_HOME` (par défaut `~/.nage/vc`). Aucune donnée personnelle ni appel cloud n'est requis.

## Preuves observées

- Tests ciblés : **189 passed in 13,68 s**.
- Ruff sur le routeur et les tests : **All checks passed**.
- `node --check v5_static/v5.js` : OK.
- `git diff --check` : OK.
- Parcours navigateur synthétique : `Réviser VC` → session 5 min → révélation → `À revoir` ; le radar passe de `0 / 20` à `1 / 20`, avec une carte due.
- Examen blanc navigateur : 5 questions, minuteur affiché à `9:59`, réponses soumises, correction observée **60 / 100**, remédiation ciblée sur `VC07`.

## Plan de travail jusqu'à vendredi

1. Faire une session courte quotidienne sur les topics fragiles ou non testés ; ne pas regarder la correction avant d'avoir formulé une réponse.
2. Enchaîner un drill ou un cas sur chaque topic signalé fragile par le radar.
3. Faire un examen blanc chronométré sans documents, puis corriger les erreurs par catégorie (formule, unité, ordre, convention, données manquantes).
4. Utiliser les supports de cours autorisés pour compléter les cartes avec citations ; aucune réponse ne doit être inventée si la source manque.
5. Refaire un examen blanc la veille et consacrer la dernière session aux erreurs persistantes, pas à la relecture passive de tout le cours.

## Limites actuelles

L'export PDF et le tuteur RAG à partir de PDF ne sont pas encore raccordés à l'écran V5. Ils constituent le prochain lot produit, après validation du choix de stockage et des supports de cours autorisés.
