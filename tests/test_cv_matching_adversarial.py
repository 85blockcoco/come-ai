"""Banc adversarial de matching CV/offre — mission CVBOOST-08.

Chaque cas est un couple synthétique (CV, offre) qui cible un piège précis du
matching : le faux positif que produit un matching par mots-communs.  Le
banc couvre les onze familles annoncées par la mission :

* **faux_positif_lexical** — Excel / analyse financière, Java / JavaScript,
  PostgreSQL / NoSQL, AWS / Azure, Power BI / Tableau ;
* **acronyme** — M&A, Private Equity, Investment Banking, CRM/ERP/KPI ;
* **langue** — niveau déclaré, niveau absent, programme enseigné en anglais ;
* **contrat** — stage, CDI, CDD, alternance, VIE, freelance ;
* **diplome** — M1, M2, bachelor, licence, doctorat ;
* **negation** — « pas de gestion d'équipe », « sans Python » ;
* **absente** — exigence 100 % absente du CV ;
* **homonyme** — audit financier / audit IT, gestion projet / gestion équipe ;
* **quantification** — équipe de 10 personnes, budget, chiffre d'affaires ;
* **multilingue** — CV FR/EN, offre FR/EN, compétences transposables ;
* **niveau_competence** — « Excel avancé » contre un CV qui dit « Excel ».

Chaque cas est un dictionnaire qui porte la vérité terrain écrite à la main :

```python
{
    "id": "ADV-001",
    "name": "Excel ≠ analyse financière",
    "family": "faux_positif_lexical",
    "cv_text": CV_EXCEL,
    "offer_requirements": ["Excel avance", "Analyse financiere"],
    "expected_actions": [
        {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
        {"code": "DO_NOT_ADD", "requirement": "Analyse financiere", "cv_evidence": None},
    ],
    "expected_score_range": (0.5, 0.5),
    "expected_warnings": [],
}
```

Les invariants vérifiés sur **chaque** cas :

1. les actions produites sont exactement celles attendues (code + preuve) ;
2. le score global tombe dans la plage déduite de la vérité terrain ;
3. les avertissements annoncés sont émis ;
4. toute preuve citée est une sous-chaîne exacte du CV, à l'offset exact ;
5. une exigence sans preuve n'est jamais étayée (``DO_NOT_ADD`` sans preuve,
   et toujours avec la raison canonique) ;
6. une exigence étayée porte toujours une preuve ;
7. deux exécutions sur les mêmes entrées donnent le même résultat ;
8. le score est borné et cohérent avec les actions produites ;
9. aucune donnée de contact n'apparaît dans la décision.

Tout le jeu de données est synthétique : entreprises, offres et profils
fictifs, aucun e-mail réel, aucun appel réseau.
"""

from __future__ import annotations

import pytest

from career.cv_quality import DocumentInput, analyze_cv, match_cv_to_offer
from career.cv_quality.matching import NO_PROOF_REASON
from career.cv_quality.models import MatchAction, MatchResult

# ──────────────────────────────────────────────────────────────────────
# Profils synthétiques
# ──────────────────────────────────────────────────────────────────────

CV_EXCEL = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Controleur de gestion | Groupe Exemple
- Excel avance et tableaux de bord
- VBA et TCD
FORMATION
Master 2 en finance
LANGUES
Francais
"""

CV_EXCEL_SANS_NIVEAU = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Controleur de gestion | Groupe Exemple
- Excel et TCD
FORMATION
Master 2 en finance
LANGUES
Francais
"""

CV_EXCEL_BASIQUE = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Assistant administratif | Groupe Exemple
- Saisie Excel basique
FORMATION
Licence professionnelle
LANGUES
Francais
"""

CV_ANALYSTE = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Analyste financier | Groupe Exemple
- Modelisation financiere de 120 budgets
- Excel avance et Power BI
2019 - 2021 | Analyste | Cabinet Exemple
- Analyse financiere et audit comptable
FORMATION
Master 2 en finance
LANGUES
Anglais courant
Francais natif
Je recherche un CDI.
"""

CV_DEVELOPPEUR = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Developpeur backend | Edition Exemple
- Developpement Java et Spring
- APIs REST en PostgreSQL
2020 - 2022 | Developpeur | SaaS Exemple
- JavaScript et React
FORMATION
Master 1 en informatique
LANGUES
Anglais professionnel
Je recherche un CDI.
"""

CV_FRONTEND = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Developpeur frontend | Edition Exemple
- JavaScript et React
- Interfaces HTML et CSS
FORMATION
Master 1 en informatique
LANGUES
Anglais professionnel
Je recherche un CDI.
"""

CV_BACKEND = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Developpeur backend | Edition Exemple
- Developpement Java et Spring
- APIs REST en PostgreSQL
FORMATION
Master 1 en informatique
LANGUES
Anglais professionnel
Je recherche un CDI.
"""

CV_DATA = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Data analyst | Groupe Exemple
- Analyse de donnees et tableaux de bord
- Python et PostgreSQL
FORMATION
Master 1 en data
LANGUES
Anglais courant
Je recherche un CDI.
"""

CV_MA = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Analyste M&A | Banque Exemple
- Fusions-acquisitions M&A
- Private Equity et Leveraged Finance
FORMATION
Master 2 en finance
LANGUES
Anglais courant
Je recherche un CDI.
"""

CV_AUDIT_IT = """Candidat Exemple
EXPERIENCE
2020 - 2024 | Auditeur SI | Edition Exemple
- Audit des systemes d information
- Cybersecurite et gestion des risques
FORMATION
Master 1 en informatique
LANGUES
Anglais professionnel
Je recherche un CDI.
"""

CV_AUDIT_FINANCIER = """Candidat Exemple
EXPERIENCE
2020 - 2024 | Auditeur financier | Cabinet Exemple
- Audit comptable et commissariat aux comptes
- IFRS et consolidation
FORMATION
Master 2 en finance
LANGUES
Anglais courant
Je recherche un CDI.
"""

CV_LANGUE_SANS_NIVEAU = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Analyste | Groupe Exemple
- Analyse financiere
FORMATION
Master 2 en finance
LANGUES
Anglais
Je recherche un CDI.
"""

