# Actualisation quotidienne — modèle launchd (documenté, jamais installé)

> **Rien n’est installé automatiquement.** Ce document décrit un modèle que la
> personne peut installer elle-même, quand elle le décide. Le code de
> l’application ne crée aucun fichier `plist`, n’appelle jamais `launchctl` et
> ne programme aucune tâche.

---

## Ce que fait l’actualisation

L’actualisation manuelle de la recherche du jour lit les sources officielles
déjà configurées, puis reconstruit la synthèse locale :

- elle ne s’exécute que sur une action explicite (`POST /api/career/daily/refresh`) ;
- elle lit **au maximum deux sources en même temps** ;
- elle respecte le budget réseau de l’explorateur (60 secondes) ;
- elle n’envoie aucune donnée personnelle vers une source ;
- elle n’envoie aucune candidature.

Le fichier `career_data/career.sqlite3` conserve les offres et l’état du
cache. Un travail interrompu laisse une trace visible (« résultat partiel »)
et la prochaine actualisation repart des données déjà enregistrées.

---

## Modèle proposé (à installer à la main)

Le modèle lance un appel HTTP local vers l’application locale. Il suppose
que l’application tourne sur `http://127.0.0.1:8000` et que l’actualisation
est autorisée par la configuration locale.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.comeai.career.daily-digest</string>

    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/curl</string>
      <string>--silent</string>
      <string>--show-error</string>
      <string>--max-time</string>
      <string>300</string>
      <string>--request</string>
      <string>POST</string>
      <string>http://127.0.0.1:8000/api/career/daily/refresh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/comedelavenne/AI-Excel-Agent</string>

    <!-- Une seule fois par jour, à 07:12 (heure locale). -->
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key>
      <integer>7</integer>
      <key>Minute</key>
      <integer>12</integer>
    </dict>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>/Users/comedelavenne/AI-Excel-Agent/logs/career-daily-digest.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/comedelavenne/AI-Excel-Agent/logs/career-daily-digest.error.log</string>
  </dict>
</plist>
```

---

## Installation manuelle (facultative)

```bash
# 1. Copier le modèle dans le dossier LaunchAgents de l’utilisateur.
mkdir -p ~/Library/LaunchAgents
cp docs/career/com.comeai.career.daily-digest.plist.example \
   ~/Library/LaunchAgents/com.comeai.career.daily-digest.plist

# 2. Charger la tâche (c’est la seule commande qui installe quoi que ce soit).
launchctl load ~/Library/LaunchAgents/com.comeai.career.daily-digest.plist

# 3. Vérifier l’état.
launchctl list | grep com.comeai.career.daily-digest
```

Déinstallation :

```bash
launchctl unload ~/Library/LaunchAgents/com.comeai.career.daily-digest.plist
rm ~/Library/LaunchAgents/com.comeai.career.daily-digest.plist
```

---

## Pourquoi ce n’est pas activé par défaut

| Raison | Conséquence |
|---|---|
| Une actualisation consulte des sites externes | elle doit rester une décision de la personne |
| Le budget réseau et le nombre de sources sont bornés | une tâche répétée gaspille des requêtes sans valeur |
| Le cache a déjà une durée de vie | une actualisation quotidienne automatique est rarely nécessaire |
| Les offres « en panne » sont déjà visibles | l’écran indique déjà ce qui ne va pas |

Par défaut, la synthèse se lit au chargement de l’onglet **Tableau de bord**
sans aucune requête, et le bouton **Actualiser les sources** est le seul moyen
de lancer une lecture.

---

## Réglages utiles

| Réglage | Valeur par défaut | Où le changer |
|---|---|---|
| Durée de vie du cache | 900 s (15 min) | `PUT /api/career/daily/settings` avec `{"ttl_seconds": 1800}` |
| Sources simultanées | 2 (maximum) | non configurable : c’est une garantie |
| Sources lues | boards configurés + registre public | `POST /api/career/daily/refresh` (`include_boards`, `include_curated`) |
| Intervalle de rechecute d’une source en panne | 1 800 s | constante `BROKEN_SOURCE_RETRY_SECONDS` |
