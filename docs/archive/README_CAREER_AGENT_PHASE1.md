# Côme AI Career 4.1

> Le nom de ce fichier est conservé pour les anciens raccourcis. Son contenu
> documente bien **Career 4.1**.

Côme AI Career est l’espace personnel local de Côme AI V3 pour organiser une
recherche de stage, préparer un dossier de candidature et s’entraîner aux
entretiens. Il ne remplace pas une vérification humaine et n’envoie jamais une
candidature à ta place.

Le parcours normal ne nécessite ni Gemini ni une autre IA distante : profil,
OCR, matching, brouillons locaux, exports et Interview Coach fonctionnent sur
ce Mac. Le mode IA facultatif de l’Application Studio reste séparé et ne peut
partir qu’après une confirmation explicite.

## Démarrer

Depuis Finder, double-clique :

[`Lancer Côme AI V3.command`](Lancer%20C%C3%B4me%20AI%20V3.command)

Ou utilise Terminal :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py
```

L’application s’ouvre désormais sur `http://127.0.0.1:8765/v5`. Ouvre ensuite
`http://127.0.0.1:8765/career`, ou clique sur **Career** depuis la barre de
navigation. L’interface V3 historique reste sur `http://127.0.0.1:8765/`.
Le serveur est limité à ce Mac ; garde la fenêtre Terminal ouverte pendant
l’utilisation et utilise `Ctrl+C` pour l’arrêter.

## Ce que Career 4.1 fait réellement

| Espace | Fonctionnement actuel |
|---|---|
| **Dashboard** | Réunit les offres, dates à vérifier, suivis, brouillons et séances actives. Son plan d’action priorisé est calculé à partir de l’état local réel ; il ne déclenche aucune recherche, IA ou candidature. Les recommandations restent un score explicable sur les faits connus, jamais une probabilité de recrutement. |
| **Discover** | Ajoute une offre manuellement ou configure un board public Greenhouse. La lecture est manuelle, limitée au board choisi, temporisée et mise en cache dix minutes. |
| **Applications** | Conserve un suivi local par offre et exige une validation explicite avant de noter une réception réellement confirmée. |
| **Application Studio** | Produit un CV et une lettre factuels en français, anglais, italien ou allemand. Exports disponibles : Markdown, HTML, DOCX et PDF. |
| **Interview Coach** | Entraînement textuel local, persistant et déterministe : questions techniques, fit, case et liées à une offre ; feedback, axes de révision et historique adaptés au français, anglais, italien ou allemand choisi. |
| **Profile** | Stocke le profil que tu valides, importe un CV ou un export de profil local et propose un mini-entretien de recherche. |
| **Settings** | Modifie familles de métiers, villes, période de disponibilité et durée recherchée ; exporte les données, un calendrier `.ics` d’échéances ou supprime les seules données Career gérées. |

## Profil, CV et OCR local

Dans **Profile**, renseigne les informations que tu acceptes de conserver :
formation, expériences, compétences, langues, coordonnées facultatives,
entreprises ciblées et éligibilité déclarée.

Pour un CV ou un export de profil :

1. Ouvre **Importer mon CV ou un export LinkedIn**.
2. Choisis un PDF, DOCX, TXT ou Markdown local, ou colle le texte que tu as le
   droit d’utiliser.
3. Career lit le contenu localement. Si le PDF n’a pas de texte, l’OCR Apple
   Vision est tenté localement, avec une limite de huit pages et 55 secondes.
4. Vérifie le brouillon, modifie les propositions et coche uniquement les
   champs à appliquer.

Le profil n’est jamais modifié automatiquement. L’outil ne se connecte pas à
LinkedIn, ne lit pas de cookie, mot de passe, session ou CAPTCHA et ne fait pas
de scraping. Une URL LinkedIn est une référence locale uniquement. Pour
importer des données LinkedIn, fournis toi-même un export ou du texte copié.

Les éléments sensibles que l’application ne doit pas deviner — nationalité,
visa, âge, éligibilité ou disponibilité — restent déclaratifs.

## Découvrir des opportunités

### Board Greenhouse public

Dans **Discover**, ajoute le nom de l’entreprise et son URL de board public,
par exemple `https://boards.greenhouse.io/entreprise`. L’application accepte
seulement un identifiant Greenhouse validé et contacte l’API publique
Greenhouse lorsque tu cliques sur **Rechercher des opportunités**.

