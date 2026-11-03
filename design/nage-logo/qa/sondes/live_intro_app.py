import asyncio
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/app"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(URL)
        await pg.wait_for_timeout(700)                       # mi-course de l'intro
        ovr = await pg.evaluate("!!document.querySelector('.nage-intro')")
        print("overlay présent à 0.7 s :", ovr)
        await pg.screenshot(path="live_mid.png")
        await pg.wait_for_timeout(2100)                      # fin de la séquence
        st = await pg.evaluate("""()=>({
          overlay: !!document.querySelector('.nage-intro'),
          vis: getComputedStyle(document.querySelector('main.nage-app-root')||document.querySelector('main')).visibility,
          op: getComputedStyle(document.querySelector('main.nage-app-root')||document.querySelector('main')).opacity})""")
        print("après intro :", st)
        await pg.screenshot(path="live_end.png")
        nb1 = await pg.evaluate("document.querySelectorAll('[aria-label=\\'Actualiser les fichiers\\']').length")
        print("gérique : boutons interactifs présents =", nb1)
        await b.close()

asyncio.run(main())
