"""Optional public ATS adapters. Providers are registered but disabled by default."""

from dataclasses import dataclass

from .public_ats import AshbyConnector, LeverConnector, RecruiteeConnector, SmartRecruitersConnector
from .welcome_jungle import WelcomeJungleConnector, register_welcome_jungle_connector
from .jobteaser import JobTeaserConnector, register_jobteaser_connector
from .talent_com import TalentComConnector, register_talent_com_connector
from .apec import ApecConnector, register_apec_connector
from .linkedin_europe import LinkedInEuropeConnector, register_linkedin_europe_connector
from .eures import EuresConnector, register_eures_connector
from .jobteaser_intl import JobTeaserIntlConnector, register_jobteaser_intl_connector
from .glassdoor_intl import GlassdoorIntlConnector, register_glassdoor_intl_connector


@dataclass(frozen=True)
class ConnectorSpec:
    provider: str
    documentation_url: str
    doc_verified: bool
    enabled_by_default: bool = False
    known_conditions: str = ""


CONNECTOR_SPECS = {
    "lever": ConnectorSpec(
        provider="lever",
        documentation_url="https://github.com/lever/postings-api",
        doc_verified=True,
        known_conditions="Flux public documenté sans clé ; pagination bornée côté client.",
    ),
    "ashby": ConnectorSpec(
        provider="ashby",
        documentation_url="https://developers.ashbyhq.com/docs/public-job-posting-api",
        doc_verified=True,
        known_conditions="Flux public documenté sans clé ; une ressource par board.",
    ),
    "smartrecruiters": ConnectorSpec(
        provider="smartrecruiters",
        documentation_url="https://developers.smartrecruiters.com/docs/posting-api",
        doc_verified=True,
        known_conditions="API posting publique documentée ; pagination bornée.",
    ),
    "recruitee": ConnectorSpec(
        provider="recruitee",
        documentation_url="https://support.recruitee.com/en/articles/1066286-show-jobs-on-your-own-website",
        doc_verified=True,
        known_conditions="API publique du site carrière sans authentification ; photographie temporelle.",
    ),
    "welcome_jungle": ConnectorSpec(
        provider="welcome_jungle",
        documentation_url="https://www.welcometothejungle.com/fr/jobs",
        doc_verified=True,
        known_conditions="Source publique ; extraction locale bornée et déclenchée explicitement.",
    ),
    "jobteaser": ConnectorSpec(
        provider="jobteaser",
        documentation_url="https://www.jobteaser.com/en/jobs",
        doc_verified=True,
        known_conditions="Source publique ; extraction locale bornée et déclenchée explicitement.",
    ),
    "talent_com": ConnectorSpec(
        provider="talent_com",
        documentation_url="https://www.talent.com",
        doc_verified=True,
        known_conditions="Source publique ; extraction locale bornée et déclenchée explicitement.",
    ),
    "apec": ConnectorSpec(
        provider="apec",
        documentation_url="https://www.apec.fr",
        doc_verified=True,
        known_conditions="Source publique ; extraction locale bornée et déclenchée explicitement.",
    ),
    "linkedin_europe": ConnectorSpec("linkedin_europe", "https://www.linkedin.com/jobs/search", True, known_conditions="Recherche publique internationale bornée."),
    "eures": ConnectorSpec("eures", "https://ec.europa.eu/eures/eures-api/swagger-ui.html", True, known_conditions="API publique européenne bornée."),
    "jobteaser_intl": ConnectorSpec("jobteaser_intl", "https://www.jobteaser.com/en/jobs", True, known_conditions="Recherche publique internationale bornée."),
    "glassdoor_intl": ConnectorSpec("glassdoor_intl", "https://www.glassdoor.com/Job/jobs.htm", True, known_conditions="Recherche publique internationale bornée."),
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
    registry["recruitee"] = (RecruiteeConnector, "class")
    # New source connectors (function-based)
    register_welcome_jungle_connector(registry)
    register_jobteaser_connector(registry)
    register_talent_com_connector(registry)
    register_apec_connector(registry)
    register_linkedin_europe_connector(registry)
    register_eures_connector(registry)
    register_jobteaser_intl_connector(registry)
    register_glassdoor_intl_connector(registry)
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
        "linkedin_europe": LinkedInEuropeConnector(enabled=True),
        "eures": EuresConnector(enabled=True),
        "jobteaser_intl": JobTeaserIntlConnector(enabled=True),
        "glassdoor_intl": GlassdoorIntlConnector(enabled=True),
    }

__all__ = [
    "CONNECTOR_SPECS",
    "CONNECTOR_REGISTRY",
    "AshbyConnector",
    "ConnectorSpec",
    "default_exploration_connectors",
    "LeverConnector",
    "LinkedInEuropeConnector",
    "EuresConnector",
    "JobTeaserIntlConnector",
    "GlassdoorIntlConnector",
    "RecruiteeConnector",
    "SmartRecruitersConnector",
]
