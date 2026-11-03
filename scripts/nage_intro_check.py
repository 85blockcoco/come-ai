#!/usr/bin/env python3
"""Vérifie les assets SVG NAGe dans un Chromium headless avec Playwright."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "career_static" / "nage_assets"
SVG_FILES = (
    "favicon.svg",
    "nage-logo.svg",
    "nage-logo-mono.svg",
    "nage-logo-stencil.svg",
)


async def inspect_asset(page, filename: str) -> list[str]:
    path = ASSET_DIR / filename
    if not path.is_file():
        return [f"{filename}: fichier introuvable"]

    await page.goto(path.as_uri(), wait_until="load")
    result = await page.evaluate(
        """() => {
          const svg = document.documentElement;
          const box = svg.viewBox && svg.viewBox.baseVal;
          const uses = [...svg.querySelectorAll('use')];
          const mirrored = uses.filter((use) =>
            use.parentElement?.closest('g[transform="scale(-1,1)"]')
          );
          return {
            hasSvgRoot: svg.localName === 'svg',
            rasterImages: svg.querySelectorAll('image').length,
            viewBox: box ? [box.x, box.y, box.width, box.height] : null,
            uses: uses.map((use) => use.getAttribute('href') || use.getAttribute('xlink:href')),
            mirroredUses: mirrored.length,
          };
        }"""
    )

    errors = []
    if not result["hasSvgRoot"]:
        errors.append("racine SVG absente")
    if result["rasterImages"]:
        errors.append(f"contient {result['rasterImages']} élément(s) <image>")
    if result["viewBox"] != [0, 0, 512, 512]:
        errors.append(f"viewBox attendu 0 0 512 512, reçu {result['viewBox']}")
    if len(result["uses"]) != 2 or result["uses"].count("#nage-half") != 2:
        errors.append(f"2 références #nage-half attendues, reçues {result['uses']}")
    if result["mirroredUses"] != 1:
        errors.append(f"1 moitié dans le groupe miroir attendue, reçue {result['mirroredUses']}")

    state = "ÉCHEC" if errors else "OK"
    print(f"{state} {filename}: vectoriel, viewBox 512×512, miroir vérifié" if not errors else f"ÉCHEC {filename}: {'; '.join(errors)}")
    return errors


async def main() -> int:
    async with async_playwright() as playwright:
        # Utilise le Chrome déjà présent sur le poste pour éviter de télécharger
        # une seconde version du navigateur Playwright.
        browser = await playwright.chromium.launch(headless=True, channel="chrome")
        try:
            page = await browser.new_page()
            failures = []
            for filename in SVG_FILES:
                failures.extend(await inspect_asset(page, filename))
            return 1 if failures else 0
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("Contrôle interrompu.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        print(f"Contrôle impossible : {error}", file=sys.stderr)
        raise SystemExit(1)
