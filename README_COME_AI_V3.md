# Côme AI V3 + Côme AI 5.0

> **Nouveau :** le même lanceur ouvre désormais [Côme AI 5.0](README_COME_AI_V5.md)
> sur `/v5`. C’est le nouveau espace local unifié : orchestration sans modèle,
> file de tâches persistante, mémoire SQLite/FTS5 avec citations et accès aux
> analyses Documents & Finance ainsi qu’à Career 4.1. L’interface historique
> V3 reste disponible sur `/` ; rien n’est supprimé ni migré automatiquement.

Côme AI V3 est une application personnelle d’analyse de fichiers qui tourne
dans le navigateur **sur ce Mac uniquement**. Son interface est servie sur
`http://127.0.0.1:8765` : elle n’est ni publiée sur Internet, ni partagée avec
un tiers par défaut.

Les anciens fichiers `agent.py`, `agent_v2.py` et `app_v3.py` ont été retirés
du dépôt (2026-10-20) : code mort, aucun raccourci ni test ne les utilisait.
La nouvelle interface web démarre via `run_come_ai_v3.py` et n’écrase jamais
un fichier source.

Une extension indépendante **Côme AI Career 4.1** est également incluse. Elle
s’ouvre depuis le bouton Career Agent ou sur `/career`. Son flux normal reste
local (profil, OCR, découverte contrôlée, score explicable, entretien, CV et
lettre) ; une amélioration par modèle ne peut partir qu’après une confirmation
explicite dans le Studio. Son guide est disponible dans
[`docs/archive/README_CAREER_AGENT_PHASE1.md`](docs/archive/README_CAREER_AGENT_PHASE1.md).

## Ce que V3 livre

- une interface web locale pour Safari, Chrome ou tout navigateur du Mac ;
- import contrôlé de fichiers Excel (`.xlsx`, `.xlsm`, `.xls`), CSV/TSV, PDF,
  Word (`.docx`), Markdown et texte ;
- inspection locale, statistiques, valeurs manquantes et rapport Excel sans
  appel à une IA ;
- un agent Gemini à outils contrôlés : le modèle ne peut appeler que la liste
  des fichiers, l’inspection, l’analyse, la recherche documentaire et la
  création d’un rapport ;
- plusieurs modèles Gemini configurables, avec attente progressive pour les
  erreurs transitoires ;
- un secours Ollama facultatif, utilisant **les mêmes outils contrôlés** si
  Ollama est déjà installé sur le Mac ;
- un plafond de 90 secondes et huit appels maximum par demande IA pour éviter
  les boucles d’essais qui épuisent un quota ;
- un import privé de CV, PDF/DOCX de profil ou texte LinkedIn dans Career
  Agent : lecture locale, suggestions à vérifier puis validation explicite,
  sans connexion ni scraping LinkedIn ;
- OCR Apple Vision local pour les PDF de CV scannés sans couche texte,
  jusqu’à huit pages ;
- mini-entretien Career local qui mémorise les critères de recherche ;
- découverte manuelle d’offres depuis des boards Greenhouse publics configurés
  par l’utilisateur, avec cache local, délais, retries bornés et score de
  pertinence explicable ;
- Application Studio : CV et lettre adaptés à une offre en français, anglais,
  italien ou allemand, avec un gabarit local factuel et export
  HTML/Markdown/DOCX/PDF ;
- Interview Coach local persistant (technique, fit, case et lié à une offre),
  sans modèle distant, avec feedback déterministe et adapté à la langue de la
  séance (français, anglais, italien ou allemand) ;
- un plan d’action Career local, priorisé à partir du profil, des offres,
  brouillons, suivis et séances réellement enregistrés ;
- un export calendrier `.ics` des seules échéances encore actionnables, sans
  synchronisation externe, ainsi qu’une sauvegarde SQLite privée avant toute
  migration future de l’espace Career ;
- amélioration IA de ces brouillons uniquement après consentement explicite,
  avec un budget de trois essais modèles maximum pour cette action ;
- journaux locaux nettoyés de clés API dans `logs/` ;
- une suite de tests hors ligne qui ne lit aucune clé réelle, ne contacte aucun
  modèle et n’écrit pas dans tes dossiers de données personnels.

## Sécurité et confidentialité

- Les fichiers sont copiés dans `data/`. Les originaux ne sont jamais modifiés.
- Chaque fichier importé est limité à 50 Mo et chaque envoi à 100 Mo au total,
  y compris si le navigateur ne fournit pas de taille annoncée.
- Tout rapport est créé dans `output/`, avec un nom unique.
- L’agent reçoit des identifiants de fichiers, jamais des chemins absolus.
- Aucun outil ne permet au modèle de lancer un terminal, du Python arbitraire,
  ou de lire les variables d’environnement.
