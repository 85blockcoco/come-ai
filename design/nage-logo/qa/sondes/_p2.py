import asyncio
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path("prototype.html").resolve().as_uri()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":980})
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(url)
        await pg.eval_on_selector("body", "el=>el.remove()")
        await pg.reload()
        await pg.wait_for_timeout(300)
        await pg.evaluate("playIntro()")
        await pg.wait_for_timeout(200)
        n = await pg.evaluate("document.querySelector('#halfL').getAnimations().length")
        print("anims halfL après 200ms :", n)
        await pg.screenshot(path="probe2.png")
        await b.close()

asyncio.run(main())
