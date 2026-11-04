"""Restricted, opt-in text-only Kilo fallback; never use the default build agent.

Audited against Kilo 7.8.18 on 2026-11-04, using only help, model metadata,
and synthetic debug configuration. No inference was used for that audit.
Model IDs below had zero input/output/cache prices in ``models kilo --verbose``.
Only explicit ``:free`` models are accepted; routers are deliberately excluded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


class KiloTutorError(RuntimeError):
    """A generic failure safe to display without leaking subprocess output."""


FREE_MODELS = frozenset({
    "kilo/cohere/north-mini-code:free",
    "kilo/nvidia/nemotron-3.5-super-vl:free",
    "kilo/nvidia/nemotron-3.5-lightning:free",
    "kilo/nvidia/nemotron-3-ultra-550b-a55b:free",
})
_AGENT = "nage-vc-tutor"
_PROMPT = (
    "You are a Venture Capital course tutor. Answer only the user's supplied "
    "course question and supplied course excerpts. Never use any tool, inspect "
    "files, run commands, browse, delegate, build, or change anything. "
    "If the supplied course material is insufficient, say so."
)
_FAILURE = "Le secours Kilo est indisponible dans sa configuration sécurisée."
_MAX_OUTPUT = 2_000_000


def _json(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw) > _MAX_OUTPUT:
        raise KiloTutorError(_FAILURE)
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        raise KiloTutorError(_FAILURE) from None
    if not isinstance(value, dict):
        raise KiloTutorError(_FAILURE)
    return value


def _text_events(raw: str) -> str:
    """Return only completed assistant text, never diagnostics or tool output."""
    if not isinstance(raw, str) or len(raw) > _MAX_OUTPUT:
        raise KiloTutorError(_FAILURE)
    texts: list[str] = []
    finished = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        event = _json(line)
        kind = event.get("type")
        if kind not in {"step_start", "text", "step_finish"}:
            raise KiloTutorError(_FAILURE)
        part = event.get("part")
        if not isinstance(part, dict):
            raise KiloTutorError(_FAILURE)
        if kind == "text":
            value = part.get("text")
            if part.get("type") != "text" or not isinstance(value, str):
                raise KiloTutorError(_FAILURE)
            if not isinstance(part.get("time"), dict) or not part["time"].get("end"):
                raise KiloTutorError(_FAILURE)
            texts.append(value)
        elif kind == "step_finish":
            if part.get("reason") != "stop":
                raise KiloTutorError(_FAILURE)
            finished = True
    result = "\n".join(texts).strip()
    if not finished or not result:
        raise KiloTutorError(_FAILURE)
    return result


def run_kilo_tutor(
    prompt: str, *, system: str | None = None, model: str | None = None,
    timeout: int = 90,
) -> str:
    """Run one explicit free model with stdin text and no agent tools.

    Existing CLI authentication remains in its data directory. User config,
    repository files, environment secrets, and shell evaluation are not used.
    Every call first checks the effective CLI configuration and effective tools;
    unexpected managed/cloud settings fail closed before any model invocation.
    """
    selected = model if model is not None else os.environ.get("VC_TUTOR_KILO_MODEL")
    if (
        not isinstance(prompt, str) or not prompt.strip()
        or (system is not None and not isinstance(system, str))
        or selected not in FREE_MODELS
        or isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0
    ):
        raise KiloTutorError(_FAILURE)
    executable = shutil.which("kilo")
    if not executable:
        raise KiloTutorError(_FAILURE)
    # Preserve only the CLI's authentication location. Never read auth contents.
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    payload = prompt if system is None else system + "\n\n" + prompt
    deadline = time.monotonic() + timeout
    try:
        with tempfile.TemporaryDirectory(prefix="nage-vc-kilo-") as directory:
            config = {
                "model": selected, "default_agent": _AGENT,
                "permission": {"*": "deny"}, "tools": {"*": False},
                "agent": {_AGENT: {
                    "mode": "primary", "prompt": _PROMPT,
                    "permission": {"*": "deny"}, "tools": {"*": False},
                }},
                "share": "disabled", "plugin": [], "mcp": {}, "instructions": [],
                "compaction": {"auto": False},
            }
            env = {
                "PATH": os.defpath, "HOME": str(Path.home()), "KILO_TEST_HOME": directory,
                "XDG_DATA_HOME": data_home,
                "XDG_CONFIG_HOME": directory + "/config",
                "XDG_CACHE_HOME": directory + "/cache",
                "XDG_STATE_HOME": directory + "/state",
                "TMPDIR": directory, "TMP": directory, "TEMP": directory,
                "KILO_CONFIG_CONTENT": json.dumps(config),
                "KILO_PERMISSION": json.dumps({"*": "deny"}),
                "KILO_PURE": "1", "KILO_DISABLE_PROJECT_CONFIG": "1",
                "KILO_DISABLE_CLAUDE_CODE": "1", "KILO_DISABLE_EXTERNAL_SKILLS": "1",
                "KILO_DISABLE_DEFAULT_PLUGINS": "1", "KILO_DISABLE_AUTOUPDATE": "1",
                "KILO_DISABLE_AUTOCOMPACT": "1", "KILO_DISABLE_LSP_DOWNLOAD": "1",
                "KILO_EXPERIMENTAL_DISABLE_FILEWATCHER": "1",
                "KILO_SESSION_RETRY_LIMIT": "0",
            }

            def run(arguments: list[str], input_text: str = "") -> str:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise KiloTutorError(_FAILURE)
                completed = subprocess.run(
                    [executable, *arguments], input=input_text, text=True,
                    capture_output=True, shell=False, check=False,
                    cwd=directory, env=env, timeout=remaining,
                )
                if completed.returncode != 0:
                    raise KiloTutorError(_FAILURE)
                return completed.stdout

            if run(["--version"]).strip() != "7.8.18":
                raise KiloTutorError(_FAILURE)
            resolved = _json(run(["debug", "config", "--pure"]))
            if any(resolved.get(key) for key in ("provider", "mcp", "plugin", "instructions")):
                raise KiloTutorError(_FAILURE)
            if (
                resolved.get("share") != "disabled"
                or resolved.get("default_agent") != _AGENT
                or resolved.get("model") != selected
                or resolved.get("tools") != {"*": False}
            ):
                raise KiloTutorError(_FAILURE)
            agent = _json(run(["debug", "agent", _AGENT, "--pure"]))
            tools = agent.get("tools")
            if (
                agent.get("name") != _AGENT or agent.get("mode") != "primary"
                or agent.get("prompt") != _PROMPT
                or not isinstance(tools, dict) or not tools
                or any(value is not False for value in tools.values())
            ):
                raise KiloTutorError(_FAILURE)
            return _text_events(run([
                "run", "--pure", "--agent", _AGENT, "--model", selected,
                "--format", "json", "--title", "VC tutor",
            ], payload))
    except KiloTutorError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError):
        raise KiloTutorError(_FAILURE) from None
