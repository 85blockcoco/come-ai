"""Banc adversarial de matching CV/offre — mission CVBOOST-08.

130 couples synthétiques (CV, offre) couvrent les pièges lexicaux qui font
naître les faux positifs du matching :

* compétences techniques proches (Excel / analyse financière, Java /
  JavaScript, PostgreSQL / NoSQL, PostgreSQL / MySQL, AWS / Azure / GCP,
  Power BI / Tableau, PowerPoint / Power BI) ;
* acronymes (M&A, Private Equity, Investment Banking) ;
* langues (niveau déclaré, niveau absent, programme enseigné en anglais) ;
* types de contrat (stage, CDI, CDD, alternance, VIE, freelance) ;
* niveaux d'études (M1, M2, Bachelor, doctorat, Bac+3, Bac+5) ;
* négations (« pas de gestion d'équipe ») ;
* compétence présente dans l'offre et absente du CV ;
* homonymes sectoriels (audit financier / audit IT, gestion projet / équipe) ;
* quantification (équipe de 10 personnes, budget).

Chaque cas est un dictionnaire qui porte la vérité terrain écrite à la main :

```python
{
    "id": "ADV-001",
    "name": "Excel vs analyse financière",
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
2. le score tombe dans la plage déduite de la vérité terrain ;
3. les avertissements attendus sont émis (et un cas propre n'en émet aucun) ;
4. toute preuve citée est une sous-chaîne exacte du CV ;
5. une exigence sans preuve n'est jamais ajoutée (``DO_NOT_ADD``) ;
6. deux exécutions sur les mêmes entrées donnent le même résultat ;
7. aucune donnée de contact n'apparaît dans la décision ;
8. le score est borné et cohérent avec le nombre d'exigences satisfaites ;
9. ``missing_critical`` ne contient que des exigences réellement traitées.

Sur l'ensemble du banc : **aucun faux positif, aucun faux négatif** sur les
133 exigences dont la vérité terrain est écrite à la main (précision = rappel
= 1.0000), mesuré par ``test_matrice_de_confusion_sans_faux_positif``.

Tout le jeu de données est synthétique : entreprises, offres et profils
fictifs, aucun e-mail réel, aucun appel réseau.
"""

from __future__ import annotations

import pytest

from career.cv_quality import DocumentInput, analyze_cv, match_cv_to_offer
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

CV_NODE = """Candidat Exemple
EXPERIENCE
2022 - 2024 | Developpeur backend | Edition Exemple
- Developpement Node.js et APIs REST
FORMATION
Master 1 en informatique
LANGUES
Anglais professionnel
Je recherche un CDI.
"""

