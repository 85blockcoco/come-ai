# MISSION SPEC KIT — SK-18 : Extracteur missions complètes

> **Priorité : P1** — Après SK-16/SK-17. Module indépendant, worktree dédié, peut tourner en parallèle.

---

## Contexte

`extract_requirements()` dans `application_prep.py` ne détecte que ~47% des missions (seulement headings "Missions"/"Responsabilités"). Pas d'extraction structurée des tâches quotidiennes, responsabilités, livrables.

**Objectif** : Extracteur sections "Missions", "Responsabilités", "Vos missions", "What you'll do", "Key responsibilities", "Aufgaben", "Mansioni", "Funciones", "Taken" → liste structurée avec evidence.

---

## Module à créer

```
career/cv_quality/missions_extractor.py
tests/test_missions_extractor.py
tests/fixtures/missions_extractor/
```

---

## Contract attendu

```python
@dataclass
class MissionFact:
    mission_type: Literal["responsibility", "task", "deliverable", "kpi", "team", "scope"]
    text: str                    # excerpt verbatim nettoyé
    source_field: str            # "description_original"
    quote: str                   # excerpt original avec contexte
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]
    # Optionnel: compétences implicites détectées
    implied_skills: list[str]    # ex: ["Python", "Financial Modeling", "Client Presentation"]
```

---

## Patterns sections obligatoires (multilingues)

```python
_MISSION_HEADINGS = {
    "fr": [
        "missions", "vos missions", "responsabilités", "vos responsabilités",
        "principales missions", "activités", "tâches", "ce que vous ferez",
        "votre rôle", "description du poste", "description de la mission",
    ],
    "en": [
        "responsibilities", "key responsibilities", "what you'll do", "what you will do",
        "your role", "duties", "tasks", "main responsibilities", "scope of work",
        "job description", "role description", "day to day", "day-to-day",
    ],
    "de": [
        "aufgaben", "ihre aufgaben", "verantwortlichkeiten", "hauptaufgaben",
        "tätigkeiten", "was sie erwarten", "ihr aufgabengebiet", "aufgabenbereich",
    ],
    "it": [
        "mansioni", "le tue mansioni", "responsabilità", "principali responsabilità",
        "attività", "compiti", "cosa farai", "il tuo ruolo",
    ],
    "es": [
        "funciones", "tus funciones", "responsabilidades", "principales responsabilidades",
        "tareas", "actividades", "qué harás", "tu rol",
    ],
    "nl": [
        "verantwoordelijkheden", "jouw verantwoordelijkheden", "taken", "hoofdtaken",
        "activiteiten", "wat je gaat doen", "jouw rol",
    ],
}

_OTHER_SECTION_HEADINGS = {
    # Sections qui MARRENT la fin des missions
    "fr": ["profil", "votre profil", "qualifications", "compétences", "requis", "avantages", "bénéfices", "nous offrons", "à propos", "l'entreprise"],
    "en": ["requirements", "qualifications", "skills", "what we offer", "benefits", "about us", "the company", "who you are"],
    "de": ["anforderungen", "qualifikationen", "kompetenzen", "vorteile", "benefits", "über uns", "das unternehmen", "wer sie sind"],
    "it": ["requisiti", "qualifiche", "competenze", "benefici", "chi siamo", "l'azienda", "chi cerchiamo"],
    "es": ["requisitos", "cualificaciones", "competencias", "beneficios", "sobre nosotros", "la empresa", "quién eres"],
    "nl": ["vereisten", "kwalificaties", "competenties", "voordelen", "over ons", "het bedrijf", "wie je bent"],
}
```

---

## Logique d'extraction

```python
def extract_missions(text: str, lang: str = "auto") -> list[MissionFact]:
    # 1. Détecter langue
    # 2. Trouver TOUTES les positions des headings missions
    # 3. Pour chaque heading mission trouvé:
    #    - Extraire texte jusqu'au prochain heading (mission OU other)
    #    - Split en phrases/bullet points
    #    - Nettoyer chaque item (retirer "•", "-", numéros)
    #    - Filtrer items trop courts (< 10 chars) ou génériques
    # 4. Pour chaque item valide:
    #    - Classifier type: responsibility/task/deliverable/kpi/team/scope
    #    - Détecter compétences implicites (patterns techniques)
    #    - Calculer offsets dans texte original
    # 5. Dédupliquer (même mission répétée)
    # 6. Retourner liste MissionFact triée par offset
```

---

## Classification type de mission

```python
_MISSION_TYPE_PATTERNS = {
    "kpi": [
        r"\b(?:kpi|okr|objectif|target|goal|metric|chiffre|résultat|performance)\b",
    ],
    "deliverable": [
        r"\b(?:livrable|deliverable|output|rapport|report|presentation|modèle|model|dashboard)\b",
    ],
    "team": [
        r"\b(?:équipe|team|collaborer|collaborate|manage|manage|superviser|lead|encadrer)\b",
    ],
    "scope": [
        r"\b(?:périmètre|scope|perimeter|étendue|portefeuille|portfolio|clients?|accounts?)\b",
    ],
    "responsibility": [
        r"\b(?:responsable|responsible|accountable|owner|piloter|driver|garantir|ensure)\b",
    ],
    # Default: "task"
}
```

