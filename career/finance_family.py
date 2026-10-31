"""Finance stage family classifier (N100-C07)."""

from __future__ import annotations


FAMILIES = ("m&a", "cib", "corporate finance", "markets", "risk", "audit", "consulting", "other")

_KEYWORDS: dict[str, list[str]] = {
    "m&a": ["m&a", "mergers", "acquisitions", "fusion", "acquisition"],
    "cib": ["cib", "investment banking", "banque d'investissement", "advisory"],
    "corporate finance": ["corporate finance", "finance d'entreprise", "valuation", "valorisation", "dcf"],
    "markets": ["markets", "trading", "sales", "marchés"],
    "risk": ["risk", "risque", "compliance", "conformité"],
    "audit": ["audit", "comptabilité", "accounting"],
    "consulting": ["consulting", "conseil", "strategy", "stratégie"],
}


def classify_finance_family(text: str) -> str:
    t = (text or "").lower()
    scores: dict[str, int] = {f: 0 for f in FAMILIES}
    for family, kws in _KEYWORDS.items():
        for kw in kws:
            if kw in t:
                scores[family] += 1
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "other"
    return best