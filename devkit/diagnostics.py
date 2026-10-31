"""Offline diagnostics executed against an exported copy of the source tree.

This module does not import the application, read its configuration, install
packages, or contact a provider. Candidate patches must use ``require_sandbox``:
a Python socket guard is useful for trusted tests but is not an OS sandbox.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

SCHEMA_VERSION = 1
MAX_OUTPUT_BYTES = 64_000
MAX_TIMEOUT_SECONDS = 3_600
MAX_RECEIPT_BYTES = 16_384


@dataclass(frozen=True)
class CommandResult:
    returncode: int | None
    output: str = ""
    timed_out: bool = False


Runner = Callable[..., CommandResult]


def validate_targeted_tests(value: list[str] | None, project_root: Path | None = None) -> list[str] | None:
    """Validate a bounded file selection; never accept pytest flags or node IDs."""
    if value is None:
        return None
    from devkit.exporting import KitError, source_path_allowed

    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise KitError("Sélectionnez entre 1 et 8 fichiers de tests ciblés.")
    for name in value:
        if (not isinstance(name, str) or len(name) > 240 or not source_path_allowed(name)
                or not name.endswith(".py") or not name.startswith(("tests/", "evals/tests/"))):
            raise KitError("Un test ciblé doit être un fichier Python relatif dans tests/ ou evals/tests/.")
        if project_root is not None:
            path = project_root / name
            current = path
            while current != project_root:
                if current.is_symlink():
                    raise KitError("Les liens symboliques sont exclus des tests ciblés.")
                current = current.parent
            if not path.is_file():
                raise KitError("Un fichier de tests ciblé n’existe pas dans les sources sélectionnées.")
    return sorted(set(value))


def source_fingerprint(project_root: Path) -> str:
    """Use the exporter as the single source of truth for the source manifest."""
    from .exporting import source_fingerprint as fingerprint

    return fingerprint(project_root)


def _safe_output(value: str, *, project_root: Path, run_root: Path) -> str:
    """Redact common credential forms and absolute paths without reading secrets."""
    text = str(value)
    text = re.sub(r"(?i)(?:bearer\s+)[^\s\"'<>]+", "Bearer [masqué]", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[masqué]",
        text,
    )
    text = re.sub(r"\b(?:AIza[\w-]+|sk-(?:or-v1-)?[\w-]+)\b", "[clé masquée]", text)
    for path, label in sorted(
        ((str(run_root), "[copie isolée]"), (str(project_root), "[projet]"), (str(Path.home()), "[dossier personnel]")),
        key=lambda pair: len(pair[0]),
        reverse=True,
    ):
        if path and path != "/":
            text = text.replace(path, label)
    text = re.sub(r"/(?:Users|home)/[^\s\"'<>:]+", "[chemin personnel]", text)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_OUTPUT_BYTES:
        text = encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore") + "\n[sortie tronquée]"
    return text


def _environment(run_root: Path) -> dict[str, str]:
    """Construct from scratch: no API keys, proxy variables, or external PYTHONPATH."""
    home = run_root / "home"
    scratch = run_root / "tmp"
    home.mkdir()
    scratch.mkdir()
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin",
        "HOME": str(home),
        "TMPDIR": str(scratch),
        "TMP": str(scratch),
        "TEMP": str(scratch),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "TZ": "UTC",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PIP_NO_INDEX": "1",
        "MPLCONFIGDIR": str(home / "matplotlib"),
        "COME_AI_DIAGNOSTICS_OFFLINE": "1",
        "NO_COLOR": "1",
    }


def _default_runner(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout_seconds: float
) -> CommandResult:
    """Drain output continuously, retain a bounded prefix, and kill the process group."""
    try:
        process = subprocess.Popen(
            list(command), cwd=cwd, env=dict(env), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    except OSError as error:
        return CommandResult(127, f"Impossible de lancer la commande ({type(error).__name__}).")
    assert process.stdout is not None
    chunks = bytearray()
    truncated = False
    timed_out = False
    deadline = time.monotonic() + max(0.05, timeout_seconds)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            events = selector.select(min(remaining, 0.2))
            for key, _ in events:
                block = os.read(key.fd, 16_384)
                if not block:
                    selector.unregister(key.fileobj)
                    break
                room = MAX_OUTPUT_BYTES - len(chunks)
                chunks.extend(block[:max(0, room)])
                truncated |= len(block) > room
            # A detached child must not keep this pipe and the runner alive.
            if process.poll() is not None and not events:
                break
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=1.0)
    finally:
        selector.close()
        process.stdout.close()
    output = chunks.decode("utf-8", errors="replace")
    if truncated:
        output += "\n[sortie tronquée]"
    if timed_out:
        output += "\nDélai maximal dépassé ; processus de diagnostic arrêtés."
    return CommandResult(process.returncode, output, timed_out)


def _sandbox_profile(run_root: Path, python_executable: Path, node_executable: Path | None) -> str:
    """Seatbelt default-deny profile; original files are not an allowed subtree."""
    # The symlinked venv executable needs both the venv packages and its runtime.
    allowed = {
        "/System", "/usr", "/bin", "/sbin", "/Library/Frameworks",
        "/private/etc/ssl", "/private/var/db/timezone",
        str(python_executable.parent.parent),
        str(python_executable.resolve().parent.parent),
    }
    if node_executable:
        allowed.add(str(node_executable.resolve().parent.parent))
    clauses = [
        "(version 1)", "(deny default)", "(deny network*)",
        "(allow process-exec)", "(allow process-fork)",
        "(allow signal (target self))", "(allow sysctl-read)",
        "(allow file-read* (literal \"/dev/null\") (literal \"/dev/random\") (literal \"/dev/urandom\") (literal \"/private/etc/localtime\"))",
        "(allow file-write* (literal \"/dev/null\"))",
        # Python's macOS framework launcher resolves ancestor directories.
        # Listing the system root does not authorize contents of user homes.
        "(allow file-read* (literal \"/\") (literal \"/private\") (literal \"/private/tmp\"))",
    ]
    ancestors = {str(parent) for path in (run_root, python_executable, python_executable.resolve()) for parent in path.parents}
    clauses.append("(allow file-read-metadata " + " ".join(f"(literal {json.dumps(path)})" for path in sorted(ancestors)) + ")")
    for path in sorted(allowed):
        clauses.append(f"(allow file-read* (subpath {json.dumps(path)}))")
    clauses.append(f"(allow file-read* file-write* (subpath {json.dumps(str(run_root))}))")
    return "\n".join(clauses)


# A trusted bootstrap lives outside candidate source. It blocks Python network
# calls before loading tests and never reads project configuration or .env.
_BOOTSTRAP = r'''
import ast, importlib.metadata, json, os, pathlib, resource, runpy, socket, subprocess, sys
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024, 256 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
def forbidden(*args, **kwargs):
    raise RuntimeError("Accès réseau désactivé pendant les diagnostics hors ligne")
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
original_sendto = socket.socket.sendto
def connect(self, *args, **kwargs):
    if self.family in (socket.AF_INET, socket.AF_INET6): forbidden()
    return original_connect(self, *args, **kwargs)
def connect_ex(self, *args, **kwargs):
    if self.family in (socket.AF_INET, socket.AF_INET6): forbidden()
    return original_connect_ex(self, *args, **kwargs)
def sendto(self, *args, **kwargs):
    if self.family in (socket.AF_INET, socket.AF_INET6): forbidden()
    return original_sendto(self, *args, **kwargs)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.socket.sendto = sendto
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
os.environ.pop("PYTHONPATH", None)
sys.path.insert(0, os.getcwd())
action, *arguments = sys.argv[1:]
if action == "syntax":
    failed = []
    files = json.loads(arguments[0])
    for name in files:
        try:
            ast.parse(pathlib.Path(name).read_bytes(), filename=name)
        except (SyntaxError, ValueError, OSError) as error:
            failed.append(name)
            print(f"{name}: {type(error).__name__}: {error}")
    print(f"{len(files)} fichiers Python analysés ; {len(failed)} erreurs.")
    raise SystemExit(bool(failed))
elif action == "pytest":
    import pytest
    receipt_path = pathlib.Path(arguments[0])
    class ReceiptPlugin:
        def __init__(self):
            self.outcomes = {}
            self.collection_errors = 0
            self.finished = False
            self.collected = 0
        def pytest_runtest_logreport(self, report):
            previous = self.outcomes.get(report.nodeid)
            if report.failed:
                self.outcomes[report.nodeid] = "failed" if report.when == "call" else "error"
            elif report.skipped and previous not in ("passed", "failed", "error"):
                self.outcomes[report.nodeid] = "skipped"
            elif report.when == "call" and report.passed and previous not in ("failed", "error"):
                self.outcomes[report.nodeid] = "passed"
        def pytest_collectreport(self, report):
            if report.failed:
                self.collection_errors += 1
        def pytest_sessionfinish(self, session, exitstatus):
            self.finished = True
            self.collected = int(session.testscollected)
    plugin = ReceiptPlugin()
    test_paths = json.loads(arguments[1]) if len(arguments) > 1 else [path for path in ("tests", "evals/tests") if pathlib.Path(path).is_dir()]
    exitstatus = int(pytest.main(["-q", "--tb=short", "-p", "no:cacheprovider", *test_paths], plugins=[plugin]))
    outcomes = list(plugin.outcomes.values())
    receipt = {
        "schema_version": 1,
        "completed": plugin.finished,
        "exitstatus": exitstatus,
        "tests_collected": plugin.collected,
        "tests_executed": sum(value in ("passed", "failed", "error") for value in outcomes),
        "tests_passed": outcomes.count("passed"),
        "tests_failed": outcomes.count("failed") + outcomes.count("error") + plugin.collection_errors,
        "tests_skipped": outcomes.count("skipped"),
        "collection_errors": plugin.collection_errors,
    }
    # A receipt exists only after pytest.main returned normally. Printed text
    # or a premature os._exit(0) cannot produce a successful validation.
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False)
    raise SystemExit(exitstatus)
elif action == "smoke":
    sys.argv = [arguments[0]]
    runpy.run_path(arguments[0], run_name="__main__")
elif action == "pip_check":
    sys.argv = ["pip", "check", "--disable-pip-version-check"]
    runpy.run_module("pip", run_name="__main__")
elif action == "metadata":
    packages = sorted({(d.metadata.get("Name", "unknown"), d.version) for d in importlib.metadata.distributions()})
    print(json.dumps({"python": sys.version.split()[0], "platform": sys.platform,
                      "packages": [{"name": name, "version": version} for name, version in packages]}, ensure_ascii=False))
elif action == "javascript":
    executable, *files = arguments
    failed = 0
    for name in files:
        result = subprocess.run([executable, "--check", name], capture_output=True, text=True)
        if result.returncode:
            failed += 1
            print(name + ": " + result.stdout + result.stderr)
    print(f"{len(files)} fichiers JavaScript analysés ; {failed} erreurs.")
    raise SystemExit(bool(failed))
else:
    raise SystemExit("Action de diagnostic inconnue")
'''


def _pytest_counts(output: str) -> dict[str, int]:
    """Optional stdout display hint only; never a validation or count proof."""
    summary = ""
    for line in output.splitlines():
        if re.search(r"\b\d+ (?:passed|failed|error|errors|skipped)\b", line) and " in " in line:
            summary = line
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for amount, kind in re.findall(r"(\d+) (passed|failed|errors?|skipped)\b", summary):
        counts[kind.rstrip("s") if kind.startswith("error") else kind] += int(amount)
    return {
        "tests_executed": counts["passed"] + counts["failed"] + counts["error"],
        "tests_passed": counts["passed"],
        "tests_failed": counts["failed"] + counts["error"],
        "tests_skipped": counts["skipped"],
    }


def _read_pytest_receipt(path: Path, returncode: int | None) -> dict[str, int] | None:
    """Read bounded numeric outcomes generated after normal pytest completion."""
    fields = ("tests_executed", "tests_passed", "tests_failed", "tests_skipped", "tests_collected", "collection_errors")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as handle:
            attributes = os.fstat(handle.fileno())
            if not stat.S_ISREG(attributes.st_mode) or attributes.st_size > MAX_RECEIPT_BYTES:
                return None
            data = handle.read(MAX_RECEIPT_BYTES + 1)
        if len(data) > MAX_RECEIPT_BYTES:
            return None
        receipt = json.loads(data)
        if not isinstance(receipt, dict) or receipt.get("schema_version") != 1 or receipt.get("completed") is not True:
            return None
        if type(receipt.get("exitstatus")) is not int or receipt["exitstatus"] != returncode:
            return None
        if any(type(receipt.get(field)) is not int or not 0 <= receipt[field] <= 1_000_000 for field in fields):
            return None
        if receipt["tests_executed"] != receipt["tests_passed"] + receipt["tests_failed"] - receipt["collection_errors"]:
            return None
        if receipt["tests_executed"] + receipt["tests_skipped"] > receipt["tests_collected"]:
            return None
        return {field: receipt[field] for field in fields}
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _store_report(report: dict, directory: Path) -> None:
    if directory.is_symlink():
        raise ValueError("Le dossier des diagnostics doit être un dossier réel.")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report["created_at"].replace(":", "-").replace("+00-00", "Z")
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    lines = ["# Diagnostic Côme AI", "", f"État : **{report['status']}**", "",
             f"Date UTC : {report['created_at']}", f"Empreinte source : `{report['source_fingerprint']}`", "",
             f"Tests exécutés : {report['tests_executed']} ; réussis : {report['tests_passed']} ; erreurs : {report['tests_failed']}", "",
             f"Isolation OS : {'active' if report['sandbox_used'] else 'indisponible'}", ""]
    for check in report["checks"]:
        lines.extend([f"## {check['name']} — {check['status']}", "", "````text", check["output"], "````", ""])
    markdown = "\n".join(lines)
    for target, data in ((directory / f"{stamp}.json", payload), (directory / f"{stamp}.md", markdown),
                         (directory / "latest.json", payload), (directory / "latest.md", markdown)):
        descriptor, temporary_name = tempfile.mkstemp(prefix=".diagnostic-", suffix=".tmp", dir=directory)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(data)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def run_diagnostics(
    project_root: Path, *, report_dir: Path | None = None,
    python_executable: Path | None = None, timeout_seconds: int = 600,
    isolated: bool = True, require_sandbox: bool = False, runner: Runner | None = None,
    targeted_tests: list[str] | None = None,
) -> dict:
    """Run source checks, offline tests, and installed dependency checks.

    The ``isolated`` argument is retained for callers, but diagnostics always
    use a filtered copy so originals cannot acquire test outputs or pycache.
    ``runner`` is an injection point for deterministic unit tests only.
    """
    from .exporting import materialize_source

    root = Path(project_root).resolve()
    targeted_tests = validate_targeted_tests(targeted_tests, root)
    executable = Path(python_executable or root / ".venv/bin/python").absolute()
    started = time.monotonic()
    budget = max(1, min(int(timeout_seconds), MAX_TIMEOUT_SECONDS))
    command_runner = runner or _default_runner
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked", "checks": [], "source_fingerprint": "",
        "isolated": True, "sandbox_available": False, "sandbox_used": False,
        "network": "disabled", "dependencies": {},
        "pytest_receipt_verified": False,
        "tests_executed": 0, "tests_passed": 0, "tests_failed": 0, "tests_skipped": 0,
        "targeted_tests": targeted_tests,
    }
    destination = Path(report_dir) if report_dir is not None else root / ".devkit/diagnostics"
    with tempfile.TemporaryDirectory(prefix="come-ai-diagnostics-") as temporary:
        run_root = Path(temporary).resolve()
        source = run_root / "source"
        try:
            inventory = materialize_source(root, source)
            validate_targeted_tests(targeted_tests, source)
            report["source_fingerprint"] = source_fingerprint(source)
        except (OSError, ValueError, RuntimeError) as error:
            report["checks"].append({"name": "source_copy", "status": "blocked", "returncode": None,
                                     "duration_seconds": 0.0,
                                     "output": f"Copie de sources indisponible ({type(error).__name__})."})
            report["duration_seconds"] = round(time.monotonic() - started, 3)
            _store_report(report, destination)
            return report
        environment = _environment(run_root)
        bootstrap = run_root / "diagnostics_bootstrap.py"
        bootstrap.write_text(_BOOTSTRAP, encoding="utf-8")
        pytest_receipt = run_root / "pytest-receipt.json"
        node = shutil.which("node")
        sandbox = shutil.which("sandbox-exec")
        prefix: list[str] = []
        if sandbox:
            profile = _sandbox_profile(run_root, executable, Path(node) if node else None)
            probe = command_runner([sandbox, "-p", profile, str(executable), "-I", "-c", "print('sandbox-ready')"],
                                   cwd=source, env=environment, timeout_seconds=min(10, budget))
            if probe.returncode == 0 and not probe.timed_out:
                report["sandbox_available"] = True
                report["sandbox_used"] = True
                prefix = [sandbox, "-p", profile]
        if require_sandbox and not report["sandbox_used"]:
            report["checks"].append({"name": "sandbox", "status": "blocked", "returncode": None,
                                     "duration_seconds": round(time.monotonic() - started, 3),
                                     "output": "Validation de correctif bloquée : isolation OS indisponible. Aucun code du candidat exécuté."})
        elif not executable.is_file():
            report["checks"].append({"name": "python", "status": "blocked", "returncode": None,
                                     "duration_seconds": 0.0,
                                     "output": "Python du venv indisponible ; aucune installation automatique."})
        else:
            # source_inventory consists of safe relative source entries.
            entries = inventory.get("files", []) if isinstance(inventory, dict) else inventory
            paths = [str(entry["path"]) for entry in entries]
            python_paths = sorted(path for path in paths if path.endswith(".py"))
            javascript_paths = sorted(path for path in paths if path.endswith(".js"))
            plan: list[tuple[str, list[str] | None, str]] = [
                ("python_syntax", ["syntax", json.dumps(python_paths)], "Aucun fichier Python exporté."),
                ("environment", ["metadata"], ""),
                ("pip_check", ["pip_check"], ""),
                ("pytest", ["pytest", str(pytest_receipt), *([json.dumps(targeted_tests)] if targeted_tests else [])] if any((source / path).is_dir() for path in ("tests", "evals/tests")) else None, "Dossiers de tests absents ; aucun test exécuté."),
                ("offline_smoke", ["smoke", "test_v3_offline.py"] if (source / "test_v3_offline.py").is_file() else None, "Smoke test V3 absent."),
                ("javascript_syntax", ["javascript", node, *javascript_paths] if node and javascript_paths else None,
                 "Node absent." if not node else "Aucun fichier JavaScript exporté."),
            ]
            for name, arguments, skipped_reason in plan:
                check_started = time.monotonic()
                remaining = budget - (check_started - started)
                if arguments is None:
                    result = CommandResult(None, skipped_reason)
                    status = "skipped"
                elif remaining <= 0:
                    result = CommandResult(None, "Budget de temps global épuisé ; vérification non exécutée.")
                    status = "blocked"
                else:
                    try:
                        result = command_runner([*prefix, str(executable), "-I", str(bootstrap), *arguments],
                                                cwd=source, env=environment, timeout_seconds=remaining)
                    except (OSError, subprocess.SubprocessError) as error:
                        result = CommandResult(None, f"Commande indisponible ({type(error).__name__}).")
                    status = "failed" if result.timed_out or result.returncode != 0 else "passed"
                output = _safe_output(result.output, project_root=root, run_root=run_root)
                receipt = None
                if name == "pytest" and arguments is not None and status != "blocked":
                    receipt = _read_pytest_receipt(pytest_receipt, result.returncode)
                    if receipt is None:
                        status = "failed"
                        output += "\nReçu de fin pytest absent ou invalide ; aucun résultat de test vérifié."
                    else:
                        report["pytest_receipt_verified"] = True
                        report.update(receipt)
                        if receipt["tests_failed"] or result.returncode != 0:
                            status = "failed"
                check = {"name": name, "status": status, "returncode": result.returncode,
                         "duration_seconds": round(time.monotonic() - check_started, 3), "output": output}
                if name == "pytest" and arguments is not None and receipt is None:
                    check["unverified_stdout_summary"] = _pytest_counts(output)
                report["checks"].append(check)
                if name == "environment" and status == "passed":
                    try:
                        metadata = json.loads(output)
                        if isinstance(metadata, dict):
                            report["dependencies"] = metadata
                    except json.JSONDecodeError:
                        pass
        statuses = {check["status"] for check in report["checks"]}
        try:
            unchanged = source_fingerprint(root) == report["source_fingerprint"] == source_fingerprint(source)
        except (OSError, ValueError, RuntimeError):
            unchanged = False
        if not unchanged:
            report["checks"].append({"name": "source_consistency", "status": "blocked", "returncode": None,
                                     "duration_seconds": 0.0,
                                     "output": "Les sources ont changé pendant le diagnostic ; résultat non utilisable pour appliquer un correctif."})
            statuses.add("blocked")
        report["status"] = "blocked" if "blocked" in statuses else "failed" if "failed" in statuses else "passed"
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["isolation_notice"] = (
            "Copie filtrée, environnement sans clés, réseau refusé par le sandbox OS."
            if report["sandbox_used"] else
            "Copie filtrée et garde réseau Python ; mode réservé au diagnostic de sources de confiance."
        )
        _store_report(report, destination)
        return report


__all__ = ["CommandResult", "run_diagnostics", "source_fingerprint"]
