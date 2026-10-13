# AI Workspace V3

> **Documentation historique — ne pas suivre pour la V3 actuelle.** Cette
> documentation décrit l’ancienne interface Tkinter conservée dans `app_v3.py`.
> Pour Côme AI V3, utilise [`README_COME_AI_V3.md`](README_COME_AI_V3.md) et
> double-clique `Lancer Côme AI V3.command` (ou lance `run_come_ai_v3.py`).

Cette V3 remplace le prototype console par une petite application de bureau pour analyser des fichiers Excel, CSV, PDF, Word et texte. Elle garde les données dans `data/`, produit tout nouveau fichier dans `output/`, et écrit ses diagnostics dans `logs/`.

## Ce qui a été corrigé

V2 affichait une liste d’« outils » dans le prompt, mais ne les passait jamais à Gemini. Elle ne pouvait donc rien exécuter. V3 utilise le function calling déclaré de manière explicite et le pilote elle-même : Gemini peut demander une action, l’application vérifie ses paramètres, l’exécute localement, puis lui renvoie un résultat limité.

L’application ne laisse pas le modèle lancer Python, lire un chemin arbitraire, modifier un document importé ou accéder aux secrets. Les contenus de fichiers sont traités comme des données non fiables, y compris s’ils contiennent des instructions.

## Lancer l’application

Depuis Terminal :

```bash
cd ~/AI-Excel-Agent
source .venv/bin/activate
python -m pip install -r requirements-v3.txt
python app_v3.py
```

Ou, dans Finder, double-clique `Lancer AI Workspace V3.command`. Si macOS
l’empêche de s’ouvrir la première fois, fais un clic droit dessus puis choisis
**Ouvrir**.

La dernière installation ajoute seulement `pypdf` (lecture locale des PDF) et `xlrd` (anciens classeurs `.xls`). Elle ne réinstalle ni Python, ni le venv, ni les bibliothèques déjà présentes.

La clé Gemini peut continuer à être définie dans le Terminal, comme avant. Pour éviter de la retaper à chaque session, copie `.env.example` en `.env`, puis complète seulement `GEMINI_API_KEY=` dans ce fichier local. Ne colle jamais la clé dans une conversation et ne partage jamais `.env`.

## Utilisation

1. Clique sur **Ajouter des fichiers** et importe un ou plusieurs fichiers. Une copie contrôlée est placée dans `data/`; l’original ne change jamais.
2. Sélectionne un fichier et clique sur **Inspecter en local** si tu veux les feuilles, colonnes, valeurs manquantes et aperçu sans appeler d’IA.
3. Dans Assistant, demande une analyse claire, par exemple :
   - `Inspecte le fichier et explique toutes ses feuilles.`
   - `Analyse les tendances de revenus, les valeurs manquantes et les anomalies.`
   - `Cherche « échéance » dans les contrats PDF et Word.`
   - `Crée un rapport Excel de statistiques pour la feuille Budget.`
4. Les rapports générés arrivent dans `output/`. Le fichier d’origine n’est jamais écrasé.

## Résilience face aux indisponibilités

La V3 comprend :

- une limite de 60 secondes par requête ;
- trois tentatives avec attente progressive et aléatoire pour les erreurs temporaires `429`, `5xx`, `timeout` ou réseau ;
- les modèles Gemini de secours configurables dans `.env` ;
- une interface qui reste réactive pendant l’analyse ;
- un journal local sans clé API dans `logs/ai-workspace.log` ;
- l’inspection et les calculs locaux même sans modèle disponible.

Un `503 UNAVAILABLE` est un problème temporaire côté service Gemini ; l’application ne peut pas le faire disparaître, mais elle évite qu’il fasse planter l’interface et essaie d’autres modèles. Les quotas `429` dépendent de l’offre et de la limite de ton projet ; l’application indique clairement ce cas au lieu de faire croire que les données ont été analysées.

## Secours totalement local, facultatif

Si tu installes plus tard Ollama avec un modèle compatible Intel, indique son nom dans `.env`, par exemple `OLLAMA_MODEL=qwen2.5:7b`. En cas d’indisponibilité de Gemini, l’application utilisera alors `http://127.0.0.1:11434/api/chat`, sans envoyer la demande à Internet. La V3 marche aussi sans Ollama : ce n’est pas une dépendance obligatoire.

## Réglages de modèles

Le modèle principal par défaut est celui du prototype : `gemini-3.8-flash`. Les secours par défaut sont `gemini-3.6-flash` puis `gemini-3.5-flash-lite`. Ils sont configurables sans toucher au code :

```dotenv
GEMINI_PRIMARY_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODELS=gemini-3.6-flash,gemini-3.5-flash-lite
```

Les modèles réellement disponibles dépendent de ton projet Gemini et peuvent évoluer. Si l’un d’eux n’est pas disponible, l’application l’écrit dans le journal puis essaie le suivant.

## Vérifier localement avant Gemini

Avant de lancer l’interface, tu peux vérifier le cœur sans appeler l’API ni consommer de quota :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python test_v3_offline.py
```

Le test crée un CSV temporaire, vérifie l’inspection et les calculs, puis génère un rapport temporaire.

## Limites saines de V3

- Les PDF scannés sans couche texte demandent un OCR, qui n’est pas inclus ici.
- Les statistiques financières sont descriptives, et jamais une recommandation d’investissement.
- Pour les fichiers très volumineux, l’application limite les aperçus et l’extrait envoyé au modèle, afin de limiter temps, coût et exposition de données.
- `data/`, `output/`, `logs/` et `.env` sont à garder hors de Git et des dossiers synchronisés publiquement si les documents sont sensibles.
