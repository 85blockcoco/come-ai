import asyncio
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path("prototype.html").resolve().as_uri()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":1700})
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        pg.on("console", lambda m: print(m.type.upper(), m.text) if m.type in ("error","warning") else None)
        await pg.goto(url)
        await pg.wait_for_timeout(3200)
        print("wordmark opacity:", await pg.eval_on_selector("#wordmark", "el=>getComputedStyle(el).opacity"))
        print("halfL transform:", await pg.eval_on_selector("#halfL", "el=>getComputedStyle(el).transform"))
        print("fakeui opacity:", await pg.eval_on_selector("#fakeui", "el=>getComputedStyle(el).opacity"))
        print("anims:", await pg.evaluate("currentAnims.length"))
        # rejouer et figer à mi-course
        await pg.evaluate("playIntro()")
        await pg.wait_for_timeout(900)
        await pg.screenshot(path="shot_mid.png")
        await b.close()

asyncio.run(main())
