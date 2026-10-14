"""Tests d'isolation, de sécurité et de non-régression du garde-fou.

Vérifient qu'aucun appel réseau n'est possible depuis le paquet, qu'aucune
donnée personnelle réelle n'entre dans le dépôt Git, que les fichiers possédés
par d'autres intervenants ne sont pas touchés, et que ce lot n'ajoute rien en
dehors de son périmètre autorisé : ``consent_guard/``, ``tests/test_consent_guard_*.py``
et la documentation du contrat.
"""

from __future__ import annotations

import ast
import json
import os
import re
import socket
import sys
import subprocess
from pathlib import Path

import pytest

from consent_guard import ConsentGuard

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "consent_guard"
FIXTURE = PACKAGE_DIR / "fixtures" / "synthetic_transmission.json"
CONTRACT = PACKAGE_DIR / "contracts" / "integration_contract.json"
REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORTS = {
    "socket",
    "ssl",
    "http",
    "http.client",
    "httpx",
    "requests",
    "urllib",
    "urllib.request",
    "urllib.error",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncio",
    "aiohttp",
    "websocket",
    "boto3",
    "google",
    "openai",
    "anthropic",
}

#: Modules possédés par les autres lots : jamais importés, jamais modifiés.
PROTECTED_MODULES = {
    "hybrid_chat",
    "intelligence_bridge",
    "come_ai_web",
    "free_ai_router",
    "v5_orchestrator",
    "career",
    "devkit",
    "evals",
    "workspace_core",
    "personal_memory",
    "memory_storage",
    "task_queue",
    "usage_ledger",
    "personal_profile",
    "study_coach",
    "agent",
    "agent_v2",
    "app_v3",
    "local_ai_runtime",
    "profile_chat",
    "personal_profile_web",
    "study_web",
}

#: Fichiers possédés par d'autres intervenants : jamais modifiés par ce lot.
PROTECTED_PATHS = (
    "hybrid_chat.py",
    "intelligence_bridge.py",
    "come_ai_web.py",
    "free_ai_router.py",
    "v5_orchestrator.py",
    "agent.py",
    "agent_v2.py",
    "app_v3.py",
    "local_ai_runtime.py",
    "memory_storage.py",
    "personal_memory.py",
    "task_queue.py",
    "usage_ledger.py",
    "workspace_core.py",
    "profile_chat.py",
    "personal_profile_web.py",
    "study_web.py",
    "run_come_ai_v3.py",
    "pytest.ini",
    "requirements-v3.txt",
    ".env",
    ".env.example",
)

#: Modules standards autorisés : le paquet reste stdlib-only.
ALLOWED_ROOT_MODULES = {
    "__future__",
    "argparse",
    "ast",
    "contextlib",
    "dataclasses",
    "datetime",
    "hashlib",
    "hmac",
    "json",
    "os",
    "pathlib",
    "re",
    "secrets",
    "shutil",
    "sqlite3",
    "sys",
    "tempfile",
    "threading",
    "typing",
    "consent_guard",
}

#: Préfixes de chemins que ce lot est autorisé à ajouter.
EXPECTED_NEW_PREFIXES = ("consent_guard/", "tests/test_consent_guard_", "docs/CONSENT_GUARD", "HANDOFF_consent_guard")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_PHONE_RE = re.compile(r"\b0[1-9](?:[ .-]?\d{2}){4}\b")


def _python_files() -> list[Path]:
    return sorted(path for path in PACKAGE_DIR.rglob("*.py") if "__pycache__" not in path.parts)


