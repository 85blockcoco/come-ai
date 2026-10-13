# Laboratoire d'évaluations Côme AI (`evals/`)

Laboratoire issu de `feature/evals-qualite`, intégré par lots contrôlés pour
mesurer les régressions et, progressivement, des services réels de Côme AI.
Les auto-tests simulés du laboratoire ne mesurent jamais la qualité de l’application.

## Principes

- **Aucun cloud requis.** Les cibles fournies utilisent des données synthétiques.
  `ComeAITarget` bloque les sockets et le transport cloud, sans charger `.env`.
  Le runner est extensible : un adaptateur tiers devra fournir ses propres
  garanties. Une consommation déclarée par une cible n’est pas une mesure du réseau.
- **Aucune donnée personnelle, aucun secret.** Tous les cas utilisent des
  données synthétiques.
- **Aucun changement d'architecture** de Côme AI et aucune modification des
  fichiers des autres agents.
- **Aucun résultat inventé.** Les métriques du rapport sont mesurées
  (durée, mémoire pic, compteurs), jamais estimées. L'affichage le signale.

## Découpage

```
evals/
├── cases/            # 60 cas documentés (JSON), 4 catégories
│   ├── memoire.json       20 cas : mémoire, recherche, citations, documents
│   ├── documents.json     15 cas : analyse PDF et Excel
│   ├── finance.json       15 cas : calculs, hypothèses, cohérence, erreurs
│   ├── conversation.json  10 cas : conversation, routage, outils
│   └── come_ai_real.json  sous-suite distincte de services réellement exécutés
├── schema.py         # chargement + validation de l'intégrité de la suite
├── checks.py         # 14 validateurs déterministes
├── runner.py         # exécution, métriques, comparaison de runs
├── report.py         # rapports Markdown
├── __main__.py       # CLI : list | suite | run | compare
├── come_ai_target.py  # adaptateur borné vers les services locaux existants
├── runs/             # archives des démonstrations simulées d’origine
└── tests/            # tests automatisés du laboratoire (pytest)
```

## Cas d'évaluation

Chaque cas porte : identifiant, objectif, données d'entrée, résultat attendu,
critères d'acceptation vérifiables, conditions d'échec, fonctionnalités
requises et un **statut** :

- `supported` — contrat de test prêt à être évalué. **Ce statut seul ne prouve
  pas que Côme AI sait exécuter le scénario.** La cible réelle doit déclarer les
  capacités nécessaires et posséder un handler du cas ; sinon il reste non pris
  en charge. Les 49 contrats d’origine n’équivalent pas à 49 parcours vérifiés.
- `future` — la fonctionnalité n'existe pas encore (ex. recherche vectorielle,
  OCR, consolidation Nemotron). Le cas est **documenté mais non exécuté**,
  compté « non pris en charge » et jamais compté comme bug.

### Familles de défauts détectées

| Défaut | Validateur(s) |
|---|---|
| Réponse incorrecte / erreur de calcul | `numeric_close`, `exact_value` |
| Information inventée | `no_hallucinated_facts` |
| Mauvaise citation | `citations_valid` |
| Perte d'information | `facts_present`, `contains_all` |
| Mauvais choix d'outil | `tools_called`, `tools_not_called` |
| Plan invalide | `plan_valid` |
| Échec silencieux | `error_signaled` |
| Consommation excessive | `budget_respected` |
| Fuite de secret / chemin | `not_contains` |

## CLI

```bash
python -m evals list                        # la suite de 60 cas
python -m evals suite                       # résumé JSON
python -m evals run --target simulated      # auto-test du runner
python -m evals run --target fault:wrong_answer --strict
python -m evals run --target come-ai --strict # sous-suite réelle, sans modèle/cloud
python -m evals compare .devkit/evals/runs/A.json .devkit/evals/runs/B.json --strict
python -m pytest evals/tests -q             # tests du laboratoire
```

Les nouveaux runs sont persistés sous `.devkit/evals/runs/`, hors Git et hors
export. La suite contractuelle par défaut reste constituée des quatre fichiers
historiques (60 cas). Le fichier `come_ai_real.json` est chargé séparément pour
la cible réelle ; une suite JSON explicite peut être choisie avec `--cases-dir`.
Python 3.12+ ; stdlib pour le runner, environnement existant de Côme AI pour
la cible réelle, pytest pour les tests. `pytest` et `devkit check` incluent
désormais `evals/tests`.

