import asyncio
import pathlib
from playwright.async_api import async_playwright

async def main():
    url = pathlib.Path("prototype.html").resolve().as_uri()
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width":1300, "height":980})
        pg.on("console", lambda m: print("CONSOLE:", m.text))
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(url)
        await pg.wait_for_timeout(380)
        r = await pg.evaluate("""()=>{
          const l=document.querySelector('#halfL');
          const kf=[{transform:'translateX(0)'},{transform:'translateX(-300px)', offset:0.42},{transform:'translateX(-676px)'}];
          kf[2]={...kf[2], offset:1};
          const a=l.animate(kf,{duration:2200, fill:'both', easing:'ease-in-out'});
          return {createdExisting:l.getAnimations().length,
                  eff:getComputedStyle(l).transform};
        }""")
        print("t=0:", r)
        await pg.wait_for_timeout(700)
        print("t=700:", await pg.evaluate("({t:getComputedStyle(document.querySelector('#halfL')).transform, a:document.querySelector('#halfL').getAnimations().length})"))
        await b.close()

asyncio.run(main())
