"""Deterministic, local-first finance interview coach.

The engine deliberately does not call an LLM.  It provides a reliable text
practice loop when a provider is unavailable: a bounded question bank,
transparent keyword/structure feedback, adaptive difficulty, and a reference
answer.  Its scores describe a response against the displayed exercise only;
they are never a prediction of recruiting success.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from .models import clean_text, normalized_text
from workspace_core import UserFacingError


INTERVIEW_MODES = {
    "technical": "Technical Interview",
    "behavioral": "Behavioral / Fit",
    "case": "Case Interview",
    "company": "Company Specific",
}
DIFFICULTIES = ("beginner", "intermediate", "advanced", "investment_banking", "private_equity", "highly_competitive")
LANGUAGES = ("fr", "en", "it", "de")
_DIFFICULTY_RANK = {value: index for index, value in enumerate(DIFFICULTIES)}


# The question bank deliberately stores its canonical finance concepts in one
# place.  The copy below localises the *coaching experience* without changing
# the deterministic score formula or asking a model to translate anything at
# run time.  This is important for a local-first tool: a German or Italian
# answer must not be treated as less structured simply because it does not use
# English transition words.
_COACH_COPY: dict[str, dict[str, Any]] = {
    "fr": {
        "job_context": "Contexte d’offre fourni",
        "answer_too_short": "Écris une réponse d’au moins quelques mots avant de demander un retour.",
        "strength_coverage": "{count} axe(s) de référence apparaissent dans ta réponse.",
        "strength_length": "La réponse est assez développée pour être structurée et vérifiable.",
        "strength_structure": "Des marqueurs de raisonnement rendent la progression plus lisible.",
        "gap_length": "Développe avec une structure explicite, des mécanismes et une conclusion courte.",
        "gap_missing": "Points de référence à travailler : {points}.",
        "gap_structure": "Annonce un fil directeur (par exemple : point de départ, mécanisme, conclusion) pour gagner en clarté.",
        "coaching_low": "Réponds une seconde fois en traitant un seul point manquant à la fois ; ne mémorise pas une formule sans pouvoir expliquer le mécanisme.",
        "coaching_high": "Pour renforcer la réponse, ajoute une hypothèse, un contrôle de cohérence ou un risque précis, puis termine par une conclusion nette.",
        "disclaimer": "Retour déterministe sur cette réponse et cet exercice ; il ne mesure pas une probabilité de recrutement.",
        "progress_disclaimer": "La progression synthétise des exercices locaux ; elle ne prédit pas un résultat de recrutement.",
        "score_labels": {
            "technical": "Couverture technique / pertinence",
            "precision": "Couverture des points clés",
            "structure": "Structure",
            "clarity": "Clarté",
            "relevance": "Pertinence",
            "overall": "Score de l’exercice",
        },
        "progress_labels": {
            "answered_count": "Réponses travaillées",
            "average_score": "Moyenne des exercices",
            "topics_practised": "Sujets travaillés",
            "revision_priorities": "Priorités de révision",
        },
    },
    "en": {
        "job_context": "Provided job context",
        "answer_too_short": "Write at least a few words before requesting feedback.",
        "strength_coverage": "Your answer covers {count} reference area(s).",
        "strength_length": "The answer is developed enough to assess its structure and reasoning.",
        "strength_structure": "Reasoning markers make the progression easier to follow.",
        "gap_length": "Develop the answer with an explicit structure, mechanisms, and a short conclusion.",
        "gap_missing": "Reference areas to practise: {points}.",
        "gap_structure": "Signpost a clear line of reasoning (for example: starting point, mechanism, conclusion) to improve clarity.",
        "coaching_low": "Try the answer again by addressing one missing point at a time; do not memorise a formula unless you can explain the mechanism.",
        "coaching_high": "To strengthen the answer, add a specific assumption, sanity check, or risk, then finish with a clear conclusion.",
        "disclaimer": "This is deterministic feedback on this response and exercise only; it does not measure your likelihood of being recruited.",
        "progress_disclaimer": "This progress summary aggregates local practice exercises; it does not predict a recruiting outcome.",
        "score_labels": {
            "technical": "Technical coverage / relevance",
            "precision": "Key-point coverage",
            "structure": "Structure",
            "clarity": "Clarity",
            "relevance": "Relevance",
            "overall": "Exercise score",
        },
        "progress_labels": {
            "answered_count": "Answers practised",
            "average_score": "Exercise average",
            "topics_practised": "Topics practised",
            "revision_priorities": "Revision priorities",
        },
    },
    "it": {
        "job_context": "Contesto dell’offerta fornito",
        "answer_too_short": "Scrivi almeno alcune parole prima di chiedere un feedback.",
        "strength_coverage": "La risposta copre {count} area/e di riferimento.",
        "strength_length": "La risposta è abbastanza sviluppata da poter valutarne struttura e ragionamento.",
        "strength_structure": "I segnali di ragionamento rendono più chiaro il filo logico.",
        "gap_length": "Sviluppa la risposta con una struttura esplicita, i meccanismi e una breve conclusione.",
        "gap_missing": "Aree di riferimento da esercitare: {points}.",
        "gap_structure": "Anticipa il filo logico (per esempio: punto di partenza, meccanismo, conclusione) per aumentare la chiarezza.",
        "coaching_low": "Prova a rispondere di nuovo affrontando un solo punto mancante alla volta; non memorizzare una formula se non sai spiegarne il meccanismo.",
        "coaching_high": "Per rendere la risposta più solida, aggiungi un’ipotesi, un controllo di coerenza o un rischio specifico e chiudi con una conclusione chiara.",
        "disclaimer": "Questo feedback è deterministico e riguarda soltanto questa risposta e questo esercizio; non misura la probabilità di ottenere il ruolo.",
        "progress_disclaimer": "Il riepilogo aggrega esercizi locali; non prevede l’esito di una selezione.",
        "score_labels": {
            "technical": "Copertura tecnica / pertinenza",
            "precision": "Copertura dei punti chiave",
            "structure": "Struttura",
            "clarity": "Chiarezza",
            "relevance": "Pertinenza",
            "overall": "Punteggio dell’esercizio",
        },
        "progress_labels": {
            "answered_count": "Risposte esercitate",
            "average_score": "Media degli esercizi",
            "topics_practised": "Argomenti esercitati",
            "revision_priorities": "Priorità di ripasso",
        },
    },
    "de": {
        "job_context": "Bereitgestellter Stellenkontext",
        "answer_too_short": "Schreiben Sie mindestens einige Wörter, bevor Sie Feedback anfordern.",
        "strength_coverage": "Die Antwort deckt {count} Referenzaspekt(e) ab.",
        "strength_length": "Die Antwort ist ausreichend ausgearbeitet, um Struktur und Argumentation zu beurteilen.",
        "strength_structure": "Strukturwörter machen den Gedankengang leichter nachvollziehbar.",
        "gap_length": "Baue die Antwort mit einer klaren Struktur, Mechanismen und einem kurzen Fazit aus.",
        "gap_missing": "Zu übende Referenzaspekte: {points}.",
        "gap_structure": "Kündige einen klaren Gedankengang an (zum Beispiel Ausgangspunkt, Mechanismus, Fazit), um die Klarheit zu erhöhen.",
        "coaching_low": "Beantworte die Frage noch einmal und bearbeite jeweils nur einen fehlenden Punkt; lerne keine Formel auswendig, ohne den Mechanismus erklären zu können.",
        "coaching_high": "Ergänze zur Stärkung der Antwort eine konkrete Annahme, Plausibilitätsprüfung oder ein Risiko und schließe mit einem klaren Fazit.",
        "disclaimer": "Dieses Feedback ist deterministisch und bezieht sich nur auf diese Antwort und Übung; es misst nicht Ihre Wahrscheinlichkeit, eingestellt zu werden.",
        "progress_disclaimer": "Diese Zusammenfassung bündelt lokale Übungsaufgaben; sie sagt kein Recruiting-Ergebnis voraus.",
        "score_labels": {
            "technical": "Technische Abdeckung / Relevanz",
            "precision": "Abdeckung der Kernpunkte",
            "structure": "Struktur",
            "clarity": "Klarheit",
            "relevance": "Relevanz",
            "overall": "Übungspunktzahl",
        },
        "progress_labels": {
            "answered_count": "Geübte Antworten",
            "average_score": "Übungsdurchschnitt",
            "topics_practised": "Geübte Themen",
            "revision_priorities": "Wiederholungsprioritäten",
        },
    },
}


# ``topic`` remains the canonical, stable identifier displayed in existing
# saved sessions.  ``topic_label`` is added alongside it for clients that want
# to render the selected language without breaking older records or API users.
_TOPIC_LABELS: dict[str, dict[str, str]] = {
    "technical_dcf_basics": {"fr": "DCF", "en": "DCF", "it": "DCF", "de": "DCF"},
    "technical_three_statements": {
        "fr": "Trois états financiers",
        "en": "Three financial statements",
        "it": "Tre prospetti finanziari",
        "de": "Drei Finanzberichte",
    },
    "technical_ev_equity_value": {
        "fr": "Enterprise Value et Equity Value",
        "en": "Enterprise value and equity value",
        "it": "Enterprise Value ed Equity Value",
        "de": "Enterprise Value und Equity Value",
    },
    "technical_lbo_returns": {"fr": "LBO et private equity", "en": "LBO and private equity", "it": "LBO e private equity", "de": "LBO und Private Equity"},
    "technical_market_view": {"fr": "Marchés", "en": "Markets", "it": "Mercati", "de": "Märkte"},
    "behavioral_tell_me": {"fr": "Présentez-vous", "en": "Tell me about yourself", "it": "Presentazione", "de": "Stellen Sie sich vor"},
    "behavioral_why_role": {"fr": "Motivation", "en": "Motivation", "it": "Motivazione", "de": "Motivation"},
    "case_investment_screen": {"fr": "Cas d’investissement", "en": "Investment case", "it": "Caso di investimento", "de": "Investment Case"},
    "company_specific_fit": {"fr": "Adéquation au poste", "en": "Company-specific fit", "it": "Compatibilità con il ruolo", "de": "Passung zur Stelle"},
    "company_specific_technical": {
        "fr": "Préparation technique au poste",
        "en": "Role-specific technical preparation",
        "it": "Preparazione tecnica al ruolo",
        "de": "Rollenspezifische technische Vorbereitung",
    },
}


# The original question groups cover French and English.  These aliases make
# the same transparent coverage test fairer when a candidate answers in
# Italian or German.  They are added to—not substituted for—the original
# terms, so mixed-language finance answers remain recognised.
_KEYWORD_ALIASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "technical_dcf_basics": (
        ("flussi di cassa", "flusso di cassa", "freier cashflow", "freier cash flow", "cashflows"),
        ("scont", "abzins", "diskont"),
        ("valeur terminale", "valore terminale", "perpetuita", "rendita perpetua", "ewige rente", "terminalwert"),
        ("valore d impresa", "valore del capitale proprio", "debito netto", "unternehmenswert", "eigenkapitalwert", "nettoverschuldung"),
    ),
    "technical_three_statements": (
        ("conto economico", "utile netto", "gewinn und verlustrechnung", "jahresueberschuss"),
        ("imposte", "aliquota", "steuersatz", "steueraufwand"),
        ("rendiconto finanziario", "flussrechnung", "cashflow rechnung"),
        ("stato patrimoniale", "bilanz", "immobilizzazioni", "anlagevermogen", "eigenkapital"),
    ),
    "technical_ev_equity_value": (
        ("azionista", "azionisti", "aktionar", "aktionare", "eigenkapitalgeber"),
        ("debito", "indebitamento", "nettoverschuldung", "verbindlichkeiten"),
        ("operativo", "operativa", "zinsergebnis", "betrieblich", "zinsen"),
        ("struttura del capitale", "kapitalstruktur"),
    ),
    "technical_lbo_returns": (
        ("crescita", "margine", "margen", "wachstum"),
        ("rimborso del debito", "riduzione del debito", "schuldentilgung", "cashflow"),
        ("multiplo di uscita", "exit multiple", "exit multiple", "exit multiplikator"),
        ("leva", "leverage", "verschuldung", "kreditbedingungen", "zins"),
    ),
    "technical_market_view": (
        ("inflazione", "crescita", "occupazione", "inflation", "wachstum", "arbeitsmarkt"),
        ("tasso di sconto", "rendimenti", "risikopramie", "diskontsatz", "rendite", "risikoprämie"),
        ("azioni", "obbligazioni", "credito", "valuta", "aktien", "anleihen", "wahrung", "währung"),
        ("rischio", "alternativa", "scenario", "invalid", "risiko", "szenario", "widerleg"),
    ),
    "behavioral_tell_me": (
        ("formazione", "universita", "università", "studium", "hochschule"),
        ("esperienza", "progetto", "tirocinio", "erfahrung", "praktikum", "projekt"),
        ("finanza", "valutazione", "analisi", "finanz", "bewertung", "analyse"),
        ("ruolo", "posizione", "perche", "warum", "stelle", "position"),
    ),
    "behavioral_why_role": (
        ("esperienza", "progetto", "corso", "tirocinio", "erfahrung", "praktikum", "studium"),
        ("analisi", "valutazione", "cliente", "investimento", "analyse", "bewertung", "kund", "investition"),
        ("competenze", "imparare", "sviluppare", "fahigkeit", "lernen", "entwickeln"),
        ("ruolo", "lavoro", "settore", "stelle", "beruf", "job"),
    ),
    "case_investment_screen": (
        ("mercato", "crescita", "concorrenza", "markt", "wachstum", "wettbewerb"),
        ("cliente", "margine", "cassa", "kunden", "marge", "cashflow"),
        ("valutazione", "multiplo", "prezzo", "bewertung", "multiplikator", "preis"),
        ("rischio", "due diligence", "scenario", "risiko", "szenario"),
    ),
    "company_specific_fit": (
        ("offerta", "ruolo", "posizione", "stelle", "stellenanzeige"),
        ("requisito", "competenza", "esperienza", "anforderung", "fahigkeit", "erfahrung"),
        ("ufficiale", "verificato", "fonte", "offiziell", "gepruft", "quelle"),
        ("domanda", "chiedere", "frage", "fragen"),
    ),
    "company_specific_technical": (
        ("requisito", "offerta", "descrizione", "anforderung", "stellenanzeige", "beschreibung"),
        ("esempio", "esercizio", "pratica", "beispiel", "ubung", "übung"),
        ("ipotesi", "limite", "einschrankung", "einschränkung", "annahme", "grenze"),
        ("profilo", "imparare", "prova", "profil", "lernen", "beleg"),
    ),
}


_MISSING_FOCUS: dict[str, dict[str, tuple[str, ...]]] = {
    "technical_dcf_basics": {
        "fr": ("flux de trésorerie disponible", "actualisation au WACC", "valeur terminale", "passage EV vers Equity Value"),
        "en": ("free cash flow", "WACC discounting", "terminal value", "EV-to-equity bridge"),
        "it": ("flussi di cassa disponibili", "attualizzazione al WACC", "valore terminale", "ponte EV–Equity Value"),
        "de": ("Free Cashflow", "Abzinsung mit WACC", "Terminal Value", "Überleitung von EV zu Equity Value"),
    },
    "technical_three_statements": {
        "fr": ("compte de résultat", "effet fiscal", "tableau de flux de trésorerie", "bilan"),
        "en": ("income statement", "tax effect", "cash flow statement", "balance sheet"),
        "it": ("conto economico", "effetto fiscale", "rendiconto finanziario", "stato patrimoniale"),
        "de": ("GuV", "Steuereffekt", "Cashflow-Rechnung", "Bilanz"),
    },
    "technical_ev_equity_value": {
        "fr": ("détenteurs d’Equity", "dette nette", "métrique opérationnelle", "neutralité de structure du capital"),
        "en": ("equity holders", "net debt", "operating metric", "capital-structure neutrality"),
        "it": ("azionisti", "debito netto", "metrica operativa", "neutralità della struttura del capitale"),
        "de": ("Eigenkapitalgeber", "Nettoverschuldung", "operative Kennzahl", "Kapitalstruktur-Neutralität"),
    },
    "technical_lbo_returns": {
        "fr": ("croissance et marge", "désendettement", "multiple de sortie", "levier et risque de dette"),
        "en": ("growth and margin", "debt paydown", "exit multiple", "leverage and debt risk"),
        "it": ("crescita e margine", "rimborso del debito", "multiplo di uscita", "leva e rischio del debito"),
        "de": ("Wachstum und Marge", "Schuldentilgung", "Exit-Multiple", "Leverage- und Schuldenrisiko"),
    },
    "technical_market_view": {
        "fr": ("indicateur macroéconomique", "canal de transmission", "classes d’actifs", "scénario d’invalidation"),
        "en": ("macroeconomic indicator", "transmission channel", "asset classes", "disconfirming scenario"),
        "it": ("indicatore macroeconomico", "canale di trasmissione", "asset class", "scenario di invalidazione"),
        "de": ("makroökonomischer Indikator", "Übertragungskanal", "Anlageklassen", "Widerlegungsszenario"),
    },
    "behavioral_tell_me": {
        "fr": ("formation actuelle", "expérience factuelle", "lien avec la finance", "cohérence avec le poste"),
        "en": ("current education", "factual experience", "finance link", "fit with the role"),
        "it": ("formazione attuale", "esperienza concreta", "legame con la finanza", "coerenza con il ruolo"),
        "de": ("aktuelle Ausbildung", "faktische Erfahrung", "Finanzbezug", "Bezug zur Stelle"),
    },
    "behavioral_why_role": {
        "fr": ("déclencheur factuel", "compétence à développer", "apport du métier", "réalisme sur le rôle"),
        "en": ("factual trigger", "skill to develop", "substance of the work", "realism about the role"),
        "it": ("motivatore concreto", "competenza da sviluppare", "contenuto del lavoro", "realismo sul ruolo"),
        "de": ("konkreter Auslöser", "zu entwickelnde Fähigkeit", "Inhalt der Arbeit", "Realismus zur Rolle"),
    },
    "case_investment_screen": {
        "fr": ("marché et concurrence", "qualité de l’activité", "valorisation", "risque et due diligence"),
        "en": ("market and competition", "business quality", "valuation", "risk and diligence"),
        "it": ("mercato e concorrenza", "qualità del business", "valutazione", "rischio e due diligence"),
        "de": ("Markt und Wettbewerb", "Unternehmensqualität", "Bewertung", "Risiko und Due Diligence"),
    },
    "company_specific_fit": {
        "fr": ("offre et poste", "exigences du rôle", "sources vérifiées", "question pour l’intervieweur"),
        "en": ("job and role", "role requirements", "verified sources", "question for the interviewer"),
        "it": ("offerta e ruolo", "requisiti del ruolo", "fonti verificate", "domanda per l’intervistatore"),
        "de": ("Stelle und Rolle", "Rollenanforderungen", "geprüfte Quellen", "Frage an die interviewende Person"),
    },
    "company_specific_technical": {
        "fr": ("exigence de l’offre", "exemple pratique", "hypothèses et limites", "preuve ou plan d’apprentissage"),
        "en": ("job requirement", "worked example", "assumptions and limitations", "evidence or learning plan"),
        "it": ("requisito dell’offerta", "esempio pratico", "ipotesi e limiti", "prova o piano di apprendimento"),
        "de": ("Stellenanforderung", "Praxisbeispiel", "Annahmen und Grenzen", "Beleg oder Lernplan"),
    },
}


_STRUCTURE_MARKERS: dict[str, tuple[str, ...]] = {
    "fr": ("d abord", "premier", "premiere", "ensuite", "puis", "enfin", "parce que", "donc", "cependant", "ainsi"),
    "en": ("first", "second", "then", "finally", "because", "therefore", "however", "as a result"),
    "it": ("prima", "innanzitutto", "poi", "quindi", "infine", "perche", "pertanto", "tuttavia"),
    "de": ("zuerst", "zunachst", "zunächst", "dann", "anschliessend", "anschließend", "schliesslich", "schließlich", "weil", "deshalb", "jedoch"),
}


@dataclass(frozen=True)
class CoachQuestion:
    id: str
    mode: str
    difficulty: str
    topic: str
    prompts: dict[str, str]
    reference_points: tuple[str, ...]
    keyword_groups: tuple[tuple[str, ...], ...]


def _question(
    identifier: str,
    mode: str,
    difficulty: str,
    topic: str,
    prompts: dict[str, str],
    points: Iterable[str],
    groups: Iterable[Iterable[str]],
) -> CoachQuestion:
    return CoachQuestion(
        identifier,
        mode,
        difficulty,
        topic,
        prompts,
        tuple(points),
        tuple(tuple(group) for group in groups),
    )


QUESTION_BANK: tuple[CoachQuestion, ...] = (
    _question(
        "technical_dcf_basics",
        "technical",
        "beginner",
        "DCF",
        {
            "fr": "Explique-moi les étapes d’une valorisation DCF, de la projection des flux de trésorerie jusqu’à la valeur des capitaux propres.",
            "en": "Walk me through a DCF, from forecasting cash flow to arriving at equity value.",
            "it": "Spiegami le fasi di una valutazione DCF, dalla previsione dei flussi di cassa al valore del capitale proprio.",
            "de": "Erkläre mir die Schritte einer DCF-Bewertung, von der Cashflow-Prognose bis zum Eigenkapitalwert.",
        },
        (
            "Project operating performance and derive unlevered free cash flow from EBIT after tax, non-cash items, capex and working-capital movements.",
            "Discount forecast cash flows using WACC and calculate a terminal value with a stated method and assumption.",
            "Add the present values to obtain enterprise value, then bridge from enterprise value to equity value using net debt and other relevant claims.",
            "Sanity-check the result with sensitivities and market-based valuation methods.",
        ),
        (("free cash flow", "fcf", "flux de tresorerie", "cash flow"), ("wacc", "discount", "actualis"), ("terminal", "perpetuity", "multiple"), ("enterprise value", "equity value", "net debt", "dette nette")),
    ),
    _question(
        "technical_three_statements",
        "technical",
        "intermediate",
        "Three Financial Statements",
        {
            "fr": "Une entreprise amortit 10 € supplémentaires cette année. Explique l’effet sur le compte de résultat, le tableau de flux de trésorerie et le bilan, en supposant un taux d’impôt de 25 %.",
            "en": "A company records an additional €10 of depreciation this year. Walk me through the income statement, cash flow statement and balance sheet, assuming a 25% tax rate.",
            "it": "Un’azienda registra 10 € di ammortamento aggiuntivo. Spiegane gli effetti su conto economico, rendiconto finanziario e stato patrimoniale con un’aliquota del 25%.",
            "de": "Ein Unternehmen verbucht zusätzlich 10 € Abschreibung. Erläutere bei 25% Steuersatz die Auswirkungen auf GuV, Cashflow-Rechnung und Bilanz.",
        },
        (
            "Operating income and pre-tax income decrease by 10; tax expense falls by 2.5, so net income decreases by 7.5.",
            "On the cash flow statement, start with lower net income and add back the non-cash depreciation, producing a 2.5 cash increase from the tax shield.",
            "Cash increases by 2.5, PP&E decreases by 10, retained earnings decrease by 7.5, and both balance-sheet sides decline by 7.5.",
        ),
        (("income statement", "compte de resultat", "guv", "net income", "resultat net"), ("tax", "impot", "steuer"), ("cash flow", "flux de tresorerie", "cashflow"), ("balance sheet", "bilan", "bilanz", "pp&e", "retained earnings")),
    ),
    _question(
        "technical_ev_equity_value",
        "technical",
        "intermediate",
        "Enterprise Value and Equity Value",
        {
            "fr": "Quelle est la différence entre Enterprise Value et Equity Value, et pourquoi utilise-t-on EV/EBITDA alors que P/E s’appuie sur Equity Value ?",
            "en": "What is the difference between enterprise value and equity value, and why is EV/EBITDA paired with EV while P/E is paired with equity value?",
            "it": "Qual è la differenza tra Enterprise Value ed Equity Value, e perché EV/EBITDA usa EV mentre P/E usa Equity Value?",
            "de": "Was ist der Unterschied zwischen Enterprise Value und Equity Value, und warum wird EV/EBITDA mit EV und KGV mit Equity Value verwendet?",
        },
        (
            "Equity value is the value attributable to common shareholders; enterprise value represents the value of the operating business for all capital providers.",
            "A standard bridge begins with equity value and adds net debt and other senior or non-controlling claims, with adjustments depending on the company and convention.",
            "EV/EBITDA compares a pre-interest operating metric with a capital-structure-neutral value; P/E compares net income available to shareholders with equity value.",
        ),
        (("shareholder", "equity", "actionnaire"), ("debt", "dette", "net debt", "dette nette"), ("operating", "ebitda", "interest", "interet"), ("capital structure", "structure du capital")),
    ),
    _question(
        "technical_lbo_returns",
        "technical",
        "private_equity",
        "LBO and Private Equity",
        {
            "fr": "Quels sont les principaux leviers de création de valeur et de rendement dans un LBO, et quels risques vérifierais-tu ?",
            "en": "What are the principal value-creation and return levers in an LBO, and which risks would you test?",
            "it": "Quali sono le principali leve di creazione di valore e rendimento in un LBO, e quali rischi verificheresti?",
            "de": "Was sind die wichtigsten Wertschöpfungs- und Renditetreiber eines LBO, und welche Risiken würdest du prüfen?",
        },
        (
            "Returns can come from EBITDA growth, margin improvement, debt paydown from cash generation and changes in the exit multiple.",
            "The entry price, leverage level, interest cost, downside cash generation, covenants and exit assumptions require explicit sensitivity analysis.",
            "A good answer separates operational value creation from financial engineering and makes assumptions testable.",
        ),
        (("ebitda", "growth", "croissance", "margin", "marge"), ("debt paydown", "deleverag", "remboursement", "cash flow"), ("exit multiple", "multiple de sortie"), ("leverage", "covenant", "interest", "taux")),
    ),
    _question(
        "technical_market_view",
        "technical",
        "advanced",
        "Markets",
        {
            "fr": "Choisis un indicateur macroéconomique récent qui peut influencer les marchés. Explique le mécanisme, les classes d’actifs concernées et ce qui invaliderait ton analyse.",
            "en": "Choose one recent macroeconomic indicator that can affect markets. Explain the mechanism, affected asset classes, and what would invalidate your view.",
            "it": "Scegli un indicatore macroeconomico recente che può influenzare i mercati. Spiega il meccanismo, le asset class coinvolte e cosa invaliderebbe la tua analisi.",
            "de": "Wähle einen aktuellen makroökonomischen Indikator, der Märkte beeinflussen kann. Erkläre Mechanismus, betroffene Anlageklassen und was deine Analyse widerlegen würde.",
        },
        (
            "State the observable indicator and distinguish fact from interpretation.",
            "Explain a causal channel, such as expectations, discount rates, cash flows, risk premia or liquidity.",
            "Name affected assets and an alternative outcome or disconfirming evidence.",
        ),
        (("inflation", "growth", "gdp", "employment", "taux", "rate"), ("discount", "actualis", "yield", "rendement", "risk premium"), ("equity", "bond", "credit", "currency", "action"), ("risk", "alternative", "if", "scenario", "inval")),
    ),
    _question(
        "behavioral_tell_me",
        "behavioral",
        "beginner",
        "Tell me about yourself",
        {
            "fr": "Présente-toi en 90 secondes pour un stage en finance. Structure ta réponse, n’invente aucun fait, et termine par le lien avec le poste ciblé.",
            "en": "Tell me about yourself in 90 seconds for a finance internship. Structure the answer, do not invent facts, and end with the link to the target role.",
            "it": "Presentati in 90 secondi per uno stage in finanza. Struttura la risposta, non inventare fatti e concludi con il legame con il ruolo.",
            "de": "Stelle dich in 90 Sekunden für ein Finanzpraktikum vor. Strukturiere die Antwort, erfinde keine Fakten und schließe mit dem Bezug zur Zielrolle.",
        },
        (
            "Open with current education or current role and a concise finance-relevant focus.",
            "Use one or two factual experiences, projects or skills with a concrete responsibility or result.",
            "Finish with a specific reason the next role is a coherent step, without claiming unverified company facts.",
        ),
        (("education", "master", "university", "ecole", "formation"), ("experience", "project", "stage", "intern", "projet"), ("finance", "valuation", "analysis", "analyse"), ("role", "position", "poste", "why", "pourquoi")),
    ),
    _question(
        "behavioral_why_role",
        "behavioral",
        "intermediate",
        "Motivation",
        {
            "fr": "Pourquoi souhaites-tu travailler en M&A, private equity, gestion d’actifs, marchés ou conseil ? Réponds pour le métier qui t’intéresse réellement.",
            "en": "Why do you want to work in M&A, private equity, asset management, markets, or consulting? Answer for the field that genuinely interests you.",
            "it": "Perché vuoi lavorare in M&A, private equity, asset management, mercati o consulenza? Rispondi per il settore che ti interessa davvero.",
            "de": "Warum möchten Sie in M&A, Private Equity, Asset Management, Märkten oder Beratung arbeiten? Antworten Sie für das Feld, das Sie wirklich interessiert.",
        },
        (
            "Give a specific, factual trigger from coursework, experience or a project rather than a generic prestige claim.",
            "Connect the work itself to skills you want to develop: analysis, judgement, client work, execution or investing.",
            "Acknowledge the demanding nature of the role and explain why the learning trade-off fits your goals.",
        ),
        (("experience", "project", "course", "cours", "stage"), ("analysis", "analyse", "valuation", "client", "investment", "investissement"), ("skill", "learn", "develop", "apprendre", "developper"), ("role", "work", "metier", "job")),
    ),
    _question(
        "case_investment_screen",
        "case",
        "advanced",
        "Investment case",
        {
            "fr": "Tu dois évaluer rapidement une entreprise cible pour un investissement. Donne une structure de screening avant de conclure, en distinguant faits à collecter, hypothèses et risques.",
            "en": "You need to screen a target company quickly for an investment. Give a screening structure before reaching a conclusion, separating facts to collect, assumptions, and risks.",
            "it": "Devi valutare rapidamente una società target per un investimento. Fornisci una struttura di screening prima di concludere, distinguendo fatti da raccogliere, ipotesi e rischi.",
            "de": "Sie sollen ein Zielunternehmen schnell für eine Investition prüfen. Geben Sie eine Screening-Struktur vor einer Schlussfolgerung an und trennen Sie Fakten, Annahmen und Risiken.",
        },
        (
            "Start with the investment thesis and market attractiveness, including growth, competition and relevant external drivers.",
            "Assess business quality: customers, pricing, unit economics, margins, cash conversion and management where evidence exists.",
            "Test valuation, financing, downside scenarios and concrete diligence questions before recommending a decision.",
        ),
        (("market", "marche", "growth", "croissance", "competition", "concurrence"), ("customer", "client", "margin", "marge", "cash", "unit economics"), ("valuation", "multiple", "price", "prix"), ("risk", "diligence", "downside", "scenario")),
    ),
    _question(
        "company_specific_fit",
        "company",
        "intermediate",
        "Company-specific fit",
        {
            "fr": "À partir de l’offre sélectionnée, explique comment tu préparerais « Pourquoi ce poste et cette entreprise ? » sans inventer d’information sur la société.",
            "en": "Using the selected job, explain how you would prepare “Why this role and this company?” without inventing information about the firm.",
            "it": "Partendo dall’offerta selezionata, spiega come prepareresti “Perché questo ruolo e questa azienda?” senza inventare informazioni sulla società.",
            "de": "Erklären Sie anhand der ausgewählten Stelle, wie Sie „Warum diese Rolle und dieses Unternehmen?“ vorbereiten würden, ohne Informationen über das Unternehmen zu erfinden.",
        },
        (
            "Separate verified information from the job description from hypotheses that require checking on official sources.",
            "Connect two concrete role requirements to truthful evidence from your profile or to a clearly stated learning goal.",
            "Prepare one informed question for the interviewer instead of making an unsupported company claim.",
        ),
        (("job", "role", "poste", "offer", "offre"), ("requirement", "skill", "competence", "experience", "profil"), ("official", "verified", "verifie", "source"), ("question", "ask", "demander")),
    ),
    _question(
        "company_specific_technical",
        "company",
        "advanced",
        "Role-specific technical preparation",
        {
            "fr": "À partir de l’offre sélectionnée, choisis une exigence technique vérifiable et explique comment tu t’entraînerais à la démontrer en entretien, sans prétendre la maîtriser si ce n’est pas le cas.",
            "en": "Using the selected job, choose one verifiable technical requirement and explain how you would practise demonstrating it in an interview without claiming mastery you do not have.",
            "it": "Partendo dall’offerta selezionata, scegli un requisito tecnico verificabile e spiega come ti prepareresti a dimostrarlo al colloquio senza dichiarare una padronanza che non possiedi.",
            "de": "Wählen Sie anhand der Stelle eine überprüfbare technische Anforderung und erklären Sie, wie Sie deren Demonstration im Interview üben würden, ohne unzutreffende Kompetenz zu behaupten.",
        },
        (
            "Quote or paraphrase the requirement from the official role description and name what is verified versus what needs confirmation.",
            "Break preparation into a concept review, a short worked example and a clear explanation of assumptions or limitations.",
            "State a truthful evidence point from your profile or a concrete learning plan rather than claiming unsupported expertise.",
        ),
        (("requirement", "exigence", "offer", "offre", "description"), ("example", "exemple", "practice", "entrain", "exercise", "exercice"), ("assumption", "hypothese", "limitation", "limite"), ("profile", "profil", "learn", "apprendre", "evidence", "preuve")),
    ),
)


# Canonical question data remains English for the finance-domain source of
# truth.  These vetted local translations are used only for what a candidate
# sees in the reference-answer panel; there is no provider call, machine
# translation, or hidden prompt involved.
_REFERENCE_POINT_TRANSLATIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "technical_dcf_basics": {
        "fr": (
            "Projeter la performance opérationnelle puis dériver le flux de trésorerie disponible non endetté à partir de l’EBIT après impôt, des éléments non monétaires, du capex et du besoin en fonds de roulement.",
            "Actualiser les flux prévisionnels au WACC et calculer une valeur terminale avec une méthode et une hypothèse explicites.",
            "Additionner les valeurs actualisées pour obtenir l’Enterprise Value, puis passer à l’Equity Value avec la dette nette et les autres créances pertinentes.",
            "Tester la cohérence avec des sensibilités et des méthodes de valorisation de marché.",
        ),
        "it": (
            "Proiettare la performance operativa e derivare il flusso di cassa disponibile unlevered da EBIT dopo le imposte, elementi non monetari, capex e capitale circolante.",
            "Attualizzare i flussi previsti con il WACC e calcolare un valore terminale con metodo e ipotesi espliciti.",
            "Sommare i valori attuali per ottenere l’Enterprise Value, poi passare all’Equity Value con il debito netto e le altre pretese rilevanti.",
            "Verificare il risultato con analisi di sensitività e metodi di valutazione di mercato.",
        ),
        "de": (
            "Die operative Entwicklung planen und den unverschuldeten Free Cashflow aus EBIT nach Steuern, nicht zahlungswirksamen Posten, Capex und Working Capital ableiten.",
            "Die prognostizierten Cashflows mit dem WACC abzinsen und mit einer klar benannten Methode und Annahme einen Terminal Value berechnen.",
            "Die Barwerte zum Enterprise Value addieren und mit Nettoverschuldung sowie weiteren relevanten Ansprüchen zum Equity Value überleiten.",
            "Das Ergebnis mit Sensitivitäten und marktbezogenen Bewertungsmethoden plausibilisieren.",
        ),
    },
    "technical_three_statements": {
        "fr": (
            "Le résultat d’exploitation et le résultat avant impôt baissent de 10 ; la charge d’impôt baisse de 2,5, donc le résultat net baisse de 7,5.",
            "Dans le tableau de flux de trésorerie, partir du résultat net plus faible et réintégrer l’amortissement non monétaire : le bouclier fiscal crée une hausse de trésorerie de 2,5.",
            "La trésorerie augmente de 2,5, les immobilisations diminuent de 10, les bénéfices non distribués diminuent de 7,5 et les deux côtés du bilan diminuent de 7,5.",
        ),
        "it": (
            "Il risultato operativo e quello ante imposte diminuiscono di 10; le imposte diminuiscono di 2,5, quindi l’utile netto diminuisce di 7,5.",
            "Nel rendiconto finanziario si parte dall’utile netto più basso e si riaggiunge l’ammortamento non monetario: lo scudo fiscale produce un aumento di cassa di 2,5.",
            "La cassa aumenta di 2,5, le immobilizzazioni diminuiscono di 10, gli utili portati a nuovo diminuiscono di 7,5 e entrambi i lati dello stato patrimoniale diminuiscono di 7,5.",
        ),
        "de": (
            "Operatives Ergebnis und Ergebnis vor Steuern sinken um 10; der Steueraufwand sinkt um 2,5, daher sinkt der Jahresüberschuss um 7,5.",
            "In der Cashflow-Rechnung startet man mit dem niedrigeren Jahresüberschuss und addiert die nicht zahlungswirksame Abschreibung zurück: Der Steuervorteil erhöht den Cashflow um 2,5.",
            "Cash steigt um 2,5, Sachanlagen sinken um 10, Gewinnrücklagen sinken um 7,5 und beide Seiten der Bilanz sinken um 7,5.",
        ),
    },
    "technical_ev_equity_value": {
        "fr": (
            "L’Equity Value revient aux actionnaires ordinaires ; l’Enterprise Value représente la valeur de l’activité opérationnelle pour l’ensemble des apporteurs de capitaux.",
            "Un pont standard part de l’Equity Value, ajoute la dette nette et d’autres créances prioritaires ou intérêts minoritaires, avec des ajustements selon l’entreprise et la convention retenue.",
            "EV/EBITDA compare une métrique opérationnelle avant intérêts avec une valeur neutre vis-à-vis de la structure du capital ; P/E compare le résultat net revenant aux actionnaires avec l’Equity Value.",
        ),
        "it": (
            "L’Equity Value spetta agli azionisti ordinari; l’Enterprise Value rappresenta il valore dell’attività operativa per tutti i finanziatori.",
            "Un ponte standard parte dall’Equity Value e aggiunge debito netto e altre pretese senior o di minoranza, con aggiustamenti secondo società e convenzione.",
            "EV/EBITDA confronta una metrica operativa pre-interessi con un valore neutrale rispetto alla struttura del capitale; P/E confronta l’utile netto degli azionisti con l’Equity Value.",
        ),
        "de": (
            "Der Equity Value steht den Stammaktionären zu; der Enterprise Value beschreibt den Wert des operativen Geschäfts für alle Kapitalgeber.",
            "Eine Standardüberleitung beginnt beim Equity Value und addiert Nettoverschuldung sowie weitere vorrangige oder Minderheitsansprüche, mit unternehmens- und konventionsabhängigen Anpassungen.",
            "EV/EBITDA vergleicht eine operative Kennzahl vor Zinsen mit einem kapitalstrukturneutralen Wert; das KGV vergleicht den Aktionären zurechenbaren Jahresüberschuss mit dem Equity Value.",
        ),
    },
    "technical_lbo_returns": {
        "fr": (
            "Les rendements peuvent venir de la croissance de l’EBITDA, de l’amélioration des marges, du désendettement par génération de trésorerie et de l’évolution du multiple de sortie.",
            "Le prix d’entrée, le niveau de levier, le coût de la dette, la génération de trésorerie en scénario adverse, les covenants et les hypothèses de sortie doivent faire l’objet de sensibilités explicites.",
            "Une bonne réponse sépare la création de valeur opérationnelle de l’ingénierie financière et rend les hypothèses vérifiables.",
        ),
        "it": (
            "I rendimenti possono derivare dalla crescita dell’EBITDA, dal miglioramento dei margini, dalla riduzione del debito grazie alla generazione di cassa e dal cambiamento del multiplo di uscita.",
            "Prezzo d’ingresso, leva, costo degli interessi, generazione di cassa in scenario negativo, covenant e ipotesi di uscita richiedono analisi di sensitività esplicite.",
            "Una buona risposta separa la creazione di valore operativa dall’ingegneria finanziaria e rende le ipotesi verificabili.",
        ),
        "de": (
            "Renditen können aus EBITDA-Wachstum, Margenverbesserung, Schuldentilgung durch Cash-Generierung und Veränderungen des Exit-Multiples entstehen.",
            "Einstiegspreis, Verschuldung, Zinskosten, Cash-Generierung im Downside-Szenario, Covenants und Exit-Annahmen benötigen explizite Sensitivitätsanalysen.",
            "Eine gute Antwort trennt operative Wertschöpfung von Financial Engineering und macht Annahmen überprüfbar.",
        ),
    },
    "technical_market_view": {
        "fr": (
            "Nommer l’indicateur observable et séparer le fait de son interprétation.",
            "Expliquer un canal causal, par exemple les anticipations, les taux d’actualisation, les flux de trésorerie, les primes de risque ou la liquidité.",
            "Identifier les actifs concernés et un résultat alternatif ou un élément qui invaliderait l’analyse.",
        ),
        "it": (
            "Indicare l’indicatore osservabile e distinguere il fatto dall’interpretazione.",
            "Spiegare un canale causale, ad esempio aspettative, tassi di sconto, flussi di cassa, premi per il rischio o liquidità.",
            "Indicare le attività coinvolte e un esito alternativo o un’evidenza che invaliderebbe l’analisi.",
        ),
        "de": (
            "Den beobachtbaren Indikator nennen und Fakten von der Interpretation trennen.",
            "Einen kausalen Kanal erklären, etwa Erwartungen, Diskontsätze, Cashflows, Risikoprämien oder Liquidität.",
            "Betroffene Anlageklassen sowie ein alternatives Ergebnis oder widerlegende Evidenz benennen.",
        ),
    },
    "behavioral_tell_me": {
        "fr": (
            "Commencer par l’activité actuelle ou la formation, puis annoncer un angle concis lié à la finance.",
            "Utiliser une ou deux expériences, projets ou compétences factuels avec une responsabilité ou un résultat concret.",
            "Conclure par la raison précise pour laquelle le prochain poste est cohérent, sans prétendre connaître des faits non vérifiés sur l’entreprise.",
        ),
        "it": (
            "Aprire con la formazione o il ruolo attuale e un orientamento conciso pertinente alla finanza.",
            "Usare una o due esperienze, progetti o competenze reali con una responsabilità o un risultato concreto.",
            "Concludere spiegando perché il prossimo ruolo è un passo coerente, senza sostenere fatti non verificati sull’azienda.",
        ),
        "de": (
            "Mit dem aktuellen Studium oder der aktuellen Tätigkeit beginnen und einen knappen finanzrelevanten Schwerpunkt nennen.",
            "Eine oder zwei tatsächliche Erfahrungen, Projekte oder Fähigkeiten mit einer konkreten Verantwortung oder einem Ergebnis nutzen.",
            "Mit einem konkreten Grund schließen, warum die nächste Stelle ein stimmiger Schritt ist, ohne ungeprüfte Unternehmensfakten zu behaupten.",
        ),
    },
    "behavioral_why_role": {
        "fr": (
            "Donner un déclencheur précis et factuel issu des cours, d’une expérience ou d’un projet plutôt qu’un argument générique de prestige.",
            "Relier le travail lui-même aux compétences à développer : analyse, jugement, relation client, exécution ou investissement.",
            "Reconnaître les exigences du métier et expliquer pourquoi le compromis d’apprentissage correspond aux objectifs personnels.",
        ),
        "it": (
            "Dare un motivo specifico e reale tratto da corsi, esperienza o progetto, non una motivazione generica di prestigio.",
            "Collegare il lavoro concreto alle competenze da sviluppare: analisi, giudizio, relazione con il cliente, esecuzione o investimento.",
            "Riconoscere l’impegno richiesto dal ruolo e spiegare perché il compromesso di apprendimento è coerente con gli obiettivi.",
        ),
        "de": (
            "Einen konkreten, faktischen Auslöser aus Studium, Erfahrung oder Projekt nennen statt eines allgemeinen Prestigearguments.",
            "Die Arbeit selbst mit zu entwickelnden Fähigkeiten verbinden: Analyse, Urteilsvermögen, Kundenarbeit, Umsetzung oder Investieren.",
            "Die Anforderungen der Rolle anerkennen und erklären, warum der Lern-Trade-off zu den eigenen Zielen passt.",
        ),
    },
    "case_investment_screen": {
        "fr": (
            "Commencer par la thèse d’investissement et l’attractivité du marché, notamment croissance, concurrence et facteurs externes pertinents.",
            "Évaluer la qualité de l’activité : clients, prix, unit economics, marges, conversion de trésorerie et management là où les éléments sont disponibles.",
            "Tester valorisation, financement, scénarios défavorables et questions de due diligence avant de recommander une décision.",
        ),
        "it": (
            "Partire dalla tesi di investimento e dall’attrattività del mercato, inclusi crescita, concorrenza e fattori esterni rilevanti.",
            "Valutare la qualità del business: clienti, pricing, unit economics, margini, conversione di cassa e management quando esistono evidenze.",
            "Testare valutazione, finanziamento, scenari negativi e domande di due diligence prima di raccomandare una decisione.",
        ),
        "de": (
            "Mit der Investmentthese und der Marktattraktivität beginnen, einschließlich Wachstum, Wettbewerb und relevanter externer Treiber.",
            "Die Geschäftsqualität bewerten: Kunden, Pricing, Unit Economics, Margen, Cash Conversion und Management, soweit Evidenz vorliegt.",
            "Bewertung, Finanzierung, Downside-Szenarien und konkrete Due-Diligence-Fragen prüfen, bevor eine Entscheidung empfohlen wird.",
        ),
    },
    "company_specific_fit": {
        "fr": (
            "Séparer les informations vérifiées dans l’offre des hypothèses qui nécessitent une vérification sur des sources officielles.",
            "Relier deux exigences concrètes du poste à des éléments véridiques du profil ou à un objectif d’apprentissage clairement indiqué.",
            "Préparer une question informée pour l’intervieweur au lieu d’affirmer un fait non étayé sur l’entreprise.",
        ),
        "it": (
            "Separare le informazioni verificate nella descrizione dell’offerta dalle ipotesi da controllare su fonti ufficiali.",
            "Collegare due requisiti concreti del ruolo a prove veritiere del profilo o a un obiettivo di apprendimento dichiarato chiaramente.",
            "Preparare una domanda informata per l’intervistatore invece di fare un’affermazione non supportata sull’azienda.",
        ),
        "de": (
            "In der Stellenbeschreibung überprüfte Informationen von Annahmen trennen, die auf offiziellen Quellen geprüft werden müssen.",
            "Zwei konkrete Stellenanforderungen mit wahrheitsgemäßen Profilbelegen oder einem klar benannten Lernziel verbinden.",
            "Eine fundierte Frage an die interviewende Person vorbereiten, statt eine unbelegte Unternehmensbehauptung aufzustellen.",
        ),
    },
    "company_specific_technical": {
        "fr": (
            "L’exigence de l’offre officielle doit être citée ou reformulée, en distinguant ce qui est vérifié de ce qui doit être confirmé.",
            "Découper la préparation en révision du concept, exemple court travaillé et explication claire des hypothèses ou limites.",
            "Donner un élément de preuve véridique du profil ou un plan d’apprentissage concret plutôt que d’affirmer une expertise non étayée.",
        ),
        "it": (
            "Citare o parafrasare il requisito dalla descrizione ufficiale e distinguere ciò che è verificato da ciò che deve essere confermato.",
            "Dividere la preparazione in revisione del concetto, breve esempio svolto e spiegazione chiara di ipotesi o limiti.",
            "Dichiarare una prova reale del profilo o un piano concreto di apprendimento invece di rivendicare competenze non comprovate.",
        ),
        "de": (
            "Die Anforderung aus der offiziellen Stellenbeschreibung zitieren oder paraphrasieren und Verifiziertes von noch zu Bestätigendem trennen.",
            "Die Vorbereitung in Konzeptwiederholung, ein kurzes durchgerechnetes Beispiel und eine klare Erklärung von Annahmen oder Grenzen aufteilen.",
            "Einen wahrheitsgemäßen Profilbeleg oder einen konkreten Lernplan nennen, statt unbelegte Expertise zu behaupten.",
        ),
    },
}


def _normalise_choice(value: Any, allowed: Iterable[str], label: str) -> str:
    choice = clean_text(value, limit=80).lower().replace(" ", "_")
    if choice not in set(allowed):
        raise UserFacingError(f"{label} est invalide.")
    return choice


def normalize_config(mode: Any, difficulty: Any, language: Any) -> tuple[str, str, str]:
    return (
        _normalise_choice(mode, INTERVIEW_MODES, "Le mode d’entretien"),
        _normalise_choice(difficulty, DIFFICULTIES, "Le niveau d’entretien"),
        _normalise_choice(language, LANGUAGES, "La langue d’entretien"),
    )


def _language_copy(language: str) -> dict[str, Any]:
    """Return static UI copy for a previously validated language."""
    return _COACH_COPY.get(language, _COACH_COPY["en"])


def _topic_label(question: CoachQuestion, language: str) -> str:
    return _TOPIC_LABELS.get(question.id, {}).get(language, question.topic)


def _reference_points(question: CoachQuestion, language: str) -> tuple[str, ...]:
    """Use a vetted local translation when one exists, otherwise canonical copy."""
    return _REFERENCE_POINT_TRANSLATIONS.get(question.id, {}).get(language, question.reference_points)


def _normalized_phrase(value: str) -> str:
    return normalized_text(value)


def _contains_term(normalized_answer: str, term: str) -> bool:
    """Match complete normalized words/phrases, not accidental substrings.

    For example, the English marker ``if`` must not get credit merely because
    an answer contains the word ``specific``.  Wrapping both sides in spaces
    also works for multi-word finance concepts after ``normalized_text`` has
    made punctuation and accents comparable.
    """
    normalized_term = _normalized_phrase(term)
    if not normalized_term:
        return False
    return f" {normalized_term} " in f" {normalized_answer} "


def _coverage_groups(question: CoachQuestion) -> tuple[tuple[str, ...], ...]:
    aliases = _KEYWORD_ALIASES.get(question.id, ())
    merged: list[tuple[str, ...]] = []
    for index, group in enumerate(question.keyword_groups):
        extra = aliases[index] if index < len(aliases) else ()
        # Preserve order because it is also the deterministic fallback label
        # for an older question without a translated focus map.
        merged.append(tuple(dict.fromkeys((*group, *extra))))
    return tuple(merged)


def _missing_focus(question: CoachQuestion, language: str, index: int, group: tuple[str, ...]) -> str:
    translated = _MISSING_FOCUS.get(question.id, {}).get(language, ())
    if index < len(translated):
        return translated[index]
    # Existing or future questions stay usable before translations are added.
    # The fallback remains a bounded, visible concept rather than a hidden
    # scoring detail.
    return " / ".join(group[:2])


def _prompt(question: CoachQuestion, language: str, job: dict[str, Any] | None = None) -> str:
    prompt = question.prompts.get(language) or question.prompts["en"]
    if question.mode != "company" or not job:
        return prompt
    company = clean_text(job.get("company"), limit=240)
    title = clean_text(job.get("title"), limit=300)
    if not company and not title:
        return prompt
    context_label = _language_copy(language)["job_context"]
    return f"{prompt}\n\n{context_label}: {company}{' — ' if company and title else ''}{title}."


def serialize_question(question: CoachQuestion, language: str, job: dict[str, Any] | None = None) -> dict[str, Any]:
    # ``topic`` deliberately remains the historic canonical identifier/text.
    # The additive fields make the presentation language explicit for newer
    # clients while records saved by previous releases remain readable.
    return {
        "id": question.id,
        "mode": question.mode,
        "difficulty": question.difficulty,
        "topic": question.topic,
        "topic_label": _topic_label(question, language),
        "language": language,
        "prompt": _prompt(question, language, job),
        "reference_points": list(_reference_points(question, language)),
        "reference_answer_language": language if question.id in _REFERENCE_POINT_TRANSLATIONS else "en",
    }


def select_question(
    *,
    mode: str,
    difficulty: str,
    language: str,
    asked_ids: Iterable[str] = (),
    last_score: int | None = None,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select an unseen question using a small, explainable adaptation rule."""
    asked = {clean_text(value, limit=120) for value in asked_ids}
    desired_rank = _DIFFICULTY_RANK[difficulty]
    if last_score is not None and last_score >= 80:
        desired_rank = min(desired_rank + 1, len(DIFFICULTIES) - 1)
    elif last_score is not None and last_score <= 45:
        desired_rank = max(desired_rank - 1, 0)
    candidates = [question for question in QUESTION_BANK if question.mode == mode and question.id not in asked]
    if not candidates:
        candidates = [question for question in QUESTION_BANK if question.mode == mode]
    if not candidates:
        candidates = list(QUESTION_BANK)
    candidates.sort(key=lambda question: (abs(_DIFFICULTY_RANK[question.difficulty] - desired_rank), question.id))
    return serialize_question(candidates[0], language, job)


