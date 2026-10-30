"""Page Objects Playwright des parcours Career (SPEC-009)."""

from .base import CareerPage
from .offer_detail import OfferDetailPage
from .offer_list import OfferListPage
from .pipeline import PipelinePage
from .prep_wizard import PrepWizardPage
from .profile import ProfilePage

__all__ = [
    "CareerPage",
    "OfferDetailPage",
    "OfferListPage",
    "PipelinePage",
    "PrepWizardPage",
    "ProfilePage",
    "build_pages",
]


def build_pages(app: object) -> object:
    """Instancie les Page Objects sur le même navigateur et la même origine."""

    from types import SimpleNamespace

    kwargs = {
        "page": app.page,  # type: ignore[attr-defined]
        "origin": app.origin,  # type: ignore[attr-defined]
        "network": app.network,  # type: ignore[attr-defined]
        "downloads_dir": app.downloads_dir,  # type: ignore[attr-defined]
    }
    pages = SimpleNamespace(
        offers=OfferListPage(**kwargs),
        profile=ProfilePage(**kwargs),
        detail=OfferDetailPage(**kwargs),
        prep=PrepWizardPage(**kwargs),
        pipeline=PipelinePage(**kwargs),
    )
    pages.offers.open()
    return pages
