# Côme AI — intelligence hybride réelle

## Démarrer

Double-cliquer le raccourci existant `Lancer Côme AI V3.command`, ou :

```bash
cd ~/AI-Excel-Agent
.venv/bin/python run_come_ai_v3.py
```

Le lanceur démarre le moteur déjà installé, sans téléchargement automatique.
Dans le chat central `/v5`, choisir **Hors ligne** pour Qwen et les outils
locaux. Les autres modes sont **Automatique** et **Performance** ; fournisseur
et modèle manuels restent dans les réglages avancés. Une page ouverte sur un
ancien serveur doit être rechargée après son redémarrage.

## Installation et mesures réellement obtenues sur ce Mac

- Ollama officiel **0.40.3**, binaire universel vérifié par SHA-256, exécuté en
  x86_64 sur le processeur. Installation dans `.local-ai/ollama/v0.40.3/`.
- Un seul modèle terminé : **qwen3.5:2b-q4_K_M**, poids GGUF locaux, 1,9B,
  quantification Q4_K_M, environ 1,95 Go sur disque dans `.local-ai/models/`.
  Le téléchargement du modèle Q8 par défaut a été interrompu au profit de Q4 ;
  aucun deuxième modèle n'a été installé.
- Configuration quotidienne : contexte 4096, quatre threads, une requête à la
  fois, réponse de 256 tokens maximum, `think=false`, délai local 180 secondes.
- Petite batterie synthétique de huit contrôles : **6 réussis** (français,
  anglais, consigne simple, code simple, JSON et proposition d'appel d'outil),
  **2 échoués** (conservation d'un détail du résumé et raisonnement arithmétique).
- Débit médian mesuré : **5,50 tokens/s** ; premier chargement **9,21 s** ;
  première sortie froide **11,13 s**. RSS maximal parmi les échantillons de
  cette batterie : **2,24 Gio** pour les processus Ollama, pas la RAM totale
  du Mac et pas une mesure de pic continu. La charge CPU affichée est une
  moyenne de processus issue de `ps`, pas une mesure instantanée.

Les rapports sont dans `.devkit/intelligence/benchmark-local.md` et `.json`.
Ce n'est ni un benchmark général ni une comparaison avec un 4B/cloud. Le 4B
n'est pas téléchargé : la lenteur CPU déjà mesurée justifie une comparaison
ultérieure bornée plutôt qu'une installation supplémentaire immédiate.

## Ce qui est réellement utilisable

- Conversation naturelle via Qwen dans le chat central, avec historique borné
  dans l'onglet ; aucune conversation n'est ajoutée au journal de consommation.
- Inspection et contexte des documents sélectionnés par identifiant opaque.
  Le test réel a résumé les notes fictives en conservant mardi, huit pages et Lina.
- Recherche explicite en mémoire : extraits et provenance rendus directement
  par Python, sans génération. Une synthèse plus complexe peut utiliser Qwen.
- Calcul numérique explicite, par exemple `Calcule 6*9-12` : **42**, calcul
  déterministe. Aucune exécution Python libre, importation ou commande terminal.
- Outils existants de statistiques et rapports Excel conservés ; toute création
  de rapport exige la confirmation d'écriture existante.
- Journal de métadonnées `state/hybrid_usage.sqlite3` : fournisseur, modèle,
  durée, tokens déclarés, erreurs et fallbacks ; agrégations heure/jour/semaine/mois.
  Quotas, consommations et vérifications absents restent inconnus.

Le modèle 2B n'est pas fiable pour le raisonnement multi-étapes. Un calcul
formulé en prose n'est pas garanti : exprimer la formule ou utiliser Finance
Lab. Résumés et productions importantes doivent être relus/vérifiés.

## Hors ligne vérifié, sans désactiver le réseau du Mac

Le moteur installé a été relancé sous sandbox macOS interdisant tout réseau
non local, avec Ollama Cloud désactivé. Un deuxième processus sandboxé a fait
un véritable essai TCP externe (refusé), puis exercé les routes HTTP Côme avec
Qwen, un document et une mémoire fictifs, et un calcul Python. Une demande
Gemini en mode Hors ligne a été refusée. Rapport :
`.devkit/intelligence/offline-smoke.json`.

« Zéro réseau » signifie ici **zéro réseau externe** : navigateur, application
et Ollama communiquent par la boucle locale. Le réseau des autres applications
du Mac n'a pas été modifié. Un serveur Ollama préexistant est réutilisé sans
que son isolation OS soit présumée ; le chat contrôle toujours le modèle local
et refuse les alias cloud, proxies et redirections.

## Gemini et OpenRouter : nouvelle saisie privée

Les clés publiées dans une conversation doivent être révoquées auprès de leurs
fournisseurs. Ne pas les réutiliser. Saisir les remplacements dans le Terminal :

```bash
.venv/bin/python -m devkit configure-gemini
.venv/bin/python -m devkit configure-openrouter
```

Saisie masquée obligatoire, `.env` privé 0600, pas de clé dans les arguments,
logs, exports, contexte ou réponses. TLS est vérifié avec `certifi` du venv.

Gemini exige la déclaration de projet gratuit sans facturation, un modèle
accessible et le prix texte gratuit connu. Son compte de facturation ne peut
pas être inspecté par le moteur. `gemini-2.5-flash` est exclu de la sélection
automatique du chat. OpenRouter exige un modèle `:free`, tous les prix live
explicitement nuls, un plafond zéro et aucun fallback fournisseur payant.
Le catalogue public a été réellement récupéré : **15 modèles texte gratuits
éligibles** à la date de cette livraison ; cela ne prouve ni l'authentification
ni la disponibilité d'une génération pour ce compte.

**Les générations cloud réelles restent à tester avec les nouvelles clés.**
Les tests de transport cloud sont fictifs. Le routage est prudent et utilise
les échecs observés du petit modèle, sans classement qualité inventé ni critique
indépendante automatique. Deux tentatives fournisseur maximum par demande.

Les routes web historiques V3 et d'amélioration Career utilisent maintenant
le même moteur commun en production. Les brouillons Career locaux restent
disponibles ; CV + lettre complets par IA ne sont pas revalidés avec la borne
de sortie actuelle. Une réponse tronquée est refusée avant enregistrement.

## Développement assisté

L'Atelier est configuré sur le modèle Qwen installé, sans cloud. Deux essais
réels de la petite correction de masquage ont été enregistrés : un timeout,
puis une proposition rejetée par les contrôles de staging. **Aucun candidat
validé et aucun correctif appliqué au noyau** à ce stade. L'historique figure
dans `.devkit/evolution/latest_demo.json` ; ne pas confondre generation réelle
et correction réussie.

```bash
.venv/bin/python -m devkit check
.venv/bin/python -m devkit export
.venv/bin/python -m devkit evolution demo --max-requests 1
```

Une nouvelle démonstration fait un vrai appel local, potentiellement plusieurs
minutes. Les tests ordinaires ne lancent pas de modèle. Planification continue,
contre-vérification indépendante et déploiement automatique ne sont pas activés.
Créer une tâche générale via le chat propose seulement un brouillon, clairement
non enregistré ; les tâches contrôlées Documents et Atelier restent fonctionnelles.

Sources : [Ollama macOS](https://docs.ollama.com/macos),
[Qwen 3.5 Q4](https://ollama.com/library/qwen3.5:2b-q4_K_M),
[Ollama sans cloud](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).
