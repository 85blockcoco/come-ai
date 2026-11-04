#!/usr/bin/env python3
"""Construit NAGe.app sans supprimer les applications ou fichiers existants.

Chaque mise à jour sauvegarde d'abord le bundle complet, puis ne remplace que
les fichiers gérés. Le lanceur utilise le venv du dépôt et un profil Chrome dédié.
"""
from __future__ import annotations

import plistlib
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
APP_NAME = "NAGe"
APP_PATH = Path.home() / "Desktop" / f"{APP_NAME}.app"
BACKUP_ROOT = Path.home() / "Library" / "Application Support" / "NAGE" / "backups"
ICON = HERE / "AppIcon.icns"
ICON_PNG = HERE / "icon_1024.png"
APP_URL = "http://127.0.0.1:8765/v5#v5/assistantView"


def render_launcher(repo: Path) -> str:
    """Return a shell-quoted launcher for the exact repository being installed."""
    return f"""#!/bin/zsh
# Lanceur NAGe — serveur local + fenêtre applicative.
set -u
REPO={shlex.quote(str(repo.resolve()))}
URL="http://127.0.0.1:8765"
APP_URL="{APP_URL}"
PROFILE="$HOME/Library/Application Support/NAGE/window"
LOG_DIR="$HOME/Library/Logs/NAGe"

cd "$REPO" || {{ osascript -e 'display alert "NAGe" message "Dossier du projet introuvable."'; exit 1; }}

if ! curl -sf -m 2 "$URL/api/health" >/dev/null 2>&1; then
  mkdir -p "$LOG_DIR"
  nohup "$REPO/.venv/bin/python" "$REPO/run_come_ai_v3.py" --port 8765 --no-browser >> "$LOG_DIR/server.log" 2>&1 &
  for _ in {{1..60}}; do
    curl -sf -m 1 "$URL/api/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

if ! curl -sf -m 2 "$URL/api/health" >/dev/null 2>&1; then
  osascript -e 'display alert "NAGe" message "Le serveur local n’a pas démarré. Consulte Library/Logs/NAGe/server.log."'
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
    "CFBundleIdentifier": "ai.come.nage.desktop",
    "CFBundleExecutable": "NAGe",
    "CFBundleIconFile": "NAGe",
    "CFBundlePackageType": "APPL",
    "CFBundleSignature": "????",
    "CFBundleShortVersionString": "1.0.0",
    "CFBundleVersion": "1",
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
    "LSUIElement": False,
    "NSHumanReadableCopyright": "NAGe — usage personnel local",
    "CFBundleInfoDictionaryVersion": "6.0",
}


def build_app(
    *,
    app_path: Path = APP_PATH,
    repo: Path = REPO,
    backup_root: Path = BACKUP_ROOT,
    icon: Path = ICON,
    icon_png: Path = ICON_PNG,
    refresh: bool = True,
) -> Path | None:
    """Install managed files in place; return the recoverable pre-update backup.

    All paths are injectable so tests can stay entirely inside a temporary
    directory. A failed backup aborts installation before any bundle is changed.
    """
    if not icon.is_file():
        raise FileNotFoundError(f"Icône introuvable : {icon}")
    contents = app_path / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    managed = [
        app_path, contents, macos, resources, contents / "Info.plist",
        contents / "PkgInfo", macos / "NAGe", resources / "NAGe.icns", resources / "icon.png",
    ]
    if any(path.is_symlink() for path in managed):
        raise ValueError("Un chemin géré du bundle est un lien symbolique ; installation interrompue.")
    if backup_root.resolve().is_relative_to(app_path.resolve()):
        raise ValueError("Le dossier de sauvegarde doit être extérieur au bundle.")

    info_path = contents / "Info.plist"
    info = plistlib.loads(info_path.read_bytes()) if info_path.exists() else {}
    info.update(INFO)
    backup = None
    if app_path.exists():
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = backup_root / f"{app_path.stem}-{stamp}-{uuid4().hex[:8]}.app"
        shutil.copytree(app_path, backup, symlinks=True)

    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    info_path.write_bytes(plistlib.dumps(info))
    (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
    launcher = macos / "NAGe"
    launcher.write_text(render_launcher(repo), encoding="utf-8")
    launcher.chmod(0o755)
    shutil.copy2(icon, resources / "NAGe.icns")
    if icon_png.is_file():
        shutil.copy2(icon_png, resources / "icon.png")

    if refresh:
        app_path.touch()
        lsregister = Path(
            "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
            "LaunchServices.framework/Support/lsregister"
        )
        if lsregister.exists():
            subprocess.run(
                [str(lsregister), "-f", str(app_path)], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    return backup


def main() -> None:
    backup = build_app()
    if backup is not None:
        print(f"Sauvegarde récupérable : {backup}")
    print(f"Application prête : {APP_PATH}")


if __name__ == "__main__":
    main()
