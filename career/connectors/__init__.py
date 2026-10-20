"""Optional public ATS adapters. Providers are registered but disabled by default."""

from dataclasses import dataclass

from .public_ats import AshbyConnector, LeverConnector, RecruiteeConnector, SmartRecruitersConnector


@dataclass(frozen=True)
class ConnectorSpec:
    provider: str
    documentation_url: str
    doc_verified: bool
    enabled_by_default: bool = False
    """Known, reviewed conditions of the public source (vague but honest)."""
    known_conditions: str = ""


CONNECTOR_SPECS = {
    "lever": ConnectorSpec(
        provider="lever",
        documentation_url="https://github.com/lever/postings-api",
        doc_verified=True,
        known_conditions="Flux public documenté sans clé ; pagination bornée côté client ; quick snapshot.",
    ),
    "ashby": ConnectorSpec(
        provider="ashby",
        documentation_url="https://developers.ashbyhq.com/docs/public-job-posting-api",
        doc_verified=True,
        known_conditions="Flux public documenté sans clé ; ressources unique par board ; quick snapshot.",
    ),
    "smartrecruiters": ConnectorSpec(
        provider="smartrecruiters",
        documentation_url="https://developers.smartrecruiters.com/docs/posting-api",
        doc_verified=True,
        known_conditions="API posting publique documentée, destination PUBLIC uniquement, pagination bornée.",
    ),
    "recruitee": ConnectorSpec(
        provider="recruitee",
        documentation_url="https://support.recruitee.com/en/articles/1066286-show-jobs-on-your-own-website",
        doc_verified=True,
        known_conditions="API publique du site carrière documentée sans authentification (page par défaut "
                         "uniquement, le vendeur ignore les paramètres de pagination mesurés 2026-10-20).",
    ),
}


def default_exploration_connectors(greenhouse_connector):
    """Return connectors used only after an explicit Explorer button click.

    Public ATS connector classes remain disabled when instantiated directly.
    The application map enables them because its curated registry and service
    boundary both validate source identity and provenance before any request.
    With no registered source for a provider, enabling it performs no I/O.
    """
    return {
        "greenhouse": greenhouse_connector,
        "lever": LeverConnector(enabled=True),
        "ashby": AshbyConnector(enabled=True),
        "smartrecruiters": SmartRecruitersConnector(enabled=True),
        "recruitee": RecruiteeConnector(enabled=True),
    }

__all__ = [
    "CONNECTOR_SPECS",
    "AshbyConnector",
    "ConnectorSpec",
    "default_exploration_connectors",
    "LeverConnector",
    "RecruiteeConnector",
    "SmartRecruitersConnector",
]