- La création d’un fichier par une demande conversationnelle nécessite de
  cocher **« Autoriser la création d’un rapport pour cette demande »**. Le
  bouton local « Créer un rapport » est lui-même une confirmation explicite.
- Les extraits de document ne partent vers Gemini que si tu envoies une demande
  qui nécessite cet outil. Les calculs locaux seuls n’envoient rien au cloud.
- Ne partage jamais `.env`, `data/`, `output/` ou `logs/`.

## Première installation

Le venv et les bibliothèques Excel existent déjà. Il suffit de compléter les
dépendances web une fois :

```bash
cd ~/AI-Excel-Agent
source .venv/bin/activate
python -m pip install -r requirements-v3.txt
```

## Configurer Gemini sans afficher la clé

Crée le fichier local `.env` à partir de l’exemple :

```bash
cd ~/AI-Excel-Agent
cp .env.example .env
chmod 600 .env
```

Ouvre ensuite `.env` dans un éditeur local et remplis seulement la valeur de
`GEMINI_API_KEY=`. Ne colle pas la clé dans le navigateur, le chat, un script
ou un fichier partagé. L’application n’affiche jamais cette valeur.

Les modèles peuvent être adaptés sans modifier le code :

```dotenv
GEMINI_PRIMARY_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.5-flash-lite
AI_REQUEST_TIMEOUT_SECONDS=30
AI_RETRY_ATTEMPTS=3
```

La disponibilité exacte dépend de ton projet Gemini. Côme AI ne lance aucun
test API au démarrage ; elle essaie le modèle seulement lorsque tu envoies une
demande IA.

## Démarrer l’application

Méthode la plus simple : double-clique
[`Lancer Côme AI V3.command`](Lancer%20C%C3%B4me%20AI%20V3.command) dans Finder.
Le navigateur s’ouvre sur l’adresse locale. La fenêtre Terminal qui apparaît
doit rester ouverte pendant l’utilisation ; `Ctrl+C` l’arrête proprement.

Ou depuis Terminal :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py
```

Pour choisir un autre port local :

```bash
.venv/bin/python run_come_ai_v3.py --port 8876
```

L’application se lie volontairement à `127.0.0.1`, jamais à `0.0.0.0`, et ne
génère aucun lien public.

## Utiliser Côme AI

1. Ajoute un ou plusieurs fichiers à gauche. Ils sont copiés dans `data/`.
2. Sélectionne un fichier. Les boutons **Inspecter**, **Analyser** et **Créer
   un rapport** fonctionnent localement, sans modèle et sans quota Gemini.
3. Pour l’IA, écris une demande dans le panneau principal. Le fichier
   sélectionné est signalé au modèle, mais son contenu reste inaccessible tant
   que l’agent ne choisit pas un outil autorisé.
4. Les rapports Excel arrivent dans la section **Rapports créés** et peuvent
   être téléchargés depuis l’interface.

Pour suivre des offres de stage sans utiliser Gemini, clique sur **Career
Agent** dans l’en-tête. Les données de carrière sont isolées dans
`career_data/`, jamais dans `data/` ou `output/`. Les CV et exports de profil
importés dans Career Agent restent eux aussi dans ce répertoire privé : ils ne
sont pas proposés au chat général. Ils ne sont transmis à un fournisseur IA
que lorsque tu sélectionnes l’option d’amélioration IA, pour l’offre choisie,
et coches la confirmation correspondante.

Exemples de demandes utiles :

- `Inspecte le classeur sélectionné et explique toutes ses feuilles.`
- `Analyse les revenus, les coûts, les données manquantes et les anomalies.`
- `Cherche "échéance" dans les documents importés.`
- `Crée un rapport de statistiques pour la feuille Sheet1.`

Les observations financières sont descriptives ; elles ne constituent pas un
conseil d’investissement. Les écarts « début/fin » suivent l’ordre des lignes
du fichier : ils ne sont une tendance que si les données sont réellement
rangées de façon chronologique.

## Secours local Ollama — facultatif

Si tu installes plus tard Ollama et télécharges toi-même un modèle adapté à ton
Mac Intel, ajoute par exemple son nom dans `.env` :

```dotenv
OLLAMA_MODEL=nom-du-modele-deja-installe
OLLAMA_BASE_URL=http://127.0.0.1:11434/api/chat
```

V3 ne télécharge ni Ollama ni un modèle automatiquement. La rapidité dépendra
de la RAM et des performances du Mac Intel. En cas d’indisponibilité de Gemini,
le secours local peut néanmoins utiliser les mêmes outils Excel/documents
contrôlés. Par sécurité, `OLLAMA_BASE_URL` est refusée si elle ne pointe pas
vers `127.0.0.1`, `localhost` ou `::1` : l’application ne transmet jamais les
prompts ou extraits à un serveur Ollama distant.

## Vérifications effectuées hors ligne

À la livraison, ont été vérifiés sans clé ni appel réseau :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m pytest -q
```