def _find_question(question_id: Any) -> CoachQuestion:
    identifier = clean_text(question_id, limit=120)
    for question in QUESTION_BANK:
        if question.id == identifier:
            return question
    raise UserFacingError("La question d’entretien demandée est inconnue.")


def _coverage(
    normalized_answer: str,
    question: CoachQuestion,
    language: str,
) -> tuple[int, list[str]]:
    matched = 0
    missing: list[str] = []
    for index, group in enumerate(_coverage_groups(question)):
        if any(_contains_term(normalized_answer, term) for term in group):
            matched += 1
        else:
            missing.append(_missing_focus(question, language, index, group))
    return matched, missing


def evaluate_answer(question_id: Any, answer: Any, language: Any = "fr") -> dict[str, Any]:
    """Give bounded, factual coaching against a known exercise.

    The response is scored only for observable coverage and presentation.  The
    engine avoids claims about a candidate's actual competence or employability.
    """
    question = _find_question(question_id)
    normalized_language = _normalise_choice(language, LANGUAGES, "La langue d’entretien")
    copy = _language_copy(normalized_language)
    raw = clean_text(answer, limit=6_000)
    if len(raw) < 3:
        raise UserFacingError(copy["answer_too_short"])
    words = re.findall(r"[\wÀ-ÿ'-]+", raw)
    word_count = len(words)
    normalized = normalized_text(raw)
    covered, missing = _coverage(normalized, question, normalized_language)
    total_groups = max(1, len(question.keyword_groups))
    precision = round(100 * covered / total_groups)
    clarity = 25 if word_count < 15 else 55 if word_count < 35 else 85 if word_count <= 320 else 62
    structure_markers = _STRUCTURE_MARKERS[normalized_language]
    structure = min(100, 35 + 22 * sum(1 for marker in structure_markers if _contains_term(normalized, marker)))
    relevance = min(100, round((precision * 0.72) + (clarity * 0.28)))
    overall = round((precision * 0.50) + (clarity * 0.25) + (structure * 0.15) + (relevance * 0.10))
    if word_count < 15:
        overall = min(overall, 38)
    strengths: list[str] = []
    if covered:
        strengths.append(copy["strength_coverage"].format(count=covered))
    if word_count >= 35:
        strengths.append(copy["strength_length"])
    if structure >= 70:
        strengths.append(copy["strength_structure"])
    gaps: list[str] = []
    if word_count < 35:
        gaps.append(copy["gap_length"])
    if missing:
        gaps.append(copy["gap_missing"].format(points=", ".join(missing[:3])))
    if structure < 70:
        gaps.append(copy["gap_structure"])
    coaching = copy["coaching_low"] if overall < 60 else copy["coaching_high"]
    return {
        "question_id": question.id,
        "topic": question.topic,
        "topic_label": _topic_label(question, normalized_language),
        "word_count": word_count,
        "scores": {
            "technical": precision if question.mode in {"technical", "case"} else relevance,
            "precision": precision,
            "structure": structure,
            "clarity": clarity,
            "relevance": relevance,
            "overall": overall,
        },
        "score_labels": dict(copy["score_labels"]),
        "feedback_labels": {
            "strengths": {
                "fr": "Points solides",
                "en": "Strengths",
                "it": "Punti di forza",
                "de": "Stärken",
            }[normalized_language],
            "gaps": {
                "fr": "À retravailler",
                "en": "Areas to practise",
                "it": "Aree da esercitare",
                "de": "Übungsfelder",
            }[normalized_language],
            "reference_answer": {
                "fr": "Réponse de référence",
                "en": "Reference answer",
                "it": "Risposta di riferimento",
                "de": "Referenzantwort",
            }[normalized_language],
            "coaching": {
                "fr": "Conseil de coaching",
                "en": "Coaching guidance",
                "it": "Indicazione di coaching",
                "de": "Coaching-Hinweis",
            }[normalized_language],
        },
        "strengths": strengths[:3],
        "gaps": gaps[:4],
        "coaching": coaching,
        "reference_answer": list(_reference_points(question, normalized_language)),
        "reference_answer_language": normalized_language if question.id in _REFERENCE_POINT_TRANSLATIONS else "en",
        "disclaimer": copy["disclaimer"],
        "language": normalized_language,
    }


