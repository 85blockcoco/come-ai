# Parcours rapide — import du CV

## Livraison

Le tableau de bord propose maintenant « Importer mon CV ». Le raccourci ouvre la vue Profil puis place le focus sur le champ de fichier. Il ne lance aucun traitement sans action de l'utilisateur : la lecture reste locale et l'aperçu doit être relu et approuvé.

## Vérifications

- `node --check career_static/career.js` : succès.
- Tests UI ciblés : `13 passed in 2.43s`.
- Suite complète : `1098 passed in 116.19s`.
- Aucun appel cloud, aucune donnée personnelle et aucune modification de schéma.

## Limite

Le raccourci réduit les clics mais ne constitue pas à lui seul une validation de la qualité OCR/extraction sur un CV réel. Cette validation doit rester une étape séparée, avec aperçu et approbation.

