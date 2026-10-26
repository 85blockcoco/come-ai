"""Petit adaptateur « page » pour les parcours E2E (SPEC-007).

Deux implémentations du même contrat :

* ``BrowserPage`` — Playwright/Chromium réel (job CI ``browser-e2e``) ;
* ``HttpPage`` — repli HTTP déterministe quand Playwright n'est pas installé,
  pour que les mêmes scénarios restent exécutables en local sans installation.

Les tests ne connaissent que ce contrat : ``open``, ``api`` et ``download``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass
class ApiResult:
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""

    def json(self) -> Any:
        return json.loads(self.text) if self.text else None


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def synthetic_offer(**overrides: Any) -> dict[str, Any]:
    payload = fixture("offers/synthetic_offer.json")
    payload.update(overrides)
    return payload


def synthetic_profile(**overrides: Any) -> dict[str, Any]:
    payload = fixture("profiles/synthetic_profile.json")
    payload.update(overrides)
    return payload


def wait_for_app_ready(page: Any) -> None:
    """Attend la fin du chargement asynchrone de l'espace Career.

    Les tests navigateur interagissent avec les formulaires et le sélecteur
    d'offres : attendre le badge de santé et la note de profil évite de saisir
    des données qu'un ``loadProfile`` encore en vol écraserait.
    """
    page.wait_for_text("#career-health", "aucune candidature envoyée")
    page.wait_for_text("#profile-readiness-score", "Profil prêt à")


def run_offer_analysis_ui(page: Any, job_id: str, *, expect: str | None = None) -> str:
    """Parcours réel dans l'UI Stage Hunter : offre → analyse → panneau de prépa.

    Nécessite une page navigateur ; les étapes misent en scène les mêmes
    éléments que l'utilisateur clique (onglet, sélecteur d'offre, bouton
    « Analyser cette offre »).
    """
    page.click("#tab-stagehunter")
    page.wait_for_option("#stagehunter-prep-job", job_id)
    page.select("#stagehunter-prep-job", job_id)
    page.click("#stagehunter-prep-submit")
    page.wait_for_text("#stagehunter-prep", "Variante CV recommandée")
    if expect:
        page.wait_for_text("#stagehunter-prep", expect)
    return page.text("#stagehunter-prep")


def generate_kit_from_prep_ui(page: Any, *, variant: str = "m_a") -> str:
    """Depuis le panneau de préparation, génère le kit et ouvre sa vue Candidatures."""
    page.select(".kit-variant-select", variant)
    page.click_button("#stagehunter-prep", "Préparer le kit de candidature")
    page.wait_for("#view-applications:not([hidden])")
    page.wait_for(".application-kit:not([hidden])")
    page.wait_for_text(".application-kit:not([hidden])", "Kit de candidature local")
    return page.text(".application-kit:not([hidden])")


def fill_profile_ui(page: Any, profile: dict[str, Any]) -> None:
    """Renseigne puis enregistre le profil via le vrai formulaire de l'UI."""
    page.click("#tab-profile")
    page.wait_for("#view-profile:not([hidden])")
    page.fill("#profile-display-name", str(profile.get("display_name", "")))
    page.fill("#profile-education", str(profile.get("education", "")))
    page.fill("#profile-experience", str(profile.get("experience", "")))
    page.fill("#profile-skills", str(profile.get("skills", "")))
    page.fill("#profile-languages", str(profile.get("languages", "")))
    page.click("#profile-form button[type=submit]")
    page.wait_for_text("#career-message", "Profil enregistré localement.")


class HttpPage:
    """Repli hors navigateur : mêmes requêtes, même serveur applicatif."""

    mode = "http"
    supports_ui = False

    def __init__(self, base_url: str) -> None:
        import httpx

        self.base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=30.0)

    def __enter__(self) -> "HttpPage":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def open(self, path: str) -> str:
        response = self._client.get(path)
        assert response.status_code == 200, f"GET {path} → {response.status_code}"
        return response.text

    def api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> ApiResult:
        response = self._client.request(method, path, json=payload)
        content_type = response.headers.get("content-type", "")
        readable = ("json" in content_type) or content_type.startswith("text/")
        return ApiResult(
            status=response.status_code,
            text=response.content.decode("utf-8", "replace") if readable else "",
            headers=dict(response.headers),
            content=response.content,
        )

    def download(self, path: str) -> ApiResult:
        return self.api("GET", path)


class BrowserPage:
    """Page Playwright réelle ; ``page.request`` partage le contexte navigateur."""

    mode = "browser"
    supports_ui = True

    def __init__(self, page: Any, base_url: str) -> None:
        self._page = page
        self.base_url = base_url

    # --- interactions UI (réservées au mode navigateur) ---------------------

    def click(self, selector: str) -> None:
        self._page.click(selector, timeout=20_000)

    def fill(self, selector: str, value: str) -> None:
        self._page.fill(selector, value, timeout=20_000)

    def select(self, selector: str, value: str) -> None:
        self._page.select_option(selector, value, timeout=20_000)

    def text(self, selector: str) -> str:
        return self._page.locator(selector).first.inner_text(timeout=20_000)

    def value(self, selector: str) -> str:
        return self._page.locator(selector).first.input_value(timeout=20_000)

    def count(self, selector: str) -> int:
        return self._page.locator(selector).count()

    def wait_for(self, selector: str, *, state: str = "visible", timeout: int = 20_000) -> None:
        self._page.locator(selector).first.wait_for(state=state, timeout=timeout)

    def wait_for_option(self, selector: str, value: str, *, timeout: int = 20_000) -> None:
        self._page.locator(f'{selector} option[value="{value}"]').first.wait_for(
            state="attached", timeout=timeout
        )

    def click_button(self, container: str, text: str) -> None:
        self._page.locator(container).get_by_role("button", name=text, exact=True).first.click(
            timeout=20_000
        )

    def download_in(self, container: str, label: str) -> ApiResult:
        """Clique un lien de téléchargement de l'UI et restitue son contenu."""
        with self._page.expect_download(timeout=30_000) as pending:
            self._page.locator(container).get_by_role("link", name=label, exact=True).first.click(
                timeout=20_000
            )
        download = pending.value
        content = b""
        if download is not None:
            path = download.path()
            if path:
                content = Path(path).read_bytes()
        return ApiResult(status=200, text="", headers={}, content=content)

    def wait_for_text(self, selector: str, needle: str, *, timeout: int = 20_000) -> None:
        self._page.locator(selector).filter(has_text=needle).first.wait_for(state="attached", timeout=timeout)

    def open(self, path: str) -> str:
        response = self._page.goto(f"{self.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None and response.ok, f"GET {path} → {response.status if response else 'aucune réponse'}"
        return self._page.content()

    def _result(self, response: Any) -> ApiResult:
        body = response.body()
        content_type = response.headers.get("content-type", "")
        readable = ("json" in content_type) or content_type.startswith("text/")
        return ApiResult(
            status=response.status,
            text=body.decode("utf-8", "replace") if readable else "",
            headers={key.lower(): value for key, value in response.headers.items()},
            content=body,
        )

    def api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> ApiResult:
        response = self._page.request.fetch(
            f"{self.base_url}{path}",
            method=method,
            data=payload,
            headers={"Content-Type": "application/json"} if payload is not None else {},
        )
        return self._result(response)

    def download(self, path: str) -> ApiResult:
        return self._result(self._page.request.get(f"{self.base_url}{path}"))
