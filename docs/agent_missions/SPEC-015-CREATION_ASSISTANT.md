# MISSION SPEC KIT — SPEC-015 : Assistance à la Création

> **Priorité : P1** — Module utilisateur, améliore l'expérience de création (CV, lettre, candidature, profil). Worktree dédié.

---

## Contexte

La création de CV, lettres, candidatures et profils est aujourd'hui partiellement automatisée mais l'utilisateur reste seul face aux choix complexes : quelle compétence mettre en avant, comment reformuler, quelle preuve attacher, comment gérer les gaps. Il faut un **assistant intelligent** qui guide, propose, explique et valide à chaque étape.

---

## Objectif

Créer un **assistant à la création** qui :
1. Guide l'utilisateur pas à pas dans la création (CV, lettre, profil, candidature)
2. Propose des suggestions contextuelles basées sur les preuves, l'offre, le profil
3. Explique le "pourquoi" de chaque suggestion (traçabilité)
4. Valide en temps réel (cohérence, complétude, anti-invention)
5. Apprend des choix de l'utilisateur (préférences, style)

---

## Nouveaux modules à créer

```
career/creation_assistant.py        # Core: moteur suggestions, guidance
career/creation_session.py          # État session, historique, préférences
career/creation_validator.py        # Validation temps réel, anti-invention
career/router.py                    # Endpoints session, suggestions, validation
career_static/js/creation-assistant.js # UI wizard, suggestions, explications
tests/test_creation_assistant.py
docs/agent-reports/SPEC-015-CREATION_ASSISTANT.md
```

---

## Contrat attendu

### CreationSession (état d'une session de création)

```python
@dataclass
class CreationSession:
    session_id: str
    user_id: str
    creation_type: Literal["cv", "cover_letter", "profile", "application", "interview_prep"]
    target_offer_id: str | None
    status: Literal["draft", "reviewing", "validating", "finalized", "exported"]
    current_step: int
    total_steps: int
    context: dict                         # Contexte: offer_id, profile_id, preferences
    steps: list[CreationStep]
    created_at: str
    updated_at: str
    completed_at: str | None
```

### CreationStep (étape du wizard)

```python
@dataclass
class CreationStep:
    step_id: str
    step_number: int
    title: str
    description: str
    type: Literal["select", "write", "review", "validate", "attach", "choose"]
    content: dict                         # Contenu spécifique à l'étape
    suggestions: list[Suggestion]         # Suggestions contextuelles
    validation: ValidationRule | None
    user_input: dict | None
    status: Literal["pending", "in_progress", "completed", "skipped"]
    started_at: str | None
    completed_at: str | None
```

### Suggestion (proposition contextuelle)

```python
@dataclass
class Suggestion:
    suggestion_id: str
    type: Literal["text", "structure", "proof", "reformulation", "addition", "removal", "reorder"]
    content: str                          # Texte suggéré
    rationale: str                        # Pourquoi cette suggestion
    evidence_refs: list[str]              # IDs EvidenceItem qui justifient
    confidence: float                     # 0.0-1.0
    alternatives: list[str]               # Alternatives possibles
    action: Literal["accept", "modify", "reject", "defer"]
    applied_at: str | None
    applied_by: Literal["user", "auto"] | None
```

---

## Moteur de suggestions (contextuel)

### Sources de suggestions

| Source | Type de suggestion | Exemple |
|--------|-------------------|---------|
| **Preuves (SK-10)** | Preuve à attacher | "Ajoutez la preuve 'Analyse financière LBO' pour l'exigence 'Modélisation LBO'" |
| **Offre (SK-02)** | Compétence à ajouter | "L'offre exige 'Python' - vous avez 'Python (pandas, numpy)' dans vos preuves" |
| **Matching (SK-21)** | Reformulation | "Reformulez 'Gestion équipe' en 'Management équipe 5 pers' (terme offre)" |
| **Gaps (SK-03)** | Gap à combler | "Preuve manquante pour 'Anglais C1' - ajouter certificat ou expérience" |
| **Style utilisateur** | Reformulation perso | "Vous préférez 'Dirigé' à 'Géré' - appliquer ?" |
| **Best practices** | Structure | "Ajoutez une section 'Projets clés' avant 'Expériences'" |

### Algorithme de scoring suggestions

```
score = 0.4 * evidence_relevance +
        0.3 * offer_alignment +
        0.2 * user_preference_match +
        0.1 * best_practice_score
```

Seuil affichage: confidence >= 0.6

---

## Wizard par type de création

