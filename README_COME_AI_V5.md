# Côme AI 5.0 — noyau personnel local

Côme AI 5.0 est la prochaine fondation de l’application : une interface web
locale plus claire, un orchestrateur de tâches contrôlé et une mémoire
personnelle persistante. Elle s’ajoute à V3 et à Career 4.1 ; elle ne les
remplace pas, ne modifie pas leurs données, et ne lance aucun modèle au
démarrage.

> **État de cette livraison.** Le premier vertical slice V5 est réellement
> utilisable hors ligne : documents → plan → outils locaux → résultat →
> citations/rapport. Les appels Gemini, Ollama, Greenhouse, LinkedIn ou autres
> services externes n’ont pas été exécutés pendant sa construction ni ses
> tests.

## Démarrer

Double-clique simplement sur :

[`Lancer Côme AI V3.command`](Lancer%20C%C3%B4me%20AI%20V3.command)

Le nom est volontairement conservé pour ne pas casser le raccourci existant.
Il ouvre maintenant :

```text
http://127.0.0.1:8765/v5
```

Ou, dans Terminal :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py
```

Les trois espaces sont servis par le même serveur local :

| Adresse | Espace réel |
|---|---|
| `/v5` | Côme AI 5.0 : assistant local, mémoire, documents/finance, suivi de tâches |
| `/` | Interface V3 historique : chat de fournisseur optionnel et actions fichiers existantes |
| `/career` | Career 4.1 : profil, offres, candidatures, Application Studio et Interview Coach |

Garde la fenêtre Terminal ouverte pendant l’utilisation. `Ctrl+C` arrête le
serveur. Il est lié à `127.0.0.1` uniquement : aucune page n’est publiée sur
Internet.

## Ce qui fonctionne réellement sans API

### Assistant local orchestré

Depuis **Assistant**, sélectionne un fichier puis formule par exemple :

```text
Analyse financière en profondeur le fichier sélectionné et crée un rapport.
```

L’application construit un petit plan côté serveur, visible dans l’interface :

```text
inspect_file → analyze_table → create_analysis_workbook
```

Chaque étape appelle les outils V3 déjà contrôlés ; il ne s’agit pas d’une
réponse inventée. Le rapport n’est créé que si tu coches l’autorisation prévue
pour cette demande. Le fichier source n’est jamais écrasé : le nouveau
classeur est placé dans `output/`.

Le mode V5 est volontairement conservateur : il reconnaît pour l’instant les
intentions locales d’inspection, d’analyse, de rapport, d’indexation dans la
mémoire et de recherche mémoire. Une demande ambiguë demande un fichier ou une
action plus précise plutôt que de faire semblant de l’avoir comprise. Aucun
texte utilisateur ne peut choisir une fonction Python, une commande Terminal,
une URL ou un chemin disque.

### Mémoire personnelle persistante et stockage visible

L’onglet **Mémoire & stockage** permet de :

1. créer des projets, par exemple « Révisions finance » ou « Stage M&A » ;
2. sélectionner un document déjà importé dans l’espace de travail ;
3. lancer son indexation locale dans la file persistante, sans laisser le
   navigateur bloqué pendant un PDF, Word ou Excel plus lourd ;
4. rechercher un terme et retrouver un extrait avec son document, sa page
   (pour les PDF), sa feuille/plage de lignes (pour Excel) ou ses lignes
   approximatives (pour les autres documents) ;
5. redémarrer l’application et retrouver les mêmes sources et résultats.

L’indexation a son propre statut et sa propre annulation coopérative : elle ne
remplace pas le suivi d’un plan Assistant en cours. Elle est relancée de façon
idempotente après un redémarrage ; l’empreinte du contenu évite les doublons.
La progression est honnête : les états correspondent à la vérification, à
l’extraction/indexation puis à la finalisation. Une lecture interne de PDF ou
d’Excel ne peut pas encore être arrêtée au milieu de sa page/feuille active.

L’index repose sur SQLite FTS5, sans appel cloud. L’import est explicite, un
document à la fois dans ce premier flux, protégé par une enveloppe de
ressources configurable dans le moteur et dédupliqué par empreinte du contenu
: un même texte ne prend pas deux fois de place, mais peut être relié à
plusieurs projets.

Formats indexables dans la mémoire V5 : `.txt`, `.md`, `.csv`, `.tsv`,
`.json`, `.html`, `.htm`, `.docx`, PDF avec couche texte, ainsi que `.xlsx`
et `.xlsm`. Pour Excel, l’ouverture est strictement en lecture seule ; les
valeurs et les formules sont indexées comme texte, sans recalcul, sans
exécution de macro et sans lien externe. Une recherche peut donc citer par
exemple `Dossier de stage — feuille « Finance », lignes 24–28`.

La zone **État de la bibliothèque** affiche réellement la taille de la base et
de ses journaux, les fichiers de mémoire les plus volumineux, l’espace libre du
volume, le nombre de sources/extraits, l’état de la queue d’indexation et la
présence éventuelle d’un dossier de sauvegarde local. Elle ne parcourt jamais
le reste du disque. La détection d’un dossier `backup/` n’est pas une promesse
de sauvegarde automatique : Côme AI n’en crée ni n’en efface encore.

Un PDF scanné sans texte est signalé honnêtement ; l’OCR générique et
l’indexation page-par-page reprenable restent la prochaine étape, tandis que
Career 4.1 possède déjà son OCR local dédié aux CV.

### File de tâches locale

Les plans V5 passent dans une file SQLite persistante avec :

- un worker local unique, adapté au Mac Intel et évitant deux analyses lourdes
  en parallèle ;
- progression basée sur les vraies étapes, et non une fausse estimation ;
- annulation coopérative entre deux étapes ;
- récupération après redémarrage pour les tâches de lecture ;
- résultats, erreurs et messages bornés et nettoyés de secrets courants.

Une annulation ne peut pas tuer proprement une lecture pandas/PDF déjà en cours
au milieu de son exécution : l’interface indique donc « annulation demandée »
et s’arrête au prochain point de contrôle. Si une écriture vient tout juste de
se produire, le rapport peut déjà exister dans `output/` même si la tâche est
marquée annulée ; aucun fichier source n’est pour autant modifié.

## Données et confidentialité

```text
data/               fichiers importés pour l’espace général
output/             nouveaux rapports Excel uniquement
memory_data/        mémoire V5 SQLite/FTS5 par défaut
state/              file de tâches V5 SQLite
career_data/        données Career isolées
.env                clés/API locales, jamais affichées par l’application
```

- Les modèles reçoivent des identifiants opaques de fichiers, jamais un chemin
  absolu exposé par l’interface.
- La mémoire ne stocke ni le chemin absolu du document source ni son original ;
  elle ne conserve que le texte extrait, les métadonnées nécessaires et les
  références de citation.
- La suppression disponible dans le moteur mémoire ne supprime jamais le
  fichier original. Elle n’est pas encore exposée dans l’interface V5 afin de
  conserver une confirmation UI explicite lors du prochain incrément.
- Career garde son stockage séparé : V5 ne l’indexe pas et ne transmet pas de
  CV/profil à un autre module automatiquement.

Pour mettre la mémoire sur un SSD local déjà monté, ajoute volontairement dans
`.env` une ligne telle que :

```dotenv
COME_AI_MEMORY_DIR=/Volumes/MonSSD/Come-AI-Memory
```

Le chemin reste local et n’est jamais envoyé à un fournisseur. La page
**Mémoire & stockage** affiche une forme redacted de l’emplacement : le dossier
par défaut est nommé par son rôle, et un emplacement externe peut être reconnu
sans divulguer le nom de ton compte macOS. Ne configure pas un chemin réseau si
tu ne veux pas que tes extraits soient stockés sur ce volume.

## Modèles externes : ce qui reste séparé

Le chat V3 existant sur `/` peut toujours utiliser Gemini, puis Ollama local
si tu l’as configuré. Ses retries, limites de durée et secours restent en
place. La V5 ne consomme aucun quota dans son flux actuel ; elle n’appelle pas
Gemini/Ollama pour planifier ou répondre.

Une évolution future pourra demander à un modèle de **proposer** un plan, mais
le serveur V5 devra toujours le valider contre le même registre d’outils et les
mêmes confirmations. Un vrai test réseau devra être lancé seulement avec ton
accord explicite sur le budget API à utiliser.

## Vérifier l’installation

Les vérifications suivantes ne lisent aucune clé réelle, ne contactent aucun
fournisseur et utilisent des données temporaires :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

La suite V5 couvre notamment :

- le scénario Assistant : CSV synthétique → inspection → analyse → rapport
  créé avec confirmation ;
- le scénario Mémoire : Markdown synthétique → projet → indexation → recherche
  citée → redémarrage de l’application → résultat retrouvé ;
- l’indexation asynchrone réelle : document de cours → tâche `memory_index`
  persistante → recherche source-citée sans fournisseur ;
- l’indexation Excel multi-feuilles en lecture seule, avec citation de feuille
  et de lignes ;
- le tableau Mémoire & stockage : tailles locales, espace libre, fichiers
  volumineux et absence de fuite de chemin absolu ;
- le scénario Finance : statistiques réelles sur le CSV synthétique ;
- les limites d’import, déduplication, citations PDF/DOCX, recherche FTS sûre,
  annulation coopérative, persistance/reprise et nettoyage de secrets ;
- les régressions V3 et Career 4.1 existantes.

## Limites connues de ce premier incrément

- Il n’y a pas encore d’OCR générique, d’import massif de dossiers ni de file
  multi-worker ; c’est volontaire pour rester stable sur un Mac Intel.
- L’indexation PDF/Word/Excel est maintenant persistante et suivie par tâche,
  mais elle n’est pas encore découpée en checkpoints par page ou par feuille :
  l’annulation est observée avant/après l’extraction en cours, jamais promise
  comme instantanée.
- Les très grands Excel restent limités par les plafonds V3 actuels (analyse
  sur les 100 000 premières lignes) ; DuckDB/Parquet et un benchmark 10k / 100k
  / 1M constituent la prochaine extension Finance.
- Study est déjà possible via import + mémoire + recherche citée, mais il n’a
  pas encore son espace pédagogique dédié (fiches, flashcards, planification).
- Les connecteurs externes, l’envoi de candidature, le calendrier et les
  recherches web ne sont pas déclenchés par V5.

## Priorités recommandées ensuite

1. OCR local générique et ingestion PDF incrémentale avec reprise.
2. Benchmarks et pipeline DuckDB/Parquet pour gros tableaux, avec mesures
   réelles sur ce Mac.
3. Module Study local : plan de révision, fiches sourcées et QCM.
4. Registre commun permettant à Gemini/Ollama de proposer — jamais exécuter
   directement — un plan validé par V5.
5. Centre Organize : projets, tâches, échéances et briefing local, avant toute
   intégration de calendrier ou service externe.
