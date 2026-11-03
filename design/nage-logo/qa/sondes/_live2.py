import asyncio
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/app"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        pg.on("console", lambda m: print("CONSOLE:", m.type, m.text[:160]))
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(URL)
        await pg.wait_for_timeout(250)
        r = await pg.evaluate("""()=>{
          const els=[...document.querySelectorAll('.nage-intro')].map((el,i)=>({
            i, hidden: el.hidden, cls: el.className,
            hasSvg: !!el.querySelector('svg'),
            halfL: !!el.querySelector('[data-half=\\'L\\']'),
            word: !!el.querySelector('[data-word]'),
            disp: getComputedStyle(el).display,
            op: getComputedStyle(el).opacity,
            zIndex: getComputedStyle(el).zIndex,
            pos: getComputedStyle(el).position}));
          return {els,seen:sessionStorage.getItem('nage_intro_played'),
                  api: typeof window.initNageIntro};
        }""")
        for e in r["els"]:
            print("EL:", e)
        print("sessionStorage:", r["seen"], "| initNageIntro:", r["api"])
        await pg.wait_for_timeout(600)
        await pg.screenshot(path="live_mid2.png")
        await b.close()

asyncio.run(main())
