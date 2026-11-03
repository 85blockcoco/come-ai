# P0 candidature facile — recette actualisée au 27 octobre 2026

**Verdict actuel : parcours navigateur en trois interactions VALIDÉ sur fixture synthétique isolée.**

Le verdict négatif du 26 octobre portait sur le snapshot UI `f8344ba`. Il est
conservé plus bas comme historique, mais il ne décrit plus la candidate
`codex/v3-stable-consolidation` depuis le correctif `5d44474`.

## Preuve navigateur fraîche

- Candidate : `c0be89df45d7a1f7cd424fb312a9ce7923b936ae`.
- Serveur Uvicorn isolé : `127.0.0.1:18927`.
- Base temporaire distincte : une offre, un profil et un dossier explicitement
  synthétiques ; fournisseur de modèle simulé.
- État de départ observé : « Dossier à préparer », action « Préparer en anglais ».
- Aucun kit n'avait été généré par API avant cette seconde recette fraîche.

| Interaction humaine | Résultat observé |
|---|---|
| 1. `Préparer en anglais` | Modal complet en 468 ms : CV, lettre, quatre exports, réponses, guide, provenance et avertissement « aucun envoi automatique » |
| 2. `J’ai relu mon dossier · Ouvrir le site officiel` | Revue de la version exacte enregistrée ; bouton de confirmation activé ; destination officielle ouverte dans un onglet séparé |
| 3. `J’ai envoyé ma candidature` | Déclaration synthétique enregistrée localement ; navigation automatique vers Suivi ; une ligne « envoi déclaré » et une date de relance apparaissent |

Après l'interaction 3 :

- `consoleIssues = 0` pour les niveaux erreur et avertissement ;
- la page Suivi contient exactement le dossier synthétique ;
- l'API locale expose `stage=submitted` et un seul suivi ;
- après arrêt réel puis redémarrage d'Uvicorn sur la même base temporaire, la
  ligne et l'état « envoi déclaré » sont toujours présents ;
- aucune requête de soumission de formulaire n'a été effectuée par Côme AI.

Le clic 2 a chargé en lecture seule la page publique correspondant à la
destination officielle de la fixture. Aucune donnée personnelle, document,
champ de formulaire ou candidature ne lui a été transmis. Le clic 3 a agi
uniquement sur l'API locale de la fixture.

Preuve structurée :
`docs/agent-reports/p0-e2e-2026-10-27/browser-three-interactions.json`.

## Responsive NAGE Studio

La page Candidatures a aussi été mesurée à `390 × 844` :

- `innerWidth = body.scrollWidth = documentElement.scrollWidth = 390` ;
- aucun débordement horizontal ;
- tous les boutons visibles ont un nom accessible ;
- `theme=studio` et le choix persiste après rechargement.

## Tests ciblés rejoués

```text
python -m pytest -q tests/test_desktop_app.py \
  tests/test_career_manual_destination.py tests/test_send_confirmation.py
34 passed in 13.86s (temps réel 15.09s)
```

`node --check desktop_static/app.js`, Ruff sur Career et les trois fichiers de
tests, puis `git diff --check` sont également verts. Aucune suite complète n'a
été lancée pendant que les autres workers utilisaient la machine.

## Historique du constat corrigé

Le snapshot `f8344ba` échouait réellement le 26 octobre : `prompt()` non pris
en charge, mauvais canal `site`, écran Suivi non dispatché, absence de revue de
version et débordement mobile. Ces défauts avaient alors conduit au verdict
« non validé ». La recette fraîche ci-dessus démontre que la candidate actuelle
ne reproduit plus ces blocages ; elle ne prétend pas valider une candidature
réelle ni la réception par un employeur.
