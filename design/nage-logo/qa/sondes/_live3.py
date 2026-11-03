import asyncio
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/app"

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        await pg.goto(URL)
        await pg.wait_for_timeout(500)
        r = await pg.evaluate("""()=>{
          const ovs=[...document.querySelectorAll('.nage-intro')];
          const ovl=ovs.find(x=>!x.hidden && getComputedStyle(x).display!=='none');
          if(!ovl) return {noOverlay:true};
          const svg=ovl.querySelector('svg');
          const hl=svg.querySelector('[data-half="L"]')||svg.querySelector('#halfL');
          const ua=hl?hl.querySelectorAll('use'):null;
          const geo=document.querySelectorAll('#ribbonGeo').length;
          const gEm=document.querySelectorAll('#gEm').length;
          const box=svg.getBoundingClientRect();
          return { geo, gEm, svgW:box.width, svgH:box.height,
                   uses: ua? [...ua].map(u=>({f:getComputedStyle(u).fill.slice(0,80),
                                               box:(()=>{const b=u.getBoundingClientRect();return [b.width.toFixed(0),b.height.toFixed(0)];})() })):null};
        }""")
        print(r)
        await b.close()

asyncio.run(main())
