# Côme IA — Feuille de Route Priorisée

## Objectif
Définir la séquence prioritisée des cycles de développement Spec Kit pour combler les écarts identifiés et atteindre les objectifs de la vision maître. Chaque cycle suit le workflow complet Spec Kit (spec → plan → research → data-model → contracts/interfaces → quickstart → checklists → tasks) et produit des artefacts réutilisables.

---

## Hiérarchie des cycles

### Niveau 1 : Fondations (déjà completes ✅)
| Cycle | Intitulé | État | Objectif principal | Dépendances |
|-------|----------|------|-------------------|-------------|
| 001 | Persist qualification facts | ✅ Completed | Extraire et persister qualificatifs offres (dates, type contrat, durée, citations) | Aucune |
| 002 | Fix missions key confusion | ✅ Planifié | Clarifier confusion "requirements" vs "missions" sur 9 offres | 001 |
| 003 | Expand _DURATION regex | ✅ Planifié | Capturer 6 offres supplémentaires (semaines/semestres) | 001 |
| 004 | Normalize location | ✅ Planifié | Country ≥ 95/121 offers (split ville/pays) | 001 |

### Niveau 2 : Cible 70% exhaustivité (après Niveau 1)
| Cycle | Intitulé | État | Objectif principal | Dépendances |
|-------|----------|------|-------------------|-------------|
| 005 | Add R2 fields | ⏳ Planifié | Exhaustivité globale ≥ 70% (ajout salary, education, conditions, missions) | 002, 003, 004 |

### Niveau 3 : Fonctionnalités subséquentes
| Cycle | Intitulé | État | Objectif principal | Dépendances |
|-------|----------|------|-------------------|-------------|
| 006 | Application dossier assembly | ⏳ Planifié | Assemblage end-to-end des dossiers candidature depuis offres qualifiées | 005 |
| 007 | Missions extractor integration | ⏳ Planifié | Extraction automatique missions depuis offres | 001, 005 |
| 008 | Education extractor integration | ⏳ Planifié | Extraction éducation depuis offres/profil | 001 |

---

## Séquence d'exécution recommandée

### Phase 1 : Cycles indépendants (peut démarrer immédiatement)
**Fenêtre de temps :** Sprint 1-2
| Cycle | Action | Estimation | Parallelisable | Résultat attendu |
|-------|--------|------------|----------------|------------------|
| 002 | Missions key clarification | 3-5 tâches [P] | ✅ Oui (avec 003) | 0/9 offres avec panel vide résolu |
| 003 | Duration regex expansion | 2-3 tâches [P] | ✅ Oui (avec 002) | +6 offres capturées, fiche_pct +1-2% |

**Exécution Phase 1 :**
- Lancer les deux cycles en parallèle via agents OpenCode séparés
- Maximum 3 agents exécutants pour cette première vague
- Valider les deux cycles avant de passer au suivant
- Produire artefacts Spec Kit pour chaque cycle (spec.md, plan.md, tasks.md, quickstart.md)

### Phase 2 : Cycle dépendant (après Phase 1)
**Fenêtre de temps :** Sprint 3
| Cycle | Action | Estimation | Dépendances | Résultat attendu |
|-------|--------|------------|-------------|------------------|
| 004 | Location normalization | 5-7 tâches [P] | 001 (déjà complet) | Country ≥ 95/121 offers; localisation normalisée |

**Exécution Phase 2 :**
- Commencer après validation Phase 1 (cycles 002 + 003 "done")
- 1 agent exécutant (plus complexe, plus de dépendances inter-modules)
- Valider normalisation avant/après sur corpus 121 offres
- Produire artefacts Spec Kit complets

### Phase 3 : Cycle cible exhaustivité (après Phase 2)
**Fenêtre de temps :** Sprint 4-5
| Cycle | Action | Estimation | Dépendances | Résultat attendu |
|-------|--------|------------|-------------|------------------|
| 005 | Add R2 fields | 8-12 tâches [P] | 002, 003, 004 terminés | Exhaustivité globale ≥ 70% (cible principale) |

**Exécution Phase 3 :**
- 1-2 agents exécutants (charge travail plus importante)
- Validation exhaustivité globale sur corpus complet
- Vérifier tous les success criteria SC-001 à SC-007
- Produire artefacts Spec Kit complets + quickstart validation scenarios

### Phase 4 : Fonctionnalités subséquentes (après Phase 3)
**Fenêtre de temps :** Sprint 6+
| Cycle | Action | Estimation | Dépendances | Résultat attendu |
|-------|--------|------------|-------------|------------------|
| 006 | Application dossier assembly | 5-8 tâches [P] | 005 terminés | End-to-end dossier candidature génération |
| 007 | Missions extractor integration | 4-6 tâches [P] | 001, 005 terminés | Missions extraites automatiquement des offres |
| 008 | Education extractor integration | 4-6 tâches [P] | 001 terminés | Éducation extraite depuis offres/profil |

---

## Dépendances entre cycles

