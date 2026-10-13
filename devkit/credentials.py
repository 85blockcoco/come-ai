"""Human-only, hidden terminal entry of a persistent provider credential."""
from __future__ import annotations

import getpass
import re
import warnings
from pathlib import Path

from devkit.exporting import KitError
from devkit.patching import _atomic_write
from workspace_core import read_dotenv


def _configuration_path(project_root: Path) -> Path:
    path = Path(project_root) / ".env"
    if path.is_symlink():
        raise KitError("Le fichier .env ne peut pas être un lien symbolique.")
    if path.exists() and (not path.is_file() or path.stat().st_size > 64 * 1024):
        raise KitError("Le fichier .env doit être un petit fichier local ordinaire.")
    return path


def _hidden_key(provider: str, pattern: str) -> str:
    # getpass normally falls back to echoing input when terminal masking
    # is unavailable. Refuse that fallback before any credential is read.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(f"Clé {provider} (saisie masquée, conservée localement) : ").strip()
    except (getpass.GetPassWarning, EOFError, OSError):
        raise KitError("Saisie masquée indisponible. Lance cette commande dans ton Terminal. Aucun fichier modifié.") from None
    if not re.fullmatch(pattern, value):
        raise KitError("La saisie de clé est vide ou mal formée. Aucun fichier modifié.")
    return value


def _persist_values(path: Path, values: dict[str, str]) -> None:
    current = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    lines = [line for line in current.splitlines() if not any(
        re.match(r"^\s*(?:export\s+)?" + re.escape(name) + r"\s*=", line)
        for name in values
    )]
    lines.extend(name + "=" + value for name, value in values.items())
    _atomic_write(path, ("\n".join(lines) + "\n").encode("utf-8"), 0o600)
    # Verify the application loader, not merely file existence. The loaded
    # values are never returned, printed or added to a report.
    loaded = read_dotenv(path)
    if not all(loaded.get(name) == value for name, value in values.items()):
        raise KitError("La configuration enregistrée n’est pas chargeable par l’application.")


def configure_gemini(project_root: Path, *, confirm_free_project: bool = False) -> dict:
    path = _configuration_path(project_root)
    values = read_dotenv(path)
    free = confirm_free_project or values.get("COME_AI_GEMINI_FREE_PROJECT_CONFIRMED", "false").lower() == "true"
    if not free:
        raise KitError("Confirme d’abord que le projet Gemini est gratuit sans facturation activée, avec --confirm-free-project.")
    # Validate safely representable key characters without assuming that Google
    # will always use one prefix. This is syntax validation, not authentication.
    value = _hidden_key("Gemini", r"[A-Za-z0-9_.-]{20,256}")
    _persist_values(path, {"GEMINI_API_KEY": value, "COME_AI_GEMINI_FREE_PROJECT_CONFIRMED": "true"})
    return {"configured": True, "configuration_loadable": True, "free_project_declared": True,
            "authentication_verified": False}


def configure_openrouter(project_root: Path) -> dict:
    """Human-only private entry; no catalogue, generation or billing request."""
    path = _configuration_path(project_root)
    value = _hidden_key("OpenRouter", r"sk-or-v1-[A-Fa-f0-9]{64}")
    _persist_values(path, {"OPENROUTER_API_KEY": value})
    return {"configured": True, "configuration_loadable": True, "authentication_verified": False}
