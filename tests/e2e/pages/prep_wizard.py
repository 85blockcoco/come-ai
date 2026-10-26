"""Preparation wizard: variant recommendation, coverage and local kit."""

from __future__ import annotations

from typing import Any

from pages.base import BasePage
from utils import artifact_paths, mandatory_coverage


class PrepWizardPage(BasePage):
    def analyse(self, title: str) -> None:
        self.show("stagehunter")
        select = self.page.locator("#stagehunter-prep-job")
        value = select.locator("option", has_text=title).first.get_attribute("value")
        assert value, f"Offre « {title} » absente du sélecteur de préparation."
        select.select_option(value=value)
        self.page.locator("#stagehunter-prep-submit").click()
        prep = self.page.locator("#stagehunter-prep")
        prep.wait_for(state="visible")
        prep.locator("h4", has_text=title).wait_for(state="visible")
        prep.get_by_text("Variante CV recommandée").wait_for(state="visible")
        prep.get_by_text("Couverture obligatoire").first.wait_for(state="visible")

    def prep_text(self) -> str:
        return self.page.locator("#stagehunter-prep").inner_text()

    def mandatory_coverage(self) -> float:
        return mandatory_coverage(self.prep_text())

    def recommended_variant(self) -> str:
        return self.page.locator("#stagehunter-prep .variant-specific p").first.inner_text().strip()

    def assert_gap_with_source(self, requirement: str) -> None:
        gaps = self.page.locator("#stagehunter-prep .variant-specific li")
        texts = gaps.all_inner_texts()
        matching = [text for text in texts if requirement in text]
        assert matching, f"Aucun écart pour {requirement!r} parmi {texts}"
        assert any("Source :" in text for text in matching)

    def prepare_kit(self, language: str, variant: str) -> dict[str, Any]:
        self.page.locator("#stagehunter-prep .kit-language-select").select_option(language)
        self.page.locator("#stagehunter-prep .kit-variant-select").select_option(variant)
        with self.page.expect_response(
            lambda response: response.url.endswith("/api/career/application-kits")
            and response.request.method == "POST"
        ) as response_info:
            self.page.get_by_role("button", name="Préparer le kit de candidature").click()
        payload = response_info.value.json()
        self.page.locator("#view-applications").wait_for(state="visible")
        kit = self.page.locator(".application-kit", has_text="Kit de candidature local").first
        kit.wait_for(state="visible", timeout=20_000)
        return self.kit_payload(kit, payload)

    @staticmethod
    def kit_payload(kit: Any, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        cv_area, letter_area = kit.locator("textarea").all()[:2]
        artifacts = artifact_paths(
            kit.locator(".variant-specific li").all_inner_texts()
        )
        if not artifacts and payload:
            artifacts = {
                {"cv": "CV ciblé DOCX", "cover_letter": "Lettre ciblée DOCX", "prep_sheet": "Fiche de préparation"}[
                    key
                ]: path
                for key, path in (payload.get("artifacts") or {}).items()
            }
        return {
            "cv": cv_area.input_value(),
            "letter": letter_area.input_value(),
            "artifacts": artifacts,
            "disclaimer": kit.locator(".application-kit-disclaimer").inner_text(),
            "checks": kit.locator(".application-kit-checks").inner_text(),
            "payload": payload or {},
        }

    def kit(self) -> Any:
        return self.page.locator(".application-kit", has_text="Kit de candidature local").first

    def _download_artifact(self, kind: str) -> str:
        """Download one generated kit artifact through its UI link."""
        with self.page.expect_download() as download_info:
            self.kit().locator(f'a[data-artifact="{kind}"]').click()
        return download_info.value.suggested_filename

    def download_cv_docx(self) -> str:
        return self._download_artifact("cv")

    def download_letter_docx(self) -> str:
        return self._download_artifact("cover_letter")

    def download_prep_sheet(self) -> str:
        return self._download_artifact("prep_sheet")
