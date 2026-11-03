# -*- coding: utf-8 -*-
"""Génère les exports SVG statiques + PNG du logo NAGe.

Charge prototype.html en file:// via Playwright/Chromium headless, attend
DOMContentLoaded, puis évalue dans la page la même construction que la
fonction exportCurrent() du prototype :
    defs + body + <g transform="scale(-1,1)">body</g> + wordmark

Ne modifie aucun autre fichier du repo — n'écrit que dans exports/.
Exécuter :  /Users/comedelavenne/AI-Excel-Agent/.venv/bin/python _build.py
"""
import json
import pathlib
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PROTO = HERE.parent / "prototype.html"
BG = "#050705"

# Géométrie identique au prototype ; ribbonPath réécrit avec toFixed(2).
# viewBox du ruban complet : calculée au bbox réel + marge (les lobes
# débordent du carré -256..256 du prototype, on ne les rogne pas).
IN_PAGE = r"""
() => {
  const tl = (v) => v.toFixed(2);

  const controlPoints = (p) => {
    const kx=p.kx, ky=p.ky, kt=Number(p.kt);
    const a = kx*(0.4+0.6*kt), b = ky*(0.4+0.6*kt);
    return [
      [-100,-256], [-100,-198],
      [-118,-164], [-260,-112], [-392,-6], [-330,84], [-170,118],
      [-74,84], [-30,-6], [-66,-b], [-30,-b-14], [-a-18,b-46],
      [-a-30,b+30], [-352,172], [-300,212], [-128,222],
      [-100,244], [-100,256],
    ].map(v=>[v[0],v[1]]);
  };
  const sampleChain = (pts, per) => {
    const out=[];
    for(let i=0;i<pts.length-1;i++){
      const p0=pts[Math.max(0,i-1)], p1=pts[i], p2=pts[i+1], p3=pts[Math.min(pts.length-1,i+2)];
      for(let j=0;j<per;j++){
        const u=j/per, u2=u*u, u3=u2*u;
        out.push([
          0.5*((2*p1[0])+(-p0[0]+p2[0])*u+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*u2+(-p0[0]+3*p1[0]-3*p2[0]+p3[0])*u3),
          0.5*((2*p1[1])+(-p0[1]+p2[1])*u+(2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*u2+(-p0[1]+3*p1[1]-3*p2[1]+p3[1])*u3),
        ]);
      }
    }
    out.push(pts[pts.length-1].slice());
    return out;
  };
  const widthAt = (t, n) => {
    const {wEnd,wLobe,wKink}=n;
    const kink = Math.exp(-Math.pow((t-0.44)/0.11,2))* (wKink-wLobe);
    const lobeU= Math.exp(-Math.pow((t-0.19)/0.13,2))* (wLobe-wEnd);
    const lobeL= Math.exp(-Math.pow((t-0.80)/0.15,2))* (wLobe-wEnd);
    const taper= Math.min(1, Math.min(t,1-t)*10);
    return (wEnd/2 + lobeU + lobeL + kink) * (0.55+0.45*taper);
  };
  const ribbonPath = (center, n) => {
    const left=[], right=[];
    for(let i=0;i<center.length;i++){
      const t=i/(center.length-1), p=center[i];
      const q=center[Math.min(i+1,center.length-1)], r=center[Math.max(i-1,0)];
      let dx=q[0]-r[0], dy=q[1]-r[1];
      const len=Math.hypot(dx,dy)||1; dx/=len; dy/=len;
      const w=widthAt(t,n);
      left.push([p[0]-dy*w, p[1]+dx*w]);
      right.push([p[0]+dy*w, p[1]-dx*w]);
    }
    const c=center[center.length-1], c0=center[0];
    let d=`M ${tl(left[0][0])} ${tl(left[0][1])}`;
    for(const v of left) d+=` L ${tl(v[0])} ${tl(v[1])}`;
    const endR=right[right.length-1];
    d+=` Q ${tl(c[0])} ${tl(c[1])} ${tl(endR[0])} ${tl(endR[1])}`;
    for(let i=right.length-1;i>=0;i--){
      if(i===right.length-1) continue;
      d+=` L ${tl(right[i][0])} ${tl(right[i][1])}`;
    }
    d+=` Q ${tl(c0[0])} ${tl(c0[1])} ${tl(left[0][0])} ${tl(left[0][1])} Z`;
    return d;
  };
  const buildWord = (finish) => {
    const fill = finish==='mono' ? '#00d47a' : '#eafff4';
    return `<text x="0" y="14" text-anchor="middle" font-family="Space Grotesk, system-ui, sans-serif" font-size="64" font-weight="400" letter-spacing="18" fill="${fill}">NAG<tspan style="font-size:58">e</tspan></text>`;
  };

  const P0 = P, F = FINISHES;
  const nW = {wEnd:P0.wEnd, wLobe:P0.wLobe, wKink:P0.wKink};
  const center = sampleChain(controlPoints(P0), 10);
  const d = ribbonPath(center, nW);

  const defsGradient = F.gradient.defs;
  const defsStencil  = F.stencil.defs;
  const bodyGradient =
    `<use href="#ribbonGeo" fill="url(#gEm)" filter="url(#fGlow)"/>` +
    `<use href="#ribbonGeo" fill="url(#gEm)"/>` +
    `<use href="#ribbonGeo" fill="url(#gSheen)" style="mix-blend-mode:screen"/>`;
  const bodyMono    = `<use href="#ribbonGeo" fill="#00d47a"/>`;
  const bodyStencil = `<use href="#ribbonGeo" fill="none" stroke="url(#gEm2)" stroke-width="3.5"/>`;

  /* ---- mesure du bbox réel (moitié gauche seule, sans miroir) ---- */
  const meas = document.createElementNS('http://www.w3.org/2000/svg','svg');
  meas.setAttribute('viewBox','-600 -600 1200 1200');
  meas.style.position='absolute'; meas.style.left='-9999px';
  meas.innerHTML = `<defs><path id="ribbonGeo" d="${d}"/></defs><g>${bodyMono}</g>`;
  document.body.appendChild(meas);
  const hb = meas.querySelector('g').getBBox();
  meas.remove();

  /* ---- mesure du bbox du wordmark seul ---- */
  const measW = document.createElementNS('http://www.w3.org/2000/svg','svg');
  measW.setAttribute('viewBox','-600 -600 1200 1200');
  measW.style.position='absolute'; measW.style.left='-9999px';
  measW.innerHTML = `<g>${buildWord('gradient')}</g>`;
  document.body.appendChild(measW);
  const wb = measW.querySelector('g').getBBox();
  measW.remove();

  /* le fragment final (defs + body + miroir + wordmark) est assemblé en Python */
  return { d, defsGradient, defsStencil, bodyGradient, bodyMono, bodyStencil,
           info: { half: {x:+hb.x.toFixed(2), y:+hb.y.toFixed(2), w:+hb.width.toFixed(2), h:+hb.height.toFixed(2)},
                   word: {x:+wb.x.toFixed(2), y:+wb.y.toFixed(2), w:+wb.width.toFixed(2), h:+wb.height.toFixed(2)},
                   dLen: d.length } };
}
"""

