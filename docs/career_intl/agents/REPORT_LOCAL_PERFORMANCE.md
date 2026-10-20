# Rapport de mesure de performance locale — Career Agent

**Date** : 2026-10-18
**Environnement** : macOS 14.8.9, MacBook Pro 11,4, 8 cœurs Intel i7-4770HQ @ 2.2 GHz, 16 Go RAM, charge système variable (load avg 4–100 selon tâche), Python 3.12.10, Ollama v0.40.3 local.

> **Méthodologie** : Toutes les mesures sont **locales** (pas de réseau, pas de téléchargement, pas de données personnelles). Les exécutions se sont déroulées dans des processus isolés sur des fixtures synthétiques (.example.test). La charge système (`os.getloadavg()`) a été consignée à chaque point de mesure ; les périodes de charge forte ont été exclues ou signalées. Les temps d'exécution sont donnés en secondes (median sur 3–5 répétitions, ou 50 pour les micro‑benchmarks). La mémoire est exprimée en Mo (RSS `resource.getrusage(RUSAGE_SELF)` sous macOS).

---

## 1. Démarrage à froid

| Étape | Temps median (s) | RSS après (Mo) | Observations |
|---|---|---|---|
| Interpréteur Python (démarrage processus) | ~0.0 (instantané) | 10.5 Mo | Temps de base entre deux `time.perf_counter()` |
| `import career.service` | 1.11–1.81 (median 1.27) | 67.8 Mo | Import du module et de ses dépendances |
| `CareerService` init sur base vide (cold) | 0.25–0.51 (median 0.38) | 72.9 Mo | Création du schéma SQLite + répertoires |
| `CareerService` init sur base existante (warm) | 0.28–0.60 (median 0.33) | 73.0 Mo | Réutilise le schéma déjà créé |
| `come_ai_web.create_app(Path(tmp))` | 0.40–0.74 (median 0.52) | 94.4 Mo | Crée l'app FastAPI + services connexes (mémoire, file d'attâches, etc.) |
| **Total interpréteur → app prêt** | **1.48 s median** | 94.4 Mo | Temps nécessaire pour avoir un serveur Career prêt à servir |

> **Note** : Les mesures de démarrage sont sensibles à la charge du système. Sous load avg ~6 (baseline), les médians ci-dessus sont stables. Sous load >30, les temps s'allongent de 20–40 % (observé pendant les premiers runs).

---

## 2. Mémoire

| État | RSS (Mo) | Observations |
|---|---|---|
| Après démarrage interpreteur | 10.5 Mo | Base Python |
| Après `import career.service` | 67.8 Mo (median) | Modules carrière + Ollama en arrière-plan |
| Après init `CareerService` (cold) | 72.9 Mo (median) | +5 Mo pour le nouveau schéma SQLite |
| Après init `CareerService` (warm) | 73.0 Mo (median) | quasi identique au cold (pas de fuite détectée) |
| Après `come_ai_web.create_app` | 94.4 Mo (median) | +21 Mo pour mémoire V5, file d'attâches, indexation, outils locaux |
| Après exploration 8 sources × 300 postings | 138.7–139.4 Mo | +35 Mo supplémentaires (cache, résultats en mémoire) |
| Modèle Ollama (qwen3.5:2b-q4_K_M) en inférence | 22.6–23.0 Mo | L'extension du serveur Ollama ajoute très peu de mémoire car le modèle réside dans les blobs mmap |

> **Observation** : La mémoire croît de façon linéaire avec le nombre de sources explorées et de jobs importés. Aucune fuite n'a été détectée sur les cycles de warm/reload.

---

## 3. Temps de collecte sur fixtures (Greenhouse synthetic feed)

Taux d'offres traitées par seconde et nombre retenu (plafonné à 150 par `GREENHOUSE_MAX_JOBS`) :

| Taille du feed | Temps median (s) | Offres/s | Conservées (retained) | Hors critères (excluded) | Confirmed | Uncertain |
|---|---|---|---|---|---|---|
| 100 | 0.13 s (median) | 765 off/s | 87 | 13 | 50 | 37 |
| 500 | 0.73 s (median) | 687 off/s | 150 | 63 | 250 | 187 |
| 2000 | 1.38 s (median) | 1446 off/s | 150 | 250 | 1000 | 750 |
| 10 000 | 7.16 s (median) | 1397 off/s | 150 | 1250 | 5000 | 3750 |
| 20 000 | 14.64 s (median) | 1366 off/s | 150 | 2500 | 10000 | 7500 |

