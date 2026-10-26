# Côme IA Career — installer et utiliser sur un Mac (guide étudiant)

Côme IA est un assistant de candidature qui tourne **entièrement sur ta machine**.
Il t'aide à préparer des candidatures solides (CV adapté, lettre, checklist,
suivi, préparation d'entretien) sans jamais envoyer quoi que ce soit à ta place
et sans envoyer tes données ailleurs.

## Ce dont tu as besoin

- Un Mac (macOS récent), ~1 Go d'espace libre
- 3 minutes
- Ton CV (PDF, DOCX ou copier-coller du texte) et **une vraie offre** qui t'intéresse

## Installer (méthode simple : zip)

1. Récupère le fichier `come-ai-career.zip` et double-clique dessus pour le décompresser.
2. Ouvre le dossier décompressé.
3. Double-clique sur **`scripts/demarrer_come_ai_mac.command`**
   - Si macOS refuse (« développeur non identifié ») : clic droit → **Ouvrir** → **Ouvrir**,
     ou Réglages Système → Confidentialité et sécurité → **Ouvrir quand même**.
4. Une fenêtre Terminal s'ouvre, installe ce qu'il faut (~2 min la première fois),
   puis ton navigateur s'ouvre sur **http://127.0.0.1:8747/career**

Garde la fenêtre Terminal ouverte pendant que tu utilises l'app. `Ctrl+C` pour arrêter.

## Installer (méthode étudiante : GitHub)

Si tu as accès au dépôt privé (invitation GitHub) :

```bash
git clone <url-du-depot-privé> come-ai-career
cd come-ai-career
./scripts/demarrer_come_ai_mac.command
```

Rien d'autre à faire : le script crée un environnement Python isolé (`.venv`),
installe les dépendances et démarre le service local.

## Ton premier parcours (10 minutes)

1. **Profil → Importer** : dépose ton CV. Le système extrait les faits
   (formation, expériences, compétences) et te les montre **un par un**.
   Tu approuves ce qui est juste : **rien n'entre dans ton profil sans ton clic**.
2. **Offres → Importer** : colle le texte d'une offre réelle
   (ou son lien si le connecteur la prend en charge).
   Choisis sa **famille métier** (Mode / Stylisme, Design, Marketing, Commerce…).
3. **Générer le kit** : CV adapté à l'offre + lettre + checklist.
4. **Télécharger** en DOCX (compatible ATS) et PDF.
5. **Suivi** : la candidature apparaît dans ton tableau de bord ; tu peux
   y ajouter la deadline (fichier calendrier) et préparer l'entretien.

## Ce que l'outil fait — et ne fait pas

| Fait | Ne fait pas |
|---|---|
| Adapte ton CV aux mots-clés de l'offre | Inventer une expérience ou une compétence |
| Rédige une lettre personnalisée | Envoyer une candidature à ta place |
| Vérifie que chaque phrase s'appuie sur un fait approuvé | Envoyer tes données sur un serveur |
| Prépare des questions d'entretien ciblées | Promettre un résultat de recrutement |

## Données et vie privée

- Tout est stocké **localement** (dossier `.come_ai/` dans le projet).
- Rien n'est publié, rien n'est partagé, aucune soumission automatique.
- Tu peux effacer toutes tes données depuis l'app (Profil → Données → Supprimer).

## Si quelque chose ne marche pas

- Le terminal affiche une erreur Python : vérifie `python3 --version` (≥ 3.10).
- Le port 8747 est occupé : ferme l'autre application, ou relance le script.
- Une offre est refusée : vérifie que la **famille métier** est bien dans la liste proposée.