## Cible simulée : ce que ça prouve, et ce que ça ne prouve pas

`SimulatedTarget` reconstruit l'idéal de chaque cas. Elle sert **uniquement**
à vérifier que le laboratoire fonctionne : détection, métriques, rapports,
comparaison. Les taux qu'elle produit ne disent **rien** sur la qualité d'un
modèle IA. `FaultInjectionTarget` injecte une faute connue par famille pour
prouver que chaque famille est effectivement captée.

### Cible réelle bornée

`ComeAITarget` utilise un workspace temporaire différent pour chaque cas :

- calculs et recherche mémoire via les fast paths réels de `HybridChatService` ;
- mémoire FTS5 et citations issues de `PersonalMemoryStore` ;
- fichiers CSV/XLSX synthétiques, inspection et statistiques via `LocalTools`
  et exécution du plan de `LocalOrchestrator` ;
- refus d’identifiant de fichier non autorisé, confirmation d’écriture et
  validation des propositions d’outils par le registre existant.

L’adaptateur ne reconstruit pas ses réponses depuis `case.expected`. Les valeurs
attendues ne sont lues que par les validateurs. Les traces incluent les services
appelés et leurs sorties/refus réels. Les UUID de mémoire sont associés aux IDs
des fixtures pour rendre les citations reproductibles.

Cette sous-suite **ne mesure pas** la qualité rédactionnelle, le raisonnement
d’un LLM, le routage cloud ou une conversation Qwen. La génération de modèle
est explicitement non prise en charge. Elle ne démontre pas non plus le parcours
complet avec rapport confirmé et tâche personnelle de suivi.

### Étendre une cible

Le runner est découplé de la cible. Une cible déclare son `execution_kind`
(`real`, `simulated` ou `unknown`) et ses capacités. Le contrat `TargetResult`
permet de signaler une observation, une capacité non prise en charge ou une
erreur d’exécution, avec les traces. Une ancienne cible retournant un dictionnaire
sans provenance ne peut pas produire un score réel. L'observation attendue :

```json
{
  "answer": "texte final ou null",
  "structured": {"...": "sortie JSON-safe ou null"},
  "citations": [{"source_id": "SRC-1", "quote": "extrait exact"}],
  "facts": ["faits allégués"],
  "tools_called": ["outil"],
  "plan": [{"step_id": "s1", "tool": "inspect_file", "arguments": {}, "depends_on": []}],
  "usage": {"api_calls": 0, "tokens": 0, "cost_usd": 0.0},
  "error": "null, ou message d'erreur explicite"
}
```

Ajouter des handlers explicites plutôt qu’un nom de méthode libre provenant du
cas. Conserver les fichiers synthétiques, l’isolation des stores, les limites de
permissions et le refus de réseau. Toute nouvelle capacité doit avoir un test
positif, un cas incorrect et un cas de refus/erreur approprié.

## Métriques produites

- Nombre de cas exécutés, réussis, en échec, non pris en charge
- Taux de réussite des cas exécutables (les cas « futur » en sont exclus)
- Erreurs critiques (sévérité `critical` en échec)
- Exactitude des calculs vérifiables (`numeric_close`)
- Validité des structures (`structure_valid`, `plan_valid`)
- Traçabilité des sources (`citations_valid`)
- Garde anti-hallucination (`no_hallucinated_facts`, `facts_present`)
- Durée d'exécution et mémoire pic (**mesurées** localement)
- Résultats réels séparés des simulations et des provenances inconnues
- Consommation **déclarée**, ou inconnue : jamais un zéro « mesuré » par défaut
- Erreur d’exécution distincte de résultat incorrect et de capacité non prise en charge

## Comparaison et régressions

`python -m evals compare base.json candidat.json` produit la liste des
**régressions** (cas qui passaient et échouent), des **améliorations**, des
changements de statut et du delta de suite. `--strict` sort avec le code 1 si
une régression ou une perte de couverture est détectée. Les comparaisons de
provenances différentes (simulation contre réel) ou inconnues sont refusées.
Les rapports historiques de `runs/` restent des démonstrations de version 1,
pas des mesures actuelles de l’application.
