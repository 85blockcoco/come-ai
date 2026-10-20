# Intelligence & évolution — première boucle bornée

L’Atelier Développeur possède un backlog persistant et un moteur de correction
réutilisant les copies, diagnostics, empreintes et sauvegardes du DevKit.
Un cycle explicitement lancé fait : référence → sélection du modèle →
proposition JSON → staging → tests sous sandbox → décision → historique.
Il peut envoyer les erreurs et le diff au modèle pour un second essai.
Le maximum est de 2 générations par défaut, 3 dans les réglages avancés.
Les candidats restent soumis à une application manuelle. La planification
nocturne et le déploiement automatique ne sont pas activés.

## Configuration privée Gemini

```bash
cd ~/AI-Excel-Agent
.venv/bin/python -m devkit configure-gemini
```

La saisie est masquée et enregistrée dans `.env` avec permissions 0600.
Si le Terminal ne permet pas de masquer la saisie, la commande s’arrête sans
lire la clé ni modifier le fichier. Colle uniquement la clé, pas le nom de variable.
Elle ne passe pas dans les arguments, journaux, exports ou contexte du modèle.
Le projet gratuit sans facturation doit être déclaré par
`COME_AI_GEMINI_FREE_PROJECT_CONFIRMED=true` ; le moteur ne peut pas inspecter
le compte de facturation Google et ne prétend pas le vérifier lui-même.

Le choix `auto` croise `models.list` avec les modèles de texte dont le niveau
gratuit a été vérifié dans la documentation officielle le 13 octobre 2026.
Un identifiant disparu est exclu à l’actualisation. Les modèles inconnus ou
sans prix établi sont refusés. Le catalogue expire après 24 heures.
La disponibilité réelle et le quota ne sont confirmés que par les réponses
du fournisseur. `generateContent` ne prouve pas le support des outils : le
catalogue ne revendique pas un function calling Gemini réellement testé.

## Saisie privée OpenRouter et clés exposées

```bash
.venv/bin/python -m devkit configure-openrouter
```

Cette commande demande la clé avec la même saisie masquée, conserve les autres
réglages de `.env`, impose les permissions 0600 et vérifie le chargement local.
Elle n’envoie aucun appel et ne confirme pas l’authentification du fournisseur.
Ne transmettez jamais une clé dans le chat : une clé déjà collée dans une
conversation doit être révoquée chez son fournisseur et remplacée ici par une
nouvelle clé. Les clés exposées dans la mission ne sont pas réutilisées.
Les connexions HTTPS utilisent le fichier de certificats `certifi` du venv,
avec vérification du certificat et du nom d’hôte, sans changer Python global.

## Premier cycle réel, sans modifier le noyau

```bash
.venv/bin/python -m devkit evolution demo --max-requests 2
```

La démonstration copie la fonction `safe_error` de Côme dans un petit projet
isolé et reproduit son défaut de masquage d’un jeton OpenRouter fictif.
Un modèle configuré propose le correctif. Trois tests détenus par le moteur,
hors du périmètre modifiable par le modèle, vérifient le cas OpenRouter, la
protection Gemini et la lisibilité d’une erreur normale. Le candidat passe
les vrais diagnostics et tests du DevKit dans la sandbox macOS.

Résultats : `.devkit/evolution/latest_demo.json` et l’historique dans
`.devkit/evolution/demos/`. Un état `needs_review` indique un candidat testé ;
`waiting_provider` conserve un blocage de clé, quota, modèle ou prix. Une
simulation ne constitue jamais une preuve d’utilisation d’un modèle réel.
Le noyau principal reste inchangé pendant ce premier essai.

## Tâches du projet

```bash
.venv/bin/python -m devkit evolution add \
  --title "Problème concret" --description "Étapes et correction attendue" \
  --file module.py --acceptance "Tests et résultats nécessaires"
.venv/bin/python -m devkit evolution run --max-requests 2
.venv/bin/python -m devkit evolution status
```

L’interface affiche les tâches, modèles choisis, résultats et statistiques
provenant des événements. Les consommations non déclarées restent inconnues.
Les clés et documents privés sont absents des copies de test. Arrêter un
cycle empêche les nouveaux appels ; l’appel en cours reste borné par son
délai. Une session récupérée après interruption reste en attente d’une reprise
explicite et ne rejoue aucun appel cloud automatiquement.

## OpenRouter et fonctionnement local

OpenRouter exige `OPENROUTER_API_KEY` dans `.env`, un modèle `:free`, des prix
d’entrée/sortie/requête explicitement nuls dans son catalogue avant chaque
génération, et un plafond de prix nul avec les fallbacks de fournisseur
désactivés. Un 429/402 met en attente ; un 401/403 ne déclenche aucune rotation.
Un 404/5xx peut utiliser un autre modèle gratuit du même fournisseur, dans
le budget du cycle. Aucun achat de crédit ou activation de facturation.

Qwen via Ollama est prêt côté adaptateur mais nécessite une installation et
un modèle locaux. Ollama accepte macOS 14+ sur x86 avec calcul CPU uniquement.
Pour ce Mac 16 Go, commencer par Qwen 3.5 2B, puis comparer un 4B seulement si
le test du 2B justifie le téléchargement supplémentaire. Les modèles proposés
par Ollama sont quantifiés ; le catalogue 2B affiche Q8_0. Ni vitesse ni RAM
d’inférence ne sont prétendues mesurées avant installation. L’adaptateur
confirme des poids GGUF locaux et refuse les alias cloud ; il ne télécharge
rien. Contexte 8192, 4 threads et réponse bornée limitent la charge.

Le classement actuel est une préférence technique de modèles gratuits
accessibles, pas un benchmark établissant « le meilleur modèle ». La critique
par un second modèle, le streaming et le function calling multi-fournisseur
ne sont pas activés dans cette première boucle. Les outils locaux V5 restent
utilisables indépendamment des fournisseurs.

Sources officielles : [tarifs Gemini](https://ai.google.dev/gemini-api/docs/pricing),
[API Models](https://ai.google.dev/api/models),
[API OpenRouter](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties),
[Ollama macOS](https://docs.ollama.com/macos),
[Qwen 3.5 2B](https://ollama.com/library/qwen3.5:2b).
