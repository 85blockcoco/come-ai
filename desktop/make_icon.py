#!/usr/bin/env python3
"""Icône NAGE — brutal machine : noir profond, phosphore vert, monogramme N.

Sortie : desktop/AppIcon.icns + desktop/icon_1024.png
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
S = 4096
OUT = 1024
GREEN = (0, 255, 102, 255)


def build_background() -> Image.Image:
    yy, xx = np.mgrid[0:S, 0:S]
    cx, cy = S * 0.5, S * 0.45
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (S * 0.75)
    glow = np.clip(1.0 - dist, 0, 1) ** 2
    base = np.zeros((S, S, 3), dtype=float)
    base[..., 0] = 4 + 12 * glow
    base[..., 1] = 10 + 46 * glow
    base[..., 2] = 7 + 18 * glow
    img = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "RGB").convert("RGBA")

    # grille machine subtile
    grid = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = S // 16
    for x in range(0, S, step):
        gd.line([(x, 0), (x, S)], fill=(0, 255, 102, 16), width=2)
    for y in range(0, S, step):
        gd.line([(0, y), (S, y)], fill=(0, 255, 102, 16), width=2)
    return Image.alpha_composite(img, grid)


def squircle_mask(size: int, margin: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    radius = int((size - 2 * margin) * 0.2237)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, size - margin, size - margin), radius=radius, fill=255)
    return mask


def n_glyph() -> Image.Image:
    """Monogramme N anguleux, à double trait (effet stencil machine)."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    left, right = S * 0.28, S * 0.72
    top, bottom = S * 0.245, S * 0.755
    stroke = S * 0.088
    chamfer = S * 0.055

    # barre gauche (chanfrein haut)
    d.polygon([
        (left + chamfer, top), (left + stroke, top), (left + stroke, bottom),
        (left, bottom), (left, top + chamfer),
    ], fill=GREEN)
    # barre droite (chanfrein bas)
    d.polygon([
        (right - stroke, top), (right, top + chamfer), (right, bottom),
        (right - chamfer, bottom), (right - stroke, bottom),
    ], fill=(0, 255, 102, 255))
    # diagonale
    d.polygon([
        (left + stroke * 0.05, top),
        (left + stroke * 1.10, top),
        (right - stroke * 0.10, bottom),
        (right - stroke * 1.15, bottom),
    ], fill=GREEN)

    # encoche : on évide le centre bas de la diagonale pour un look stencil
    d.polygon([
        (left + stroke * 1.55, bottom - S * 0.02),
        (right - stroke * 1.55, bottom - S * 0.02),
        (right - stroke * 2.05, bottom - S * 0.10),
        (left + stroke * 2.05, bottom - S * 0.10),
    ], fill=(0, 0, 0, 0))

    return layer


def main() -> None:
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = squircle_mask(S, int(S * 0.05))
    icon.paste(build_background(), (0, 0), mask)

    # liseré vert intérieur
    edge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    m = int(S * 0.05) + S * 0.016
    ed.rounded_rectangle((m, m, S - m, S - m), radius=int((S - 2 * m) * 0.2237),
                         outline=(0, 255, 102, 235), width=int(S * 0.0075))
    icon = Image.alpha_composite(icon, edge)

    # halo du monogramme
    glyph = n_glyph()
    halo = glyph.filter(ImageFilter.GaussianBlur(S * 0.035))
    halo = halo.point(lambda v, a=90: min(255, v * 2))
    icon = Image.alpha_composite(icon, halo)
    icon = Image.alpha_composite(icon, glyph)

    # curseur machine (bloc plein, bas droite)
    cur = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cur)
    blink_w = S * 0.055
    cd.rectangle((S * 0.735, S * 0.715, S * 0.735 + blink_w, S * 0.715 + S * 0.030),
                 fill=(0, 255, 102, 255))
    # trois témoins machine en bas à gauche
    for i in range(3):
        x = S * 0.215 + i * S * 0.042
        cd.rectangle((x, S * 0.725, x + S * 0.026, S * 0.735), fill=(0, 255, 102, 200))
    icon = Image.alpha_composite(icon, cur)

    # coins HUD
    hud = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hud)
    pad = int(S * 0.085)
    arm = int(S * 0.055)
    w = int(S * 0.009)
    col = (0, 255, 102, 190)
    for (x, y, dx, dy) in ((pad, pad, 1, 1), (S - pad, pad, -1, 1),
                           (pad, S - pad, 1, -1), (S - pad, S - pad, -1, -1)):
        hd.line([(x, y), (x + dx * arm, y)], fill=col, width=w)
        hd.line([(x, y), (x, y + dy * arm)], fill=col, width=w)
    icon = Image.alpha_composite(icon, hud)

    final = icon.resize((OUT, OUT), Image.LANCZOS)
    final.save(HERE / "icon_1024.png")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 64, 128, 256, 512):
            final.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            final.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        final.save(iconset / "icon_512x512@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "AppIcon.icns")],
                       check=True)
    print(f"icône NAGE prête : {HERE / 'AppIcon.icns'}")


if __name__ == "__main__":
    main()
