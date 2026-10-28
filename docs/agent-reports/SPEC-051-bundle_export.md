# SPEC-051 — Export groupé ZIP et copie du dossier en un clic

**Statut :** livré (branche `agent/spec-051-bundle_export`)
**Priorité :** P1
**Périmètre :** interface bureau `desktop_static/`, route locale `/api/career/...`
**Données :** offre et profil synthétiques uniquement ; aucun envoi automatique

## Objectif

Le modal « Dossier prêt » exposait quatre téléchargements séparés (CV et lettre,
en PDF et DOCX) mais aucune action groupée. La personne devait cliquer quatre
fois, puis recomposer le dossier à la main pour le coller dans un formulaire ou
un e-mail. SPEC-051 ajoute deux gestes uniques :

1. **Tout télécharger (.zip)** — une archive déterministe contenant les quatre
   pièces et un `dossier.txt` lisible ;
2. **Copier le dossier** — le même contenu (offre, readiness, variante,
   réponses, lettre, CV, checklist) dans le presse-papiers, avec retour visuel
   « copié ✓ ».

## Livrables

| Fichier | Rôle |
|---|---|
| `career/bundle_export.py` | `render_bundle_text()` et `write_bundle_archive()` — fonctions pures, sans réseau |
| `career/apply_kit.py` | expose `draft_id` dans `ApplyKit` (dernier champ, rétrocompatible) |
| `career/service.py` | `build_apply_kit_bundle()` : réutilise les exports existants, écrit l’archive, trace l’audit |
| `career/router.py` | `GET /api/career/apply-kit/{job_id}/bundle.zip` (`FileResponse`, `no-store`) |
| `desktop_static/app.js` | boutons « tout télécharger (.zip) » et « copier le dossier », `kitBundleText()`, retour de copie |
| `desktop_static/app.css` | barre d’actions `.bundle-actions` |
| `tests/test_apply_kit_bundle.py` | 7 tests : texte, archive, traversée de chemin, service, endpoint, nommage, câblage UI |
| `docs/agent-reports/SPEC-051-bundle_export.md` | ce rapport |

## Décisions

- **Pas de bibliothèque ZIP côté navigateur.** Le serveur local assemble déjà
  des DOCX/PDF ; le ZIP est écrit côté Python avec les mêmes fichiers que les
  liens unitaires. Aucun CDN, aucun `npm install`, aucune dépendance nouvelle.
- **Archive reproductible.** Les entrées ont des noms fixes (`cv.pdf`,
  `cv.docx`, `lettre.pdf`, `lettre.docx`, `dossier.txt`), un horodatage ZIP
  fixe (`1980-01-01`) et sont triées : deux exports du même dossier sont
  identiques octet pour octet.
- **Noms d’entrées validés.** `write_bundle_archive()` refuse tout nom contenant
  `/`, `\`, `..` ou vide. Le nom du fichier ZIP est assaini avec
  `re_sub_filename()` ; une offre malveillante ne peut pas écrire hors du
  dossier `application_studio`.
- **Copie et archive racontent la même histoire.** `render_bundle_text()` et
  `kitBundleText()` suivent le même plan ; tous deux rappellent que la
  candidature est déposée manuellement et qu’aucun envoi n’est automatique.
- **Aucun nouveau schéma SQLite, aucun changement de `schema_version`.** La
  route réutilise `build_apply_kit()` et `export_application_draft()`.
- **Retour de copie non bloquant.** `copyText()` accepte désormais un bouton
  optionnel, affiche « copié ✓ » pendant 1,6 s et conserve le libellé d’origine ;
  les appels existants (relances, réponses types) restent inchangés.

## Contrat HTTP

```http
GET /api/career/apply-kit/{job_id}/bundle.zip?language=fr&variant=m_a
200 application/zip
Content-Disposition: attachment; filename="dossier_Banque_de_Demo_Stagiaire_MA_xxxxxxxx.zip"
Cache-Control: no-store
```

- `400` si l’offre est inconnue ou si aucun brouillon local n’est disponible.
- Le ZIP contient toujours les mêmes cinq entrées ; aucune pièce vide.
- `dossier.txt` contient le titre, l’entreprise, le readiness, la variante, le
  lien officiel, les points à vérifier, les réponses, la lettre, le CV et la
  checklist humaine.

## Tests

### Tests automatisés ciblés

```text
$ .venv/bin/python -m pytest -q tests/test_apply_kit_bundle.py tests/test_apply_kit.py
12 passed in 6.29s

$ .venv/bin/python -m pytest -q tests/contract/test_kit_generation.py tests/contract/test_pipeline_api.py
4 passed in 1.54s

$ .venv/bin/python -m ruff check career/bundle_export.py career/apply_kit.py career/service.py career/router.py tests/test_apply_kit_bundle.py
All checks passed!

$ node --check desktop_static/app.js
JS syntax OK
```

Les 7 tests SPEC-051 couvrent : rendu texte, déterminisme de l’archive,
rejet de `../escape.txt`, présence des cinq pièces, endpoint + `400`, nommage
assaini pour `../../Stagiaire M&A` / `..\Banque/Démo`, et câblage UI.

### Test manuel CDP (Chrome headless via Playwright)

Scénario exécuté sur un serveur local jetable (`create_app(base_dir=tmp)`),
avec profil et offre synthétiques :

1. `PUT /api/career/profile` puis `POST /api/career/jobs/import` ;
2. `POST /api/career/apply-kit/{job_id}` pour créer le dossier ;
3. ouverture de `/app#applications`, clic sur « préparer » ;
4. clic sur « tout télécharger (.zip) », capture du téléchargement ;
5. clic sur « copier le dossier », lecture du presse-papiers.

Résultat réel :

```text
modal: True
zip_link_visible: True
copy_button_visible: True
zip_entries: ['cv.docx', 'cv.pdf', 'dossier.txt', 'lettre.docx', 'lettre.pdf']
zip_dossier_chars: 3286
copy_feedback: True                  # bouton passé à « copié ✓ »
clipboard_chars: 3121
clipboard_has_header: True           # « DOSSIER DE CANDIDATURE — Stagiaire M&A »
clipboard_has_manual_reminder: True  # « aucun envoi automatique »
console_errors: []
```

Capture : `spec051-modal.png` (hors dépôt, générée par le script CDP).

## Limites

- Le ZIP contient les documents **déjà générés** par le dossier ; il ne
  re-génère pas un CV différent. Toute correction passe par l’édition du
  brouillon existant, comme avant.
- La copie dépend de l’API presse-papiers du navigateur ; un repli
  `document.execCommand("copy")` est conservé pour les contextes non sécurisés.
- Aucune pièce n’est signée ni horodatée : l’archive est un assemblage local,
  pas une preuve de dépôt.