### 1. CV Ciblé (depuis offre)
```
Étape 1: Sélection offre → Analyse gaps (SK-03)
Étape 2: Sélection variante (SK-11) → Aperçu CV
Étape 3: Relecture bloc par bloc → Suggestions par bloc
Étape 4: Validation preuves → Anti-invention check
Étape 5: Export DOCX/PDF → Sauvegarde candidature
```

### 2. Lettre de motivation
```
Étape 1: Sélection offre + CV → Points forts identifiés
Étape 2: Structure lettre (intro/corps/conclusion) → Suggestions paragraphes
Étape 3: Preuves par paragraphe → Citations exactes
Étape 4: Ton/style → Adaptation secteur/entreprise
Étape 5: Relecture finale → Export
```

### 3. Profil candidat
```
Étape 1: Import CV/DOCX → Extraction (SK-01)
Étape 2: OCR si image → Propositions faits
Étape 3: Approbation champ par champ → Preuves
Étape 4: Complétion gaps → Suggestions sources
Étape 5: Profil actif → Prêt pour matching
```

### 4. Candidature complète
```
Étape 1: Offre + Profil → Kit candidature (SK-11)
Étape 2: Relecture CV + Lettre → Ajustements
Étape 3: Checklist documents → Pièces jointes
Étape 4: Validation finale → Export dossier
Étape 5: Envoi manuel → Suivi candidature
```

---

## Validation temps réel

### Règles de validation

| Règle | Type | Action si violation |
|-------|------|---------------------|
| **Anti-invention** | Bloquante | Bloquer export, afficher placeholder |
| **Preuve manquante obligatoire** | Bloquante | Bloquer export, suggérer preuve |
| **Incohérence dates** | Avertissement | Alerte visuelle, suggestion correction |
| **Dépassement longueur** | Avertissement | Compteur caractères, suggestion raccourci |
| **Ton inapproprié** | Info | Suggestion reformulation |
| **Placeholders non résolus** | Bloquante | Blocage export, liste placeholders |

---

## Apprentissage préférences utilisateur

| Préférence | Apprentissage | Application |
|------------|---------------|-------------|
| **Verbes d'action préférés** | "Dirigé" vs "Géré" | Auto-reformulation |
| **Structure CV** | Projets avant Expériences | Ordre sections |
| **Niveau détail** | Synthétique vs Détaillé | Niveau granularité |
| **Termes techniques** | Acronymes vs Mots complets | Glossaire perso |
| **Tonalité lettre** | Formel vs Direct | Adaptation ton |

---

## API attendue

```
POST   /creation/sessions                   # Nouvelle session
GET    /creation/sessions/{id}              # État session
PATCH  /creation/sessions/{id}              # Mise à jour étape/input
POST   /creation/sessions/{id}/suggestions  # Générer suggestions étape
POST   /creation/sessions/{id}/validate     # Valider étape
POST   /creation/sessions/{id}/suggest/{suggestion_id}/accept  # Accepter suggestion
POST   /creation/sessions/{id}/suggest/{suggestion_id}/reject   # Rejeter
POST   /creation/sessions/{id}/export       # Export final (DOCX/PDF/JSON)
GET    /creation/preferences                # Préférences utilisateur
PATCH  /creation/preferences                # MAJ préférences
```

---

## UI attendue (career_static/js/creation-assistant.js)

- **Wizard stepper** : Étapes numérotées, progression visuelle
- **Panneau suggestions** : Cartes suggestions avec rationale, evidence, actions
- **Éditeur riche** : Texte avec suggestions inline (accept/reject inline)
- **Validation panel** : Checklist temps réel, blocs rouges/jaunes/verts
- **Preuve panel** : Preuves disponibles, drag-drop vers blocs
- **Preuve manquante** : Formulaire ajout rapide (texte, fichier, lien)
- **Preuve preview** : Aperçu citation, source, offsets
- **Export preview** : Aperçu DOCX/PDF avant export

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_creation_assistant.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] Wizard 4 types (CV, Lettre, Profil, Candidature) fonctionnels
- [ ] Suggestions contextuelles : pertinence > 80% (évaluation utilisateur)
- [ ] Explications rationale + evidence_refs pour chaque suggestion
- [ ] Validation temps réel : anti-invention, complétude, cohérence
- [ ] Apprentissage préférences : adaptation après 3-5 sessions
- [ ] Export DOCX/PDF/JSON propre, prêt à l'emploi
- [ ] Intégration SK-02, SK-03, SK-10, SK-11, SK-21, SPEC-011, SPEC-012
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-015-CREATION_ASSISTANT.md`

---

**Tu as tout. Lance-toi.** Branche `agent/spec-015-creation-assistant`, worktree dédié, code, tests, rapport, push. Je relis et j'intègre.