Elle ne contacte pas un board au démarrage, applique des délais, un nombre
borné de tentatives et un cache de dix minutes. Les descriptions HTML sont
converties en texte inerte avant stockage. Chaque résultat conserve l’URL
officielle et l’heure de dernière vérification.

Cette V4.1 ne propose pas de recherche générale sur le web, de connecteur Lever,
d’accès à des comptes, ni de recherche LinkedIn. Aucun board réel n’a été
interrogé pendant les tests de livraison : le connecteur a été vérifié contre
un transport simulé local.

### Offre importée manuellement

Tu peux aussi copier les informations d’une offre que tu as obtenue légalement.
Career déduplique d’abord via l’URL officielle, puis avec entreprise, poste et
ville. Les dates absentes, la langue ou l’éligibilité non annoncées restent
**à vérifier**. Une modification de ta période de disponibilité ou de la durée
recherchée requalifie les offres enregistrées.

Le score de pertinence explique les facteurs métiers, compétences, localisation,
disponibilité, éligibilité, entreprise et langues. Il sert à trier et à
identifier ce qu’il faut vérifier ; il ne prédit jamais une réponse ou un
recrutement.

### Plan d’action local

Le tableau de bord transforme ton suivi en prochaines étapes lisibles : profil
incomplet, mini-entretien à terminer, source/offres à ajouter, échéances sous
sept jours, informations à vérifier, brouillons à relire, dépôt manuel validé,
réception inconnue ou séance active. Les éléments sont recalculés et bornés à
partir de données déjà présentes. Une étape **Ouvrir** change uniquement de
vue : elle ne contacte pas un board, un modèle, un calendrier ou un site de
candidature.

## Préparer une candidature

Dans **Applications**, crée un suivi local depuis une offre. Le bouton
**Préparer un dossier** ouvre l’Application Studio.

Le mode **Gabarit local factuel** construit un CV et une lettre depuis les
faits validés du profil, les réponses au mini-entretien et l’offre choisie. Il
laisse un repère `[à compléter]` lorsqu’une information manque : il n’invente
ni expérience, ni diplôme, ni résultat, ni compétence.

Tu peux télécharger chaque brouillon en :

- Markdown ou HTML modifiable ;
- DOCX éditable ;
- PDF A4 prêt à relire ou imprimer.

Les exports DOCX/PDF ne contiennent ni macro, ni lien externe, ni script. Ils
sont créés dans l’espace Career privé. Relis toujours le résultat avant usage.

### Calendrier d’échéances

Dans **Réglages → Mes données Career**, le bouton **Télécharger les échéances
(.ics)** crée un fichier calendrier local. Il comprend seulement les dates
limites connues, aujourd’hui ou futures, d’offres encore actionnables. Les
offres fermées, archivées ou déjà passées à une candidature confirmée, à une
réponse ou à un entretien sont exclues. Tu peux importer ce fichier dans ton
calendrier si tu le souhaites ; Career ne se synchronise pas avec un calendrier
et ne crée ni rappel distant ni candidature automatique.

Le mode **Amélioration par IA configurée** n’est pas obligatoire. Avant tout
appel, l’interface demande de cocher le consentement : seules les données
Career nécessaires (profil, mini-entretien et offre choisie) peuvent alors être
transmises au fournisseur configuré. Cette option peut consommer le quota et
rencontrer une indisponibilité fournisseur ; elle ne se déclenche jamais par
défaut, pendant l’import d’un CV ou pendant la découverte d’offres.

## Suivi et dépôt manuel

Career ne préremplit aucun formulaire distant et n’a aucune route de
soumission. **Approuver pour dépôt manuel** ne soumet rien : il enregistre
seulement ton intention locale pour cette offre précise.

Après ton dépôt manuel sur le site officiel, tu peux inscrire une preuve réelle
de réception (e-mail, référence ou numéro de dossier). Si la réception est
incertaine, utilise **Réception inconnue**. L’outil ne renverra jamais une
candidature automatiquement.

## Interview Coach local

Dans **Interview Coach**, choisis :

- le mode : Technical Interview, Behavioral / Fit, Case ou Company Specific ;
- le niveau : débutant, intermédiaire, avancé, Investment Banking, Private
  Equity ou Highly Competitive ;
