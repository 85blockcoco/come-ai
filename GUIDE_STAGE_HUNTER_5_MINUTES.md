# CAREER STAGE HUNTER — DÉMARRER EN 5 MINUTES

Pas besoin de compétences techniques. Il suffit d'un navigateur sur ton Mac.

---

## 1. Ouvrir Career

1. Lance Côme AI comme d'habitude.
2. Dans ton navigateur, ouvre : **http://127.0.0.1:8765/career** (si tu choisis un autre port au lancement, remplace `8765`).
3. Clique sur l'onglet **Stage Hunter** (entre « Découvrir » et « Candidatures »).

## 2. Définir mes critères (Étape A)

Tout est facultatif : ne remplis que ce qui compte pour toi, rien n'est supposé à ta place.

- **Domaines de la finance** : coche ce que tu vises (M&A, Corporate Finance, Private Equity, Transaction Services, Audit financier, Asset Management, FP&A…). Tu peux aussi décrire tes propres métiers dans « Autres métiers financiers ».
- **Pays / Villes** : tape des villes ou pays séparés par des virgules (ex. `Paris, Lyon`).
- **Date de début** et **Durée minimale** : quand tu veux commencer et combien de mois au minimum.
- **Niveau d'études** (ex. `Master 2`) et **Langues** (ex. `anglais C1`).
- **Contraintes** : écris en phrase libre ce qui compte (ex. « pas de mobilité internationale »).
- **Préférences de classement** : pour chaque critère, un poids de 0,5 à 2. Exemple : mettre `2` sur « Domaine » fait compter le domaine deux fois plus que les autres critères dans le classement.

Clique **« Enregistrer mes critères »**. Ils restent sur ton Mac.

## 3. Configurer les sources d'offres (Étape B)

Career ne lit que des pages d'offres **publiques** que toi-même ajoutes. Pas de compte, pas de clé API, pas d'accès à LinkedIn.

