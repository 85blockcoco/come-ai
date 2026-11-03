import asyncio
import sys
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path(sys.argv[1]).resolve().as_uri()
    shot = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":1600}, device_scale_factor=1)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        await pg.goto(url)
        await pg.wait_for_timeout(3500)
        await pg.screenshot(path=shot, full_page=True)
        for e in errs:
            print("ERR:", e)
        await b.close()

asyncio.run(main())