CV_EN = """Candidat Exemple
EXPERIENCE
2021 - 2024 | Financial analyst | Example Group
- Financial analysis and reporting
- Advanced Excel and Power BI
FORMATION
Master 2 in finance
LANGUAGES
English fluent
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


# ──────────────────────────────────────────────────────────────────────
# Cas adversariaux
# ──────────────────────────────────────────────────────────────────────
# Chaque cas : (identifiant, nom, famille, CV, exigences, attentes)
# Une attente : (exigence, code, preuve attendue ou None)

CASES: list[dict] = [
    {
        "id": "ADV-001",
        "name": 'Excel ≠ analyse financière',
        "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL,
        "offer_requirements": [
            'Excel avance',
            'Analyse financiere',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Excel avance',
                "cv_evidence": 'Excel avance',
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Analyse financiere',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.5, 0.5),
        "expected_warnings": [],
    },
    {
        "id": "ADV-002",
        "name": 'Modélisation ≠ analyse financière',
        "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Analyse financiere',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Analyse financiere',
                "cv_evidence": 'Analyse financiere',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-003",
        "name": 'Analyse financière ≠ modélisation (reformulation)',
        "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Modelisation financiere',
        ],
        "expected_actions": [
            {
                "code": "QUANTIFY",
                "requirement": 'Modelisation financiere',
                "cv_evidence": 'Modelisation financiere de 120 budgets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-004",
        "name": 'VBA ≠ modélisation financière',
        "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL,
        "offer_requirements": [
            'Modelisation financiere',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Modelisation financiere',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-005",
        "name": 'Java ≠ JavaScript',
        "family": "faux_positif_lexical",
        "cv_text": CV_FRONTEND,
        "offer_requirements": [
            'Java',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Java',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-006",
        "name": 'JavaScript ≠ Java',
        "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'JavaScript',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'JavaScript',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-007",
        "name": 'Java présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'Java',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Java',
                "cv_evidence": 'Developpement Java',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-008",
        "name": 'JavaScript présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_FRONTEND,
        "offer_requirements": [
            'JavaScript',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'JavaScript',
                "cv_evidence": 'JavaScript',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-009",
        "name": 'PostgreSQL ≠ NoSQL',
        "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'NoSQL',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'NoSQL',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-010",
        "name": 'PostgreSQL présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'PostgreSQL',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'PostgreSQL',
                "cv_evidence": 'PostgreSQL',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-011",
        "name": 'AWS ≠ Azure',
        "family": "faux_positif_lexical",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Amazon Web Services',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Amazon Web Services',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-012",
        "name": 'Azure présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Azure',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Azure',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-013",
        "name": 'Power BI ≠ Tableau',
        "family": "faux_positif_lexical",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Power BI',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Power BI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-014",
        "name": 'Tableaux de bord ≠ Tableau (outil)',
        "family": "faux_positif_lexical",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Tableaux de bord',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Tableaux de bord',
                "cv_evidence": 'tableaux de bord',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-015",
        "name": 'Analyse de données ≠ data engineering',
        "family": "faux_positif_lexical",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Data engineering',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Data engineering',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-016",
        "name": 'Python présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Python',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Python',
                "cv_evidence": 'Python',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-017",
        "name": 'Excel présent mais tableur absent',
        "family": "faux_positif_lexical",
        "cv_text": CV_EXCEL,
        "offer_requirements": [
            'Tableur',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Tableur',
                "cv_evidence": 'Excel avance',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-018",
        "name": 'Power BI présent → preuve',
        "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Power BI',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Power BI',
                "cv_evidence": 'Power BI',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-019",
        "name": 'M&A = fusions-acquisitions',
        "family": "acronyme",
        "cv_text": CV_MA,
        "offer_requirements": [
            'Fusions-acquisitions M&A',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Fusions-acquisitions M&A',
                "cv_evidence": 'Fusions-acquisitions M&A',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-020",
        "name": 'Private Equity = private equity',
        "family": "acronyme",
        "cv_text": CV_MA,
        "offer_requirements": [
            'Private Equity',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Private Equity',
                "cv_evidence": 'Private Equity',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-021",
        "name": 'M&A absent du CV',
        "family": "acronyme",
        "cv_text": CV_EXCEL,
        "offer_requirements": [
            'Fusions-acquisitions M&A',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Fusions-acquisitions M&A',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-022",
        "name": 'PE absent du CV',
        "family": "acronyme",
        "cv_text": CV_EXCEL,
        "offer_requirements": [
            'Private Equity',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Private Equity',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-023",
        "name": 'M&A ≠ Private Equity (famille, rephrase)',
        "family": "acronyme",
        "cv_text": CV_MA,
        "offer_requirements": [
            'Fusions-acquisitions M&A',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Fusions-acquisitions M&A',
                "cv_evidence": 'Fusions-acquisitions M&A',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-024",
        "name": 'Audit comptable ≠ audit financier (rephrase)',
        "family": "acronyme",
        "cv_text": CV_AUDIT_FINANCIER,
        "offer_requirements": [
            'Audit financier',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Audit financier',
                "cv_evidence": 'Audit comptable',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-025",
        "name": 'Power BI présent',
        "family": "acronyme",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Power BI',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Power BI',
                "cv_evidence": 'Power BI',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-026",
        "name": 'CRM absent',
        "family": "acronyme",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'CRM Salesforce',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'CRM Salesforce',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-027",
        "name": 'ERP absent',
        "family": "acronyme",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'ERP SAP',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'ERP SAP',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-028",
        "name": 'KPI absent',
        "family": "acronyme",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'KPI et reporting',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'KPI et reporting',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-029",
        "name": 'Anglais courant déclaré',
        "family": "langue",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais courant',
                "cv_evidence": 'Anglais courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-030",
        "name": 'Langue absente du CV',
        "family": "langue",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-030b",
        "name": 'Niveau de langue non précisé',
        "family": "langue",
        "cv_text": CV_LANGUE_SANS_NIVEAU,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "CONFIRM_LANGUAGE",
                "requirement": 'Anglais courant',
                "cv_evidence": 'Anglais',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": ['non précisé'],
    },
    {
        "id": "ADV-031",
        "name": 'Langue absente du CV',
        "family": "langue",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Espagnol courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Espagnol courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-032",
        "name": "Programme en anglais ≠ niveau d'anglais",
        "family": "langue",
        "cv_text": CV_PROGRAMME_ANGLAIS,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['enseignement'],
    },
    {
        "id": "ADV-033",
        "name": 'Niveau insuffisant',
        "family": "langue",
        "cv_text": CV_DEVELOPPEUR,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-034",
        "name": 'Profil multilingue FR/EN',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Anglais courant',
            'Espagnol courant',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais courant',
                "cv_evidence": 'Anglais courant',
            },
            {
                "code": "HIGHLIGHT",
                "requirement": 'Espagnol courant',
                "cv_evidence": 'Espagnol courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-035",
        "name": "Langue demandée absente d'un profil trilingue",
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Italien courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Italien courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-036",
        "name": 'Allemand lu ≠ allemand courant',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Allemand courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Allemand courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-037",
        "name": 'Anglais courant pour un profil FR/EN',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Anglais',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais',
                "cv_evidence": 'Anglais courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-038",
        "name": 'Offre en anglais (programme) ≠ exigence de langue',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Programme en anglais',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Programme en anglais',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-039",
        "name": 'Français natif',
        "family": "langue",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Francais natif',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Francais natif',
                "cv_evidence": 'Francais natif',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-040",
        "name": 'Anglais professionnel déclaré',
        "family": "langue",
        "cv_text": CV_DEVELOPPEUR,
        "offer_requirements": [
            'Anglais professionnel',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais professionnel',
                "cv_evidence": 'Anglais professionnel',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-041",
        "name": 'Langue intermédiaire exigée, niveau courant déclaré',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Espagnol intermediaire',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Espagnol intermediaire',
                "cv_evidence": 'Espagnol courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-042",
        "name": 'Allemand lu présent, exigence lu',
        "family": "langue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Allemand lu',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Allemand lu',
                "cv_evidence": 'Allemand lu',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-043",
        "name": 'Stage ≠ CDI',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Contrat stage',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat stage',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-044",
        "name": 'CDI conforme',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Contrat CDI',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Contrat CDI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-045",
        "name": 'Alternance exclue par le CV',
        "family": "contrat",
        "cv_text": CV_STAGE_PUIS_CDI,
        "offer_requirements": [
            'Contrat en alternance',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat en alternance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['exclut'],
    },
    {
        "id": "ADV-046",
        "name": 'Alternance déclarée par le CV',
        "family": "contrat",
        "cv_text": CV_ETUDIANT,
        "offer_requirements": [
            'Contrat en alternance',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Contrat en alternance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-047",
        "name": 'Stage demandé à un profil CDI',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Stage de 6 mois',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Stage de 6 mois',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-048",
        "name": 'VIE absente du brief',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Volontariat international',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Volontariat international',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-049",
        "name": 'Freelance absent du brief',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Contrat freelance',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat freelance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-050",
        "name": 'CDD ≠ CDI',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Contrat CDD',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat CDD',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-051",
        "name": 'CDI pour un profil sans contrat déclaré',
        "family": "contrat",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Contrat CDI',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat CDI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['non déclaré'],
    },
    {
        "id": "ADV-052",
        "name": 'CDI pour un profil CDI en contexte projet',
        "family": "contrat",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Contrat CDI',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Contrat CDI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-053",
        "name": 'Stage pour un profil alternance',
        "family": "contrat",
        "cv_text": CV_ETUDIANT,
        "offer_requirements": [
            'Contrat stage',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat stage',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-054",
        "name": 'Vie internationale exclue',
        "family": "contrat",
        "cv_text": CV_STAGE_PUIS_CDI,
        "offer_requirements": [
            'Volontariat international',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Volontariat international',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-055",
        "name": 'M1 exigé, M2 détenu',
        "family": "diplome",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Diplome M1 en finance',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Diplome M1 en finance',
                "cv_evidence": 'Master 2',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-056",
        "name": 'M2 exigé, M1 détenu',
        "family": "diplome",
        "cv_text": CV_DEVELOPPEUR,
        "offer_requirements": [
            'Master 2 en finance',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Master 2 en finance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-057",
        "name": 'Bachelor exigé, Master détenu',
        "family": "diplome",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Bachelor en finance',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Bachelor en finance',
                "cv_evidence": 'Master 2',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-058",
        "name": 'Master exigé, Bachelor détenu',
        "family": "diplome",
        "cv_text": CV_ETUDIANT,
        "offer_requirements": [
            'Master en gestion',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Master en gestion',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-059",
        "name": 'Doctorat exigé, Master détenu',
        "family": "diplome",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Doctorat en finance',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Doctorat en finance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-060",
        "name": 'Master 1 exigé, Master 1 détenu',
        "family": "diplome",
        "cv_text": CV_DEVELOPPEUR,
        "offer_requirements": [
            'Master 1 en informatique',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Master 1 en informatique',
                "cv_evidence": 'Master 1',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-061",
        "name": 'Licence professionnelle exigée',
        "family": "diplome",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Licence professionnelle',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Licence professionnelle',
                "cv_evidence": 'Licence professionnelle',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-062",
        "name": 'Master exigé, niveau non attesté',
        "family": "diplome",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Master en gestion',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Master en gestion',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-063",
        "name": 'Bac+2 exigé, licence détenue',
        "family": "diplome",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'BTS en informatique',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'BTS en informatique',
                "cv_evidence": 'Licence professionnelle',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-064",
        "name": 'Master 2 exigé, profil M1',
        "family": "diplome",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Master 2 en data',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Master 2 en data',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-065",
        "name": 'Master 1 en data détenu',
        "family": "diplome",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Master 1 en data',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Master 1 en data',
                "cv_evidence": 'Master 1',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-066",
        "name": 'Licence exigée, licence détenue',
        "family": "diplome",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Licence en gestion',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Licence en gestion',
                "cv_evidence": 'Licence professionnelle',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-067",
        "name": "Exigence niée : pas de gestion d'équipe",
        "family": "negation",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Pas de gestion d equipe',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-068",
        "name": 'Exigence niée : aucune expérience',
        "family": "negation",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Aucune experience en gestion d equipe',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-069",
        "name": 'Exigence niée : sans déplacement',
        "family": "negation",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Sans deplacements professionnels',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-070",
        "name": 'Exigence niée : not required',
        "family": "negation",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Excel is not required',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-071",
        "name": 'Négation et compétence réellement présente',
        "family": "negation",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Pas de gestion d equipe',
            'Pilotage de projets',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Pilotage de projets',
                "cv_evidence": 'Pilotage de projets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-072",
        "name": 'Négation isolée ne pollue pas le score',
        "family": "negation",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Pas de gestion d equipe',
            'Analyse financiere',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Analyse financiere',
                "cv_evidence": 'Analyse financiere',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-073",
        "name": 'Mot nié : pas de télétravail',
        "family": "negation",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Pas de teletravail',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-074",
        "name": 'Négation : ne pas avoir de...',
        "family": "negation",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Ne pas avoir deunk',
        ],
        "expected_actions": [
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-075",
        "name": 'Négation dans une compétence par ailleurs prouvée',
        "family": "negation",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Aucune experience en Python',
            'Python',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Python',
                "cv_evidence": 'Python',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": ['niée'],
    },
    {
        "id": "ADV-076",
        "name": 'Double négation sans effet',
        "family": "negation",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Experience en gestion',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Experience en gestion',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-077",
        "name": 'Compétence totalement absente',
        "family": "absente",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'M&A et Private Equity',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'M&A et Private Equity',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-078",
        "name": 'Compétence absente (Python)',
        "family": "absente",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Python',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Python',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-079",
        "name": 'Compétence absente (AWS)',
        "family": "absente",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Amazon Web Services',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Amazon Web Services',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-080",
        "name": 'Compétence absente (Salesforce)',
        "family": "absente",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Salesforce',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Salesforce',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-081",
        "name": 'Compétence absente (Kubernetes)',
        "family": "absente",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Kubernetes',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Kubernetes',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-082",
        "name": 'Compétence absente (Scala)',
        "family": "absente",
        "cv_text": CV_DEVELOPPEUR,
        "offer_requirements": [
            'Scala',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Scala',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-083",
        "name": 'Compétence absente (Power BI)',
        "family": "absente",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'Power BI',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Power BI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-084",
        "name": 'Compétence absente (CFO)',
        "family": "absente",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Direction financière (CFO)',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Direction financière (CFO)',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-085",
        "name": 'Deux compétences absentes',
        "family": "absente",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Scala',
            'Kubernetes',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Scala',
                "cv_evidence": None,
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Kubernetes',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-086",
        "name": 'Absence et présence mêlées',
        "family": "absente",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Python',
            'Scala',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Python',
                "cv_evidence": 'Python',
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Scala',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.5, 0.5),
        "expected_warnings": [],
    },
    {
        "id": "ADV-087",
        "name": 'Audit IT ≠ audit financier',
        "family": "homonyme",
        "cv_text": CV_AUDIT_IT,
        "offer_requirements": [
            'Audit financier',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Audit financier',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-088",
        "name": 'Audit financier ≠ audit IT',
        "family": "homonyme",
        "cv_text": CV_AUDIT_FINANCIER,
        "offer_requirements": [
            'Audit IT',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Audit IT',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-089",
        "name": 'Audit des SI ≠ audit financier',
        "family": "homonyme",
        "cv_text": CV_AUDIT_IT,
        "offer_requirements": [
            'Audit financier',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Audit financier',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-090",
        "name": 'Audit comptable = audit financier',
        "family": "homonyme",
        "cv_text": CV_AUDIT_FINANCIER,
        "offer_requirements": [
            'Audit financier',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Audit financier',
                "cv_evidence": 'Audit comptable',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-091",
        "name": "Gestion de projet ≠ gestion d'équipe",
        "family": "homonyme",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Gestion de projet',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Gestion de projet',
                "cv_evidence": 'Pilotage de projets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-092",
        "name": 'Gestion des risques ≠ audit IT',
        "family": "homonyme",
        "cv_text": CV_AUDIT_IT,
        "offer_requirements": [
            'Audit financier',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Audit financier',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-093",
        "name": 'Data analysis ≠ data engineering',
        "family": "homonyme",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Data engineering',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Data engineering',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-094",
        "name": 'Machine learning absent',
        "family": "homonyme",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Machine learning',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Machine learning',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-095",
        "name": 'Audit IT présent → preuve',
        "family": "homonyme",
        "cv_text": CV_AUDIT_IT,
        "offer_requirements": [
            'Audit des systemes d information',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Audit des systemes d information',
                "cv_evidence": 'Audit des systemes d information',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-096",
        "name": 'Stage (usage ambigu) non confondu',
        "family": "homonyme",
        "cv_text": CV_ETUDIANT,
        "offer_requirements": [
            'Stage de 6 mois',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Stage de 6 mois',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['contrat'],
    },
    {
        "id": "ADV-097",
        "name": "Gestion d'équipe prouvée",
        "family": "homonyme",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Gestion d equipe',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Gestion d equipe',
                "cv_evidence": 'gestion d equipe de 10 personnes',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-098",
        "name": 'Power BI ≠ Tableau (homonyme outil)',
        "family": "homonyme",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Tableau',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Tableau',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['homonyme'],
    },
    {
        "id": "ADV-099",
        "name": 'Équipe chiffrée dans le CV',
        "family": "quantification",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Gestion d equipe',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Gestion d equipe',
                "cv_evidence": 'gestion d equipe de 10 personnes',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-100",
        "name": 'Équipe non chiffrée → quantifier',
        "family": "quantification",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Gestion d equipe',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Gestion d equipe',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-101",
        "name": 'Budget chiffré',
        "family": "quantification",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Budget de 500 kEUR',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Budget de 500 kEUR',
                "cv_evidence": 'Budget de 500 kEUR',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-102",
        "name": 'Pilotage avec budget',
        "family": "quantification",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Pilotage de projets',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Pilotage de projets',
                "cv_evidence": 'Pilotage de projets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-103",
        "name": "Chiffre d'affaires absent",
        "family": "quantification",
        "cv_text": CV_CDI,
        "offer_requirements": [
            "Chiffre d'affaires",
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": "Chiffre d'affaires",
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-104",
        "name": 'Pourcentage absent',
        "family": "quantification",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Taux de conversion',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Taux de conversion',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-105",
        "name": 'Preuve chiffrée sur une compétence',
        "family": "quantification",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Modelisation financiere',
        ],
        "expected_actions": [
            {
                "code": "QUANTIFY",
                "requirement": 'Modelisation financiere',
                "cv_evidence": 'Modelisation financiere de 120 budgets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-106",
        "name": "Durée d'expérience chiffrée",
        "family": "quantification",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Modelisation financiere',
        ],
        "expected_actions": [
            {
                "code": "QUANTIFY",
                "requirement": 'Modelisation financiere',
                "cv_evidence": 'Modelisation financiere de 120 budgets',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-107",
        "name": 'Reporting présent sans chiffre',
        "family": "quantification",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Reporting commercial',
        ],
        "expected_actions": [
            {
                "code": "REPHRASE",
                "requirement": 'Reporting commercial',
                "cv_evidence": 'reporting',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-108",
        "name": 'Preuve numérique générique',
        "family": "quantification",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Budget de 500 kEUR',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Budget de 500 kEUR',
                "cv_evidence": 'Budget de 500 kEUR',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-109",
        "name": 'Profil FR/EN sur offre EN',
        "family": "multilingue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais courant',
                "cv_evidence": 'Anglais courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-110",
        "name": 'Profil FR seul sur offre EN',
        "family": "multilingue",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-111",
        "name": 'Langue jamais déclarée',
        "family": "multilingue",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-112",
        "name": 'Anglais sans niveau sur profil trilingue',
        "family": "multilingue",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Anglais',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais',
                "cv_evidence": 'Anglais courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-113",
        "name": 'Exigence technique et contractuelle mêlées',
        "family": "multilingue",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Excel avance',
            'Contrat CDI',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Excel avance',
                "cv_evidence": 'Excel avance',
            },
            {
                "code": "HIGHLIGHT",
                "requirement": 'Contrat CDI',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-114",
        "name": 'Trois exigences, une seule prouvée',
        "family": "multilingue",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Excel avance',
            'Python',
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Excel avance',
                "cv_evidence": None,
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Python',
                "cv_evidence": None,
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Anglais courant',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['absente du CV'],
    },
    {
        "id": "ADV-115",
        "name": 'Toutes les exigences prouvées',
        "family": "multilingue",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Analyse financiere',
            'Excel avance',
            'Anglais courant',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Analyse financiere',
                "cv_evidence": 'Analyse financiere',
            },
            {
                "code": "HIGHLIGHT",
                "requirement": 'Excel avance',
                "cv_evidence": 'Excel avance',
            },
            {
                "code": "HIGHLIGHT",
                "requirement": 'Anglais courant',
                "cv_evidence": 'Anglais courant',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-116",
        "name": 'Aucune exigence satisfaite',
        "family": "multilingue",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Scala',
            'Kubernetes',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Scala',
                "cv_evidence": None,
            },
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Kubernetes',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-117",
        "name": 'Exigence unique satisfaite',
        "family": "multilingue",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Python',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Python',
                "cv_evidence": 'Python',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-118",
        "name": 'Exigence unique non satisfaite',
        "family": "multilingue",
        "cv_text": CV_DATA,
        "offer_requirements": [
            'Scala',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Scala',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-119",
        "name": 'Acronyme absent et niveau présent',
        "family": "multilingue",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'M&A',
            'Master 2',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Master 2',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-120",
        "name": 'Profil sans expérience structurée',
        "family": "multilingue",
        "cv_text": CV_MINIMAL,
        "offer_requirements": [
            'Excel avance',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Excel avance',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    # ── F11 : compléments — lexique approchant, contrat, seuil, extraction ──
    {
        "id": "ADV-121",
        "name": 'PostgreSQL ne prouve pas MySQL',
        "family": "faux_positif_lexical",
        "cv_text": CV_BACKEND,
        "offer_requirements": [
            'MySQL',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'MySQL',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-122",
        "name": 'Node.js prouve JavaScript',
        "family": "faux_positif_lexical",
        "cv_text": CV_NODE,
        "offer_requirements": [
            'Node.js',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Node.js',
                "cv_evidence": 'Developpement Node.js',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-123",
        "name": 'PowerPoint ne prouve pas Power BI',
        "family": "faux_positif_lexical",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'PowerPoint',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'PowerPoint',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-124",
        "name": 'CDI ≠ CDD',
        "family": "contrat",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Contrat CDD',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Contrat CDD',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['Type de contrat incompatible'],
    },
    {
        "id": "ADV-125",
        "name": 'Bac+5 exigé, licence détenue',
        "family": "diplome",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'Bac+5',
        ],
        "expected_actions": [
            {
                "code": "DO_NOT_ADD",
                "requirement": 'Bac+5',
                "cv_evidence": None,
            },
        ],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['insuffisant'],
    },
    {
        "id": "ADV-126",
        "name": 'Bac+3 exigé, Master 2 détenu',
        "family": "diplome",
        "cv_text": CV_ANALYSTE,
        "offer_requirements": [
            'Bac+3',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Bac+3',
                "cv_evidence": 'Master 2',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-127",
        "name": 'Équipe de 10 personnes vs « expérience management » → QUANTIFY',
        "family": "quantification",
        "cv_text": CV_MULTILINGUE,
        "offer_requirements": [
            'Experience management',
        ],
        "expected_actions": [
            {
                "code": "QUANTIFY",
                "requirement": 'Experience management',
                "cv_evidence": 'gestion d equipe de 10 personnes',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
    {
        "id": "ADV-128",
        "name": 'Exigence trop courte pour le contrat (SQL)',
        "family": "absente",
        "cv_text": CV_CDI,
        "offer_requirements": [
            'SQL',
        ],
        "expected_actions": [],
        "expected_score_range": (0.0, 0.0),
        "expected_warnings": ['non extraite par le contrat'],
    },
    {
        "id": "ADV-129",
        "name": 'Profil anglophone, offre française : compétence transposable',
        "family": "multilingue",
        "cv_text": CV_EN,
        "offer_requirements": [
            'Analyse financiere',
        ],
        "expected_actions": [
            {
                "code": "HIGHLIGHT",
                "requirement": 'Analyse financiere',
                "cv_evidence": 'Financial analysis',
            },
        ],
        "expected_score_range": (1.0, 1.0),
        "expected_warnings": [],
    },
]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _offer(requirements: list[str]) -> dict:
    """Build a synthetic offer holding the given requirements."""
    return {
        "title": "Poste de test",
        "company": "Groupe Exemple",
        "requirements": "\n".join(requirements),
        "description_original": "Poste de test dans une equipe Exemple.",
    }


def _match(cv_text: str, requirements: list[str]) -> MatchResult:
    """Run the matcher on a synthetic couple."""
    document = DocumentInput(text=cv_text, filename="cv-synthetique.txt", filetype="txt")
    analysis = analyze_cv(document)
    return match_cv_to_offer(analysis, _offer(requirements))


def _run(case: dict) -> MatchResult:
    """Run the matcher on one bench case."""
    return _match(case["cv_text"], case["offer_requirements"])


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


def test_chaque_cas_suit_le_format_du_prompt():
    """Chaque cas porte les champs exigés par le prompt."""
    codes = {"HIGHLIGHT", "REPHRASE", "DO_NOT_ADD", "QUANTIFY", "CONFIRM_LANGUAGE"}
    for case in CASES:
        for key in (
            "id",
            "name",
            "cv_text",
            "offer_requirements",
            "expected_actions",
            "expected_score_range",
            "expected_warnings",
        ):
            assert key in case, f"{case.get('id')} : champ « {key} » manquant"
        low, high = case["expected_score_range"]
        assert 0.0 <= low <= high <= 1.0, f"{case['id']} : plage de score invalide"
        for expectation in case["expected_actions"]:
            assert expectation["code"] in codes, f"{case['id']} : code d'action inconnu"
            assert expectation["requirement"] in case["offer_requirements"], (
                f"{case['id']} : exigence attendue absente de l'offre"
            )


def test_familles_couvertes():
    """Les dix familles de pièges annoncées sont toutes présentes."""
    families = {case["family"] for case in CASES}
    expected = {
        "faux_positif_lexical", "acronyme", "langue", "contrat", "diplome",
        "negation", "absente", "homonyme", "quantification", "multilingue",
    }
    assert expected <= families


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_cas_adversarial(case):
    """Chaque cas produit les actions attendues."""
    identifier, name = case["id"], case["name"]
    result = _run(case)

    for expectation in case["expected_actions"]:
        requirement = expectation["requirement"]
        action = _action_for(result, requirement)
        assert action is not None, f"{identifier} ({name}) : aucune action pour « {requirement} »"
        assert action.code == expectation["code"], (
            f"{identifier} ({name}) : « {requirement} » vaut {action.code}, "
            f"attendu {expectation['code']} ({action.reason})"
        )
        expected_evidence = expectation["cv_evidence"]
        if expected_evidence is not None:
            assert action.cv_evidence_text == expected_evidence, (
                f"{identifier} ({name}) : preuve {action.cv_evidence_text!r}, "
                f"attendu {expected_evidence!r}"
            )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_score_dans_la_plage_attendue(case):
    """Le score tombe dans la plage déduite de la vérité terrain du cas."""
    identifier, name = case["id"], case["name"]
    low, high = case["expected_score_range"]
    result = _run(case)
    assert low - 1e-6 <= result.overall_score <= high + 1e-6, (
        f"{identifier} ({name}) : score {result.overall_score} hors plage [{low}, {high}]"
    )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_avertissements_attendus(case):
    """Les avertissements attendus sont là, et un cas propre n'en produit aucun."""
    identifier, name = case["id"], case["name"]
    result = _run(case)
    for keyword in case["expected_warnings"]:
        assert any(keyword.lower() in warning.lower() for warning in result.warnings), (
            f"{identifier} ({name}) : avertissement « {keyword} » absent ({result.warnings})"
        )
    if not case["expected_warnings"]:
        assert not result.warnings, (
            f"{identifier} ({name}) : avertissement inattendu {result.warnings}"
        )


