"""Optional public ATS adapters. Providers are registered but disabled by default."""

from dataclasses import dataclass

from .public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector


@dataclass(frozen=True)
class ConnectorSpec:
    provider: str
    documentation_url: str
    doc_verified: bool
    enabled_by_default: bool = False


CONNECTOR_SPECS = {
    "lever": ConnectorSpec(
        provider="lever",
        documentation_url="https://github.com/lever/postings-api",
        doc_verified=True,
    ),
    "ashby": ConnectorSpec(
        provider="ashby",
        documentation_url="https://developers.ashbyhq.com/docs/public-job-posting-api",
        doc_verified=True,
    ),
    "smartrecruiters": ConnectorSpec(
        provider="smartrecruiters",
        documentation_url="https://developers.smartrecruiters.com/docs/posting-api",
        doc_verified=True,
    ),
}


def default_exploration_connectors(greenhouse_connector):
    """Return the app's connector map; new ATS adapters remain inert by default."""
    return {
        "greenhouse": greenhouse_connector,
        "lever": LeverConnector(),
        "ashby": AshbyConnector(),
        "smartrecruiters": SmartRecruitersConnector(),
    }

__all__ = [
    "CONNECTOR_SPECS",
    "AshbyConnector",
    "ConnectorSpec",
    "default_exploration_connectors",
    "LeverConnector",
    "SmartRecruitersConnector",
]
