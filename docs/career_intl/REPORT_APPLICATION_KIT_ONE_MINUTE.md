# RAPPORT — CVBOOST-05 : Kit de candidature local en moins d'une minute

Date : 2026-10-20 · Branche : `agent/cvboost-05` · Statut : implémenté, tests verts.

## 0. Ce qui existait déjà (réutilisé, pas dupliqué)

- `career/application_studio.py` : gabarits factuels CV/lettre localisés (fr/en/it/de), sections factuelles du profil + mini-entretien + offre.
- `career/document_export.py` : exports DOCX/PDF/MD/HTML purement locaux (aucun contenu exécutable ni ressource distante).
- Événements de candidature existants : `application_events` (`application_created`, `stage_updated`, `manual_submission_approved`, `receipt_confirmed`, `receipt_unknown`) et table `application_drafts`.
- Suivi idempotent : `CareerService.create_application(job_id)` crée `to_review` une seule fois par offre.
- Vérificateur de faits déterministe : `career/application_prep.py` (`prepare_application` → `unverified_elements`, preuve = extrait verbatim du profil).

## 1. Décision « schéma ou événements JSON ? »

**Aucun changement de schéma.** Les événements JSON suffisent : les textes éditables du kit
(motivation courte, disponibilité) sont persistés dans `application_events` avec
`event_type = "kit_content"` et un `detail` JSON validé. Chaque enregistrement est un delta
partiel ; la lecture rejoue les événements dans l'ordre (`created_at ASC, rowid ASC`), donc
la dernière sauvegarde gagne champ par champ, et l'historique reste auditable.
Un test statique verrouille les colonnes des tables `applications`, `application_events`
et `application_drafts` (pas de colonne ajoutée, pas de migration).
Le point d'arrêt prévu par la mission (« sinon arrêter et documenter ») n'a pas été déclenché.

## 2. Nouveautés back-end

### 2.1 `career/application_studio.py`
- `build_kit_texts(profile, intake, job, language)` : motivation courte + disponibilité, générées localement avec exactement les mêmes sections factuelles que le CV/lettre (aucune invention, placeholders entre crochets). La disponibilité cite verbatim la réponse `constraints` du mini-entretien, marquée « À relire », ou reste un placeholder explicite.
- `scan_kit_placeholders(texts)` : passe locale du vérificateur de faits — chaque marqueur croché restant est remonté comme « à compléter avant usage ».
- `KIT_TEXT_FIELDS` / `KIT_TEXT_LIMITS` (motivation ≤ 1 200, disponibilité ≤ 400).

### 2.2 `career/service.py`
- `create_application_kit(job_id, language)` — **UNE action utilisateur explicite** :
  1. suivi créé si nécessaire via `create_application` (idempotent, événement `application_created` unique) ;
  2. brouillon local (offre, langue) créé **une seule fois** puis réutilisé ;
  3. événement `kit_prepared` (JSON : draft_id, langue, mode) enregistré à la première préparation.
  Réponse enrichie des drapeaux `created_tracking` / `created_draft`.
- `get_application_kit(application_id, language)` : assemblage lecture seule — application, brouillon le plus récent **dans la langue demandée sinon le dernier brouillon local**, textes du kit (générés + éditions rejouées), faits à copier-coller (titre, entreprise, référence `jobs.source_id`, URL officielle, date limite), vérificateur de faits (placeholders + `unverified_requirements` via `prepare_application`), contrôles d'honnêteté et avertissement « envoi strictement manuel ».
- `update_kit_texts(application_id, texts)` : sauvegarde partielle validée (texte lisible, limite de taille, entrée doit être un dict) → événement `kit_content` JSON + audit.
- `update_application_draft(draft_id, cv, letter)` : correction humaine du brouillon avant export (non vide, borné à `MAX_DRAFT_CHARS`, audit `application_draft_edited`). Les exports DOCX/PDF/MD/HTML lisent la version relue.

### 2.3 `career/router.py`
- `POST /api/career/application-kits` `{job_id, language}` (un clic = un kit pour UNE offre).
- `GET /api/career/applications/{id}/kit?language=fr`.
- `PATCH /api/career/applications/{id}/kit` `{motivation_short?, availability?}`.
- `PATCH /api/career/application-drafts/{draft_id}` `{cv_markdown, letter_markdown}`.

## 3. Front-end (`career_static/`)