def progress_summary(turns: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return an honest, language-aware local aggregate for saved turns.

    ``CareerService`` persists the selected language inside each feedback item.
    Reading it here keeps this pure helper backward compatible while ensuring
    that revision priorities and the disclaimer use the language of the latest
    completed answer.  Empty legacy sessions retain the historic French
    fallback because no selected-language value exists in their turns.
    """
    completed = [turn for turn in turns if isinstance(turn, dict) and isinstance(turn.get("feedback"), dict)]
    latest_language = "fr"
    for turn in reversed(completed):
        candidate = clean_text(turn["feedback"].get("language"), limit=8).lower()
        if candidate in LANGUAGES:
            latest_language = candidate
            break
    copy = _language_copy(latest_language)
    scores = [int(turn["feedback"].get("scores", {}).get("overall", 0)) for turn in completed]
    topics: dict[str, int] = {}
    for turn in completed:
        feedback = turn["feedback"]
        topic = clean_text(feedback.get("topic_label") or turn.get("topic"), limit=160)
        if not topic:
            topic = {"fr": "À préciser", "en": "To clarify", "it": "Da chiarire", "de": "Zu klären"}[latest_language]
        topics[topic] = topics.get(topic, 0) + 1
    weak = sorted(
        (
            clean_text(gap, limit=500)
            for turn in completed
            for gap in turn["feedback"].get("gaps", [])
            if clean_text(gap, limit=500)
        ),
        key=lambda value: value,
    )
    return {
        "answered_count": len(completed),
        "average_score": round(sum(scores) / len(scores)) if scores else None,
        "topics_practised": topics,
        "revision_priorities": list(dict.fromkeys(weak))[:5],
        "labels": dict(copy["progress_labels"]),
        "disclaimer": copy["progress_disclaimer"],
        "language": latest_language,
    }
