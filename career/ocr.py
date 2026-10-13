"""Bounded, local OCR for Career profile sources on macOS.

The app first reads an embedded PDF text layer.  This module is only used when
that layer is absent or too short.  It uses Apple's on-device Vision framework
through a tiny Objective-C helper; no image or CV content is uploaded anywhere.
"""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workspace_core import UserFacingError


MAX_OCR_PAGES = 8
MAX_OCR_TEXT_CHARS = 100_000
OCR_TIMEOUT_SECONDS = 55
_COMPILE_TIMEOUT_SECONDS = 60
_BUILD_LOCK = threading.RLock()


@dataclass(frozen=True)
class OCRResult:
    text: str
    pages: int
    truncated: bool
    warnings: list[str]
    engine: str = "macos_vision"


class LocalVisionOCR:
    """Compile and call the bundled macOS Vision helper only when needed."""

    def __init__(self, cache_dir: Path, source_path: Path | None = None):
        self.cache_dir = cache_dir
        self.source_path = source_path or Path(__file__).with_name("vision_ocr.m")

    def _sdk_path(self) -> Path | None:
        """Locate the active macOS SDK without trusting a shell expansion."""
        configured = os.environ.get("SDKROOT", "").strip()
        if configured and Path(configured).is_dir():
            return Path(configured)
        xcrun = shutil.which("xcrun")
        if not xcrun:
            return None
        try:
            result = subprocess.run(
                [xcrun, "--show-sdk-path"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        path = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None
        return path if path and path.is_dir() else None

    def status(self) -> dict[str, Any]:
        clang = shutil.which("clang")
        sdk = self._sdk_path() if sys.platform == "darwin" and clang else None
        available = sys.platform == "darwin" and bool(clang) and sdk is not None and self.source_path.is_file()
        return {
            "available": available,
            "engine": "macOS Vision" if available else "indisponible",
            "network": False,
            "reason": "" if available else "Les outils de ligne de commande Apple, le SDK macOS ou le composant OCR sont introuvables.",
        }

    @staticmethod
    def _run_command(arguments: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        """Run one fixed local command and reap its complete process group."""
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                process.communicate()
            raise error
        return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)

    def extract_pdf(self, path: Path, *, max_pages: int = MAX_OCR_PAGES) -> OCRResult:
        source = path.resolve()
        if source.suffix.lower() != ".pdf" or not source.is_file():
            raise UserFacingError("L’OCR local accepte uniquement un PDF de profil valide.")
        if not 1 <= max_pages <= 12:
            raise UserFacingError("La limite de pages OCR est invalide.")
        executable = self._ensure_helper()
        try:
            completed = self._run_command(
                [str(executable), str(source), str(max_pages)],
                timeout=OCR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise UserFacingError("L’OCR local a dépassé 55 secondes. Essaie un PDF plus court ou plus net.") from error
        except OSError as error:
            raise UserFacingError("L’OCR local macOS n’a pas pu démarrer.") from error
        if completed.returncode != 0:
            raise UserFacingError(
                "L’OCR local macOS n’a pas pu lire ce PDF. Essaie un PDF non protégé, plus net, ou un DOCX."
            )
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise UserFacingError("L’OCR local a renvoyé un résultat invalide.") from error
        text = str(payload.get("text") or "").replace("\x00", "").strip()
        if len(text) > MAX_OCR_TEXT_CHARS:
            text = text[:MAX_OCR_TEXT_CHARS].rstrip()
            truncated = True
        else:
            truncated = bool(payload.get("truncated"))
        if not text:
            raise UserFacingError(
                "Le PDF ne contient pas de texte lisible, même avec l’OCR local. Essaie une image plus nette ou un autre document."
            )
        warnings = [str(item)[:300] for item in payload.get("warnings", []) if str(item).strip()]
        if len(str(payload.get("text") or "")) > len(text):
            warnings.append("Texte OCR limité à 100 000 caractères.")
        return OCRResult(
            text=text,
            pages=max(0, int(payload.get("pages") or 0)),
            truncated=truncated,
            warnings=warnings[:4],
        )

    def _ensure_helper(self) -> Path:
        status = self.status()
        if not status["available"]:
            raise UserFacingError(
                "L’OCR local macOS nécessite les outils de ligne de commande Apple. "
                "Installe-les avec « xcode-select --install », puis relance Côme AI."
            )
        if not self.source_path.is_file():
            raise UserFacingError("Le composant OCR local est introuvable.")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.cache_dir, 0o700)
        except OSError:
            pass
        executable = self.cache_dir / "come-ai-vision-ocr"
        with _BUILD_LOCK:
            if executable.is_file() and os.access(executable, os.X_OK):
                return executable
            compiler = shutil.which("clang")
            sdk = self._sdk_path()
            if not compiler or not sdk:
                raise UserFacingError(
                    "L’OCR local macOS est indisponible : les outils de ligne de commande Apple ou le SDK sont introuvables."
                )
            temporary = self.cache_dir / f".vision-ocr-{uuid.uuid4().hex}.part"
            try:
                completed = self._run_command(
                    [
                        compiler,
                        "-fobjc-arc",
                        "-isysroot",
                        str(sdk),
                        "-framework",
                        "Foundation",
                        "-framework",
                        "AppKit",
                        "-framework",
                        "PDFKit",
                        "-framework",
                        "Vision",
                        str(self.source_path),
                        "-o",
                        str(temporary),
                    ],
                    timeout=_COMPILE_TIMEOUT_SECONDS,
                )
                if completed.returncode != 0 or not temporary.is_file():
                    raise UserFacingError(
                        "L’OCR local macOS n’a pas pu être préparé. "
                        "Vérifie les outils de ligne de commande Apple puis relance l’application."
                    )
                try:
                    os.chmod(temporary, 0o700)
                except OSError:
                    pass
                temporary.replace(executable)
                return executable
            except subprocess.TimeoutExpired as error:
                raise UserFacingError("La préparation de l’OCR local a dépassé 60 secondes.") from error
            except OSError as error:
                raise UserFacingError("La préparation de l’OCR local macOS a échoué.") from error
            finally:
                temporary.unlink(missing_ok=True)