CV_MULTILINGUE = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Chef de projet | Groupe Exemple
- Pilotage de projets et gestion d equipe de 10 personnes
- Budget de 500 kEUR
FORMATION
Master 2 en gestion
LANGUES
Anglais courant
Espagnol courant
Allemand lu
Je recherche un CDI.
"""

CV_ETUDIANT = """Candidat Exemple
EXPERIENCE
2024 - 2025 | Alternance en marketing | Groupe Exemple
- Gestion de projet et reporting
FORMATION
Bachelor en marketing
LANGUES
Anglais courant
Je recherche une alternance.
"""

CV_CDI = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Assistant commercial | Groupe Exemple
- Relation client et reporting
FORMATION
Licence professionnelle
LANGUES
Francais
Je recherche un CDI.
"""

CV_MINIMAL = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Assistant | Groupe Exemple
- Support administratif
FORMATION
Licence professionnelle
LANGUES
Francais
"""

CV_PROGRAMME_ANGLAIS = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Stagiaire | Groupe Exemple
- Programme en anglais dans une equipe internationale
FORMATION
Master 2 en commerce international
LANGUES
Francais
"""

CV_STAGE_PUIS_CDI = """Candidat Exemple
EXPERIENCE
2024 - 2025 | Stagiaire | Groupe Exemple
- Analyse de donnees
2025 - 2025 | Alternance | Groupe Exemple
- Reporting commercial
FORMATION
Master 2 en data
LANGUES
Anglais professionnel
Je recherche un CDI, pas d'alternance.
"""

CV_ANGLAIS_LU = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Analyste | Groupe Exemple
- Analyse de donnees
FORMATION
Master 2 en finance
LANGUES
Anglais lu
Francais natif
Je recherche un CDI.
"""

CV_SANS_DIPLOME = """Candidat Exemple
EXPERIENCE
2023 - 2024 | Assistant | Groupe Exemple
- Support administratif
LANGUES
Francais
"""

CV_MODELISATION = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Controleur de gestion | Groupe Exemple
- Modelisation financiere de 120 budgets
- Excel avance et Power BI
FORMATION
Master 2 en finance
LANGUES
Francais
Je recherche un CDI.
"""

CV_COMMERCIAL = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Commercial | Groupe Exemple
- Suivi d'un chiffre d'affaires de 3 millions
- Relation client
FORMATION
Master 2 en commerce
LANGUES
Francais natif
Je recherche un CDI.
"""

CV_CHEF_PROJET_SANS_CHIFFRE = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Chef de projet | Groupe Exemple
- Pilotage de projets et encadrement d equipe
FORMATION
Master 2 en gestion
LANGUES
Francais
Je recherche un CDI.
"""