def _changed_files() -> list[str]:
    """Fichiers ajoutés ou modifiés par ce lot, commit compris ou non."""

    changed: list[str] = []
    for arguments in (
        ["git", "diff", "--name-only", "c32b284", "HEAD"],
        ["git", "diff", "--name-only", "c32b284"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        try:
            output = subprocess.run(
                arguments, cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - hors Git
            continue
        changed.extend(line for line in output.stdout.splitlines() if line.strip())
    return sorted(set(changed))


class TestNoCloudCalls:
    def test_package_never_imports_a_network_module(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in _python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found: set[str] = set()
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    if name in FORBIDDEN_IMPORTS or root in FORBIDDEN_IMPORTS:
                        found.add(name)
            if found:
                offenders[path.name] = sorted(found)
        assert offenders == {}, f"Modules réseau détectés : {offenders}"

    def test_package_only_uses_the_standard_library(self) -> None:
        for path in _python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    assert root in ALLOWED_ROOT_MODULES, f"{path.name} importe {name}"

    def test_no_eval_exec_or_compile(self) -> None:
        for path in _python_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile"}, f"{path.name} utilise {node.func.id}"

    def test_no_transport_lives_inside_the_package(self) -> None:
        """Le paquet décide : il n'embarque aucun expéditeur, fictif ou réel."""

        for path in _python_files():
            if path.name in {"demo.py", "check.py"}:
                continue
            blob = path.read_text(encoding="utf-8")
            for token in ("http://", "https://", "generativelanguage", "openrouter.ai", "api_key", "API_KEY"):
                assert token not in blob, f"{path.name} mentionne {token}"

    def test_sockets_are_blocked_during_a_full_cycle(self, tmp_path, monkeypatch) -> None:
        def _fail(*args: object, **kwargs: object) -> None:  # pragma: no cover
            raise AssertionError("Un appel réseau a été tenté.")

        monkeypatch.setattr(socket, "socket", _fail)
        monkeypatch.setattr(socket, "create_connection", _fail)
        monkeypatch.setattr(socket, "getaddrinfo", _fail)

        guard = ConsentGuard(tmp_path)
        grant = guard.grant(
            provider="gemini",
            model="gemini-3.8-flash",
            purpose="generic",
            payload={"marker": "MARQUEUR-SYNTHETIQUE", "items": ["a"]},
        )
        assert guard.check(
            grant.consent_id,
            provider="gemini",
            model="gemini-3.8-flash",
            purpose="generic",
            payload={"marker": "MARQUEUR-SYNTHETIQUE", "items": ["a"]},
        ).allowed
        guard.consume(
            grant.consent_id,
            provider="gemini",
            model="gemini-3.8-flash",
            purpose="generic",
            payload={"marker": "MARQUEUR-SYNTHETIQUE", "items": ["a"]},
        )
        guard.forget_everything()
        guard.close()

    def test_no_cloud_key_is_required(self, tmp_path, monkeypatch) -> None:
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        guard = ConsentGuard(tmp_path)
        assert guard.grant(
            provider="gemini", model="gemini-3.8-flash", purpose="generic", payload="contenu synthétique"
        ).consent_id
        guard.close()


class TestNoRealPersonalData:
    def test_fixture_contains_no_email_or_phone(self) -> None:
        blob = FIXTURE.read_text(encoding="utf-8")
        assert not _EMAIL_RE.search(blob)
        assert not _PHONE_RE.search(blob)

    def test_fixture_is_declared_synthetic(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert data["schema"] == "come-consent-guard-request/1"
        assert "synthétique" in data["note"].lower()
        assert data["payload"]["subject_label"].startswith("synthetic")
        assert "AUCUNE-DONNEE-REELLE" in data["payload"]["marker"]

    def test_source_code_contains_no_personal_identifier(self) -> None:
        for path in _python_files():
            blob = path.read_text(encoding="utf-8")
            assert not _EMAIL_RE.search(blob), f"{path.name} contient une adresse e-mail"
            assert not _PHONE_RE.search(blob), f"{path.name} contient un numéro de téléphone"

    def test_no_personal_path_appears_in_the_contract(self) -> None:
        blob = CONTRACT.read_text(encoding="utf-8")
        assert "/Users/" not in blob
        assert os.path.expanduser("~") not in blob

    def test_the_store_never_records_an_absolute_path(self, tmp_path) -> None:
        guard = ConsentGuard(tmp_path)
        grant = guard.grant(
            provider="gemini", model="gemini-3.8-flash", purpose="generic", payload="contenu synthétique"
        )
        exported = json.dumps(grant.as_dict(), ensure_ascii=False)
        assert str(tmp_path) not in exported
        assert "/Users/" not in exported
        assert os.path.expanduser("~") not in exported
        guard.close()


class TestNoProtectedFileTouched:
    def test_package_lives_in_its_own_directory(self) -> None:
        assert PACKAGE_DIR.is_dir()
        assert PACKAGE_DIR.name == "consent_guard"

    def test_only_authorised_paths_were_added(self) -> None:
        tracked = set(_changed_files())
        unexpected = [
            path
            for path in tracked
            if not path.startswith(EXPECTED_NEW_PREFIXES)
            and not path.startswith("tests/test_consent_guard_")
        ]
        assert unexpected == [], f"Chemins hors périmètre : {sorted(unexpected)}"

    def test_protected_backend_files_are_untouched(self) -> None:
        tracked = set(_changed_files())
        for protected in PROTECTED_PATHS:
            matches = [path for path in tracked if path.endswith(f"/{protected}") or path == protected]
            assert matches == [], f"{protected} a été modifié par ce lot"

    def test_package_does_not_import_protected_modules(self) -> None:
        for path in _python_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert name.split(".")[0] not in PROTECTED_MODULES, f"{path.name} importe {name}"

    def test_package_is_self_contained(self) -> None:
        for path in _python_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    assert root in {"consent_guard"} | ALLOWED_ROOT_MODULES, f"{path.name} importe {node.module}"

    def test_tests_do_not_import_protected_modules(self) -> None:
        for path in sorted(REPO_ROOT.glob("tests/test_consent_guard_*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    assert name.split(".")[0] not in PROTECTED_MODULES, f"{path.name} importe {name}"


class TestContractDocument:
    def test_the_machine_readable_contract_is_valid_json(self) -> None:
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        assert data["contract"] == "come-consent-guard-integration/1"
        assert data["guarantees"]
        assert data["methods"]["grant"]["signature"]
        assert "single_use" in json.dumps(data)

    def test_the_contract_lists_every_refusal_code(self) -> None:
        from consent_guard import REFUSAL_CODES

        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = set(data["refusal_codes"])
        assert declared == set(REFUSAL_CODES)

    def test_the_documented_contract_matches_the_package(self) -> None:
        from consent_guard import CONTRACT_ID

        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        assert data["envelope"]["contract"] == CONTRACT_ID
        assert data["envelope"]["single_use"] == 1


class TestNonRegression:
    def test_the_demonstration_is_green(self) -> None:
        """Non-régression : la démonstration locale réussit de bout en bout."""

        result = subprocess.run(
            [sys.executable, "-m", "consent_guard.demo", "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout[-2000:]
        report = json.loads(result.stdout)
        assert report["success"] is True
        assert report["transport_calls"] == 1
        assert all(entry[2] for entry in report["steps"])

    def test_the_white_box_check_is_green(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "consent_guard.check", str(FIXTURE), "--json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout[-2000:]
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["summary"]["provider"] == "gemini"
        assert payload["summary"]["single_use"] is True

    def test_no_python_bytecode_is_committed(self) -> None:
        tracked = set(_changed_files())
        assert not [path for path in tracked if path.endswith((".pyc", ".pyo"))]
