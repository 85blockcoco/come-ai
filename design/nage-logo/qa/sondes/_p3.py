import asyncio
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path("prototype.html").resolve().as_uri()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":980})
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.evaluate("window.__dbg=1")
        await pg.goto(url)
        await pg.wait_for_timeout(400)
        # animation brute d'opacité sur halfL
        await pg.evaluate("""{
          const l=document.querySelector('#halfL');
          window.__a=l.animate([{opacity:1},{opacity:0.2}],{duration:3000, fill:'both'});
        }""")
        for ms in [50,300,800,1500]:
            await pg.wait_for_timeout(ms if ms==50 else ms - [50,300,800,1500][max(0,[50,300,800,1500].index(ms)-1)])
            o = await pg.evaluate("getComputedStyle(document.querySelector('#halfL')).opacity")
            print(f"t~{ms:>4}ms  halfL opacity={o}")
        # purge + séquence réelle
        await pg.evaluate("playIntro()")
        await pg.wait_for_timeout(350)
        st = await pg.evaluate("""()=>{const l=document.querySelector('#halfL');
          return {o:getComputedStyle(l).opacity, t:getComputedStyle(l).transform,
                  a:l.getAnimations().length}}""")
        print("durant intro:", st)
        await pg.screenshot(path="midseq.png")
        await b.close()

asyncio.run(main())
