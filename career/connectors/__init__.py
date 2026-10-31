"""Optional public ATS adapters. Providers are registered but disabled by default."""

from dataclasses import dataclass

from .public_ats import AshbyConnector, LeverConnector, SmartRecruitersConnector
from .welcome_jungle import WelcomeJungleConnector, register_welcome_jungle_connector
from .jobteaser import JobTeaserConnector, register_jobteaser_connector
from .talent_com import TalentComConnector, register_talent_com_connector
from .apec import ApecConnector, register_apec_connector
from .uk_sources import UkSourcesConnector, register_uk_sources_connector


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
    "welcome_jungle": ConnectorSpec(
        provider="welcome_jungle",
        documentation_url="https://www.welcometothejungle.com/fr/jobs",
        doc_verified=True,
    ),
    "jobteaser": ConnectorSpec(
        provider="jobteaser",
        documentation_url="https://www.jobteaser.com/en/jobs",
        doc_verified=True,
    ),
    "talent_com": ConnectorSpec(
        provider="talent_com",
        documentation_url="https://www.talent.com",
        doc_verified=True,
    ),
    "apec": ConnectorSpec(
        provider="apec",
        documentation_url="https://www.apec.fr",
        doc_verified=True,
    ),
    "prospects": ConnectorSpec(
        provider="prospects",
        documentation_url="https://www.prospects.ac.uk",
        doc_verified=True,
    ),
    "gradcracker": ConnectorSpec(
        provider="gradcracker",
        documentation_url="https://www.gradcracker.com",
        doc_verified=True,
    ),
    "targetjobs": ConnectorSpec(
        provider="targetjobs",
        documentation_url="https://targetjobs.co.uk",
        doc_verified=True,
    ),
}

# Internal connector registry for the exploration service
_CONNECTOR_REGISTRY: dict[str, tuple] = {}


def _init_connector_registry() -> dict[str, tuple]:
    """Initialize the connector registry with all available connectors."""
    registry: dict[str, tuple] = {}
    # Public ATS connectors (class-based)
    registry["lever"] = (LeverConnector, "class")
    registry["ashby"] = (AshbyConnector, "class")
    registry["smartrecruiters"] = (SmartRecruitersConnector, "class")
    # New source connectors (function-based)
    register_welcome_jungle_connector(registry)
    register_jobteaser_connector(registry)
    register_talent_com_connector(registry)
    register_apec_connector(registry)
    register_uk_sources_connector(registry)
    return registry


CONNECTOR_REGISTRY = _init_connector_registry()


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
        "smartrecruiters": SmartRecruitersConnector(enabled=True, enrich_details=True),
        "welcome_jungle": WelcomeJungleConnector(enabled=True),
        "jobteaser": JobTeaserConnector(enabled=True),
        "talent_com": TalentComConnector(enabled=True),
        "apec": ApecConnector(enabled=True),
        "prospects": UkSourcesConnector(enabled=True),
        "gradcracker": UkSourcesConnector(enabled=True),
        "targetjobs": UkSourcesConnector(enabled=True),
    }

__all__ = [
    "CONNECTOR_SPECS",
    "CONNECTOR_REGISTRY",
    "AshbyConnector",
    "ConnectorSpec",
    "default_exploration_connectors",
    "LeverConnector",
    "SmartRecruitersConnector",
    "UkSourcesConnector",
]