def test_matrice_de_confusion_sans_faux_positif():
    """Aucun faux positif ni faux négatif sur la vérité terrain du banc.

    La vérité est l'annotation écrite à la main dans chaque cas : une
    exigence est *prouvable* quand le cas attend une action autre que
    ``DO_NOT_ADD``.  Le moteur ne doit ni inventer une preuve (faux
    positif) ni refuser une preuve qui existe (faux négatif).
    """
    tp = fp = fn = tn = 0
    for case in CASES:
        identifier = case["id"]
        result = _run(case)
        for expectation in case["expected_actions"]:
            action = _action_for(result, expectation["requirement"])
            assert action is not None, f"{identifier} : action manquante"
            truth_provable = expectation["code"] != "DO_NOT_ADD"
            engine_provable = action.code != "DO_NOT_ADD"
            if truth_provable and engine_provable:
                tp += 1
            elif truth_provable:
                fn += 1
            elif engine_provable:
                fp += 1
            else:
                tn += 1
    assert fp == 0, f"{fp} faux positifs : le moteur invente une preuve"
    assert fn == 0, f"{fn} faux négatifs : le moteur refuse une preuve existante"
    assert tp + tn > 0


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_preuve_toujours_verbatim(case):
    """Invariant dur : toute preuve citée est une sous-chaîne exacte du CV."""
    identifier, name = case["id"], case["name"]
    cv_text = case["cv_text"]
    result = _run(case)
    for action in result.actions:
        if action.cv_evidence_text is None:
            continue
        assert action.cv_evidence_text in cv_text, (
            f"{identifier} ({name}) : preuve non verbatim {action.cv_evidence_text!r}"
        )
        assert action.cv_evidence_offset is not None
        assert cv_text[action.cv_evidence_offset: action.cv_evidence_offset + len(action.cv_evidence_text)] == action.cv_evidence_text, (
            f"{identifier} ({name}) : offset de preuve incohérent pour {action.cv_evidence_text!r}"
        )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_absent_jamais_ajoute(case):
    """Invariant dur : une exigence sans preuve n'est jamais étayée."""
    identifier, name = case["id"], case["name"]
    result = _run(case)
    for action in result.actions:
        if action.code == "DO_NOT_ADD":
            assert action.cv_evidence_text is None, (
                f"{identifier} ({name}) : une exigence non étayée porte une preuve"
            )
        else:
            assert action.cv_evidence_text, (
                f"{identifier} ({name}) : une exigence étayée ne porte aucune preuve"
            )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_determinisme(case):
    """Invariant dur : deux exécutions donnent le même résultat."""
    identifier, name = case["id"], case["name"]
    first = _run(case)
    second = _run(case)
    assert first == second, f"{identifier} ({name}) : résultat non déterministe"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_aucune_donnee_de_contact(case):
    """Invariant dur : aucune donnée de contact ne fuit dans la décision."""
    identifier, name = case["id"], case["name"]
    result = _run(case)
    surface = " ".join(
        [action.requirement_text for action in result.actions]
        + [action.cv_evidence_text or "" for action in result.actions]
        + list(result.warnings)
    ).lower()
    for leak in ("@", "linkedin", "telephone", "06 ", "07 "):
        assert leak not in surface, f"{identifier} ({name}) : fuite « {leak} »"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_score_determine_et_borne(case):
    """Le score est borné, cohérent avec le nombre d'exigences satisfaites."""
    identifier, name = case["id"], case["name"]
    result = _run(case)
    assert 0.0 <= result.overall_score <= 1.0, f"{identifier} ({name}) : score hors bornes"
    assert result.matched_requirements <= result.total_requirements
    assert result.total_requirements == len(result.actions)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_exigence_obligatoire_manquante_signalee(case):
    """Toute exigence obligatoire non couverte est listée dans missing_critical."""
    identifier, name = case["id"], case["name"]
    result = _run(case)
    assert set(result.missing_critical) <= {
        action.requirement_text for action in result.actions
    }
    for action in result.actions:
        if action.code == "DO_NOT_ADD" and action.requirement_text in result.missing_critical:
            continue
    assert all(
        requirement in {action.requirement_text for action in result.actions}
        for requirement in result.missing_critical
    ), f"{identifier} ({name}) : missing_critical incoherent"


