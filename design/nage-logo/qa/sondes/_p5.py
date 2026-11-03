import asyncio
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path("prototype.html").resolve().as_uri()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":980})
        await pg.add_init_script("window.__dbg=1")
        pg.on("console", lambda m: print("CONSOLE:", m.text))
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(url)
        await pg.wait_for_timeout(2500)
        r = await pg.evaluate("""()=>{const l=document.querySelector('#halfL');
          return {o:getComputedStyle(l).opacity, t:getComputedStyle(l).transform, a:l.getAnimations().length}}""")
        print("post-auto:", r)
        await pg.evaluate("playIntro()")
        await pg.wait_for_timeout(350)
        print("intro2:", await pg.evaluate("""()=>{const l=document.querySelector('#halfL');
          return {o:getComputedStyle(l).opacity, t:getComputedStyle(l).transform, a:l.getAnimations().length}}"""))
        await pg.screenshot(path="midseq.png")
        await b.close()

asyncio.run(main())