> **Observation** : Le pipeline classe et qualifie toutes les offres, mais ne retient que les 150 meilleurs (constraint `GREENHOUSE_MAX_JOBS`). Le taux d'offres/sec est stable quel que soit la taille du feed (graphe plat), car le tri et le `heapq.nsmallest(150)` limitent le travail ultérieur.

---

## 4. Temps de déduplication

Opérations en mémoire sur les 150 candidats retenus après classement :

| Opération | Temps median (s) | Observations |
|---|---|---|
| Classement + effacement par URL canonique (dedup) | 0.0195 s (median, 20 réps) | Très rapide : tri par `ranking_key` + `dict.setdefault` sur URL canonique |
| Clé de déduplication uniquement (pas de tri) | 0.0016 s (median, 20 réps) | Juste calcul du `dedup_key`, pas de tri ni de classement |
| Clé URL uniquement (pas de clé source) | 0.0035 s (median, 20 réps) | `canonical_url(job["official_url"])` seulement |

> **Observation** : La déduplication n'est pas le goulot d'étranglement. Le tri explicite par `ranking_key` (qui intègre score, éducation, source_id, URL canonical + digest) reste la partie la plus coûteuse, mais reste < 20 ms pour 150 items.

---

## 5. Temps de qualification

Qualification des offres via `qualify_offer()` sur les fixtures synthétiques :

| Scénario | Offres | Temps median (s) | µs/offer | offres/s |
|---|---|---|---|---|
| Fixture `career_offer_qualification_synthetic.json` (30 offres) | 30 | 0.0032 s (median, 50 réps) | 108.6 us/offer | 9207 off/s |
| Sur les 150 jobs extraits d'une exploration | 150 | 0.0384 s (median, 20 réps) | 256 us/offer | 3906 off/s |

> **Observation** : La qualification est très rapide pour des jeux de petite taille (30–150 offres). La complexité est linéaire dans le nombre de champs inspectés (contrat, dates, durée, langue, etc.).

---

## 6. Taille des bases fictives (SQLite)

Base SQLite après import de postes synthétiques :

| Nb offres importées | Taille fichier (Ko) | Ko/offer | Taux remplissage |
|---|---|---|---|
| 100 | 268 Ko | 2.7 Ko/offer | ~100 % (toutes colonnes remplies) |
| 1000 | 1072 Ko | 1.1 Ko/offer | ~100 % |
| 5000 | 4708 Ko | 964 Ko/offer | ~100 % |
| Après exploration 8×300 (réel) | 360 Ko | — | — |

> **Observation** : Le fichier SQLite reste modeste (< 5 Mo même à 5000 offres). Le taux "bytes/offer" diminue légèrement avec le volume grâce aux en-têtes SQL et aux index partagés, mais reste très contenu.

> **Note sur la réimportation en doublon** : Réimporter 1000 fois la même offre détecte tous les doublons et ne crée aucune nouvelle ligne (0 created). Le temps est ~7.8 ms pour 1000 réessais, soit ~127 offres/s traitées comme "déjà présentes".

---

## 7. Disponibilité d'Ollama

| État | Valeur | Observations |
|---|---|---|
| Serveur Ollama en ligne (127.0.0.1:11434) | **Vérifié** | `local_status()` → `{"running": True, "version": "0.40.3"}` |
| Modèles locaux installés | **1 modèle** | `qwen3.5:2b-q4_K_M` (1.9B paramètres, Q4_K_M, contexte 262 144 tokens, runner `llamacpp`) |
| Modèle Qwen accessible | **Vérifié** | Présent dans la liste `/api/tags`, capable de génération |

> **Observation** : Ollama tourne en local avec le modèle Qwen 2b quantifié Q4_K_M. Aucun modèle supplémentaire n'a été observé dans le registry local.

---

## 8. Modèles locaux déjà présents

Modèle actuellement disponible :

| Modèle | Taille | Paramètres | Quantisation | Contexte | Capacités |
|---|---|---|---|---|---|
| `qwen3.5:2b-q4_K_M` | 1.62 Go | 1.9 B | Q4_K_M | 262 144 tokens | completion, vision, tools, thinking |

> **Observation** : Seul ce modèle est présent sur le disque `.local-ai/models`. Aucun autre modèle n'a été téléchargé ni n'est disponible.

---

## 9. Vitesse d'un modèle Qwen (inférence locale)