- la langue : français, anglais, italien ou allemand ;
- éventuellement une offre enregistrée pour donner le contexte de titre et
  d’entreprise.

Le coach choisit une question dans une banque locale et analyse la réponse
avec des règles transparentes de couverture, précision, structure, clarté et
pertinence. Il stocke la réponse, le feedback et les priorités de révision dans
la séance locale. Le score décrit uniquement la réponse à cet exercice : il ne
mesure ni ta compétence réelle ni tes chances de recrutement.

Les libellés de question, de feedback, de score, de priorité et l’avertissement
restent dans la langue choisie pour la séance. Les termes de finance restent
ceux du métier quand cela est plus clair ; aucune traduction ni IA externe ne
part pendant l’entraînement.

Il n’utilise ni modèle distant, ni microphone, ni caméra. Il n’est donc pas un
simulateur vocal et ne prétend pas être un recruteur.

## Données privées, export et suppression

Les données Career sont séparées de `data/` et `output/` de l’agent
Excel/documents :

```text
career_data/
├── career.sqlite3                 # profil, offres, suivi, drafts et séances
├── documents/                     # CV / exports de profil privés
├── application_studio/            # exports Markdown, HTML, DOCX et PDF
├── exports/                       # CSV / XLSX / JSON / calendriers .ics
├── backups/                       # snapshots SQLite privés avant migration
└── ocr/                           # helper Apple Vision local
```

Le dossier est ignoré par Git et créé avec des permissions restrictives lorsque
macOS le permet. Il n’est jamais indexé par le chat général. Avant une migration
de base existante, Career utilise l’API SQLite pour créer un snapshot vérifié
dans `backups/`, en permissions propriétaire uniquement, puis seulement ensuite
modifie le schéma. Si ce snapshot ne peut pas être créé, la migration s’arrête
sans toucher la base. Dans **Settings**, tu peux exporter une copie JSON ou
supprimer les données Career gérées, y compris les snapshots créés par Career,
après avoir saisi la phrase de confirmation demandée. Cela ne touche ni les
fichiers d’analyse, ni les rapports Excel, ni les anciens prototypes.

Comme toute application locale sans compte utilisateur, Career suppose que la
session macOS est de confiance. Ne partage pas cette session ou son dossier
Career lorsque tes données personnelles sont ouvertes.

## Vérifier sans quota ni réseau

Depuis le dossier du projet :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Ces vérifications sont locales. Elles utilisent des bases temporaires et des
transports simulés : elles ne lisent pas la clé API, n’appellent pas Gemini,
Ollama, LinkedIn, Greenhouse ou une entreprise. À cette livraison V4.1, les
**59 tests** hors ligne, le parcours local du coach dans l’interface et le
rendu visuel d’exports DOCX/PDF temporaires ont été validés.

## Limites connues

- Un board Greenhouse réel reste à essayer volontairement depuis ton Mac, une
  fois que tu auras choisi une entreprise ; il s’agit d’un appel réseau public.
- Aucun connecteur LinkedIn, Lever ou portail privé n’est inclus.
- Les réponses et brouillons restent à relire ; l’application ne garantit ni
  exactitude complète ni résultat de candidature.
- L’OCR est borné aux PDF de profil et dépend de macOS Vision / des Command
  Line Tools Apple.
- Gemini et Ollama n’ont pas été appelés durant la validation finale. Le mode
  IA optionnel doit donc être essayé séparément, avec une demande courte et
  non sensible lorsque tu le souhaites.

## Architecture utile

```text
come_ai_web.py
└── /api/career/*
    └── career/service.py
        ├── SQLite locale et règles métier
        ├── career/discovery.py       # Greenhouse public borné
        ├── career/scoring.py         # score déterministe explicable
        ├── career/profile_import.py  # CV / profil + relecture
        ├── career/ocr.py             # Apple Vision local
        ├── career/application_studio.py
        ├── career/document_export.py # Markdown / HTML / DOCX / PDF
        ├── career/calendar_export.py # export .ics local d’échéances
        └── career/interview.py       # coach textuel local
```

L’interface reste dans `career_static/`, séparée de l’espace Analyse &
documents de V3. Cette séparation empêche le modèle général d’obtenir un accès
arbitraire aux fichiers Career ou d’exécuter du code sur le Mac.
