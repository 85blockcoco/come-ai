#!/usr/bin/env python3
"""Construit « NAGE.app » sur le Bureau : icône dédiée + lancement local.

Le bundle :
  - démarre le serveur local s'il ne tourne pas (venv du dépôt) ;
  - ouvre une fenêtre Chrome en mode application (sans onglets ni barre d'URL),
    avec un profil dédié pour un vrai rendu « app » ;
  - garde l'icône dans le Dock pendant que la fenêtre est ouverte.
Aucune donnée ne sort de la machine (127.0.0.1 uniquement).
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
APP_NAME = "NAGE"
APP_PATH = Path.home() / "Desktop" / f"{APP_NAME}.app"
ICON = HERE / "AppIcon.icns"

LAUNCHER = f"""#!/bin/zsh
# Lanceur NAGE — serveur local + fenêtre applicative.
set -u
REPO="{REPO}"
URL="http://127.0.0.1:8765"
APP_URL="$URL/app"
PROFILE="$HOME/Library/Application Support/NAGE/window"

cd "$REPO" || {{ osascript -e 'display alert "NAGE" message "Dossier du projet introuvable."'; exit 1; }}

if ! curl -sf -m 2 "$URL/api/health" >/dev/null 2>&1; then
  mkdir -p "$REPO/logs"
  nohup "$REPO/.venv/bin/python" run_come_ai_v3.py --no-browser >> "$REPO/logs/app_server.log" 2>&1 &
  for _ in {{1..60}}; do
    curl -sf -m 1 "$URL/api/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

if ! curl -sf -m 2 "$URL/api/health" >/dev/null 2>&1; then
  osascript -e 'display alert "NAGE" message "Le serveur local n’a pas démarré. Ouvre le dossier du projet et lance : .venv/bin/python run_come_ai_v3.py"'
  exit 1
fi

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$PROFILE"
if [ -x "$CHROME" ]; then
  exec "$CHROME" \\
    --app="$APP_URL" \\
    --user-data-dir="$PROFILE" \\
    --window-size=1460,950 \\
    --no-first-run \\
    --no-default-browser-check \\
    --disable-features=TranslateUI,GlobalMediaControls,MediaRouter \\
    --disable-sync \\
    --hide-crash-restore-bubble \\
    >/dev/null 2>&1
else
  exec open -a Safari "$APP_URL"
fi
"""

INFO = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": "com.nage.cockpit",
    "CFBundleExecutable": "ComeIA",
    "CFBundleIconFile": "AppIcon",
    "CFBundlePackageType": "APPL",
    "CFBundleSignature": "????",
    "CFBundleShortVersionString": "1.0.0",
    "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
    "LSUIElement": False,
    "NSHumanReadableCopyright": "NAGE — usage personnel local",
    "CFBundleInfoDictionaryVersion": "6.0",
}


def main() -> None:
    if not ICON.exists():
        subprocess.run([".venv/bin/python", str(HERE / "make_icon.py")], cwd=str(REPO), check=True)

    # remplace l'ancienne application nommée Côme IA
    legacy = Path.home() / "Desktop" / "Côme IA.app"
    if legacy.exists():
        shutil.rmtree(legacy, ignore_errors=True)
    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)
    macos = APP_PATH / "Contents" / "MacOS"
    resources = APP_PATH / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    (APP_PATH / "Contents" / "Info.plist").write_bytes(plistlib.dumps(INFO))
    (APP_PATH / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")

    launcher = macos / "ComeIA"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)

    shutil.copy2(ICON, resources / "AppIcon.icns")
    icon_png = HERE / "icon_1024.png"
    if icon_png.exists():
        shutil.copy2(icon_png, resources / "icon.png")

    # rafraîchit le cache d'icônes du Finder
    subprocess.run(["touch", str(APP_PATH)], check=False)
    lsregister = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                  "LaunchServices.framework/Support/lsregister")
    if os.path.exists(lsregister):
        subprocess.run([lsregister, "-f", str(APP_PATH)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Application prête : {APP_PATH}")


if __name__ == "__main__":
    main()
