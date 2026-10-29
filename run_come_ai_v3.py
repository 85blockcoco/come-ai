"""Local launcher for the unified NAGE application."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

import uvicorn

from come_ai_web import create_app
from workspace_core import UserFacingError


def main() -> None:
    parser = argparse.ArgumentParser(description="Démarre Côme AI 5.0 sur ce Mac uniquement.")
    parser.add_argument("--port", type=int, default=8765, help="Port local (défaut : 8765).")
    parser.add_argument("--no-browser", action="store_true", help="N’ouvre pas le navigateur automatiquement.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Le port doit être compris entre 1024 et 65535.")

    url = f"http://127.0.0.1:{args.port}/app"
    from local_ai_runtime import ensure_local_runtime

    local = ensure_local_runtime(Path(__file__).resolve().parent)
    if local.get("running"):
        print("Moteur IA local disponible. Aucun modèle ni mise à jour n’est téléchargé au lancement.")
    else:
        print("Moteur IA local non disponible ; les outils locaux restent accessibles.")
    try:
        app = create_app()
    except UserFacingError as error:
        print(f"Configuration impossible : {error}")
        raise SystemExit(1) from error
    print(f"NAGE est prêt sur {url}")
    print("Le serveur est local ; arrête-le avec Ctrl+C dans cette fenêtre.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url, new=2)).start()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
