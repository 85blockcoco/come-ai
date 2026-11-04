"""Private Gemini setup in the macOS login Keychain; never exports secrets."""

from __future__ import annotations

import argparse
import getpass
import hmac
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_SECURITY = "/usr/bin/security"
_LOGIN_KEYCHAIN = Path.home() / "Library" / "Keychains" / "login.keychain-db"
_PROVIDER_ENV = Path.home() / "Library" / "Application Support" / "NAGE" / "providers.env"
_FLAGS = {
    "VC_TUTOR_CLOUD": "1",
    "VC_TUTOR_KILO": "1",
    "VC_TUTOR_KILO_MODEL": "kilo/nvidia/nemotron-3.5-super-vl:free",
}


class KeychainError(RuntimeError):
    """A bounded error that never contains credentials or subprocess output."""


def _service(slot: int) -> str:
    if isinstance(slot, bool) or not isinstance(slot, int) or slot not in (1, 2, 3):
        raise KeychainError("Invalid Keychain slot.")
    return f"ai.come.nage.gemini.{slot}"


def _valid_key(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.~+/=-]{20,256}", value) is not None


def _available() -> bool:
    return sys.platform == "darwin" and Path(_SECURITY).is_file()


def _run(args, *, runner=None, **kwargs):
    if runner is None:
        if not _available():
            raise KeychainError("The macOS Keychain is unavailable.")
        runner = subprocess.run
    try:
        return runner(args, capture_output=True, text=True, timeout=30, check=False, **kwargs)
    except Exception:
        raise KeychainError("The macOS Keychain operation failed.") from None


def read_key(slot: int, *, runner=None, keychain: Path | None = None) -> str | None:
    service = _service(slot)
    result = _run(
        [_SECURITY, "find-generic-password", "-a", "NAGe", "-s", service, "-w", str(keychain if keychain is not None else _LOGIN_KEYCHAIN)],
        runner=runner,
    )
    if result.returncode == 44:  # errSecItemNotFound, not an authentication failure.
        return None
    if result.returncode != 0:
        raise KeychainError("The macOS Keychain could not read a key.")
    value = result.stdout.rstrip("\r\n")
    if not _valid_key(value):
        raise KeychainError("The stored Keychain value is invalid.")
    return value


def write_key(slot: int, value: str, *, runner=None, keychain: Path | None = None) -> None:
    service = _service(slot)
    if not _valid_key(value):
        raise KeychainError("Invalid key: use an ASCII token of 20 to 256 characters.")
    target = str(keychain if keychain is not None else _LOGIN_KEYCHAIN)
    if any(char in target for char in "\r\n\0"):
        raise KeychainError("Invalid Keychain path.")
    # Token validation excludes quotes, whitespace and command delimiters. The
    # credential is carried in stdin, never in process argv or a shell command.
    target = target.replace("\\", "\\\\").replace('"', '\\"')
    command = f'add-generic-password -U -a NAGe -s {service} -w {value} "{target}"\n'
    result = _run([_SECURITY, "-i", "-q"], runner=runner, input=command)
    if result.returncode != 0:
        raise KeychainError("The macOS Keychain could not save a key.")
    stored = read_key(slot, runner=runner, keychain=keychain)
    if stored is None or not hmac.compare_digest(stored, value):
        raise KeychainError("The macOS Keychain verification failed.")


def gemini_key_environment(*, runner=None, keychain: Path | None = None) -> dict[str, str]:
    result = {}
    for slot in (1, 2, 3):
        value = read_key(slot, runner=runner, keychain=keychain)
        if value:
            result["GEMINI_API_KEY" if slot == 1 else f"GEMINI_API_KEY_{slot}"] = value
    return result


def _reject_symlinks(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise KeychainError("The provider configuration path must not use symlinks.")


def write_provider_flags(path: Path | None = None) -> None:
    """Atomically update consent flags; credentials never enter this file."""
    target = Path(path) if path is not None else _PROVIDER_ENV
    temporary = None
    try:
        _reject_symlinks(target)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_symlinks(target)
        if target.exists() and not stat.S_ISREG(target.stat().st_mode):
            raise KeychainError("The provider configuration is not a regular file.")
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        lines = []
        replaced = set()
        for line in text.splitlines():
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            name = match.group(1) if match else None
            if name in _FLAGS:
                if name not in replaced:
                    lines.append(f"{name}={_FLAGS[name]}")
                    replaced.add(name)
            else:
                lines.append(line)
        lines.extend(f"{name}={value}" for name, value in _FLAGS.items() if name not in replaced)
        descriptor, temporary = tempfile.mkstemp(prefix=".providers-", dir=target.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _reject_symlinks(target)
        os.replace(temporary, target)
        temporary = None
    except KeychainError:
        raise
    except Exception:
        raise KeychainError("The provider configuration could not be saved.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def reload_tutor(*, opener=None) -> bool:
    """Refresh the local tutor configuration, without requesting inference."""
    request = Request("http://127.0.0.1:8765/api/vc/tutor/reload", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        local_open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
        with local_open(request, timeout=5) as response:
            return response.status == 200
    except (OSError, URLError, ValueError):
        return False


def setup(
    *,
    runner=None,
    keychain: Path | None = None,
    provider_path: Path | None = None,
    input_stream=None,
    prompt=None,
    output=None,
    reload_callback=None,
) -> int:
    stream = input_stream if input_stream is not None else sys.stdin
    out = output if output is not None else sys.stdout
    if not stream.isatty():
        raise KeychainError("Keychain setup requires an interactive terminal.")
    reader = prompt if prompt is not None else getpass.getpass
    for slot in (1, 2, 3):
        existing = read_key(slot, runner=runner, keychain=keychain)
        value = reader(f"Gemini key {slot} (hidden; Enter keeps the existing slot): ")
        if value:
            write_key(slot, value, runner=runner, keychain=keychain)
        elif existing is None:
            raise KeychainError("An empty slot requires a key.")
    values = gemini_key_environment(runner=runner, keychain=keychain)
    if len(set(values.values())) < len(values):
        print("Warning: duplicate keys occupy multiple slots; the tutor will deduplicate them.", file=out)
    write_provider_flags(provider_path)
    refreshed = (reload_callback or reload_tutor)()
    print(f"Saved {len(values)} Gemini slots in the macOS login Keychain.", file=out)
    print("Tutor configuration refreshed." if refreshed else "Restart NAGe to load the saved configuration.", file=out)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Configure three private Gemini Keychain slots.")
    parser.add_argument("--status", action="store_true", help="Show only slot presence and count.")
    args = parser.parse_args(argv)
    try:
        if args.status:
            values = gemini_key_environment()
            print(f"Configured Gemini slots: {len(values)}/3")
            for slot in (1, 2, 3):
                name = "GEMINI_API_KEY" if slot == 1 else f"GEMINI_API_KEY_{slot}"
                print(f"Slot {slot}: {'present' if name in values else 'empty'}")
            return 0
        return setup()
    except (KeychainError, EOFError, KeyboardInterrupt):
        print("Keychain setup unavailable or incomplete; no plaintext fallback was used.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
