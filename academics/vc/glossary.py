"""Lexique VC minimal, original et bilingue, avec inconnus explicites."""

from __future__ import annotations

CORE_TERMS = {
    "pre-money": {"fr": "valorisation avant investissement", "effect": "base de calcul avant le nouveau tour"},
    "post-money": {"fr": "valorisation après investissement", "effect": "pre-money plus le montant investi"},
    "liquidation preference": {"fr": "préférence de liquidation", "effect": "ordre prioritaire de récupération à la sortie"},
    "anti-dilution": {"fr": "protection anti-dilution", "effect": "ajustement potentiel en cas de tour à la baisse"},
    "pro rata": {"fr": "droit de suivre", "effect": "possibilité de maintenir sa part lors d'un tour suivant"},
}


def lookup_term(term: str) -> dict[str, str] | None:
    key = str(term or "").strip().casefold()
    item = CORE_TERMS.get(key)
    return {"term": key, **item} if item else None


def decode_clause(clause: str) -> dict[str, str]:
    text = str(clause or "").strip()
    lowered = text.casefold()
    for term, item in CORE_TERMS.items():
        if term in lowered:
            return {"clause": text, "term": term, **item, "status": "documenté"}
    return {"clause": text, "term": "", "fr": "non documenté", "effect": "inconnu", "status": "à vérifier"}