---

## Détection compétences implicites

```python
_IMPLICIT_SKILL_PATTERNS = {
    "Python": r"\bpython\b",
    "Excel": r"\bexcel\b",
    "VBA": r"\bvba\b",
    "SQL": r"\bsql\b",
    "Power BI": r"\bpower\s*bi\b",
    "Tableau": r"\btableau\b",
    "Bloomberg": r"\bbloomberg\b",
    "Financial Modeling": r"\b(?:financial\s+modeling|modélisation\s+financière|modello\s+finanziario|finanzielles\s+modell)\b",
    "Valuation": r"\b(?:valuation|évaluation|bewertung|valorazione|valoración)\b",
    "M&A": r"\b(?:m&a|merger|acquisition|fusion|acquisition)\b",
    "LBO": r"\blbo\b",
    "Due Diligence": r"\b(?:due\s+diligence|diligence)\b",
    "Client Presentation": r"\b(?:client\s+presentation|présentation\s+client|kundenpräsentation)\b",
    "Project Management": r"\b(?:project\s+management|gestion\s+de\s+projet|projektmanagement)\b",
}
```

---

## Validation

### Fixtures synthétiques (minimum 20)

| Langue | Texte source | Missions attendues |
|--------|--------------|-------------------|
| FR | "Missions : Modélisation financière LBO. Présentation aux clients. Gestion équipe 3 personnes." | 3 missions: deliverable, task, team |
| FR | "Vos missions : Analyse due diligence. Reporting mensuel. Support transactions M&A." | 3 missions: task, deliverable, responsibility |
| EN | "Key responsibilities: Build financial models. Lead client presentations. Manage analyst team." | 3 missions: deliverable, task, team |
| EN | "What you'll do: Daily valuation work. Prepare pitch books. KPI: deal closure rate." | 3 missions: task, deliverable, kpi |
| DE | "Ihre Aufgaben: Finanzmodellierung. Kundenpräsentationen. Teamleitung." | 3 missions |
| IT | "Mansioni: Analisi valutazione. Reportistica. Coordinamento team." | 3 missions |
| ES | "Funciones: Modelado financiero. Presentaciones. Gestión equipo." | 3 missions |
| NL | "Taken: Financiële modellering. Klantpresentaties. Teamleiding." | 3 missions |
| FR | "Missions : • Modélisation • Reporting • Client" (bullets) | 3 missions |
| FR | "Responsabilités :\n1. Modélisation\n2. Reporting" (numéroté) | 2 missions |
| MULTI | Section missions + section profil mélangées | Seulement missions extraites |
| FR | "Missions : Selon profil" (trop vague) | 0 missions (filtré) |

### Pièges obligatoires

| Piège | Règle |
|-------|-------|
| "Selon profil" / "To be discussed" | Filtré (trop vague) |
| Section "Profil recherché" | **Jamais** extraite comme mission |
| Bullets vides / numéros seuls | Filtrés |
| Mission > 500 chars | Tronquée à 500, note "truncated" |
| Compétence implicite détectée | Ajoutée dans `implied_skills` |

---

## Intégration

```python
# Dans qualify_offer() ou summarize_offer()
from career.cv_quality.missions_extractor import extract_missions

missions = extract_missions(job.get("description_original", ""))
if missions:
    evidence["missions"] = FactEvidence(
        [m.text for m in missions], "missions_extractor", missions[0].quote
    )
```

---

## Commandes de validation

```bash
./checklist_codex.sh
.venv/bin/python -m pytest -q tests/test_missions_extractor.py
.venv/bin/python -m pytest -q
git diff --check
```

---

## Critères de réussite

- [ ] `extract_missions(text: str, lang: str = "auto") -> list[MissionFact]`
- [ ] 6 langues supportées
- [ ] 6 mission_type classifiés
- [ ] Headings détectés + fin de section par headings "other"
- [ ] Bullets, numéroté, paragraphes supportés
- [ ] Compétences implicites détectées (10+ patterns finance)
- [ ] 20+ fixtures synthétiques
- [ ] Intégré dans `qualify_offer()` → `evidence["missions"]`
- [ ] Ruff clean, suite complète verte, `git diff --check` propre
- [ ] Rapport `docs/agent-reports/SPEC-SK18-MISSIONS_EXTRACTOR.md`

---

## Squelette minimal

```python
# career/cv_quality/missions_extractor.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional
import re

@dataclass
class MissionFact:
    mission_type: Literal["responsibility", "task", "deliverable", "kpi", "team", "scope"]
    text: str
    source_field: str
    quote: str
    start_offset: int
    end_offset: int
    confidence: Literal["explicit", "inferred", "ambiguous"]
    contradictions: list[str]
    implied_skills: list[str]

def extract_missions(text: str, lang: str = "auto") -> list[MissionFact]:
    ...
```

---

**Tu as tout. Lance-toi.** Branche `agent/spec-sk18-missions-extractor`, worktree dédié, code, tests (20+ cas multilingues), rapport, push. Je relis et j'intègre.