PAD_RIBBON = 14   # marge pour le halo fGlow (stdDeviation 9)
PAD_WORD = 4


def ribbon_viewbox(half):
    """BBox complet du logo (moitié + miroir) avec marge de halo."""
    half_x0 = half["x"]
    half_x1 = half["x"] + half["w"]
    x_min = min(half_x0, -half_x1)   # miroir = intervalle [-x1, -x0]
    x_max = max(half_x1, -half_x0)
    y_min, y_max = half["y"], half["y"] + half["h"]
    x0 = round(x_min - PAD_RIBBON)
    y0 = round(y_min - PAD_RIBBON)
    x1 = round(x_max + PAD_RIBBON)
    y1 = round(y_max + PAD_RIBBON)
    return f"{x0} {y0} {x1 - x0} {y1 - y0}"


def word_viewbox(w):
    x0 = round(w["x"] - PAD_WORD)
    y0 = round(w["y"] - PAD_WORD)
    x1 = round(w["x"] + w["w"] + PAD_WORD)
    y1 = round(w["y"] + w["h"] + PAD_WORD)
    return f"{x0} {y0} {x1 - x0} {y1 - y0}"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1200})
        page.goto(PROTO.as_uri())
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(400)

        res = page.evaluate(IN_PAGE)
        d = res["d"]
        info = res["info"]
        print("info:", json.dumps(info))

        VB_LOGO = ribbon_viewbox(info["half"])
        VB_WORD = word_viewbox(info["word"])

        mirror = lambda b: f'  <g transform="scale(-1,1)">{b}</g>\n'
        geo_def = f'<path id="ribbonGeo" d="{d}"/>'

        def open_svg(vb: str) -> str:
            return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="NAGe">\n'

        def word(finish: str) -> str:
            fill = "#00d47a" if finish == "mono" else "#eafff4"
            return (f'<text x="0" y="14" text-anchor="middle" '
                    f'font-family="Space Grotesk, system-ui, sans-serif" '
                    f'font-size="64" font-weight="400" letter-spacing="18" '
                    f'fill="{fill}">NAG<tspan style="font-size:58">e</tspan></text>')

        bg, st = res["bodyGradient"], res["bodyStencil"]
        defs_g = res["defsGradient"]
        defs_s = res["defsStencil"]

        svgs = {
            # 1. gradient : defs gEm + gSheen + fGlow, wordmark, fond transparent
            "nage-logo.svg":
                open_svg(VB_LOGO) +
                f'  <defs>{defs_g}{geo_def}</defs>\n  {bg}\n' + mirror(bg) +
                f'  <g>{word("gradient")}</g>\n</svg>\n',
            # 2. mono : aucune def superflue, wordmark #00d47a
            "nage-logo-mono.svg":
                open_svg(VB_LOGO) +
                f'  <defs>{geo_def}</defs>\n  {res["bodyMono"]}\n' + mirror(res["bodyMono"]) +
                f'  <g>{word("mono")}</g>\n</svg>\n',
            # 3. stencil : stroke url(#gEm2), pas de wordmark
            "nage-logo-stencil.svg":
                open_svg(VB_LOGO) +
                f'  <defs>{defs_s}{geo_def}</defs>\n  {st}\n' + mirror(st) + '</svg>\n',
            # 4. mot seul, viewBox ajustée au bbox réel du texte
            "nage-word-only.svg":
                open_svg(VB_WORD) + f'  <g>{word("gradient")}</g>\n</svg>\n',
            # 5. moitié gauche seule, pas de miroir (pour animations halfL en CSS)
            "nage-ribbon-half.svg":
                open_svg(VB_LOGO) +
                f'  <defs>{defs_g}{geo_def}</defs>\n  {bg}\n</svg>\n',
        }

        files = list(svgs)
        for fname in files:
            (HERE / fname).write_text(svgs[fname], encoding="utf-8")
            print(f"écrit  {fname}  ({(HERE / fname).stat().st_size} octets)")

        # ---- PNG 512×512, fond #050705 — SVG inline dans un wrapper file:// ----
        wrapper = ['<!DOCTYPE html><meta charset="utf-8"><body style="margin:0;'
                   f'background:{BG};width:512px;height:512px">']
        for i, fname in enumerate(files):
            svg = svgs[fname]
            w = 'width="512" height="512" style="display:block"'
            svg_embedded = svg.replace("<svg ", f"<svg {w} ", 1)
            wrapper.append('<div id="shot{}" style="width:512px;height:512px">{}</div>'
                           .format(i, svg_embedded))
        wrapper.append("</body>")
        wrap_path = HERE / "_shots.html"
        wrap_path.write_text("".join(wrapper), encoding="utf-8")

        png_page = browser.new_page(viewport={"width": 512, "height": 2200})
        png_page.goto(wrap_path.as_uri())
        png_page.wait_for_load_state("load")
        png_page.wait_for_timeout(500)
        for i, fname in enumerate(files):
            stem = fname[:-4].replace("nage-", "")
            png = HERE / f"preview-{stem}.png"
            png_page.locator(f"#shot{i}").screenshot(path=str(png))
            print(f"écrit  {png.name}  ({png.stat().st_size} octets)")
        png_page.close()

        # ---- gallery.html : inline SVG, 3 visuels par variante, ids uniques ----
        def descope(inner: str, suffix: str) -> str:
            for rid in ("ribbonGeo", "gEm2", "gEm", "gSheen", "fGlow"):
                inner = inner.replace(f'id="{rid}"', f'id="{rid}-{suffix}"')
                inner = inner.replace(f'url(#{rid})', f'url(#{rid}-{suffix})')
                inner = inner.replace(f'href="#{rid}"', f'href="#{rid}-{suffix}"')
            return inner

        def inner_of(fname: str) -> str:
            return svgs[fname].split(">", 1)[1].rsplit("</svg>", 1)[0]

        rows = []
        for i, fname in enumerate(files):
            vb = svgs[fname].split('viewBox="')[1].split('"')[0]
            cells = "".join([
                (f'<div class="cell"{" small" if sz==96 else " tiny" if sz==32 else ""}>'
                 f'<div class="frame"><svg viewBox="{vb}">'
                 f'{descope(inner_of(fname), f"{sz}c{i}")}</svg></div>'
                 f'<div class="cap">{sz} px</div></div>')
                for sz in (512, 96, 32)
            ])
            rows.append(f'<section class="row"><h2>{fname} <code>· {vb}</code></h2>'
                        f'<div class="set">{cells}</div></section>')

        transparent = ('<div><svg viewBox="' + VB_LOGO + '" role="img" aria-label="NAGe">'
                       f'{descope(inner_of("nage-logo.svg"), "tx")}</svg>'
                       '<div class="cap">nage-logo.svg — fond transparent</div></div>')

        gallery = GALLERY.replace("{rows}", "".join(rows)).replace("{transparent}", transparent)
        (HERE / "gallery.html").write_text(gallery, encoding="utf-8")
        print("écrit  gallery.html")
        browser.close()


