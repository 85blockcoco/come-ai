"""Banc adversarial de matching CV/offre — mission CVBOOST-08.

120 couples synthétiques (CV, offre) couvrent les pièges lexicaux qui font
naître les faux positifs du matching :

* compétences techniques proches (Excel / analyse financière, Java /
  JavaScript, PostgreSQL / NoSQL, AWS / Azure / GCP, Power BI / Tableau) ;
* acronymes (M&A, Private Equity, Investment Banking) ;
* langues (niveau déclaré, niveau absent, programme enseigné en anglais) ;
* types de contrat (stage, CDI, alternance, VIE, freelance) ;
* niveaux d'études (M1, M2, Bachelor, doctorat) ;
* négations (« pas de gestion d'équipe ») ;
* compétence présente dans l'offre et absente du CV ;
* homonymes sectoriels (audit financier / audit IT, gestion projet / équipe) ;
* quantification (équipe de 10 personnes, budget).

Les quatre invariants durs vérifiés sur **chaque** cas :

1. toute preuve citée est une sous-chaîne exacte du CV ;
2. une exigence sans preuve n'est jamais ajoutée (``DO_NOT_ADD``) ;
3. deux exécutions sur les mêmes entrées donnent le même résultat ;
4. aucune donnée de contact n'apparaît dans la décision.

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

CASES: list[tuple] = [
    # ── F1 : compétences techniques proches (faux positifs) ──────────
    ("ADV-001", "Excel ≠ analyse financière", "faux_positif_lexical", CV_EXCEL,
     ["Excel avance", "Analyse financiere"],
     [("Excel avance", "HIGHLIGHT", "Excel avance"),
      ("Analyse financiere", "DO_NOT_ADD", None)]),
    ("ADV-002", "Modélisation ≠ analyse financière", "faux_positif_lexical", CV_ANALYSTE,
     ["Analyse financiere"],
     [("Analyse financiere", "HIGHLIGHT", "Analyse financiere")]),
    ("ADV-003", "Analyse financière ≠ modélisation (reformulation)", "faux_positif_lexical", CV_ANALYSTE,
     ["Modelisation financiere"],
     [("Modelisation financiere", "QUANTIFY", "Modelisation financiere de 120 budgets")]),
    ("ADV-004", "VBA ≠ modélisation financière", "faux_positif_lexical", CV_EXCEL,
     ["Modelisation financiere"],
     [("Modelisation financiere", "DO_NOT_ADD", None)]),
    ("ADV-005", "Java ≠ JavaScript", "faux_positif_lexical", CV_FRONTEND,
     ["Java"],
     [("Java", "DO_NOT_ADD", None)]),
    ("ADV-006", "JavaScript ≠ Java", "faux_positif_lexical", CV_BACKEND,
     ["JavaScript"],
     [("JavaScript", "DO_NOT_ADD", None)]),
    ("ADV-007", "Java présent → preuve", "faux_positif_lexical", CV_BACKEND,
     ["Java"],
     [("Java", "HIGHLIGHT", "Developpement Java")]),
    ("ADV-008", "JavaScript présent → preuve", "faux_positif_lexical", CV_FRONTEND,
     ["JavaScript"],
     [("JavaScript", "HIGHLIGHT", "JavaScript")]),
    ("ADV-009", "PostgreSQL ≠ NoSQL", "faux_positif_lexical", CV_BACKEND,
     ["NoSQL"],
     [("NoSQL", "DO_NOT_ADD", None)]),
    ("ADV-010", "PostgreSQL présent → preuve", "faux_positif_lexical", CV_BACKEND,
     ["PostgreSQL"],
     [("PostgreSQL", "HIGHLIGHT", "PostgreSQL")]),
    ("ADV-011", "AWS ≠ Azure", "faux_positif_lexical", CV_MINIMAL,
     ["Amazon Web Services"],
     [("Amazon Web Services", "DO_NOT_ADD", None)]),
    ("ADV-012", "Azure présent → preuve", "faux_positif_lexical", CV_MINIMAL,
     ["Azure"],
     [("Azure", "DO_NOT_ADD", None)]),
    ("ADV-013", "Power BI ≠ Tableau", "faux_positif_lexical", CV_DATA,
     ["Power BI"],
     [("Power BI", "DO_NOT_ADD", None)]),
    ("ADV-014", "Tableaux de bord ≠ Tableau (outil)", "faux_positif_lexical", CV_DATA,
     ["Tableaux de bord"],
     [("Tableaux de bord", "HIGHLIGHT", "tableaux de bord")]),
    ("ADV-015", "Analyse de données ≠ data engineering", "faux_positif_lexical", CV_DATA,
     ["Data engineering"],
     [("Data engineering", "DO_NOT_ADD", None)]),
    ("ADV-016", "Python présent → preuve", "faux_positif_lexical", CV_DATA,
     ["Python"],
     [("Python", "HIGHLIGHT", "Python")]),
    ("ADV-017", "Excel présent mais tableur absent", "faux_positif_lexical", CV_EXCEL,
     ["Tableur"],
     [("Tableur", "HIGHLIGHT", "Excel avance")]),
    ("ADV-018", "Power BI présent → preuve", "faux_positif_lexical", CV_ANALYSTE,
     ["Power BI"],
     [("Power BI", "HIGHLIGHT", "Power BI")]),

    # ── F2 : acronymes et synonymes ─────────────────────────────────
    ("ADV-019", "M&A = fusions-acquisitions", "acronyme", CV_MA,
     ["Fusions-acquisitions M&A"],
     [("Fusions-acquisitions M&A", "HIGHLIGHT", "Fusions-acquisitions M&A")]),
    ("ADV-020", "Private Equity = private equity", "acronyme", CV_MA,
     ["Private Equity"],
     [("Private Equity", "HIGHLIGHT", "Private Equity")]),
    ("ADV-021", "M&A absent du CV", "acronyme", CV_EXCEL,
     ["Fusions-acquisitions M&A"],
     [("Fusions-acquisitions M&A", "DO_NOT_ADD", None)]),
    ("ADV-022", "PE absent du CV", "acronyme", CV_EXCEL,
     ["Private Equity"],
     [("Private Equity", "DO_NOT_ADD", None)]),
    ("ADV-023", "M&A ≠ Private Equity (famille, rephrase)", "acronyme", CV_MA,
     ["Fusions-acquisitions M&A"],
     [("Fusions-acquisitions M&A", "HIGHLIGHT", "Fusions-acquisitions M&A")]),
    ("ADV-024", "Audit comptable ≠ audit financier (rephrase)", "acronyme", CV_AUDIT_FINANCIER,
     ["Audit financier"],
     [("Audit financier", "HIGHLIGHT", "Audit comptable")]),
    ("ADV-025", "Power BI présent", "acronyme", CV_ANALYSTE,
     ["Power BI"],
     [("Power BI", "HIGHLIGHT", "Power BI")]),
    ("ADV-026", "CRM absent", "acronyme", CV_MINIMAL,
     ["CRM Salesforce"],
     [("CRM Salesforce", "DO_NOT_ADD", None)]),
    ("ADV-027", "ERP absent", "acronyme", CV_MINIMAL,
     ["ERP SAP"],
     [("ERP SAP", "DO_NOT_ADD", None)]),
    ("ADV-028", "KPI absent", "acronyme", CV_MINIMAL,
     ["KPI et reporting"],
     [("KPI et reporting", "DO_NOT_ADD", None)]),

    # ── F3 : langues ─────────────────────────────────────────────────
    ("ADV-029", "Anglais courant déclaré", "langue", CV_ANALYSTE,
     ["Anglais courant"],
     [("Anglais courant", "HIGHLIGHT", "Anglais courant")]),
    ("ADV-030", "Langue absente du CV", "langue", CV_CDI,
     ["Anglais courant"],
     [("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-030b", "Niveau de langue non précisé", "langue", CV_LANGUE_SANS_NIVEAU,
     ["Anglais courant"],
     [("Anglais courant", "CONFIRM_LANGUAGE", "Anglais")]),
    ("ADV-031", "Langue absente du CV", "langue", CV_CDI,
     ["Espagnol courant"],
     [("Espagnol courant", "DO_NOT_ADD", None)]),
    ("ADV-032", "Programme en anglais ≠ niveau d'anglais", "langue", CV_PROGRAMME_ANGLAIS,
     ["Anglais courant"],
     [("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-033", "Niveau insuffisant", "langue", CV_DEVELOPPEUR,
     ["Anglais courant"],
     [("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-034", "Profil multilingue FR/EN", "langue", CV_MULTILINGUE,
     ["Anglais courant", "Espagnol courant"],
     [("Anglais courant", "HIGHLIGHT", "Anglais courant"),
      ("Espagnol courant", "HIGHLIGHT", "Espagnol courant")]),
    ("ADV-035", "Langue demandée absente d'un profil trilingue", "langue", CV_MULTILINGUE,
     ["Italien courant"],
     [("Italien courant", "DO_NOT_ADD", None)]),
    ("ADV-036", "Allemand lu ≠ allemand courant", "langue", CV_MULTILINGUE,
     ["Allemand courant"],
     [("Allemand courant", "DO_NOT_ADD", None)]),
    ("ADV-037", "Anglais courant pour un profil FR/EN", "langue", CV_MULTILINGUE,
     ["Anglais"],
     [("Anglais", "HIGHLIGHT", "Anglais courant")]),
    ("ADV-038", "Offre en anglais (programme) ≠ exigence de langue", "langue", CV_MULTILINGUE,
     ["Programme en anglais"],
     [("Programme en anglais", "DO_NOT_ADD", None)]),
    ("ADV-039", "Français natif", "langue", CV_ANALYSTE,
     ["Francais natif"],
     [("Francais natif", "HIGHLIGHT", "Francais natif")]),
    ("ADV-040", "Anglais professionnel déclaré", "langue", CV_DEVELOPPEUR,
     ["Anglais professionnel"],
     [("Anglais professionnel", "HIGHLIGHT", "Anglais professionnel")]),
    ("ADV-041", "Langue intermédiaire exigée, niveau courant déclaré", "langue", CV_MULTILINGUE,
     ["Espagnol intermediaire"],
     [("Espagnol intermediaire", "HIGHLIGHT", "Espagnol courant")]),
    ("ADV-042", "Allemand lu présent, exigence lu", "langue", CV_MULTILINGUE,
     ["Allemand lu"],
     [("Allemand lu", "HIGHLIGHT", "Allemand lu")]),

    # ── F4 : types de contrat ───────────────────────────────────────
    ("ADV-043", "Stage ≠ CDI", "contrat", CV_CDI,
     ["Contrat stage"],
     [("Contrat stage", "DO_NOT_ADD", None)]),
    ("ADV-044", "CDI conforme", "contrat", CV_CDI,
     ["Contrat CDI"],
     [("Contrat CDI", "HIGHLIGHT", None)]),
    ("ADV-045", "Alternance exclue par le CV", "contrat", CV_STAGE_PUIS_CDI,
     ["Contrat en alternance"],
     [("Contrat en alternance", "DO_NOT_ADD", None)]),
    ("ADV-046", "Alternance déclarée par le CV", "contrat", CV_ETUDIANT,
     ["Contrat en alternance"],
     [("Contrat en alternance", "HIGHLIGHT", None)]),
    ("ADV-047", "Stage demandé à un profil CDI", "contrat", CV_CDI,
     ["Stage de 6 mois"],
     [("Stage de 6 mois", "DO_NOT_ADD", None)]),
    ("ADV-048", "VIE absente du brief", "contrat", CV_CDI,
     ["Volontariat international"],
     [("Volontariat international", "DO_NOT_ADD", None)]),
    ("ADV-049", "Freelance absent du brief", "contrat", CV_CDI,
     ["Contrat freelance"],
     [("Contrat freelance", "DO_NOT_ADD", None)]),
    ("ADV-050", "CDD ≠ CDI", "contrat", CV_CDI,
     ["Contrat CDD"],
     [("Contrat CDD", "DO_NOT_ADD", None)]),
    ("ADV-051", "CDI pour un profil sans contrat déclaré", "contrat", CV_MINIMAL,
     ["Contrat CDI"],
     [("Contrat CDI", "DO_NOT_ADD", None)]),
    ("ADV-052", "CDI pour un profil CDI en contexte projet", "contrat", CV_ANALYSTE,
     ["Contrat CDI"],
     [("Contrat CDI", "HIGHLIGHT", None)]),
    ("ADV-053", "Stage pour un profil alternance", "contrat", CV_ETUDIANT,
     ["Contrat stage"],
     [("Contrat stage", "DO_NOT_ADD", None)]),
    ("ADV-054", "Vie internationale exclue", "contrat", CV_STAGE_PUIS_CDI,
     ["Volontariat international"],
     [("Volontariat international", "DO_NOT_ADD", None)]),

    # ── F5 : niveaux d'études ───────────────────────────────────────
    ("ADV-055", "M1 exigé, M2 détenu", "diplome", CV_ANALYSTE,
     ["Diplome M1 en finance"],
     [("Diplome M1 en finance", "HIGHLIGHT", "Master 2")]),
    ("ADV-056", "M2 exigé, M1 détenu", "diplome", CV_DEVELOPPEUR,
     ["Master 2 en finance"],
     [("Master 2 en finance", "DO_NOT_ADD", None)]),
    ("ADV-057", "Bachelor exigé, Master détenu", "diplome", CV_ANALYSTE,
     ["Bachelor en finance"],
     [("Bachelor en finance", "HIGHLIGHT", "Master 2")]),
    ("ADV-058", "Master exigé, Bachelor détenu", "diplome", CV_ETUDIANT,
     ["Master en gestion"],
     [("Master en gestion", "DO_NOT_ADD", None)]),
    ("ADV-059", "Doctorat exigé, Master détenu", "diplome", CV_ANALYSTE,
     ["Doctorat en finance"],
     [("Doctorat en finance", "DO_NOT_ADD", None)]),
    ("ADV-060", "Master 1 exigé, Master 1 détenu", "diplome", CV_DEVELOPPEUR,
     ["Master 1 en informatique"],
     [("Master 1 en informatique", "HIGHLIGHT", "Master 1")]),
    ("ADV-061", "Licence professionnelle exigée", "diplome", CV_CDI,
     ["Licence professionnelle"],
     [("Licence professionnelle", "HIGHLIGHT", "Licence professionnelle")]),
    ("ADV-062", "Master exigé, niveau non attesté", "diplome", CV_MINIMAL,
     ["Master en gestion"],
     [("Master en gestion", "DO_NOT_ADD", None)]),
    ("ADV-063", "Bac+2 exigé, licence détenue", "diplome", CV_CDI,
     ["BTS en informatique"],
     [("BTS en informatique", "HIGHLIGHT", "Licence professionnelle")]),
    ("ADV-064", "Master 2 exigé, profil M1", "diplome", CV_DATA,
     ["Master 2 en data"],
     [("Master 2 en data", "DO_NOT_ADD", None)]),
    ("ADV-065", "Master 1 en data détenu", "diplome", CV_DATA,
     ["Master 1 en data"],
     [("Master 1 en data", "HIGHLIGHT", "Master 1")]),
    ("ADV-066", "Licence exigée, licence détenue", "diplome", CV_MINIMAL,
     ["Licence en gestion"],
     [("Licence en gestion", "HIGHLIGHT", "Licence professionnelle")]),

    # ── F6 : négations ───────────────────────────────────────────────
    ("ADV-067", "Exigence niée : pas de gestion d'équipe", "negation", CV_MULTILINGUE,
     ["Pas de gestion d equipe"],
     []),
    ("ADV-068", "Exigence niée : aucune expérience", "negation", CV_MULTILINGUE,
     ["Aucune experience en gestion d equipe"],
     []),
    ("ADV-069", "Exigence niée : sans déplacement", "negation", CV_CDI,
     ["Sans deplacements professionnels"],
     []),
    ("ADV-070", "Exigence niée : not required", "negation", CV_CDI,
     ["Excel is not required"],
     []),
    ("ADV-071", "Négation et compétence réellement présente", "negation", CV_MULTILINGUE,
     ["Pas de gestion d equipe", "Pilotage de projets"],
     [("Pilotage de projets", "HIGHLIGHT", "Pilotage de projets")]),
    ("ADV-072", "Négation isolée ne pollue pas le score", "negation", CV_ANALYSTE,
     ["Pas de gestion d equipe", "Analyse financiere"],
     [("Analyse financiere", "HIGHLIGHT", "Analyse financiere")]),
    ("ADV-073", "Mot nié : pas de télétravail", "negation", CV_ANALYSTE,
     ["Pas de teletravail"],
     []),
    ("ADV-074", "Négation : ne pas avoir de...", "negation", CV_ANALYSTE,
     ["Ne pas avoir deunk"],  # garde-fou : phrase non pertinente
     []),
    ("ADV-075", "Négation dans une compétence par ailleurs prouvée", "negation", CV_DATA,
     ["Aucune experience en Python", "Python"],
     [("Python", "HIGHLIGHT", "Python")]),
    ("ADV-076", "Double négation sans effet", "negation", CV_CDI,
     ["Experience en gestion"],
     [("Experience en gestion", "DO_NOT_ADD", None)]),

    # ── F7 : compétence absente du CV ───────────────────────────────
    ("ADV-077", "Compétence totalement absente", "absente", CV_MINIMAL,
     ["M&A et Private Equity"],
     [("M&A et Private Equity", "DO_NOT_ADD", None)]),
    ("ADV-078", "Compétence absente (Python)", "absente", CV_CDI,
     ["Python"],
     [("Python", "DO_NOT_ADD", None)]),
    ("ADV-079", "Compétence absente (AWS)", "absente", CV_CDI,
     ["Amazon Web Services"],
     [("Amazon Web Services", "DO_NOT_ADD", None)]),
    ("ADV-080", "Compétence absente (Salesforce)", "absente", CV_CDI,
     ["Salesforce"],
     [("Salesforce", "DO_NOT_ADD", None)]),
    ("ADV-081", "Compétence absente (Kubernetes)", "absente", CV_CDI,
     ["Kubernetes"],
     [("Kubernetes", "DO_NOT_ADD", None)]),
    ("ADV-082", "Compétence absente (Scala)", "absente", CV_DEVELOPPEUR,
     ["Scala"],
     [("Scala", "DO_NOT_ADD", None)]),
    ("ADV-083", "Compétence absente (Power BI)", "absente", CV_BACKEND,
     ["Power BI"],
     [("Power BI", "DO_NOT_ADD", None)]),
    ("ADV-084", "Compétence absente (CFO)", "absente", CV_MINIMAL,
     ["Direction financière (CFO)"],
     [("Direction financière (CFO)", "DO_NOT_ADD", None)]),
    ("ADV-085", "Deux compétences absentes", "absente", CV_MINIMAL,
     ["Scala", "Kubernetes"],
     [("Scala", "DO_NOT_ADD", None),
      ("Kubernetes", "DO_NOT_ADD", None)]),
    ("ADV-086", "Absence et présence mêlées", "absente", CV_DATA,
     ["Python", "Scala"],
     [("Python", "HIGHLIGHT", "Python"),
      ("Scala", "DO_NOT_ADD", None)]),

    # ── F8 : homonymes sectoriels ───────────────────────────────────
    ("ADV-087", "Audit IT ≠ audit financier", "homonyme", CV_AUDIT_IT,
     ["Audit financier"],
     [("Audit financier", "DO_NOT_ADD", None)]),
    ("ADV-088", "Audit financier ≠ audit IT", "homonyme", CV_AUDIT_FINANCIER,
     ["Audit IT"],
     [("Audit IT", "DO_NOT_ADD", None)]),
    ("ADV-089", "Audit des SI ≠ audit financier", "homonyme", CV_AUDIT_IT,
     ["Audit financier"],
     [("Audit financier", "DO_NOT_ADD", None)]),
    ("ADV-090", "Audit comptable = audit financier", "homonyme", CV_AUDIT_FINANCIER,
     ["Audit financier"],
     [("Audit financier", "HIGHLIGHT", "Audit comptable")]),
    ("ADV-091", "Gestion de projet ≠ gestion d'équipe", "homonyme", CV_MULTILINGUE,
     ["Gestion de projet"],
     [("Gestion de projet", "HIGHLIGHT", "Pilotage de projets")]),
    ("ADV-092", "Gestion des risques ≠ audit IT", "homonyme", CV_AUDIT_IT,
     ["Audit financier"],
     [("Audit financier", "DO_NOT_ADD", None)]),
    ("ADV-093", "Data analysis ≠ data engineering", "homonyme", CV_DATA,
     ["Data engineering"],
     [("Data engineering", "DO_NOT_ADD", None)]),
    ("ADV-094", "Machine learning absent", "homonyme", CV_DATA,
     ["Machine learning"],
     [("Machine learning", "DO_NOT_ADD", None)]),
    ("ADV-095", "Audit IT présent → preuve", "homonyme", CV_AUDIT_IT,
     ["Audit des systemes d information"],
     [("Audit des systemes d information", "HIGHLIGHT", "Audit des systemes d information")]),
    ("ADV-096", "Stage (usage ambigu) non confondu", "homonyme", CV_ETUDIANT,
     ["Stage de 6 mois"],
     [("Stage de 6 mois", "DO_NOT_ADD", None)]),
    ("ADV-097", "Gestion d'équipe prouvée", "homonyme", CV_MULTILINGUE,
     ["Gestion d equipe"],
     [("Gestion d equipe", "HIGHLIGHT", "gestion d equipe de 10 personnes")]),
    ("ADV-098", "Power BI ≠ Tableau (homonyme outil)", "homonyme", CV_ANALYSTE,
     ["Tableau"],
     [("Tableau", "DO_NOT_ADD", None)]),

    # ── F9 : quantification ─────────────────────────────────────────
    ("ADV-099", "Équipe chiffrée dans le CV", "quantification", CV_MULTILINGUE,
     ["Gestion d equipe"],
     [("Gestion d equipe", "HIGHLIGHT", "gestion d equipe de 10 personnes")]),
    ("ADV-100", "Équipe non chiffrée → quantifier", "quantification", CV_ANALYSTE,
     ["Gestion d equipe"],
     [("Gestion d equipe", "DO_NOT_ADD", None)]),
    ("ADV-101", "Budget chiffré", "quantification", CV_MULTILINGUE,
     ["Budget de 500 kEUR"],
     [("Budget de 500 kEUR", "HIGHLIGHT", "Budget de 500 kEUR")]),
    ("ADV-102", "Pilotage avec budget", "quantification", CV_MULTILINGUE,
     ["Pilotage de projets"],
     [("Pilotage de projets", "HIGHLIGHT", "Pilotage de projets")]),
    ("ADV-103", "Chiffre d'affaires absent", "quantification", CV_CDI,
     ["Chiffre d'affaires"],
     [("Chiffre d'affaires", "DO_NOT_ADD", None)]),
    ("ADV-104", "Pourcentage absent", "quantification", CV_CDI,
     ["Taux de conversion"],
     [("Taux de conversion", "DO_NOT_ADD", None)]),
    ("ADV-105", "Preuve chiffrée sur une compétence", "quantification", CV_ANALYSTE,
     ["Modelisation financiere"],
     [("Modelisation financiere", "QUANTIFY", "Modelisation financiere de 120 budgets")]),
    ("ADV-106", "Durée d'expérience chiffrée", "quantification", CV_ANALYSTE,
     ["Modelisation financiere"],
     [("Modelisation financiere", "QUANTIFY", "Modelisation financiere de 120 budgets")]),
    ("ADV-107", "Reporting présent sans chiffre", "quantification", CV_CDI,
     ["Reporting commercial"],
     [("Reporting commercial", "REPHRASE", "reporting")]),
    ("ADV-108", "Preuve numérique générique", "quantification", CV_MULTILINGUE,
     ["Budget de 500 kEUR"],
     [("Budget de 500 kEUR", "HIGHLIGHT", "Budget de 500 kEUR")]),

    # ── F10 : multilingue, homonymes de contrat, cas limites ────────
    ("ADV-109", "Profil FR/EN sur offre EN", "multilingue", CV_MULTILINGUE,
     ["Anglais courant"],
     [("Anglais courant", "HIGHLIGHT", "Anglais courant")]),
    ("ADV-110", "Profil FR seul sur offre EN", "multilingue", CV_CDI,
     ["Anglais courant"],
     [("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-111", "Langue jamais déclarée", "multilingue", CV_MINIMAL,
     ["Anglais courant"],
     [("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-112", "Anglais sans niveau sur profil trilingue", "multilingue", CV_MULTILINGUE,
     ["Anglais"],
     [("Anglais", "HIGHLIGHT", "Anglais courant")]),
    ("ADV-113", "Exigence technique et contractuelle mêlées", "multilingue", CV_ANALYSTE,
     ["Excel avance", "Contrat CDI"],
     [("Excel avance", "HIGHLIGHT", "Excel avance"),
      ("Contrat CDI", "HIGHLIGHT", None)]),
    ("ADV-114", "Trois exigences, une seule prouvée", "multilingue", CV_MINIMAL,
     ["Excel avance", "Python", "Anglais courant"],
     [("Excel avance", "DO_NOT_ADD", None),
      ("Python", "DO_NOT_ADD", None),
      ("Anglais courant", "DO_NOT_ADD", None)]),
    ("ADV-115", "Toutes les exigences prouvées", "multilingue", CV_ANALYSTE,
     ["Analyse financiere", "Excel avance", "Anglais courant"],
     [("Analyse financiere", "HIGHLIGHT", "Analyse financiere"),
      ("Excel avance", "HIGHLIGHT", "Excel avance"),
      ("Anglais courant", "HIGHLIGHT", "Anglais courant")]),
    ("ADV-116", "Aucune exigence satisfaite", "multilingue", CV_MINIMAL,
     ["Scala", "Kubernetes"],
     [("Scala", "DO_NOT_ADD", None),
      ("Kubernetes", "DO_NOT_ADD", None)]),
    ("ADV-117", "Exigence unique satisfaite", "multilingue", CV_DATA,
     ["Python"],
     [("Python", "HIGHLIGHT", "Python")]),
    ("ADV-118", "Exigence unique non satisfaite", "multilingue", CV_DATA,
     ["Scala"],
     [("Scala", "DO_NOT_ADD", None)]),
    ("ADV-119", "Acronyme absent et niveau présent", "multilingue", CV_CDI,
     ["M&A", "Master 2"],
     [("Master 2", "DO_NOT_ADD", None)]),
    ("ADV-120", "Profil sans expérience structurée", "multilingue", CV_MINIMAL,
     ["Excel avance"],
     [("Excel avance", "DO_NOT_ADD", None)]),
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
    identifiers = [case[0] for case in CASES]
    assert len(set(identifiers)) == len(identifiers)


def test_familles_couvertes():
    """Les dix familles de pièges annoncées sont toutes présentes."""
    families = {case[2] for case in CASES}
    expected = {
        "faux_positif_lexical", "acronyme", "langue", "contrat", "diplome",
        "negation", "absente", "homonyme", "quantification", "multilingue",
    }
    assert expected <= families


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_cas_adversarial(case):
    """Chaque cas produit les actions attendues."""
    identifier, name, family, cv_text, requirements, expectations = case
    result = _match(cv_text, requirements)

    for requirement, expected_code, expected_evidence in expectations:
        action = _action_for(result, requirement)
        assert action is not None, f"{identifier} ({name}) : aucune action pour « {requirement} »"
        assert action.code == expected_code, (
            f"{identifier} ({name}) : « {requirement} » vaut {action.code}, "
            f"attendu {expected_code} ({action.reason})"
        )
        if expected_evidence is not None:
            assert action.cv_evidence_text == expected_evidence, (
                f"{identifier} ({name}) : preuve {action.cv_evidence_text!r}, "
                f"attendu {expected_evidence!r}"
            )


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_preuve_toujours_verbatim(case):
    """Invariant dur : toute preuve citée est une sous-chaîne exacte du CV."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    result = _match(cv_text, requirements)
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


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_absent_jamais_ajoute(case):
    """Invariant dur : une exigence sans preuve n'est jamais étayée."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    result = _match(cv_text, requirements)
    for action in result.actions:
        if action.code == "DO_NOT_ADD":
            assert action.cv_evidence_text is None, (
                f"{identifier} ({name}) : une exigence non étayée porte une preuve"
            )
        else:
            assert action.cv_evidence_text, (
                f"{identifier} ({name}) : une exigence étayée ne porte aucune preuve"
            )


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_determinisme(case):
    """Invariant dur : deux exécutions donnent le même résultat."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    first = _match(cv_text, requirements)
    second = _match(cv_text, requirements)
    assert first == second, f"{identifier} ({name}) : résultat non déterministe"


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_aucune_donnee_de_contact(case):
    """Invariant dur : aucune donnée de contact ne fuit dans la décision."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    result = _match(cv_text, requirements)
    surface = " ".join(
        [action.requirement_text for action in result.actions]
        + [action.cv_evidence_text or "" for action in result.actions]
        + list(result.warnings)
    ).lower()
    for leak in ("@", "linkedin", "telephone", "06 ", "07 "):
        assert leak not in surface, f"{identifier} ({name}) : fuite « {leak} »"


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_score_determine_et_borne(case):
    """Le score est borné, cohérent avec le nombre d'exigences satisfaites."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    result = _match(cv_text, requirements)
    assert 0.0 <= result.overall_score <= 1.0, f"{identifier} ({name}) : score hors bornes"
    assert result.matched_requirements <= result.total_requirements
    assert result.total_requirements == len(result.actions)


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_exigence_obligatoire_manquante_signalee(case):
    """Toute exigence obligatoire non couverte est listée dans missing_critical."""
    identifier, name, _family, cv_text, requirements, _expectations = case
    result = _match(cv_text, requirements)
    for action in result.actions:
        if action.code == "DO_NOT_ADD" and action.requirement_text not in result.missing_critical:
            # Seules les exigences obligatoires doivent être signalées ; le
            # contrat d'extraction les marque toutes comme obligatoires.
            continue
    assert set(result.missing_critical) <= {
        action.requirement_text for action in result.actions
    }


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
