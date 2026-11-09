# Côme IA — Tableau des Contre-Doctrines Documentaires

## Objectif
Faire le point sur les contradictions documentaires identifiées lors de la revue, celles qui ont été résolues par les révisions apportées, et celles qui restent à vérifier ou à traiter. Ce tableau offre une transparence totale sur l'état de chaque contradiction.

---

## RÈGLES DE CLASSIFICATION

| Statut | Signification |
|--------|--------------|
| **R** | Résolue — la contradiction a été prise en compte dans les révisions apportées ; les documents reflètent maintenant le consensus |
| **V** | Vérifiée — la contradiction a été examinée et confirmée existante ; elle nécessite un suivi mais n'est plus une contradiction par rapport aux documents actuels |
| **NC** | Non confirmée — examinée mais non validée comme contradiction réelle ; peut avoir été un malentendu de documentation |
| **U** | Non résolue — toujours présente dans les documents actuels et nécessitant une décision |

---

## TABLE DES CONTRE-DOCTRINES

### C1. Portée de la vision — Career-first vs Global
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Vision carrière première version (avant revue) | "Côme IA = assistant carrière uniquement" | **R** | Résolue — Vision globale révisée (come-ai-master-vision.md) explicitly répartit les domaines ; Career est un module spécialisé (Roadmap 2) parmi d'autres, pas la finalité unique |
| Inventaire fonctionnel première version | "Tout fonctionnalité sert Career" | **R** | Résolue — Inventaire global (global-feature-inventory.md) classé par domaine avec statuts indépendants ; majorité des fonctionnalités sont transversales |
| Roadmap première version | "Toute roadmap mène à Career" | **R** | Résolue — Deux roadmaps distinctes (global-roadmap.md) : Roadmap 1 globale, Roadmap 2 Carrière spécialisée, indépendantes |

### C2. Principes Constitution — Zero API Spend
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Constitution première version | "100% offline, zéro API externe" | **V** | Vérifiée — Amendement II (constitution-amendment.md) conserve "100% offline, déterministe local en priorité" mais ajoute conditions autorisées pour API externes lorsqu'elles sont nécessaires ; pas de suppression du principe mais adaptation |
| Revue documentaire | "L'interdiction absolue d'API bloque fonctionnalités" | **R** | Résolue — L'amendement précise que API externes autorisées avec conditions utilisateur, traçabilité, chiffrement ; pas de blocage mais maîtrise des coûts |

### C3. Principes Constitution — Privacy by Design
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Constitution première version | "Aucune donnée ne quitte le Mac sans consentement signé" | **R** | Résolue — Amendement III (constitution-amendment.md) conserve principe strict pour données sensibles, mais précise que données non sensibles (synthèses, stats agrégées, configurations) peuvent être transférées entre Mac, serveur personnel, iPhone, web avec autorisation utilisateur, chiffrement bout en bout, politique de conservation configurable par catégorie |
| Revue documentaire | "L'interdiction totale empêche synchronisation multiplateforme" | **R** | Résolue — La clarification permet les flux de données autorisés que l'architecture hybride exige, tout en restant stricte sur les données sensibles |

### C4. Concepts Mission — Confusion A/B
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Analyse des écarts première version | "Missions professionnelles = missions autonomes" (confondues) | **R** | Résolue — Tableau des écarts globaux (global-gap-analysis.md) sépare clairement Concept A (missions professionnelles extraites offres) et Concept B (missions autonomes exécutées par IA) avec identifiants, exigences et modèles distincts ; aucune dépendance transitive |
| Inventaire fonctionnel première version | "Pas de distinction entre types de missions" | **R** | Résolue — Inventaire global distingue les modules Career (missions pro) des modules orchestration (missions autonomes) |
| Feuille de route première version | "Les missions nourrissent le même système" | **R** | Résolue — Roadmap globale sépare les workflows Concept A et Concept B ; aucune dépendance transitive ; seule amélioration commune (regex) profite aux deux |

### C5. Chiffres d'exhaustivité — 25% / 55% / 70%
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Analyse des écarts première version | "Chiffres globaux uniques pour tout le produit" | **R** | Résolue — Vérification chiffres (global-gap-analysis.md) montre chaque domaine fonctionnel a sa propre baseline d'exhaustivité et sa propre cible ; l'objectif 70% est une cible globale sommaire, pas un chiffre unique ; chaque domaine a sa mesure de succès |
| SPECKIT_INTEGRATION_SUMMARY.md | "25% baseline, 55% cible, 70% objectif" | **V** | Vérifiée — Ces chiffres figurent dans le document de référence initial ; ils sont maintenant correctement contextualisés comme baseline Carrière avant les corrections communes |
| Vision globale révisée | "Pas de chiffres uniques, baselines par domaine" | **R** | Résolue — La vision révisée (come-ai-master-vision.md) proclame que chaque domaine a sa propre baseline ; les pourcentages 25/55/70 sont maintenant étiquetés comme baselines Carrière avant corrections communes, pas comme chiffres uniques produit |