GALLERY = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAGe — galerie des exports statiques</title>
<style>
  :root{ --emerald:#00d47a; --dim:#7d8f86 }
  *{ box-sizing:border-box; margin:0 }
  body{ background:#050705; color:#e8f5ee; font-family:system-ui, sans-serif; padding:40px 6vw 80px }
  h1{ font-weight:400; font-size:21px; letter-spacing:.06em }
  p.sub{ color:var(--dim); font-size:13px; margin:8px 0 36px; max-width:72ch; line-height:1.7 }
  code{ color:#9fb8ab }
  .row{ margin-bottom:46px }
  .row h2{ font-size:11px; text-transform:uppercase; letter-spacing:.16em;
    color:var(--emerald); font-weight:500; margin-bottom:14px }
  .set{ display:flex; align-items:flex-end; gap:34px; flex-wrap:wrap }
  .cell{ text-align:center }
  .cell .frame{ width:532px; height:532px; display:grid; place-items:center;
    border:1px solid #122c1f; border-radius:14px; background:#070a08 }
  .cell.small .frame{ width:120px; height:120px }
  .cell.tiny .frame{ width:56px; height:56px }
  .frame svg{ width:512px; height:512px }
  .cell.small .frame svg{ width:96px; height:96px }
  .cell.tiny .frame svg{ width:32px; height:32px }
  .cell .cap{ font-size:11px; color:var(--dim); margin-top:10px }
  .check{ margin-top:8px; padding:26px; display:flex; gap:26px; align-items:flex-end;
    width:fit-content; border:1px solid #122c1f; border-radius:14px;
    background:repeating-conic-gradient(#0c0f0d 0% 25%, #131a15 0% 50%) 0 0/32px 32px }
  .check svg{ width:320px; height:320px; display:block }
  .check .cap{ font-size:11px; color:var(--dim); margin-top:10px }
</style>
</head>
<body>
<h1>NAGe — exports vectoriels statiques</h1>
<p class="sub">Générés depuis <code>../prototype.html</code> (Ruban Catmull-Rom + profil d'épaisseur,
miroir <code>scale(-1,1)</code>). Chaque variante est montrée à 512 px, 96 px et 32 px sur fond
noir pour contrôler la lisibilité en petite taille, puis sur fond en damier pour vérifier le
fond transparent réel des SVG. Rasterisations : <code>preview-*.png</code>.</p>
{rows}
<section>
<h2 style="font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:var(--emerald);font-weight:500;margin-bottom:14px">Contrôle du fond transparent</h2>
<div class="check">{transparent}</div>
</section>
</body>
</html>
"""

if __name__ == "__main__":
    main()