- **Stage Hunter** : bouton « Préparer le kit de candidature » + sélecteur de langue (fr défaut). Un clic enchaîne : création du suivi si nécessaire → kit prérempli → ouverture dans l'onglet Candidatures avec le panneau kit déplié (`state.pendingKitApplicationId`).
- **Candidatures** : chaque carte expose « Ouvrir le kit de candidature » puis un panneau kit :
  - faits copiables (Poste, Entreprise, Référence offre, URL officielle, Date limite) avec bouton « Copier » ;
  - documents : CV + lettre **modifiables** (textareas) avec « Enregistrer les corrections du dossier », puis exports DOCX/PDF (les exports utilisent la version relue) ;
  - réponses types (motivation courte, disponibilité) éditables, sauvegarde partielle ;
  - « Vérificateur de faits local » : marqueurs ouverts + exigences non étayées « Non trouvé dans ton profil » + rappels d'honnêteté.
- **Presse-papiers** : `copyKitValue()` n'est appelée QUE depuis un écouteur de clic. `navigator.clipboard` indisponible (CSP, contexte non sécurisé) ou promesse refusée → message de repli « sélectionne le texte et copie-le » ; aucun `document.execCommand`, aucun `mailto:`, aucune transmission réseau. CSP existante inchangée (`connect-src 'self'`).

## 4. Garde-fous maintenus

- Une action explicite par création (bouton) ; pas de boucle de candidatures (le double clic réouvre le même kit : 1 suivi, 1 brouillon, 1 événement `kit_prepared`).
- Envoi strictement manuel : aucune route d'envoi n'existe (test statique sur toutes les routes du routeur + absence de `smtplib`/`requests`/`urllib`/`http.client` dans le service + absence de `mailto:` côté JS).
- Tout langage invalide, texte vide/trop long, application ou offre inconnue → `UserFacingError` en français.

## 5. Couverture (tests synthétiques, offline)

`tests/test_career_application_kit.py` — 17 tests :

1. Création idempotente du suivi et du brouillon (drapeaux `created_*`).
2. Double clic : 1 suivi, 1 brouillon, 1 événement.
3. Champs préremplis exacts depuis l'offre (titre, entreprise, référence, URL, date limite) + aucun fait exigé revendiqué.
4. Portée : le kit d'une offre ne touche pas les autres offres (aucun suivi/brouillon fantôme).
5. Langue conservée par choix explicite (fr/en séparés, réouverture idempotente).
6. Profil vide : placeholders crochets, aucun fait inventé, champs manquants signalés.
7. Exigence non étayée (LBO/private equity absents du profil) : listée « Non trouvé dans ton profil », jamais revendiquée dans la motivation.
8. Éditions des textes du kit : rechargement, delta partiel, 2 événements `kit_content`.
9. Validation : vide, blanc, trop long, dict invalide, application inconnue.
10. Correction du brouillon → exports MD/DOCX/PDF vérifiés (contenu relu, signature %PDF, ZIP Word).
11. Échec d'export → `UserFacingError` français, aucun fichier partiel laissé.
12. Parcours HTTP complet (TestClient) : profil → offre → kit → réouverture → textes → corrections → 4 exports → refus de texte trop long.
13. Preuve statique : aucune route d'envoi/courriel (`send|mail|smtp|transmit`), langage interdit absent du service, pas de `mailto:` côté client.
14. Preuve statique : schémas des trois tables inchangés.
15. Copie presse-papiers : débranchée au chargement, branchée au clic, repli manuel documenté.
16-17. Comportements `copyKitValue` exécutés **réellement dans Node** (clipboard indisponible → repli ; résolu → « Copié. » ; refusé → repli ; valeur vide → rien n'est écrit).

## 6. Limites connues

- La « référence » provient de `jobs.source_id` (manuel : souvent vide → « À compléter (voir l'offre officielle) »).
- La disponibilité préremplie à partir de `constraints` reste un texte « à relire » : c'est un point pratique déclaré, pas une disponibilité vérifiée.
- Le kit ne gère qu'un brouillon par (offre, langue) : « régénérer » passe par l'Application Studio (action distincte explicite).
- Un parcours réel dans un navigateur graphique n'est pas exécuté dans la suite (aucun driver téléchargé) ; le comportement JS est vérifié par exécution Node réelle du code client.

## 7. Validation

```text
python -m pytest tests/test_career_application_kit.py  → 17 passed
ruff check                                             → All checks passed!
python -m pytest -q (suite complète)                   → en cours d'exécution lors du rendu (consignée dans le commit)
```