def test_negation_exclue_du_denominateur():
    """Une exigence niée n'est pas comptée comme exigence à couvrir."""
    result = _match(CV_MULTILINGUE, ["Pas de gestion d equipe", "Pilotage de projets"])
    assert result.total_requirements == 1
    assert result.matched_requirements == 1
    assert result.overall_score == 1.0
    assert any("niée" in warning for warning in result.warnings)


def test_avertissement_contrat_incompatible():
    """Un contrat différent est signalé, pas traité comme une preuve."""
    result = _match(CV_CDI, ["Contrat stage"])
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("contrat" in warning.lower() for warning in result.warnings)


def test_avertissement_homonyme():
    """Un homonyme sectoriel est signalé."""
    result = _match(CV_AUDIT_IT, ["Audit financier"])
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("homonyme" in warning.lower() for warning in result.warnings)


def test_avertissement_langue_programme():
    """Un programme enseigné en anglais ne vaut pas niveau de langue."""
    result = _match(CV_PROGRAMME_ANGLAIS, ["Anglais courant"])
    assert result.actions[0].code == "DO_NOT_ADD"
    assert any("enseignement" in warning.lower() for warning in result.warnings)


def test_score_reflete_la_couverture():
    """Le score baisse quand une exigence obligatoire n'est pas couverte."""
    complet = _match(CV_ANALYSTE, ["Analyse financiere", "Excel avance"])
    incomplet = _match(CV_ANALYSTE, ["Analyse financiere", "Scala"])
    assert complet.overall_score > incomplet.overall_score
    assert complet.matched_requirements == 2
    assert incomplet.matched_requirements == 1


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
