"""Page Object du choix de variante et de la génération du kit."""

from __future__ import annotations

from pathlib import Path

from .base import CareerPage


class PrepWizardPage(CareerPage):
    def choose_variant(self, variant: str) -> "PrepWizardPage":
        select = self.page.locator("#stagehunter-prep .kit-variant-select")
        select.select_option(variant)
        assert select.input_value() == variant, f"Variante {variant} non sélectionnée"
        return self

    def choose_language(self, language: str) -> "PrepWizardPage":
        self.page.select_option("#stagehunter-prep .kit-language-select", language)
        return self

    def generate_kit(self) -> "PrepWizardPage":
        self.page.locator("#stagehunter-prep").get_by_role(
            "button", name="Préparer le kit de candidature"
        ).click()
        self.page.wait_for_selector("#view-applications:not([hidden])", timeout=20_000)
        self.page.wait_for_selector(
            "#applications-list .application-kit h4:text-is('Kit de candidature local')",
            timeout=30_000,
        )
        self.wait_message("Kit de candidature prêt localement")
        return self

    # -- contenu du kit -------------------------------------------------
    def kit(self):
        return self.page.locator("#applications-list .application-kit:visible").first

    def kit_text(self) -> str:
        return self.kit().inner_text()

    def cv_text(self) -> str:
        return self.kit().locator(".application-kit-documents textarea").nth(0).input_value()

    def letter_text(self) -> str:
        return self.kit().locator(".application-kit-documents textarea").nth(1).input_value()

    def fact_checks_text(self) -> str:
        return self.kit().locator(".application-kit-checks").inner_text()

    def variant_label(self) -> str:
        text = self.kit_text()
        for line in text.splitlines():
            if line.startswith("Variante générée"):
                return line
        raise AssertionError(f"Aucune variante générée dans le kit : {text[:800]}")

    # -- preuve persistée (l'API GET du kit ne renvoie pas les artefacts) --
    def application_id(self) -> str:
        value = self.kit().get_attribute("data-application-id")
        assert value, "Le kit affiché n'est rattaché à aucun suivi"
        return value

    def job_id(self) -> str:
        value = self.kit().get_attribute("data-job-id")
        assert value, "Le kit affiché n'est rattaché à aucune offre"
        return value

    def persisted_kit(self) -> dict[str, object]:
        application_id = self.application_id()
        response = self.page.request.get(
            f"{self.origin}/api/career/applications/{application_id}/kit"
        )
        assert response.ok, f"Kit introuvable via l'API : {response.status}"
        return response.json()

    def targeted_artifacts(self, language: str = "fr") -> dict[str, str]:
        import json

        response = self.page.request.post(
            f"{self.origin}/api/career/application-kits",
            data=json.dumps(
                {
                    "job_id": self.job_id(),
                    "language": language,
                    "variant": self.persisted_kit().get("draft", {}).get("variant", "m_a"),
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        assert response.ok, f"Artefacts du kit indisponibles : {response.status}"
        payload = response.json()
        return dict(payload.get("artifacts") or {})

    def download_documents(self) -> list[Path]:
        links = self.kit().locator(".application-kit-documents a[download]")
        count = links.count()
        assert count >= 2, f"Liens de téléchargement absents (trouvés : {count})"
        saved: list[Path] = []
        for index in range(count):
            link = links.nth(index)
            label = (link.get_attribute("aria-label") or link.inner_text()).strip()
            with self.page.expect_download(timeout=20_000) as download_info:
                link.click()
            download = download_info.value
            suffix = Path(download.suggested_filename).suffix.lower()
            assert suffix in {".docx", ".pdf"}, f"Export inattendu pour {label} : {suffix}"
            target = self.downloads_dir / f"{index:02d}-{download.suggested_filename}"
            download.save_as(str(target))
            assert target.stat().st_size > 0, f"Fichier vide : {target}"
            saved.append(target)
        return saved