```mermaid
graph TD
    subgraph Phase 1 "Phase 1: Cycles indépendants"
        A[Cycle 002: Missions key] -->|peut paralléliser| B[Cycle 003: Duration regex]
    end
    
    subgraph Phase 2 "Phase 2: Dépendant Phase 1"
        B -->|attend validation| C[Cycle 004: Location normalization]
    end
    
    subgraph Phase 3 "Phase 3: Cible 70% exhaustivité"
        C -->|attend validation| D[Cycle 005: R2 fields addition]
    end
    
    subgraph Phase 4 "Phase 4: Fonctionnalités subséquentes"
        D -->|attend validation| E[Cycle 006: Application dossier]
        D -->|attend validation| F[Cycle 007: Missions extractor]
        D -->|attend validation| G[Cycle 008: Education extractor]
    end
    
    style Phase 1 fill:#cfe2f3,stroke:#157347
    style Phase 2 fill:#cfe2f3,stroke:#157347
    style Phase 3 fill:#bbdefb,stroke:#157347
    style Phase 4 fill:#e8f5e9,stroke:#2e7d32
```

---

## Capacité d'agents exécutants

### Première vague (Phase 1) : Maximum 3 agents
- Agent A : Cycle 002 tasks (missions key clarification) — 3-5 tâches [P]
- Agent B : Cycle 003 tasks (duration regex expansion) — 2-3 tâches [P]
- Agent C : Support/review (review Phase 1 output, prepare Phase 2)

### Deuxième vague (Phase 2) : 1 agent
- Agent unique : Cycle 004 tasks (location normalization) — plus complexe, nécessite concentration

### Troisième vague (Phase 3) : 1-2 agents
- Agent A : Cycle 005 tasks (R2 fields addition) — plus grand volume de tâches
- Agent B : Support/review et préparation Phase 4

### Quatrième vague (Phase 4) : 1 agent par cycle
- Chaque cycle 006, 007, 008 peut avoir son propre agent (indépendants les uns des autres après 005)

---

## Livrables par cycle (workflow Spec Kit complet)

Chaque cycle produit ces artefacts dans `specs/<cycle-number>-<title>/`:

1. **spec.md** — Feature specification (2-5 user stories, 9 FRs, 7 SCs minimum)
2. **plan.md** — Implementation plan (Phases 0-6)
3. **research.md** — Technical decisions (schema, integration points, citations)
4. **data-model.md** — Entity definitions, validation rules, state transitions
5. **contracts/interfaces.md** — qualify_offer, import pipeline, migration contracts
6. **quickstart.md** — Validation scenarios (unit, integration, exhaustivity)
7. **checklists/requirements.md** — Quality checklist (all passing)
8. **tasks.md** — N tâches (62% parallelisables par cycle, marqués [P])

Chaque cycle intègre aussi :
- Mise à jour de la constitution si nouveaux principes nécessaires
- Provenance traçabilité sur toutes les affirmations factuelles
- Tests de non-régression (ciblés, pas suite complète pendant flotte tourne)
- Converge assessment avant intégration

---

## Critères de réussite par phase

| Phase | Critère de réussite | Mesure |
|-------|--------------------|--------|
| Phase 1 | Cycles 002 + 003 "done" | Branche sur origin + tests ciblés rejoués |
| Phase 2 | Cycle 004 "done" | Country ≥ 95/121 offers normalisés |
| Phase 3 | Cycle 005 "done" | Global fiche_pct ≥ 70% (simulé ou réel) |
| Phase 4 | Cycles 006+ "done" | Dossier génération complet; missions extraites; éducation extractée |

---

## Prochaines actions immédiates (Next 2 sprints)

### Sprint 1 :
- [ ] Démarrer Cycle 002 (missions key clarification) via `/speckit.specify` puis `/speckit.plan`
- [ ] Démarrer Cycle 003 (duration regex expansion) via `/speckit.specify` puis `/speckit.plan`
- [ ] Allouer 2 agents OpenCode exécutants maximum
- [ ] Valider les deux cycles à la fin du sprint
- [ ] Produire artefacts Spec Kit dans `specs/002-` et `specs/003-`

### Sprint 2 :
- [ ] Valider Cycles 002 + 003 (tests ciblés rejoués, branche sur origin)
- [ ] Démarrer Cycle 004 (location normalization) via `/speckit.specify` puis `/speckit.plan`
- [ ] Allouer 1 agent OpenCode exécutant
- [ ] Planifier Cycle 005 (R2 fields) après validation Cycle 004
- [ ] Mettre à jour roadmap.md avec état d'avancement

---

## Provenance de cette feuille de route

| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Cycle 001 baseline complète | `SPECKIT_INTEGRATION_SUMMARY.md` | "1267/1271 total tests PASS" | line 61 |
| Cycles 002-004 planifiés | `feature-inventory.md` | "Cataloguée des spécifications Spec Kit par cycle (001 à 008 planifiées)" | partie A |
| Cycle 005 cible 70% | `gap-analysis.md` | "Exhaustivité globale ≥ 70%: Impossible sans R2 champs — current 25% vers 70%" | Écarts section |
| Dépendances séquence | `roadmap-product.md` (cyc001-008) | Diagramme dépendances | Mermaid diagram |
| Capacité agents 3 max | `SPECKIT_INTEGRATION_SUMMARY.md` | "Maximum three agents executing for the first wave" | Agent delegation ready section |
| Workflow spec complet | `SPECKIT_INTEGRATION_SUMMARY.md` | "Each cycle follows same Spec Kit workflow" | Next Steps section |