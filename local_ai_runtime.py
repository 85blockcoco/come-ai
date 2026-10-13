"""Project-local Ollama launcher; never installs or downloads automatically."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


LOCAL_NETWORK_PROFILE = '(version 1) (allow default) (deny network*) (allow network-inbound (local ip "localhost:*")) (allow network-outbound (remote ip "localhost:*"))'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def local_status() -> dict:
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open("http://127.0.0.1:11434/api/version", timeout=2) as response:
            data = json.loads(response.read(4096))
        return {"running": bool(data.get("version")), "version": data.get("version")}
    except (OSError, ValueError):
        return {"running": False, "version": None}


def ensure_local_runtime(project_root: Path, *, installation_network: bool = False) -> dict:
    root = Path(project_root).resolve()
    state = local_status()
    if state["running"]:
        return {**state, "started": False}
    binary = root / ".local-ai" / "ollama" / "v0.40.3" / "ollama"
    if not binary.is_file() or binary.is_symlink():
        return {**state, "started": False, "reason": "Ollama local non installé."}
    directory = root / ".local-ai" / "runtime"
    models = root / ".local-ai" / "models"
    for path in (directory, models):
        if path.is_symlink():
            raise ValueError("Le stockage Ollama doit être local sans lien symbolique.")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Preserve the user's real home for standard runtime support, but do not
    # inherit provider credentials, proxies, debug flags or arbitrary overrides.
    environment = {name: os.environ[name] for name in ("HOME", "USER", "TMPDIR", "PATH", "LANG") if name in os.environ}
    environment.update(OLLAMA_HOST="127.0.0.1:11434", OLLAMA_MODELS=str(models),
                       OLLAMA_NO_CLOUD="1", OLLAMA_CONTEXT_LENGTH="4096",
                       OLLAMA_NUM_PARALLEL="1", OLLAMA_MAX_LOADED_MODELS="1",
                       OLLAMA_KEEP_ALIVE="5m")
    command = [str(binary), "serve"]
    isolated = False
    if not installation_network:
        sandbox = Path("/usr/bin/sandbox-exec")
        if not sandbox.is_file():
            return {"running": False, "started": False, "reason": "Sandbox macOS indisponible ; lancement isolé refusé."}
        command = [str(sandbox), "-p", LOCAL_NETWORK_PROFILE, *command]
        isolated = True
    log_path = directory / "ollama.log"
    if log_path.is_symlink():
        raise ValueError("Le journal Ollama ne peut pas être un lien symbolique.")
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, env=environment, cwd=binary.parent, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    os.chmod(log_path, 0o600)
    for _ in range(30):
        if process.poll() is not None:
            return {"running": False, "started": False, "reason": "Ollama n’a pas démarré ; consulter le journal local."}
        state = local_status()
        if state["running"]:
            return {**state, "started": True, "pid": process.pid, "network_isolated": isolated}
        time.sleep(0.2)
    process.terminate()
    return {"running": False, "started": False, "reason": "Délai de démarrage Ollama dépassé."}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Démarrer le moteur installé, sans téléchargement automatique.")
    parser.add_argument("--installation-network", action="store_true", help="Uniquement pour le téléchargement initial explicitement autorisé.")
    args = parser.parse_args()
    result = ensure_local_runtime(Path(__file__).resolve().parent, installation_network=args.installation_network)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("running") else 1)