1. Va sur le site carrières d'une entreprise que tu vises (banque, fonds, cabinet…).
2. Récupère l'adresse du **board**, par exemple `https://boards.greenhouse.io/stripe` ou `https://job-boards.greenhouse.io/stripe`. Si tu es sur une offre avec une adresse terminant par `/jobs/123`, utilise l'adresse du board sans cette fin. Tu peux aussi saisir son **identifiant exact** (`stripe` dans cet exemple) ; ce n'est pas nécessairement le nom de l'entreprise. Les autres sites ne sont pas reconnus par ce connecteur.
3. Dans Career, clique sur **« Configurer mes sources »** (ou l'onglet Découvrir).
4. Colle l'adresse (ou le nom), donne le nom de l'entreprise, puis **« Ajouter ce board officiel »**.
5. Reviens dans Stage Hunter. Tu peux ajouter jusqu'à 8 entreprises.

## 4. Trouver les offres (Étape B → C)

1. Dans Stage Hunter, clique **« Lancer une recherche sur mes boards »**.
2. Career lit les offres **publiquement publiées** par ces boards et les enregistre localement, avec : le titre, l'entreprise, la localisation quand elle est publiée, le **lien réel de candidature**, la source et l'heure de vérification.
3. Une recherche est gardée 10 minutes (cache) ; dans « Découvrir », le bouton **« Actualiser malgré le cache »** force une nouvelle lecture. Après un changement de critères, relance la recherche pour sélectionner à nouveau les meilleures offres du flux complet.
4. **Étape C** affiche le classement : chaque offre montre son score **avec la raison de chaque point** (domaine, métier, localisation, dates, durée, niveau, langues) et les avertissements (annonce peut-être fermée, contrat permanent, date limite dépassée…). Une information absente de l'annonce reste « à vérifier » — rien n'est inventé.

Astuce : les termes de recherche suggérés sous l'Étape B sont là pour tes recherches manuelles sur les sites officiels ; Career n'envoie aucune requête depuis cette liste.

## 5. Importer une offre manuellement

Pas de lien Greenhouse sous la main ?

1. Onglet **Découvrir** → section **« Importer une offre »**.
2. Colle les informations de la page officielle (entreprise, titre, URL officielle, description…). L'URL officielle est obligatoire : c'est elle qui te mènera au dépôt réel.
3. Career détecte les doublons (une même offre importée deux fois reste une seule offre) et conserve la date d'import.

## 6. Préparer ma candidature (Étape D)

1. Choisis une offre dans la liste (ou clique « Préparer cette candidature » sur une carte en Étape C).
2. Career compare les **exigences de l'offre** à **ton profil** (onglet Mon profil : compétences, expérience, formation, langues) :
   - chaque élément pertinent **cite un extrait réel de ton profil** ;
   - ce qui n'est pas trouvé est écrit « **Non trouvé dans ton profil** » — jamais « tu n'as pas » ;
   - des suggestions de CV et des points pour ton message sont proposés, **sans rien inventer à ta place**.
3. Le lien officiel de candidature est toujours conservé tel quel : c'est toi qui déposes, sur le site de l'entreprise.

## 7. Enregistrer le suivi d'une candidature (Étape E)

1. Sur une offre, clique **« Créer un suivi »** : il démarre à **« À examiner »**.
2. Choisis le statut **À préparer**, puis **Prête**, et clique **« Mettre à jour »** à chaque étape. La note de suivi se saisit directement dans la page.
3. Avant d'enregistrer **« Envoyée »**, coche **« J’approuve le dépôt manuel pour cette offre uniquement »**, puis clique **« Approuver pour dépôt manuel »**. Tu déposes toi-même sur le site officiel, puis tu peux noter « Envoyée ».
4. Reçu un accusé ? Renseigne le champ **Référence de réception** (numéro ou référence d'e-mail), puis clique **« Confirmer la réception »** : le statut passe à « Réception confirmée ». La référence est une déclaration locale, pas une vérification de ta boîte mail.
5. Ensuite : **Entretien**, **Refusée** ou **Offre reçue**. Chaque changement peut porter une note.
6. **Côme AI n'envoie jamais de candidature ni d'e-mail à ta place.**

## 8. Ce qui fonctionne sans cloud

- Tes critères, tes offres, ton profil, ta shortlist et ton suivi restent dans la **base locale** de ton Mac.
- Le classement, la préparation et le suivi fonctionnent **sans IA** et sans aucune API payante.
- Seule sortie réseau : la **lecture** des boards Greenhouse publics que tu as ajoutés (requêtes anonymes, en lecture seule).
- L'onglet Réglages propose des exports locaux. N'utilise pas la réinitialisation pour commencer : elle efface tes données Career.

## 9. Limites actuelles (honnêteté)

- **Sources** : uniquement les boards Greenhouse publics que tu ajoutes + imports manuels. Pas de Welcome to the Jungle, pas de LinkedIn, pas de Pôle emploi.
- **Classement lexical** : les offres sont reconnues par leurs mots (français et anglais), pas par une vraie compréhension du sens. Une annonce au libellage excentrique peut être sous-classée — lis les raisons affichées et corrige si besoin.
- **Statut des offres** : une offre importée porte le statut qu'affichait sa source au moment consulté (« ouverte » si elle figurait dans le flux public du jour, « à vérifier » sinon). Vérifie toujours sur la page officielle avant de postuler : les annonces vieillissent.
- **Volumes** : au plus les 150 offres admissibles les mieux classées par board et par recherche, après évaluation selon tes critères explicites. La sélection est déterministe ; les sources trop volumineuses sont refusées plutôt que lues sans limite. Une absence du top 150 ne prouve pas qu'une ancienne offre est fermée.
- **Localisation** : certaines entreprises publient des localisations composées (ex. « London OR Paris ») ; la formulation d'origine est conservée telle quelle.
- Le dépôt de candidature reste **manuel** et se fait sur le site de l'entreprise.

---

En cas de problème : conserve tes données et consulte le message de recherche. Les imports manuels restent disponibles si le board public est indisponible.

## Commande de lancement

Depuis un Terminal :

```bash
cd /Users/comedelavenne/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py --port 8765 --no-browser
```

Ouvre ensuite `http://127.0.0.1:8765/career#career/stagehunter`. Si un serveur existe déjà sur ce port, ne lance pas une seconde instance ; utilise le serveur existant ou choisis un port libre. Career ne nécessite aucun appel à Gemini ou OpenRouter pour ce parcours.