La suite couvre notamment :

- import CSV, inspection, analyse et intégrité du fichier source ;
- rapports aux noms uniques et neutralisation des formules Excel injectées ;
- blocage déterministe d’écriture par l’agent sans consentement UI ;
- boucle Gemini simulée avec appel d’outil, rôle de réponse compatible avec le
  SDK installé et conservation de l’identifiant d’appel ;
- extraction/recherche dans un document Word et boucle d’outils Ollama simulée ;
- masquage de clé et gestion d’un quota `429` ;
- endpoint de santé qui n’expose que la présence d’une clé, jamais sa valeur ;
- interface HTTP : import, inspection, rapport, téléchargement et chat simulé.
- Career Agent : profil local, préférences, SQLite, imports manuels et boards
  Greenhouse simulés, dates, déduplication, score explicable, shortlist, suivi
  des candidatures, exports CSV/XLSX, import CV/profil local avec brouillon
  vérifiable, OCR Vision local, mini-entretien, Application Studio
  HTML/Markdown/DOCX/PDF, plan d’action, calendrier `.ics`, sauvegardes de
  migration et Interview Coach persistant multilingue.

## Ce qu’il reste à tester sur ton Mac

Ces éléments nécessitent ton vrai environnement et, pour le dernier, ta clé :

1. Double-cliquer le lanceur et vérifier l’ouverture dans Safari/Chrome.
2. Importer le classeur réel déjà présent puis essayer **Inspecter**,
   **Analyser** et **Créer un rapport**.
3. Essayer un PDF texte et un fichier `.docx` personnel ; puis, si tu le
   souhaites, une copie non sensible d’un PDF scanné pour vérifier l’OCR local.
4. Une fois seulement, envoyer une demande Gemini courte (par exemple
   `Liste les fichiers disponibles.`). Cela consommera une requête API.
5. Si tu as configuré Ollama, vérifier son secours séparément — il n’est pas
   installé ni démarré par cette V3.
6. Ouvrir **Career Agent**, importer une offre factice, créer un suivi puis
   vérifier les exports CSV/XLSX, calendrier `.ics`, DOCX/PDF et une séance de
   l’Interview Coach.
   Ces vérifications ne consomment aucune requête Gemini.
7. Dans **Profil local**, importer une copie non sensible d’un CV TXT/PDF ou
   coller quelques lignes de profil ; vérifier les suggestions, puis supprimer
   la source depuis Career Agent si tu ne souhaites pas la conserver.
8. Dans **Application Studio**, importer une offre factice, répondre à une ou
   deux questions du mini-entretien, puis créer le gabarit local. Il ne
   consomme aucune requête Gemini. Pour tester l’option IA, coche le
   consentement une seule fois avec une offre non sensible : cette action peut
   consommer jusqu’à trois tentatives de fournisseur.

## Limites connues assumées

- L’OCR Career est réservé aux PDF de profil et à huit pages ; les autres PDF
  de l’espace Analyse & documents conservent leur extraction texte actuelle.
- Les documents et analyses sont plafonnés pour protéger mémoire, temps et
  quotas : les PDF sont lus jusqu’à 200 pages, les analyses de tableau jusqu’à
  100 000 lignes et les imports jusqu’à 50 Mo par fichier / 100 Mo par envoi.
- Fermer ou recharger l’onglet ne peut pas annuler de façon fiable une requête
  déjà envoyée à un fournisseur. Le délai global de 90 secondes et la limite
  de huit appels empêchent toutefois une succession d’essais prolongée.
- L’historique de chat n’est pas stocké sur disque : chaque demande est
  volontairement indépendante afin de limiter les données envoyées et les
  coûts.
- Career 4.1 prépare des brouillons de CV et de lettres exportables en
  DOCX/PDF, mais ne préremplit aucun formulaire et ne soumet jamais une
  candidature. La découverte ne lit que des boards Greenhouse publics choisis
  manuellement : il n’existe ni recherche générale, ni connecteur LinkedIn,
  Lever ou portail privé.
- L’import de profil n’ouvre pas LinkedIn : il nécessite un PDF/export ou du
  texte que tu fournis. L’OCR Vision traite seulement le PDF local importé et
  ne contourne aucune authentification, cookie ou CAPTCHA.
