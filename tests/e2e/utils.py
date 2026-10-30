"""Outils partagés par les parcours E2E Career (SPEC-009)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
OFFERS_DIR = FIXTURES_DIR / "offers"
PROFILES_DIR = FIXTURES_DIR / "profiles"

COVERAGE_PATTERN = re.compile(r"Couverture factuelle du CV\s*:\s*(\d+)\s*%")
# Un terme du vocabulaire métier n'est acceptable dans un document que s'il est
# présenté comme une lacune à vérifier, jamais comme un fait acquis.
PLACEHOLDER_MARKERS = (
    "à vérifier",
    "a verifier",
    "à compléter",
    "a completer",
    "ajouter preuve",
    "non trouvé",
    "non trouve",
    "non étayé",
    "non etaye",
    "à confirmer",
    "a confirmer",
    "[",
)
# Reformuler une exigence de l'offre n'est pas se l'approprier. Ces tournures
# parlent de l'annonce, pas des compétences de la personne.
OFFER_REFERENCE_MARKERS = (
    "votre offre mentionne",
    "l’offre mentionne",
    "l'offre mentionne",
    "l’offre exige",
    "l'offre exige",
    "exigence",
    "poste requiert",
    "requis",
    "requise",
)
# Une appropriation explicite reste une invention, même dans une phrase qui
# parle aussi de l'offre.
POSSESSION_MARKERS = (
    "je maîtrise",
    "j’ai",
    "j'ai",
    "mon expérience",
    "mes compétences",
    "je pratique",
    "je possède",
    "je possede",
)


def load_offer(name: str) -> dict[str, Any]:
    path = OFFERS_DIR / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_profile(name: str) -> dict[str, str]:
    path = PROFILES_DIR / name
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Profil de fixture invalide : {path.name}")
    return {str(key): "" if value is None else str(value) for key, value in data.items()}


def coverage_percent(text: str) -> int:
    match = COVERAGE_PATTERN.search(text)
    if not match:
        raise AssertionError(f"Aucune couverture CV trouvée dans : {text[:600]}")
    return int(match.group(1))


def affirmative_inventions(text: str, term: str) -> list[str]:
    """Lignes qui présentent ``term`` comme un fait, sans marqueur de réserve.

    Une ligne hérite de la réserve de la ligne précédente : un bloc de
    description introduit par « Éléments relevés dans l'offre (à vérifier) »
    reste signalé comme non vérifié même si le terme apparaît sur la ligne
    suivante.
    """

    culprit_lines: list[str] = []
    previous_has_marker = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.casefold()
        line_has_marker = any(marker in lowered for marker in PLACEHOLDER_MARKERS)
        refers_to_offer = any(marker in lowered for marker in OFFER_REFERENCE_MARKERS)
        claims_possession = any(marker in lowered for marker in POSSESSION_MARKERS)
        if term.casefold() in lowered and not (line_has_marker or previous_has_marker):
            if claims_possession or not refers_to_offer:
                culprit_lines.append(line)
        previous_has_marker = line_has_marker
    return culprit_lines


def assert_no_invention(text: str, term: str, label: str) -> None:
    culprits = affirmative_inventions(text, term)
    assert not culprits, (
        f"{label} affirme « {term} » sans preuve ni réserve : {culprits}. "
        "Le kit doit rester factuel et signaler la lacune."
    )


def assert_synthetic_offer(offer: dict[str, Any]) -> None:
    """Empêche toute fuite de données réelles dans les fixtures versionnées."""

    company = str(offer.get("company", ""))
    url = str(offer.get("official_url", ""))
    assert "démo" in company.lower() or "demo" in company.lower(), (
        f"Offre non synthétique (entreprise réelle ?) : {company}"
    )
    assert "example.test" in url, f"URL d'offre non synthétique : {url}"
    description = f"{offer.get('description_original', '')} {offer.get('requirements', '')}".lower()
    assert "synthétique" in description or "synthetique" in description or "démo" in description, (
        "La fixture d'offre doit s'annoncer explicitement comme synthétique."
    )