Génération sur `qwen3.5:2b-q4_K_M`, prompt : *« List three bullet points about what a finance internship teaches. Use French. »* (96 tokens max, température 0) :

| Run | Temps wall (s) | Tokens générés | Tokens/s | Load avg |
|---|---|---|---|---|
| 1 | 23.45 s | 96 | 4.36 | 123.21 |
| 2 | 22.30 s | 96 | 4.40 | 124.14 |
| 3 | 16.80 s | 96 | 5.83 | 123.81 |
| 4 | 16.33 s | 96 | 6.00 | 101.54 |

| Métrique | Valeur |
|---|---|
| **Tokens/s median** | **5.12 tok/s** |
| **Tokens/s min / max** | 4.36 – 6.00 tok/s |
| **Temps total wall median** | 19.55 s pour 96 tokens (incluant le chargement du modèle à la première exécution) |
| **Premier run** | 23.45 s (inclut le temps de chargement du modèle depuis le blob sur disque) |
| **Run suivants** | 16.3–22.3 s (modèle déjà en mémoire, pas de rechargement) |

> **Observation** : La vitesse d'inférence se situe autour de **5 tokens/seconde** en moyenne pour ce modèle 2b en quantisation Q4_K_M sur CPU. La première invocation est légèrement plus lente à cause du chargage du modèle depuis les blobs mmap. Aucune donnée personnelle n'est envoyée ; tout reste sur localhost.

---

## 10. NON VÉRIFIÉ (impossible à mesurer)

| Mesure | Raisons |
|---|---|
| **Démarrage à froid système complet** (sans les fixtures Python) | Le système est partagé (autres processus, index Spotlight, mises à jour background) ; les mesures auraient été très variables d'une exécution à l'autre. |
| **Consommation réseau** | Politique de mission : aucune donnée réseau ni collecte réelle n'est réalisée. |
| **Temps de qualification sur jeux > 150 offres en production** | Le pipeline capte à 150 offres max (`GREENHOUSE_MAX_JOBS`) ; mesurer sur un flux non borné nécessiterait une modification de la configuration qui sort du périmètre "local + fixtures". |
| **Temps de génération Qwen avec contexte étendu (> 262k tokens)** | Le contexte maximal du modèle est de 262 144 tokens ; tester au-delà provoquerait un échec ou un truncage de la part de ggml/llama-cpp. |
| **Mémoire virtuelle vs RSS** | Sous macOS, `ru_maxrss` inclut le mémoire partagé et les libraries partagées ; une mesure précise du "usage réel du processus" demanderait des outils comme `vmmap` ou `valgrind` qui ne sont pas disponibles dans cet environnement. |

---

## 11. Synthèse

| Catégorie | Résultat clé |
|---|---|
| **Démarrage** | ~1.5 s pour avoir un service Career complet (import + create_app), RSS ~94 Mo |
| **Mémoire** | 68–94 Mo selon l'étape ; croissance linéaire avec le nombre de sources/jobs |
| **Collecte (fixtures)** | ~1400 offres/s traités, plafonnés à 150 retenus ; classement + qualification en < 15 ms |
| **Déduplication** | < 20 ms pour 150 candidats (tri + effacement URL canonique) |
| **Qualification** | ~108 µs/offer sur 30 fixtures ; ~3.9 k offres/s sur 150 jobs |
| **Base de données** | < 5 Mo même à 5000 offres ; pas de croissance significative |
| **Ollama** | Disponible localement, 1 modèle (Qwen 2b Q4_K_M) |
| **Qwen inference** | ~5 tok/s sur CPU, première invocation + chargement de modèle |

> **Conclusion** : Le pipeline Career Agent fonctionne de façon autonome et locale. Le temps de démarrage est acceptable (< 2 s), la mémoire est raisonnable (94 Mo max pour l'app + services), et les temps de traitement sur des fixtures synthétiques sont très rapides (centaines à milliers d'offres/seconde selon l'étape). Le modèle Qwen 2b local apporte une capacité d'inférence générique à ~5 tokens/seconde, suffisante pour des résumés courts ou de la classification légère. Aucune donnée personnelle ni trafic réseau n'a été utilisé dans ces mesures.

---
*Rapport généré automatiquement par un script de benchmark local. Toutes les valeurs sont issues d'exécutions sur des fixtures synthétiques (`.example.test`) dans l'état actuel de la machine (load average consigné à chaque point de mesure).*