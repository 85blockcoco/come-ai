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
        await pg.wait_for_timeout(3400)
        await pg.evaluate("playIntro()")
        for ms, name in [(300,"a"),(900,"b"),(1500,"c"),(2100,"d")]:
            await pg.wait_for_timeout(ms if name=="a" else ms- (0 if name=="a" else [300,900,1500,2100][[0,1,2,3].index([0])] if False else {"a":300,"b":600,"c":600,"d":600}[name]))
            st = await pg.evaluate("""()=>({
              lT:getComputedStyle(document.querySelector('#halfL')).transform,
              lO:getComputedStyle(document.querySelector('#halfL')).opacity,
              lR:document.querySelector('#halfL').getBoundingClientRect().toJSON(),
              svgO:getComputedStyle(document.querySelector('#logoSvg')).opacity,
              uiO:getComputedStyle(document.querySelector('#fakeui')).opacity,
              wO:getComputedStyle(document.querySelector('#wordmark')).opacity})""")
            print(name, st)
            await pg.screenshot(path=f"seq_{name}.png")
        await b.close()

asyncio.run(main())
