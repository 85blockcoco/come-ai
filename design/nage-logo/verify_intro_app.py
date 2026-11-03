"""Vérification live de l'intro NAGe sur le serveur réel (CSP compris).

Lance : .venv/bin/python design/nage-logo/verify_intro_app.py
Contrôles :
  1. l'intro joue (overlay .nage-intro monté, logo cloné, phases animées) ;
  2. l'app est masquée pendant l'intro (main.nage-intro-ui-hold) puis visible ;
  3. l'overlay est retiré du DOM après ~2,3 s, événement nage:introend émis ;
  4. rejeu bloqué au second chargement (sessionStorage) ;
  5. prefers-reduced-motion → zéro intro ;
  6. le donneur sprite reste inerte (0×0 px).
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/app"
SCREENS = Path(__file__).resolve().parent / "qa"

RESULTS = []


def ok(cond, label):
    RESULTS.append((bool(cond), label))
    print(("  ✓ " if cond else "  ✗ ") + label)


async def collect(pg, sel_state):
    return await pg.evaluate(sel_state)


async def main():
    SCREENS.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()

        # ---- 1er chargement : l'intro doit jouer ----
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        events = []
        await pg.expose_function("__nageEvent", lambda: events.append(1))
        pg.on("pageerror", lambda e: print("PAGEERR:", e))
        await pg.goto(URL)
        await pg.add_init_script(
            "window.addEventListener('nage:introend',()=>{window.__nageEvent&&window.__nageEvent('end')});")
        await pg.reload()
        await pg.wait_for_timeout(400)

        intro = await pg.evaluate("""()=>{
          const ov=[...document.querySelectorAll('.nage-intro')]
            .filter(x=>getComputedStyle(x).display!=='none'&&!x.classList.contains('nage-intro-donor'));
          const o=ov[0]||null;
          const m=document.querySelector('main.nage-app-root');
          return {overlay: !!o,
                  logoCloned: !!(o&&o.querySelector('svg')&&o.querySelector('[data-half="L"]')
                                 &&getComputedStyle(o.querySelector('[data-half="L"]')).display!=='none'),
                  ribbonsDieux: (()=>{try{const u=o.querySelector('[data-half="L"] use');
                    return u&&u.getBoundingClientRect().width>0;}catch(e){return false;}})(),
                  holdClass: m?m.className:'main absent',
                  donorInert: (function(){const d=document.querySelector('#nageIntroSource');
                    const r=d.getBoundingClientRect();return r.width<2&&r.height<2;})()};}""")
        print("— Intro (premier chargement) :", intro)
        ok(intro["overlay"], "l'overlay .nage-intro est monté")
        ok(intro["logoCloned"], "le logo cloné porte les moitiés data-half")
        ok(intro["ribbonsDieux"], "les rubans peignent (boîte use > 0)")
        ok("nage-intro-ui-hold" in intro["holdClass"],
           "main reçoit la classe d'état nage-intro-ui-hold pendant l'intro")
        ok(intro["donorInert"], "le donneur sprite reste inerte (≤2×2 px)")
        await pg.screenshot(path=str(SCREENS / "v_mid.png"))

        await pg.wait_for_timeout(3400)          # fin anims + fondu .nage-intro--fade 320ms
        after = await pg.evaluate("""()=>{
          const ov=[...document.querySelectorAll('.nage-intro')]
            .filter(x=>getComputedStyle(x).display!=='none'&&!x.classList.contains('nage-intro-donor'));
          const m=document.querySelector('main.nage-app-root');
          return {overlayGone: ov.length===0,
                  flag: sessionStorage.getItem('nage_intro_played'),
                  mainVisible: m&&getComputedStyle(m).opacity==='1'&&getComputedStyle(m).visibility!=='hidden',
                  topbarShown: (function(){const t=document.querySelector('.topbar');
                    return t&&getComputedStyle(t).opacity==='1';})()};}""")
        print("— Après l'intro :", after)
        ok(after["overlayGone"], "l'overlay .nage-intro est retiré du DOM après l'intro")
        ok(after["flag"] == "1", "sessionStorage nage_intro_played posé")
        ok(after["mainVisible"], "main.nage-app-root est visible et interactif après l'intro")
        ok(events, "l'événement nage:introend a été diffusé")
        ok(after["topbarShown"], "l'app est utilisable (topbar opacity 1)")
        await pg.screenshot(path=str(SCREENS / "v_end.png"))

        # ---- rejeu : même page, la garde doit empêcher une 2e intro ----
        await pg.reload()
        await pg.wait_for_timeout(450)
        replay = await pg.evaluate("""()=>{
          const ov=[...document.querySelectorAll('.nage-intro')]
            .filter(x=>getComputedStyle(x).display!=='none'&&!x.classList.contains('nage-intro-donor'));
          return {noReplay: ov.length===0};}""")
        print("— Rejeu (sessionStorage) :", replay)
        ok(replay["noReplay"], "rejeu bloqué (pas d'overlay actif)")
        await pg.close()

        # ---- reduced-motion : zéro intro ----
        ctx = await b.new_context(reduced_motion="reduce", viewport={"width": 1440, "height": 900})
        pg3 = await ctx.new_page()
        await pg3.goto(URL)
        await pg3.wait_for_timeout(450)
        rm = await pg3.evaluate("""()=>{
          const ov=[...document.querySelectorAll('.nage-intro')]
            .filter(x=>getComputedStyle(x).display!=='none'&&!x.classList.contains('nage-intro-donor'));
          const m=document.querySelector('main.nage-app-root');
          return {none: ov.length===0,
                  visible: m&&getComputedStyle(m).opacity==='1'};}""")
        print("— Reduced-motion :", rm)
        ok(rm["none"], "prefers-reduced-motion → zéro overlay")
        ok(rm["visible"], "app visible immédiatement en reduced-motion")
        await b.close()

    bad = [l for (s, l) in RESULTS if not s]
    print("\n" + (f"ÉCHECS : {len(bad)}" if bad else "TOUS LES CONTRÔLES PASSENT ✓"))
    for l_ in bad:
        print("   -", l_)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