CV_ANALYSTE_EXPERTE = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Analyste financier senior | Groupe Exemple
- Analyse financiere experte
- Modelisation financiere de 120 budgets
FORMATION
Master 2 en finance
LANGUES
Anglais courant
Francais natif
Je recherche un CDI.
"""


# ──────────────────────────────────────────────────────────────────────
# Offres synthétiques
# ──────────────────────────────────────────────────────────────────────

def _offer(requirements: list[str]) -> dict:
    """Build a synthetic French offer holding the given requirements."""
    return {
        "title": "Poste de test",
        "company": "Groupe Exemple",
        "requirements": "\n".join(requirements),
        "description_original": "Poste de test dans une equipe Exemple.",
    }


def _offer_en(requirements: list[str]) -> dict:
    """Build a synthetic offer written in English."""
    return {
        "title": "Data analyst role",
        "company": "Example Group",
        "requirements": "\n".join(requirements),
        "description_original": (
            "We are looking for a data analyst to join our team and work "
            "with our clients in a strong business context."
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Cas adversariaux
# ──────────────────────────────────────────────────────────────────────
# ``expected_actions`` : une entrée par exigence couverte par le moteur,
# avec le code d'action attendu et la preuve verbatim attendue (ou None).
# ``expected_score_range`` : plage de score global attendue (moyenne pondérée
# des actions) — la valeur y est bornée par la vérité terrain du cas.
# ``expected_warnings`` : fragments de message qui doivent être présents.

CASES: list[dict] = [
    # ── F1 : compétences techniques proches (faux positifs) ──────────
    {
        "id": "ADV-001", "name": "Excel ≠ analyse financière", "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL, "offer_requirements": ["Excel avance", "Analyse financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
            {"code": "DO_NOT_ADD", "requirement": "Analyse financiere", "cv_evidence": None},
        ],
        "expected_score_range": (0.5, 0.5), "expected_warnings": [],
    },
    {
        "id": "ADV-002", "name": "Analyse financière présente", "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Analyse financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Analyse financiere", "cv_evidence": "Analyse financiere"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-003", "name": "Modélisation ≠ analyse financière", "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Modelisation financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Modelisation financiere",
             "cv_evidence": "Modelisation financiere de 120 budgets"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-004", "name": "VBA ≠ modélisation financière", "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL, "offer_requirements": ["Modelisation financiere"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Modelisation financiere", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-005", "name": "Java ≠ JavaScript", "family": "faux_positif_lexical",
        "cv_text": CV_FRONTEND, "offer_requirements": ["Java"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Java", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-006", "name": "JavaScript ≠ Java", "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND, "offer_requirements": ["JavaScript"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "JavaScript", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-007", "name": "Java présent → preuve", "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND, "offer_requirements": ["Java"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Java", "cv_evidence": "Developpement Java"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-008", "name": "JavaScript présent → preuve", "family": "faux_positif_lexical",
        "cv_text": CV_FRONTEND, "offer_requirements": ["JavaScript"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "JavaScript", "cv_evidence": "JavaScript"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-009", "name": "PostgreSQL ≠ NoSQL", "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND, "offer_requirements": ["NoSQL"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "NoSQL", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-010", "name": "PostgreSQL présent → preuve", "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND, "offer_requirements": ["PostgreSQL"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "PostgreSQL", "cv_evidence": "PostgreSQL"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-011", "name": "AWS ≠ Azure", "family": "faux_positif_lexical",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Amazon Web Services"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Amazon Web Services", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-012", "name": "Azure absent", "family": "faux_positif_lexical",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Azure"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Azure", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-013", "name": "Power BI ≠ Tableau", "family": "faux_positif_lexical",
        "cv_text": CV_DATA, "offer_requirements": ["Power BI"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Power BI", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-014", "name": "Tableaux de bord ≠ Tableau (outil)", "family": "faux_positif_lexical",
        "cv_text": CV_DATA, "offer_requirements": ["Tableaux de bord"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Tableaux de bord", "cv_evidence": "tableaux de bord"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-015", "name": "Analyse de données ≠ data engineering", "family": "faux_positif_lexical",
        "cv_text": CV_DATA, "offer_requirements": ["Data engineering"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Data engineering", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-016", "name": "Python présent → preuve", "family": "faux_positif_lexical",
        "cv_text": CV_DATA, "offer_requirements": ["Python"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Python", "cv_evidence": "Python"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-017", "name": "Tableur satisfait par Excel", "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL, "offer_requirements": ["Tableur"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Tableur", "cv_evidence": "Excel avance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-018", "name": "Power BI présent → preuve", "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Power BI"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Power BI", "cv_evidence": "Power BI"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },

    # ── F2 : acronymes et synonymes ─────────────────────────────────
    {
        "id": "ADV-019", "name": "M&A = fusions-acquisitions", "family": "acronyme",
        "cv_text": CV_MA, "offer_requirements": ["Fusions-acquisitions M&A"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Fusions-acquisitions M&A",
             "cv_evidence": "Fusions-acquisitions M&A"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-020", "name": "Private Equity = private equity", "family": "acronyme",
        "cv_text": CV_MA, "offer_requirements": ["Private Equity"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Private Equity", "cv_evidence": "Private Equity"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-021", "name": "M&A absent du CV", "family": "acronyme",
        "cv_text": CV_EXCEL, "offer_requirements": ["Fusions-acquisitions M&A"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Fusions-acquisitions M&A", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-022", "name": "PE absent du CV", "family": "acronyme",
        "cv_text": CV_EXCEL, "offer_requirements": ["Private Equity"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Private Equity", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-023", "name": "M&A présent mais écrit autrement", "family": "acronyme",
        "cv_text": CV_MA, "offer_requirements": ["Fusions-acquisitions"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Fusions-acquisitions", "cv_evidence": "Fusions-acquisitions M&A"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-024", "name": "Audit comptable = audit financier", "family": "acronyme",
        "cv_text": CV_AUDIT_FINANCIER, "offer_requirements": ["Audit financier"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Audit financier", "cv_evidence": "Audit comptable"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-025", "name": "Power BI présent", "family": "acronyme",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Power BI"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Power BI", "cv_evidence": "Power BI"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-026", "name": "CRM absent", "family": "acronyme",
        "cv_text": CV_MINIMAL, "offer_requirements": ["CRM Salesforce"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "CRM Salesforce", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-027", "name": "ERP absent", "family": "acronyme",
        "cv_text": CV_MINIMAL, "offer_requirements": ["ERP SAP"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "ERP SAP", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-028", "name": "KPI absent", "family": "acronyme",
        "cv_text": CV_MINIMAL, "offer_requirements": ["KPI et reporting"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "KPI et reporting", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },

    # ── F3 : langues ─────────────────────────────────────────────────
    {
        "id": "ADV-029", "name": "Anglais courant déclaré", "family": "langue",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais courant", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-030", "name": "Langue absente du CV", "family": "langue",
        "cv_text": CV_CDI, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["absente du CV"],
    },
    {
        "id": "ADV-031", "name": "Espagnol absent du CV", "family": "langue",
        "cv_text": CV_CDI, "offer_requirements": ["Espagnol courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Espagnol courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-032", "name": "Programme en anglais ≠ niveau d'anglais", "family": "langue",
        "cv_text": CV_PROGRAMME_ANGLAIS, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["enseignement"],
    },
    {
        "id": "ADV-033", "name": "Niveau de langue insuffisant", "family": "langue",
        "cv_text": CV_DEVELOPPEUR, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-034", "name": "Profil multilingue FR/EN/ES", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Anglais courant", "Espagnol courant"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais courant", "cv_evidence": "Anglais courant"},
            {"code": "HIGHLIGHT", "requirement": "Espagnol courant", "cv_evidence": "Espagnol courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-035", "name": "Langue absente d'un profil trilingue", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Italien courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Italien courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-036", "name": "Allemand lu ≠ allemand courant", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Allemand courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Allemand courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-037", "name": "Anglais sans niveau exigé", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Anglais"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-038", "name": "Programme en anglais ≠ exigence de langue", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Programme en anglais"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Programme en anglais", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-039", "name": "Français natif", "family": "langue",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Francais natif"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Francais natif", "cv_evidence": "Francais natif"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-040", "name": "Anglais professionnel déclaré", "family": "langue",
        "cv_text": CV_DEVELOPPEUR, "offer_requirements": ["Anglais professionnel"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais professionnel",
             "cv_evidence": "Anglais professionnel"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-041", "name": "Niveau exigé inférieur au niveau déclaré", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Espagnol intermediaire"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Espagnol intermediaire", "cv_evidence": "Espagnol courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-042", "name": "Allemand lu exigé et déclaré", "family": "langue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Allemand lu"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Allemand lu", "cv_evidence": "Allemand lu"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-043", "name": "Niveau de langue non précisé dans le CV", "family": "langue",
        "cv_text": CV_LANGUE_SANS_NIVEAU, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "CONFIRM_LANGUAGE", "requirement": "Anglais courant", "cv_evidence": "Anglais"},
        ],
        "expected_score_range": (0.8, 0.8), "expected_warnings": ["non précisé"],
    },

    # ── F4 : types de contrat ───────────────────────────────────────
    {
        "id": "ADV-044", "name": "Stage ≠ CDI", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Contrat stage"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat stage", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["contrat"],
    },
    {
        "id": "ADV-045", "name": "CDI conforme", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Contrat CDI"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Contrat CDI", "cv_evidence": "CDI"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-046", "name": "Alternance exclue par le CV", "family": "contrat",
        "cv_text": CV_STAGE_PUIS_CDI, "offer_requirements": ["Contrat en alternance"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat en alternance", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["exclut"],
    },
    {
        "id": "ADV-047", "name": "Alternance déclarée par le CV", "family": "contrat",
        "cv_text": CV_ETUDIANT, "offer_requirements": ["Contrat en alternance"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Contrat en alternance",
             "cv_evidence": "alternance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-048", "name": "Stage demandé à un profil CDI", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Stage de 6 mois"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Stage de 6 mois", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["contrat"],
    },
    {
        "id": "ADV-049", "name": "VIE absente du brief", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Volontariat international"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Volontariat international", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-050", "name": "Freelance absent du brief", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Contrat freelance"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat freelance", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-051", "name": "CDD ≠ CDI", "family": "contrat",
        "cv_text": CV_CDI, "offer_requirements": ["Contrat CDD"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat CDD", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["contrat"],
    },
    {
        "id": "ADV-052", "name": "CDI pour un profil sans contrat déclaré", "family": "contrat",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Contrat CDI"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat CDI", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["non déclaré"],
    },
    {
        "id": "ADV-053", "name": "Stage pour un profil alternance", "family": "contrat",
        "cv_text": CV_ETUDIANT, "offer_requirements": ["Contrat stage"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Contrat stage", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["contrat"],
    },
    {
        "id": "ADV-054", "name": "VIE pour un profil CDI", "family": "contrat",
        "cv_text": CV_STAGE_PUIS_CDI, "offer_requirements": ["Volontariat international"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Volontariat international", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },

    # ── F5 : niveaux d'études ───────────────────────────────────────
    {
        "id": "ADV-055", "name": "M1 exigé, M2 détenu", "family": "diplome",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Diplome M1 en finance"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Diplome M1 en finance", "cv_evidence": "Master 2"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-056", "name": "M2 exigé, M1 détenu", "family": "diplome",
        "cv_text": CV_DEVELOPPEUR, "offer_requirements": ["Master 2 en finance"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Master 2 en finance", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-057", "name": "Bachelor exigé, Master détenu", "family": "diplome",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Bachelor en finance"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Bachelor en finance", "cv_evidence": "Master 2"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-058", "name": "Master exigé, Bachelor détenu", "family": "diplome",
        "cv_text": CV_ETUDIANT, "offer_requirements": ["Master en gestion"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Master en gestion", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-059", "name": "Doctorat exigé, Master détenu", "family": "diplome",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Doctorat en finance"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Doctorat en finance", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-060", "name": "Master 1 exigé, Master 1 détenu", "family": "diplome",
        "cv_text": CV_DEVELOPPEUR, "offer_requirements": ["Master 1 en informatique"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Master 1 en informatique", "cv_evidence": "Master 1"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-061", "name": "Licence professionnelle exigée", "family": "diplome",
        "cv_text": CV_CDI, "offer_requirements": ["Licence professionnelle"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Licence professionnelle",
             "cv_evidence": "Licence professionnelle"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-062", "name": "Master exigé, licence détenue", "family": "diplome",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Master en gestion"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Master en gestion", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-062b", "name": "Master exigé, aucun diplôme au CV", "family": "diplome",
        "cv_text": CV_SANS_DIPLOME, "offer_requirements": ["Master en gestion"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Master en gestion", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["non attesté"],
    },
    {
        "id": "ADV-063", "name": "Bac+2 exigé, licence détenue", "family": "diplome",
        "cv_text": CV_CDI, "offer_requirements": ["BTS en informatique"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "BTS en informatique", "cv_evidence": "Licence professionnelle"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-064", "name": "Master 2 exigé, profil M1", "family": "diplome",
        "cv_text": CV_DATA, "offer_requirements": ["Master 2 en data"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Master 2 en data", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-065", "name": "Master 1 en data détenu", "family": "diplome",
        "cv_text": CV_DATA, "offer_requirements": ["Master 1 en data"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Master 1 en data", "cv_evidence": "Master 1"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-066", "name": "Licence exigée, licence détenue", "family": "diplome",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Licence en gestion"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Licence en gestion", "cv_evidence": "Licence professionnelle"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },

    # ── F6 : négations ───────────────────────────────────────────────
    {
        "id": "ADV-067", "name": "Exigence niée : pas de gestion d'équipe", "family": "negation",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Pas de gestion d equipe"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-068", "name": "Exigence niée : aucune expérience", "family": "negation",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Aucune experience en gestion d equipe"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-069", "name": "Exigence niée : sans déplacement", "family": "negation",
        "cv_text": CV_CDI, "offer_requirements": ["Sans deplacements professionnels"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-070", "name": "Exigence niée : not required", "family": "negation",
        "cv_text": CV_CDI, "offer_requirements": ["Excel is not required"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-071", "name": "Négation et compétence par ailleurs prouvée", "family": "negation",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Pas de gestion d equipe", "Pilotage de projets"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Pilotage de projets", "cv_evidence": "Pilotage de projets"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-072", "name": "Négation isolée ne pollue pas le score", "family": "negation",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Pas de gestion d equipe", "Analyse financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Analyse financiere", "cv_evidence": "Analyse financiere"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-073", "name": "Mot nié : pas de télétravail", "family": "negation",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Pas de teletravail"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-074", "name": "Négation : phrase non pertinente", "family": "negation",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Ne pas avoir deunk"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-075", "name": "Négation dans une compétence par ailleurs prouvée", "family": "negation",
        "cv_text": CV_DATA, "offer_requirements": ["Aucune experience en Python", "Python"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Python", "cv_evidence": "Python"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": ["niée"],
    },
    {
        "id": "ADV-076", "name": "Double négation sans effet", "family": "negation",
        "cv_text": CV_CDI, "offer_requirements": ["Experience en gestion"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Experience en gestion", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-077", "name": "Négation en conflit avec une compétence du CV", "family": "negation",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Pas de gestion d equipe"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ["niée", "gestion d equipe"],
    },
    {
        "id": "ADV-078", "name": "Négation en anglais contre un CV qui a la compétence", "family": "negation",
        "cv_text": CV_DATA, "offer_requirements": ["No Python required"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ["niée", "Python"],
    },
    {
        "id": "ADV-079", "name": "Négation sans conflit avec le CV", "family": "negation",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Pas de teletravail"],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["niée"],
    },

    # ── F7 : compétence absente du CV ───────────────────────────────
    {
        "id": "ADV-080", "name": "Compétence totalement absente", "family": "absente",
        "cv_text": CV_MINIMAL, "offer_requirements": ["M&A et Private Equity"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "M&A et Private Equity", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-081", "name": "Compétence absente (Python)", "family": "absente",
        "cv_text": CV_CDI, "offer_requirements": ["Python"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Python", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-082", "name": "Compétence absente (AWS)", "family": "absente",
        "cv_text": CV_CDI, "offer_requirements": ["Amazon Web Services"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Amazon Web Services", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-083", "name": "Compétence absente (Salesforce)", "family": "absente",
        "cv_text": CV_CDI, "offer_requirements": ["Salesforce"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Salesforce", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-084", "name": "Compétence absente (Kubernetes)", "family": "absente",
        "cv_text": CV_CDI, "offer_requirements": ["Kubernetes"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Kubernetes", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-085", "name": "Compétence absente (Scala)", "family": "absente",
        "cv_text": CV_DEVELOPPEUR, "offer_requirements": ["Scala"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Scala", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-086", "name": "Compétence absente (Power BI)", "family": "absente",
        "cv_text": CV_BACKEND, "offer_requirements": ["Power BI"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Power BI", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-087", "name": "Compétence absente (CFO)", "family": "absente",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Direction financiere (CFO)"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Direction financiere (CFO)", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-088", "name": "Deux compétences absentes", "family": "absente",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Scala", "Kubernetes"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Scala", "cv_evidence": None},
            {"code": "DO_NOT_ADD", "requirement": "Kubernetes", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-089", "name": "Absence et présence mêlées", "family": "absente",
        "cv_text": CV_DATA, "offer_requirements": ["Python", "Scala"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Python", "cv_evidence": "Python"},
            {"code": "DO_NOT_ADD", "requirement": "Scala", "cv_evidence": None},
        ],
        "expected_score_range": (0.5, 0.5), "expected_warnings": [],
    },

    # ── F8 : homonymes sectoriels ───────────────────────────────────
    {
        "id": "ADV-090", "name": "Audit IT ≠ audit financier", "family": "homonyme",
        "cv_text": CV_AUDIT_IT, "offer_requirements": ["Audit financier"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Audit financier", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["Homonyme"],
    },
    {
        "id": "ADV-091", "name": "Audit financier ≠ audit IT", "family": "homonyme",
        "cv_text": CV_AUDIT_FINANCIER, "offer_requirements": ["Audit IT"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Audit IT", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["Homonyme"],
    },
    {
        "id": "ADV-092", "name": "Audit des SI ≠ audit financier", "family": "homonyme",
        "cv_text": CV_AUDIT_IT, "offer_requirements": ["Audit financier"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Audit financier", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["Homonyme"],
    },
    {
        "id": "ADV-093", "name": "Audit comptable = audit financier", "family": "homonyme",
        "cv_text": CV_AUDIT_FINANCIER, "offer_requirements": ["Audit financier"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Audit financier", "cv_evidence": "Audit comptable"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-094", "name": "Gestion de projet ≠ gestion d'équipe", "family": "homonyme",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Gestion de projet"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Gestion de projet", "cv_evidence": "Pilotage de projets"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-095", "name": "Gestion des risques ≠ audit financier", "family": "homonyme",
        "cv_text": CV_AUDIT_IT, "offer_requirements": ["Audit financier"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Audit financier", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["Homonyme"],
    },
    {
        "id": "ADV-096", "name": "Data analysis ≠ data engineering", "family": "homonyme",
        "cv_text": CV_DATA, "offer_requirements": ["Data engineering"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Data engineering", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["Homonyme"],
    },
    {
        "id": "ADV-097", "name": "Machine learning absent", "family": "homonyme",
        "cv_text": CV_DATA, "offer_requirements": ["Machine learning"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Machine learning", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-098", "name": "Audit IT présent → preuve", "family": "homonyme",
        "cv_text": CV_AUDIT_IT, "offer_requirements": ["Audit des systemes d information"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Audit des systemes d information",
             "cv_evidence": "Audit des systemes d information"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-099", "name": "Stage (usage ambigu) non confondu", "family": "homonyme",
        "cv_text": CV_ETUDIANT, "offer_requirements": ["Stage de 6 mois"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Stage de 6 mois", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["contrat"],
    },
    {
        "id": "ADV-100", "name": "Power BI ≠ Tableau (homonyme outil)", "family": "homonyme",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Tableau"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Tableau", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },

    # ── F9 : quantification ─────────────────────────────────────────
    {
        "id": "ADV-101", "name": "Équipe chiffrée dans le CV", "family": "quantification",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Gestion d equipe"],
        "expected_actions": [
            {"code": "QUANTIFY", "requirement": "Gestion d equipe",
             "cv_evidence": "gestion d equipe de 10 personnes"},
        ],
        "expected_score_range": (0.9, 0.9), "expected_warnings": [],
    },
    {
        "id": "ADV-102", "name": "Équipe non chiffrée → quantifier", "family": "quantification",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Gestion d equipe"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Gestion d equipe", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-103", "name": "Budget chiffré", "family": "quantification",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Budget de 500 kEUR"],
        "expected_actions": [
            {"code": "QUANTIFY", "requirement": "Budget de 500 kEUR", "cv_evidence": "Budget de 500 kEUR"},
        ],
        "expected_score_range": (0.9, 0.9), "expected_warnings": [],
    },
    {
        "id": "ADV-104", "name": "Pilotage avec budget", "family": "quantification",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Pilotage de projets"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Pilotage de projets", "cv_evidence": "Pilotage de projets"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-105", "name": "Chiffre d'affaires absent", "family": "quantification",
        "cv_text": CV_CDI, "offer_requirements": ["Chiffre d'affaires"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Chiffre d'affaires", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-106", "name": "Pourcentage absent", "family": "quantification",
        "cv_text": CV_CDI, "offer_requirements": ["Taux de conversion"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Taux de conversion", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-107", "name": "Preuve chiffrée sur une compétence", "family": "quantification",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Modelisation financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Modelisation financiere",
             "cv_evidence": "Modelisation financiere de 120 budgets"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-108", "name": "Reporting présent sans chiffre", "family": "quantification",
        "cv_text": CV_CDI, "offer_requirements": ["Reporting commercial"],
        "expected_actions": [
            {"code": "REPHRASE", "requirement": "Reporting commercial", "cv_evidence": "reporting"},
        ],
        "expected_score_range": (0.6, 0.6), "expected_warnings": [],
    },
    {
        "id": "ADV-109", "name": "Preuve numérique générique", "family": "quantification",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Budget de 500 kEUR"],
        "expected_actions": [
            {"code": "QUANTIFY", "requirement": "Budget de 500 kEUR", "cv_evidence": "Budget de 500 kEUR"},
        ],
        "expected_score_range": (0.9, 0.9), "expected_warnings": [],
    },

    # ── F10 : multilingue ───────────────────────────────────────────
    {
        "id": "ADV-110", "name": "Profil FR/EN sur offre EN", "family": "multilingue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais courant", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-111", "name": "Profil FR seul sur offre EN", "family": "multilingue",
        "cv_text": CV_CDI, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-112", "name": "Langue jamais déclarée", "family": "multilingue",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-113", "name": "Anglais sans niveau sur profil trilingue", "family": "multilingue",
        "cv_text": CV_MULTILINGUE, "offer_requirements": ["Anglais"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-114", "name": "Exigence technique et contractuelle mêlées", "family": "multilingue",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Excel avance", "Contrat CDI"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
            {"code": "HIGHLIGHT", "requirement": "Contrat CDI", "cv_evidence": "CDI"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-115", "name": "Trois exigences, une seule prouvée", "family": "multilingue",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Excel avance", "Python", "Anglais courant"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Excel avance", "cv_evidence": None},
            {"code": "DO_NOT_ADD", "requirement": "Python", "cv_evidence": None},
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-116", "name": "Toutes les exigences prouvées", "family": "multilingue",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Analyse financiere", "Excel avance", "Anglais courant"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Analyse financiere", "cv_evidence": "Analyse financiere"},
            {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
            {"code": "HIGHLIGHT", "requirement": "Anglais courant", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-117", "name": "Aucune exigence satisfaite", "family": "multilingue",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Scala", "Kubernetes"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Scala", "cv_evidence": None},
            {"code": "DO_NOT_ADD", "requirement": "Kubernetes", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-118", "name": "Exigence unique satisfaite", "family": "multilingue",
        "cv_text": CV_DATA, "offer_requirements": ["Python"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Python", "cv_evidence": "Python"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-119", "name": "Exigence unique non satisfaite", "family": "multilingue",
        "cv_text": CV_DATA, "offer_requirements": ["Scala"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Scala", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-120", "name": "Acronyme absent et niveau présent", "family": "multilingue",
        "cv_text": CV_CDI, "offer_requirements": ["Experience en M&A", "Master 2"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Experience en M&A", "cv_evidence": None},
            {"code": "DO_NOT_ADD", "requirement": "Master 2", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-121", "name": "Profil sans expérience structurée", "family": "multilingue",
        "cv_text": CV_MINIMAL, "offer_requirements": ["Excel avance"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Excel avance", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-122", "name": "Offre en anglais, CV sans anglais", "family": "multilingue",
        "cv_text": CV_CDI, "offer": _offer_en(["Advanced Excel"]),
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Advanced Excel", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["anglais"],
    },
    {
        "id": "ADV-123", "name": "Offre en anglais, CV avec anglais courant", "family": "multilingue",
        "cv_text": CV_ANALYSTE, "offer": _offer_en(["Anglais courant"]),
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Anglais courant", "cv_evidence": "Anglais courant"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-124", "name": "Offre en anglais, CV avec anglais passif", "family": "multilingue",
        "cv_text": CV_ANGLAIS_LU, "offer": _offer_en(["Anglais courant"]),
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Anglais courant", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": ["lecture"],
    },
    {
        "id": "ADV-125", "name": "Compétence transposable FR → EN", "family": "multilingue",
        "cv_text": CV_EXCEL, "offer": _offer_en(["Advanced Excel"]),
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Advanced Excel", "cv_evidence": "Excel avance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },

    # ── F11 : niveau de compétence (au-delà de la simple présence) ───
    {
        "id": "ADV-126", "name": "Niveau exigé non attesté dans le CV", "family": "niveau_competence",
        "cv_text": CV_EXCEL_SANS_NIVEAU, "offer_requirements": ["Excel avance"],
        "expected_actions": [
            {"code": "REPHRASE", "requirement": "Excel avance", "cv_evidence": "Excel"},
        ],
        "expected_score_range": (0.6, 0.6), "expected_warnings": ["non attesté"],
    },
    {
        "id": "ADV-127", "name": "Niveau exigé supérieur au niveau du CV", "family": "niveau_competence",
        "cv_text": CV_EXCEL_BASIQUE, "offer_requirements": ["Excel avance"],
        "expected_actions": [
            {"code": "REPHRASE", "requirement": "Excel avance", "cv_evidence": "Saisie Excel basique"},
        ],
        "expected_score_range": (0.6, 0.6), "expected_warnings": ["insuffisant"],
    },
    {
        "id": "ADV-128", "name": "Niveau du CV supérieur au niveau exigé", "family": "niveau_competence",
        "cv_text": CV_EXCEL, "offer_requirements": ["Excel basique"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel basique", "cv_evidence": "Excel avance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-129", "name": "Niveau expert exigé, non attesté", "family": "niveau_competence",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Analyse financiere experte"],
        "expected_actions": [
            {"code": "REPHRASE", "requirement": "Analyse financiere experte", "cv_evidence": "Analyse financiere"},
        ],
        "expected_score_range": (0.6, 0.6), "expected_warnings": ["non attesté"],
    },
    {
        "id": "ADV-130", "name": "Niveau exigé atteint", "family": "niveau_competence",
        "cv_text": CV_EXCEL, "offer_requirements": ["Excel confirme"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel confirme", "cv_evidence": "Excel avance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-131", "name": "Exemple de la mission : Excel vs analyse financière",
        "family": "niveau_competence",
        "cv_text": CV_MODELISATION, "offer_requirements": ["Excel avance", "Analyse financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel avance", "cv_evidence": "Excel avance"},
            {"code": "REPHRASE", "requirement": "Analyse financiere", "cv_evidence": "Modelisation financiere"},
        ],
        "expected_score_range": (0.8, 0.8), "expected_warnings": [],
    },
    {
        "id": "ADV-132", "name": "Analyse financière prouvée par le CV", "family": "niveau_competence",
        "cv_text": CV_ANALYSTE, "offer_requirements": ["Analyse financiere"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Analyse financiere", "cv_evidence": "Analyse financiere"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-133", "name": "M&A écrit avec son acronyme", "family": "acronyme",
        "cv_text": CV_MA, "offer_requirements": ["Experience en M&A"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Experience en M&A", "cv_evidence": "Analyste M&A"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-134", "name": "Chiffre d'affaires présent et chiffré", "family": "quantification",
        "cv_text": CV_COMMERCIAL, "offer_requirements": ["Chiffre d'affaires"],
        "expected_actions": [
            {"code": "QUANTIFY", "requirement": "Chiffre d'affaires",
             "cv_evidence": "Suivi d'un chiffre d'affaires de 3 millions"},
        ],
        "expected_score_range": (0.9, 0.9), "expected_warnings": [],
    },
    {
        "id": "ADV-135", "name": "Encadrement présent mais non chiffré", "family": "quantification",
        "cv_text": CV_CHEF_PROJET_SANS_CHIFFRE, "offer_requirements": ["Encadrement d equipe"],
        "expected_actions": [
            {"code": "QUANTIFY", "requirement": "Encadrement d equipe", "cv_evidence": "encadrement d equipe"},
        ],
        "expected_score_range": (0.9, 0.9), "expected_warnings": [],
    },
    {
        "id": "ADV-136", "name": "Niveau expert atteint dans le CV", "family": "niveau_competence",
        "cv_text": CV_ANALYSTE_EXPERTE, "offer_requirements": ["Analyse financiere experte"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Analyse financiere experte",
             "cv_evidence": "Analyse financiere experte"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
    {
        "id": "ADV-137", "name": "Niveau exigé, compétence absente du CV", "family": "niveau_competence",
        "cv_text": CV_CDI, "offer_requirements": ["Excel basique"],
        "expected_actions": [
            {"code": "DO_NOT_ADD", "requirement": "Excel basique", "cv_evidence": None},
        ],
        "expected_score_range": (0.0, 0.0), "expected_warnings": [],
    },
    {
        "id": "ADV-138", "name": "Niveau intermédiaire dépassé par le CV", "family": "niveau_competence",
        "cv_text": CV_EXCEL, "offer_requirements": ["Excel intermediaire"],
        "expected_actions": [
            {"code": "HIGHLIGHT", "requirement": "Excel intermediaire", "cv_evidence": "Excel avance"},
        ],
        "expected_score_range": (1.0, 1.0), "expected_warnings": [],
    },
]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _offer_for(case: dict) -> dict:
    """Return the offer of a case (synthetic French offer by default)."""
    if "offer" in case:
        return case["offer"]
    return _offer(case["offer_requirements"])


def _match(cv_text: str, offer: dict) -> MatchResult:
    """Run the matcher on a synthetic couple."""
    document = DocumentInput(text=cv_text, filename="cv-synthetique.txt", filetype="txt")
    analysis = analyze_cv(document)
    return match_cv_to_offer(analysis, offer)


def _run_case(case: dict) -> MatchResult:
    """Run the matcher on the couple of a case."""
    return _match(case["cv_text"], _offer_for(case))


def _action_for(result: MatchResult, requirement: str) -> MatchAction | None:
    for action in result.actions:
        if action.requirement_text == requirement:
            return action
    return None


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

def test_banc_comporte_plus_de_100_cas():
    """Le banc doit couvrir au moins 100 couples adversariaux."""
    assert len(CASES) >= 100
    identifiers = [case["id"] for case in CASES]
    assert len(set(identifiers)) == len(identifiers)


def test_familles_couvertes():
    """Les familles de pièges annoncées sont toutes présentes."""
    families = {case["family"] for case in CASES}
    expected = {
        "faux_positif_lexical", "acronyme", "langue", "contrat", "diplome",
        "negation", "absente", "homonyme", "quantification", "multilingue",
        "niveau_competence",
    }
    assert expected <= families
    for family in expected:
        count = sum(1 for case in CASES if case["family"] == family)
        assert count >= 5, f"famille « {family} » : seulement {count} cas"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_cas_adversarial(case):
    """Chaque cas produit les actions attendues."""
    result = _run_case(case)
    for expectation in case["expected_actions"]:
        requirement = expectation["requirement"]
        action = _action_for(result, requirement)
        assert action is not None, f"{case['id']} : aucune action pour « {requirement} »"
        assert action.code == expectation["code"], (
            f"{case['id']} ({case['name']}) : « {requirement} » vaut {action.code}, "
            f"attendu {expectation['code']} ({action.reason})"
        )
        if expectation["cv_evidence"] is not None:
            assert action.cv_evidence_text == expectation["cv_evidence"], (
                f"{case['id']} ({case['name']}) : preuve {action.cv_evidence_text!r}, "
                f"attendu {expectation['cv_evidence']!r}"
            )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_score_dans_la_plage_attendue(case):
    """Le score global tombe dans la plage attendue pour le couple."""
    low, high = case["expected_score_range"]
    result = _run_case(case)
    assert low - 1e-9 <= result.overall_score <= high + 1e-9, (
        f"{case['id']} ({case['name']}) : score {result.overall_score}, "
        f"attendu dans [{low}, {high}]"
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_avertissements_attendus(case):
    """Les avertissements annoncés sont présents."""
    result = _run_case(case)
    for fragment in case["expected_warnings"]:
        assert any(fragment in warning for warning in result.warnings), (
            f"{case['id']} ({case['name']}) : aucun avertissement ne contient « {fragment} » "
            f"({result.warnings})"
        )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_preuve_toujours_verbatim(case):
    """Invariant dur : toute preuve citée est une sous-chaîne exacte du CV."""
    result = _run_case(case)
    for action in result.actions:
        if action.cv_evidence_text is None:
            continue
        assert action.cv_evidence_text in case["cv_text"], (
            f"{case['id']} ({case['name']}) : preuve non verbatim {action.cv_evidence_text!r}"
        )
        assert action.cv_evidence_offset is not None
        assert case["cv_text"][
            action.cv_evidence_offset: action.cv_evidence_offset + len(action.cv_evidence_text)
        ] == action.cv_evidence_text, (
            f"{case['id']} ({case['name']}) : offset de preuve incohérent pour {action.cv_evidence_text!r}"
        )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_absent_jamais_ajoute(case):
    """Invariant dur : une exigence sans preuve n'est jamais étayée."""
    result = _run_case(case)
    for action in result.actions:
        if action.code == "DO_NOT_ADD":
            assert action.cv_evidence_text is None, (
                f"{case['id']} ({case['name']}) : une exigence non étayée porte une preuve"
            )
            assert action.reason.startswith(NO_PROOF_REASON), (
                f"{case['id']} ({case['name']}) : raison de DO_NOT_ADD inattendue : {action.reason!r}"
            )
        else:
            assert action.cv_evidence_text, (
                f"{case['id']} ({case['name']}) : une exigence étayée ne porte aucune preuve"
            )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_determinisme(case):
    """Invariant dur : deux exécutions donnent le même résultat."""
    first = _run_case(case)
    second = _run_case(case)
    assert first == second, f"{case['id']} ({case['name']}) : résultat non déterministe"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_aucune_donnee_de_contact(case):
    """Invariant dur : aucune donnée de contact ne fuit dans la décision."""
    result = _run_case(case)
    surface = " ".join(
        [action.requirement_text for action in result.actions]
        + [action.cv_evidence_text or "" for action in result.actions]
        + list(result.warnings)
    ).lower()
    for leak in ("@", "linkedin", "telephone", "06 ", "07 "):
        assert leak not in surface, f"{case['id']} ({case['name']}) : fuite « {leak} »"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_score_determine_et_borne(case):
    """Le score est borné, cohérent avec le nombre d'exigences satisfaites."""
    result = _run_case(case)
    assert 0.0 <= result.overall_score <= 1.0, f"{case['id']} : score hors bornes"
    assert result.matched_requirements <= result.total_requirements
    assert result.total_requirements == len(result.actions)
    covering = sum(
        1 for action in result.actions
        if action.code in {"HIGHLIGHT", "QUANTIFY", "CONFIRM_LANGUAGE"}
    )
    assert result.matched_requirements == covering, (
        f"{case['id']} : matched_requirements ne compte que les exigences couvertes"
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_exigence_obligatoire_manquante_signalee(case):
    """Toute exigence obligatoire non couverte est listée dans missing_critical."""
    result = _run_case(case)
    for action in result.actions:
        if action.code == "DO_NOT_ADD":
            assert action.requirement_text in result.missing_critical, (
                f"{case['id']} : « {action.requirement_text} » n'est pas dans missing_critical"
            )


def test_negation_exclue_du_denominateur():
    """Une exigence niée n'est pas comptée comme exigence à couvrir."""
    result = _match(CV_MULTILINGUE, _offer(["Pas de gestion d equipe", "Pilotage de projets"]))
    assert result.total_requirements == 1
    assert result.matched_requirements == 1
    assert result.overall_score == 1.0
    assert any("niée" in warning for warning in result.warnings)


def test_negation_en_conflit_avec_le_cv_signalee():
    """Une compétence niée par l'offre mais présente dans le CV est signalée."""
    result = _match(CV_MULTILINGUE, _offer(["Pas de gestion d equipe"]))
    assert any("gestion d equipe" in warning for warning in result.warnings)
    assert any("Attention" in warning for warning in result.warnings)


def test_avertissement_contrat_incompatible():
    """Un contrat différent est signalé, pas traité comme une preuve."""
    result = _match(CV_CDI, _offer(["Contrat stage"]))
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("contrat" in warning.lower() for warning in result.warnings)


def test_avertissement_homonyme():
    """Un homonyme sectoriel est signalé."""
    result = _match(CV_AUDIT_IT, _offer(["Audit financier"]))
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("homonyme" in warning.lower() for warning in result.warnings)


def test_avertissement_langue_programme():
    """Un programme enseigné en anglais ne vaut pas niveau de langue."""
    result = _match(CV_PROGRAMME_ANGLAIS, _offer(["Anglais courant"]))
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("enseignement" in warning.lower() for warning in result.warnings)


def test_avertissement_niveau_de_competence():
    """Un niveau exigé mais non attesté est signalé."""
    result = _match(CV_EXCEL_SANS_NIVEAU, _offer(["Excel avance"]))
    assert result.actions[0].code == "REPHRASE"
    assert any("non attesté" in warning for warning in result.warnings)


def test_score_reflete_la_couverture():
    """Le score baisse quand une exigence obligatoire n'est pas couverte."""
    complet = _match(CV_ANALYSTE, _offer(["Analyse financiere", "Excel avance"]))
    incomplet = _match(CV_ANALYSTE, _offer(["Analyse financiere", "Scala"]))
    assert complet.overall_score > incomplet.overall_score
    assert complet.matched_requirements == 2
    assert incomplet.matched_requirements == 1


def test_score_pondere_par_modalite():
    """Une exigence obligatoire pèse plus qu'une exigence souhaitée."""
    offre = {
        "title": "Poste de test",
        "requirements": "Analyse financiere\nSouhaite : Scala",
        "description_original": "Poste de test.",
    }
    result = _match(CV_ANALYSTE, offre)
    assert result.total_requirements == 2
    assert result.overall_score < 1.0
    assert result.overall_score > 0.5


def test_texte_absent_ne_produit_aucune_preuve():
    """Sans texte de CV, le moteur ne fabrique aucune preuve."""
    from career.cv_quality.models import CVAnalysisResult, Provenance, ReadabilityScore

    vide = CVAnalysisResult(
        findings=[],
        sections=[],
        experiences=[],
        readability=ReadabilityScore(0.0, 0.0, 0.0),
        provenance=Provenance(filename=None, filetype="txt", text_length=0, page_count=None),
    )
    result = match_cv_to_offer(vide, _offer(["Analyse financiere"]))
    assert result.actions[0].code == "DO_NOT_ADD"
    assert result.actions[0].cv_evidence_text is None
    assert result.overall_score == 0.0
    assert any("indisponible" in warning for warning in result.warnings)


def test_api_publique_exportee():
    """La fonction est exportée par le package public."""
    import career.cv_quality as package

    assert "match_cv_to_offer" in package.__all__
    assert callable(package.match_cv_to_offer)