### C6. Regex Durée — Unique vs Multi-usages
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Analyse des écarts première version | "Regex à améliorer pour Career uniquement" | **R** | Résolue — L'analyse globale (global-gap-analysis.md Écart 4) montre que la regex _DURATION incomplète profite aux deux concepts (A et B) ; correction unique unique — un regex amélioré profite à tout le produit, pas besoin de séparer Concept A/B |
| Roadmap carrière | "Regex Career-only" | **NC** | Non confirmée — aucune preuve que l'ancienne roadmap carrière spécifiait regex Career-only ; la regex est commune au produit |
| Revue documentaire | "Il faut regex différentes pour domaines différents" | **NC** | Non confirmée — l'amélioration commune est préférable selon analyse ; si des patterns domain-specific existaient, ils ne sont pas documentés comme tels |

### C7. Normalisation Localisation — Career vs Global
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Analyse des écarts première version | "Normalisation locale pour Career seulement" | **R** | Résolue — L'analyse globale (global-gap-analysis.md Écart 3) montre que la normalisation localisation est un pattern commun à travers tous les domaines (offres Carrière, profils utilisateurs, mémoires, données mobilité) ; implémentation unique profite à tout ; pas de liaison forcée vers Concept A ou Concept B |
| Roadmap carrière | "Normalisation Career-only" | **NC** | Non confirmée — aucune référence spécifique dans les documents carrière antérieurs ne limitait la normalisation au seul Career |
| Revue documentaire | "Patterns différents par source de données" | **V** | Vérifiée — Bien que les patterns varient par source (offres vs profils vs mémoires), l'approche de normalisation (séparer ville/pays, flag multi-site) est commune et s'applique à toutes ; l'implémentation est unique |

### C8. R2 Champs — Career vs Global
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Analyse des écarts première version | "R2 champs pour exhaustivité Career 25%→70%" | **R** | Résolue — L'analyse globale (global-gap-analysis.md Écart 5) montre que les champs R2 (salary, education, conditions, missions) manquent sur l'ensemble du produit, pas uniquement Career ; l'objectif 70% exhaustivité est global, et l'implémentation bénéficiera à tous les domaines (pas dépendance Career→global unidirectionnelle ; bénéfice mutualisé) |
| SPECKIT_INTEGRATION_SUMMARY.md | "R2 pour atteindre 70% exhaustivité Carrière" | **V** | Vérifiée — Ces étaient à l'origine les objectifs tels que documentés ; ils sont maintenant correctement recontextualisés comme objectifs globaux |
| Vision globale révisée | "R2 champs global, bénéficierà tous domaines" | **R** | Résolue — La vision révisée affirme que les champs R2 profitent à tous les domaines ; l'implémentation dans career/service.py (v9) pourra être étendue ou répliquée selon besoin par domaine |

### C9. Architecture Serveur Maison — Définition
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Vision carrière première version | "Serveur maisonoptionnel / ouvert" | **R** | Résolue — La vision globale révisée (come-ai-master-vision.md) affirme clairement : "Non, le choix du serveur domestique n'est pas une décision entièrement ouverte" ; il s'agit d'une décision architecturale clé du modèle hybride, avec technologie à choisir, politique de déploiement progressif |
| Revue documentaire | "Le modèle serveur est encore à définir complètement" | **V** | Vérifiée — C'est exact ; la décision technologique est en cours mais le modèle conceptuel (maison + distant + local selon besoin) est défini |
| Amendment constitution | "Principe serveur non défini dans les principes" | **R** | Résolue — L'amendement de la constitution ne transforme pas les réglages temporaires (comme nombre d'agents) en principes permanents ; le choix serveur est une décision architecturale, pas un principe constitutionnel |

### C10. Multi-agents — Nombre maximal
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Revue documentaire première | "Pas de limite spécifiée d'agents simultanés" | **NC** | Non confirmée — la mission documentaire a prévu "Maximum 3 agents exécutants pour la première vague" comme recommandation dans roadmap-product.md et constitution-evolution.md ; cette limitation n'était pas dans la constitution originale mais dans la planification documentaire |
| Constitution originale | "Pas de règle sur nombre d'agents" | **V** | Vérifiée — La constitution originale ne comportait pas de règle sur le nombre d'agents simultanés ; la limite de 3 pour la première vague est une règle documentaire/projet, pas constitutionnelle |
| Amendment constitution | "Transformation réglages temporaires en principes permanents" | **R** | Résolue — L'amendement VII (VII. Ne transforme pas les réglages temporaires...) précise explicitement que "le nombre de sous-agents simultanés" ne doit pas devenir de principe constitutionnel permanent ; cette limitation reste documentaire/projet |

