"""Serveur FastAPI isolé pour les tests E2E (lancé en sous-processus).

Usage : ``python tests/e2e/server.py <base_dir> <port>``. Le ``base_dir`` est
temporaire : base SQLite, exports et mémoire y restent confinés.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

from come_ai_web import create_app


def main() -> None:
    base_dir = Path(sys.argv[1]).resolve()
    port = int(sys.argv[2])
    app = create_app(base_dir=base_dir)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
