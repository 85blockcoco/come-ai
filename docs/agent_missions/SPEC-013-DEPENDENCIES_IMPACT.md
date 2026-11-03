# MISSION SPEC KIT — SPEC-013 : Dépendances et Impact

> **Priorité : P0** — Module transverse, fondation pour l'analyse d'impact et la gestion du changement. Worktree dédié.

---

## Contexte

Le système comporte de nombreuses entités interdépendantes : offres, exigences, preuves, profils, candidatures, matchings. Un changement dans une entité (ex: modification d'une exigence, expiration d'une preuve, nouvelle offre) peut avoir un impact en cascade. Il faut un **graphe de dépendances** et un **moteur d'analyse d'impact**.

---

## Objectif

Créer un **moteur de dépendances et d'analyse d'impact** qui :
1. Construit et maintient un graphe de dépendances entre toutes les entités
2. Calcule l'impact d'un changement (propagation, étendue, criticité)
3. Fournit des scénarios "what-if" avant application
4. Génère des plans de migration/validation ordonnés
5. Détecte les cycles et les points de fragilité

---

## Nouveaux modules à créer

```
career/dependencies.py              # Core: graphe, algorithmes, impact
career/dependencies_store.py        # Persistance graphe, index, versioning
career/impact_analysis.py           # Moteur d'impact, scénarios, plans
career/router.py                    # Endpoints graphe, impact, scénarios
career_static/js/dependencies.js    # UI graphe interactif, impact, scénarios
tests/test_dependencies.py
docs/agent-reports/SPEC-013-DEPENDENCIES_IMPACT.md
```

---

## Contrat attendu

### DependencyGraph (graphe orienté)

```python
@dataclass
class DependencyNode:
    node_id: str                          # "requirement:req_123" / "evidence:ev_456" / "offer:offer_789"
    node_type: Literal["requirement", "evidence", "offer", "profile", "application", "matching", "skill", "certification"]
    label: str
    metadata: dict                        # Attributs spécifiques au type

@dataclass
class DependencyEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_type: Literal["requires", "provides", "validates", "contradicts", "derives_from", "blocks", "enables"]
    weight: float                         # 0.0-1.0, force de la dépendance
    metadata: dict                        # Conditions, contexte

@dataclass
class DependencyGraph:
    nodes: dict[str, DependencyNode]
    edges: list[DependencyEdge]
    version: int
    updated_at: str
```

### ImpactAnalysis (résultat d'analyse)

```python
@dataclass
class ImpactNode:
    node_id: str
    impact_level: Literal["none", "low", "medium", "high", "critical"]
    impact_reasons: list[str]
    affected_paths: list[list[str]]       # Chemins depuis le nœud source
    estimated_effort: Literal["trivial", "low", "medium", "high", "blocking"]

@dataclass
class ImpactAnalysis:
    source_node_id: str
    change_type: Literal["create", "update", "delete", "status_change", "link", "unlink"]
    change_details: dict
    impacted_nodes: list[ImpactNode]
    critical_path: list[str]              # Chemin le plus critique
    propagation_depth: int
    estimated_total_effort: Literal["trivial", "low", "medium", "high", "blocking"]
    breaking_changes: list[str]           # Changements cassants détectés
    recommended_order: list[str]          # Ordre recommandé pour appliquer
    rollback_plan: list[str]              # Plan de rollback si échec
```

---

## Algorithmes attendus

### 1. Construction du graphe (auto + manuel)

| Source | Règle de création d'arêtes |
|--------|----------------------------|
| SK-02 (Requirements) | requirement → provides → skill/entity |
| SK-10 (Evidence) | evidence → validates → requirement |
| SK-21 (Matching) | requirement ← matched_by → evidence |
| SK-11 (Application) | application → uses → profile/evidence |
| SK-08 (EvidenceCenter) | evidence ↔ evidence (merges, splits) |
| Manuel | User-defined links |

### 2. Propagation d'impact (BFS/DFS pondéré)

```
Algorithme:
1. Partir du nœud source modifié
2. BFS/DFS pondéré par edge.weight
3. Seuil de propagation: weight * parent_impact > threshold
4. Arrêt si impact_level = "none" ou profondeur max
5. Calcul effort cumulé par chemin
```

### 3. Détection de cycles

- Algorithme de Tarjan ou DFS avec couleurs
- Signalement cycles + proposition de résolution

### 4. Points de fragilité (centralité)

- Betweenness centrality → nœuds critiques
- PageRank adapté → nœuds d'influence
- Détection "single point of failure"

---

## Scénarios "What-If"

| Scénario | Input | Output |
|----------|-------|--------|
| Supprimer exigence | node_id + delete | ImpactAnalysis complet |
| Modifier criticité | node_id + new_criticality | ImpactAnalysis |
| Ajouter preuve | evidence_id + links | Impact réduit |
| Supprimer offre | offer_id | Cascade vers requirements, matching, applications |
| Changer criticité exigence | requirement_id + new_criticality | Recalcul matching scores |

---

## API attendue

```
POST   /dependencies/graph              # Construire/rafraîchir graphe
GET    /dependencies/graph              # Récupérer graphe complet
GET    /dependencies/graph/nodes/{id}   # Détail nœud + voisins
POST   /dependencies/edges              # Ajouter arête manuelle
DELETE /dependencies/edges/{id}         # Supprimer arête
POST   /dependencies/impact             # Analyser impact (body: source, change_type, details)
POST   /dependencies/scenario           # Simuler scénario (body: changes[])
GET    /dependencies/critical-nodes     # Nœuds critiques (centralité)
GET    /dependencies/cycles             # Cycles détectés
GET    /dependencies/fragility          # Points de fragilité
POST   /dependencies/plan               # Générer plan d'exécution ordonné
```

---

## Plan d'exécution ordonné

```python
@dataclass
class ExecutionPlan:
    steps: list[ExecutionStep]
    parallel_groups: list[list[str]]    # Groupes exécutables en parallèle
    critical_path: list[str]
    estimated_duration: str
    rollback_triggers: list[str]
```

---

## API attendue (suite)

```
POST   /dependencies/validate           # Valider cohérence graphe
POST   /dependencies/snapshot           # Créer snapshot versionné
GET    /dependencies/history            # Historique changements graphe
POST   /dependencies/rollback           # Rollback vers snapshot
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_dependencies.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Graphe auto-construit depuis SK-02, SK-10, SK-21, SK-11, SK-08
- [ ] Liens manuels CRUD + validation cohérence
- [ ] Analyse d'impact : propagation pondérée, seuils, profondeur max
- [ ] Scénarios what-if : simulation multi-changements
- [ ] Plan d'exécution ordonné + groupes parallèles + chemin critique
- [ ] Détection cycles + fragilité (centralité)
- [ ] UI graphe interactif : zoom, filtres, highlight chemin critique
- [ ] Intégration SK-02, SK-10, SK-21, SK-11, SK-08, SPEC-011
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-013-DEPENDENCIES_IMPACT.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-013-dependencies-impact`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.