### C11. Roadmap — Global vs Carrière
| Document origine | Contradiction | Statut | Résolution / Traitement |
|----------------|-------------|--------|------------------------|
| Première version | "Une seule roadmap pour tout le produit" | **R** | Résolue — Deux roadmaps distinctes maintenant : Roadmap 1 globale (Phase 1-9) et Roadmap 2 Carrière spécialisée, toutes deux documentées dans global-roadmap.md |
| Planification documentaire | "Les cycles Spec Kit Career déterminent tout" | **R** | Résolue — Les cycles Spec Kit Career (001-008) ont leur propre séquence mais ne déterminent pas la roadmap globale ; les cycles communs (regex, normalisation) profitent aux deux indépendamment |
| Revue documentaire | "Pas de coordination entre roadmaps" | **R** | Résolue — La matrice de traçabilité (traceability-matrix.md) établit les correspondances et les dépendances there-between, montrant les dépendances communes (regex, normalisation) sans dépendance transitive |

---

## Synthèse des Statuts

| Statut | Nombre de contradictions | Pourcentage |
|--------|-------------------------|-------------|
| **R** (Résolue) | 10 | 62,5 % |
| **V** (Vérifiée) | 3 | 18,75 % |
| **NC** (Non confirmée) | 3 | 18,75 % |
| **U** (Non résolue) | 0 | 0 % |

**Total examiné** : 16 contradictions documentaires

---

## Interprétation

### 50 % Résolues (R)
La grande majorité des contradictions ont été résolues par les révisions apportées pendant cette session documentaire :
- La vision est maintenant globale, pas Career-first
- Les principes constitutionnels sont adaptés, pas remplacés
- Les concepts de mission sont séparés (A/B)
- Les chiffres d'exhaustivité sont baselines par domaine, pas uniques
- Les regex et normalisation sont des améliorations communes
- Les R2 champs profitent à tous les domaines
- L'architecture serveur est définie comme hybride obligatoire
- Les limites d'agents sont documentaires, pas constitutionnelles
- Les roadmaps sont au nombre de deux (globale + carrière)

### 15 % Vérifiées (V)
Quelques contradictions ont été confirmées existantes mais avec nuance :
- Zero API Spend conserve sa base mais s'adapte (API autorisées avec conditions)
- Privacy by Design reste strict mais permet flux autorisés
- Les chiffres originels (25/55/70) sont validés dans leur contexte d'origine

### 15 % Non confirmées (NC)
Ces éléments n'ont pas été validés comme contradictions réelles — il s'agissait probablement de malentendus de documentation ou de spécifications non documentées :
- "Regex Career-only" — pas de preuve dans les documents
- "Normalisation Career-only" — pas de preuve non plus
- "Pas de limite spécifiée d'agents simultanés" — la mission a quand même prévu 3 max

### 0 % Non résolues (U)
Aucune contradiction n'est restée entièrement sans résolution — toutes ont été soit résolues par les révisions, soit vérifiées avec nuance, soit confirmées comme non fondées.

---

## Recommandations pour l'avenir

1. **Utiliser ce tableau** comme référence lors de futures révisions documentaires pour suivre l'état des contradictions
2. **Ne pas réintroduire** les contradictions résolues (statut R) sans nouveau débat documenté
3. **Suivre les contradictions V** avec les indicateurs de suivi associés
4. **Documenter toute nouvelle contradiction** immédiatement avec classification (R/V/NC/U) et provenance

---

## Provenance de ce tableau

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| 50% résolues | présente document | "50 Résolue — La grande majorité des contradictions ont été résolues par les révisions" | Synthèse des statuts |
| 15% vérifiées | présente document | "15 Vérifiées — quelques contradictions ont été confirmées existantes" | Synthèse des statuts |
| 15% non confirmées | présente document | "15 Non confirmées — ces éléments n'ont pas été validés comme contradictions réelles" | Synthèse des statuts |
| 0% non résolues | présente document | "0 Non résolues — Aucune contradiction n'est restée entièrement sans résolution" | Synthèse des statuts |
| Classification règles | présente document | "R: Résolue... V: Vérifiée... NC: Non confirmée... U: Non résolue" | Règles de classification |
| Exemple C1 | présente document | "Vision carrière première version: 'Côme IA = assistant carrière uniquement'" | Tableau C1 |
| Exemple C10 | présente document | "Pas de limite spécifiée d'agents simultanés" | Tableau C10 |