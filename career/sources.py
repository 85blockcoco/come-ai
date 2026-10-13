"""Authorized-source contracts and search vocabulary for Côme AI Career.

There is deliberately no HTTP client in this module.  The vocabulary is a
local preparation aid only; a future connector must still be explicitly
authorized, rate-limited and compliant with its source's terms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import JOB_FAMILIES, PRIMARY_LOCATIONS


PERIOD_HINTS = ("2027", "Spring 2027", "H1 2027", "Off-Cycle")
LOCAL_LANGUAGE_HINTS = ("tirocinio", "stage", "Praktikum", "Werkstudent")

# Kept as source-faithful phrases rather than inferred job titles.  A future
# connector must still inspect the original posting to distinguish, for
# example, a student internship from a permanent or senior role.
SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "M&A / Investment Banking": (
        "M&A Intern",
        "Investment Banking Intern",
        "Investment Banking Off-Cycle Analyst",
        "Corporate Finance Advisory Intern",
        "Global Advisory Internship",
        "Transaction Advisory Intern",
        "Stage Fusion-Acquisition",
        "Stage Banque d'Affaires",
    ),
    "Private Equity": (
        "Private Equity Intern",
        "Investment Team Intern",
        "Buyout Intern",
        "Growth Equity Intern",
        "Investment Analyst Intern",
        "Stage Private Equity",
        "Stage Capital-Investissement",
    ),
    "Asset Management": (
        "Asset Management Intern",
        "Portfolio Management Intern",
        "Investment Research Intern",
        "Equity Research Intern",
        "Fixed Income Intern",
        "Investment Management Internship",
        "Stage Gestion d'Actifs",
    ),
    "Sales & Trading": (
        "Sales & Trading Intern",
        "Global Markets Intern",
        "Markets Off-Cycle Analyst",
        "Fixed Income Sales Intern",
        "Equity Sales Intern",
        "Trading Internship",
        "Stage Sales / Trading",
    ),
    "Corporate Finance": (
        "Corporate Finance Intern",
        "Financial Analysis Intern",
        "FP&A Intern",
        "Treasury Intern",
        "Strategic Finance Intern",
        "Valuation Intern",
        "Stage Analyse Financière",
    ),
    "Consulting": (
        "Strategy Consulting Intern",
        "Consulting Intern",
        "Transaction Services Intern",
        "Deals Advisory Intern",
        "Financial Services Consulting Intern",
        "Stage Conseil en Stratégie",
    ),
}


@dataclass(frozen=True)
class DiscoveryRequest:
    """A deterministic query plan, never an authorization to browse."""

    family: str
    terms: tuple[str, ...]
    period_hints: tuple[str, ...] = PERIOD_HINTS
    location_keys: tuple[str, ...] = tuple(key for key, _, _ in PRIMARY_LOCATIONS)


def discovery_request_for(family: str) -> DiscoveryRequest:
    """Build a local Phase-2 query plan for one configured career family."""
    if family not in JOB_FAMILIES or family not in SEARCH_TERMS:
        raise ValueError("Unknown Career Agent family")
    return DiscoveryRequest(family=family, terms=SEARCH_TERMS[family])


class JobSourceConnector(Protocol):
    """An authorized source adapter; implementations must never bypass access rules."""

    name: str

    def discover(self, request: DiscoveryRequest) -> list[dict[str, object]]:
        """Return normalized source data or raise a controlled local error."""


class ManualJobSource:
    """A person pasted or typed the offer locally; no network request occurs."""

    name = "manual"

    def discover(self, request: DiscoveryRequest) -> list[dict[str, object]]:
        _ = request
        return []
