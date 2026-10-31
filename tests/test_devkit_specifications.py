"""Spec planning, persistence and OpenCode handoff on synthetic source only."""

import io
import json
import os
import shlex
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from devkit.exporting import KitError
from devkit.router import create_developer_router
from devkit.service import DeveloperWorkshop
from devkit.specifications import SpecificationWorkshop


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "core.py").write_text("VALUE = 1\n")
    (root / "tests").mkdir()
    (root / "tests/test_core.py").write_text("def test_value():\n    assert True\n")
    return root


def payload(**changes):
    result = {
        "title": "Améliorer le calcul synthétique",
        "objective": "La somme de deux valeurs synthétiques doit être exacte.",
        "acceptance": ["2 + 3 vaut 5.", "Les entrées invalides produisent une erreur lisible."],
        "selected_files": ["core.py"],
        "targeted_tests": ["tests/test_core.py"],
    }
    return {**result, **changes}


def test_spec_persists_and_repeated_request_is_idempotent(project):
    store = SpecificationWorkshop(project, project / ".devkit")
    first = store.create(**payload())
    second = store.create(**payload())
    assert first["id"] == second["id"]
    restored = SpecificationWorkshop(project, project / ".devkit").get(first["id"])
    assert restored["status"] == "specified"
    assert len(restored["source_hashes"]) == 2
    assert "AC-01" in restored["documents"]["spec.md"]
    assert "2 + 3 vaut 5" in restored["documents"]["tasks.md"]
    assert os.stat(store.path).st_mode & 0o777 == 0o600


def test_bundle_is_portable_and_contains_no_source_or_private_data(project):
    (project / ".env").write_text("PERSONAL=not-for-export\n")
    store = SpecificationWorkshop(project, project / ".devkit")
    mission = store.create(**payload())
    with zipfile.ZipFile(io.BytesIO(store.bundle(mission["id"]))) as archive:
        assert set(archive.namelist()) == {"spec.md", "plan.md", "tasks.md", "OPENCODE_MISSION.md", "mission.json", "RESULT_TEMPLATE.json"}
        data = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"not-for-export" not in data
        assert str(project).encode() not in data
        assert b"VALUE = 1" not in data
        plan = archive.read("plan.md").decode()
        assert "python -m pytest -q tests/test_core.py" in plan
        assert "git reset" not in data.decode()
        assert json.loads(archive.read("mission.json"))["status"] == "specified"


@pytest.mark.parametrize("changes", [
    {"selected_files": ["../other.py"]},
    {"selected_files": [".env"]},
    {"selected_files": ["career_data/profile.md"]},
    {"targeted_tests": ["core.py"]},
    {"targeted_tests": ["tests/not_here.py"]},
    {"targeted_tests": ["tests/test_core.py;touch hacked"]},
    {"selected_files": ["tests/test_core.py"]},
    {"acceptance": []},
])
def test_invalid_or_private_scope_is_rejected(project, changes):
    store = SpecificationWorkshop(project, project / ".devkit")
    with pytest.raises(KitError):
        store.create(**payload(**changes))


def test_symlink_source_and_storage_are_rejected(project, tmp_path):
    external = tmp_path / "external.py"
    external.write_text("PRIVATE = 1\n")
    (project / "link.py").symlink_to(external)
    store = SpecificationWorkshop(project, project / ".devkit")
    with pytest.raises(KitError):
        store.create(**payload(selected_files=["link.py"]))
    target = tmp_path / "linked-storage"
    target.mkdir()
    (project / "other-storage").symlink_to(target)
    with pytest.raises(KitError):
        SpecificationWorkshop(project, project / "other-storage")


def test_user_secret_is_redacted_before_persistence(project):
    store = SpecificationWorkshop(project, project / ".devkit")
    secret = "sk-proj-" + "s" * 40
    mission = store.create(**payload(objective="Masquer le secret " + secret))
    assert secret not in json.dumps(store.get(mission["id"]), ensure_ascii=False)


def test_queue_is_idempotent_and_retains_targeted_tests(project):
    store = SpecificationWorkshop(project, project / ".devkit")
    mission = store.create(**payload())
    first = store.queue(mission["id"])
    second = store.queue(mission["id"])
    assert first["evolution_task_id"] == second["evolution_task_id"]
    from devkit.evolution_store import EvolutionStore

    task = EvolutionStore(project / ".devkit").get_task(first["evolution_task_id"])
    assert task["targeted_tests"] == ["tests/test_core.py"]
    assert task["status"] == "queued"
    assert "2 + 3 vaut 5" in task["acceptance"]


def test_stale_source_prevents_queueing(project):
    store = SpecificationWorkshop(project, project / ".devkit")
    mission = store.create(**payload())
    (project / "core.py").write_text("VALUE = 2\n")
    with pytest.raises(KitError, match="changé"):
        store.queue(mission["id"])


def test_http_auth_creation_bundle_and_restart(project):
    workshop = DeveloperWorkshop(project)
    app = FastAPI()
    app.include_router(create_developer_router(lambda: workshop))
    with TestClient(app) as client:
        assert client.get("/api/devkit/specifications").status_code == 403
        assert client.get("/api/devkit/session").status_code == 403
        assert client.get("/api/devkit/session", headers={"Origin": "https://outside.example"}).status_code == 403
        token = client.get("/api/devkit/session", headers={"Origin": "http://testserver"}).json()["workshop_token"]
        headers = {"X-Workshop-Token": token}
        assert client.get("/api/devkit/specifications", headers={**headers, "Origin": "https://outside.example"}).status_code == 403
        overview = client.get("/api/devkit/specifications", headers=headers)
        assert overview.status_code == 200
        assert overview.json()["automatic_deployment"] is False
        created = client.post("/api/devkit/specifications", json=payload(), headers=headers)
        assert created.status_code == 200, created.text
        identifier = created.json()["id"]
        url = f"/api/devkit/specifications/{identifier}"
        assert client.get(url + "/bundle").status_code == 403
        bundle = client.get(url + "/bundle", headers=headers)
        assert bundle.status_code == 200
        assert bundle.headers["cache-control"] == "no-store"
        assert bundle.content.startswith(b"PK")
        assert len(client.get("/api/devkit/specifications", headers=headers).json()["missions"]) == 1
        bad = client.post("/api/devkit/specifications", json=payload(title="x" * 161), headers=headers)
        assert bad.status_code == 422
    workshop.close()
    restored = DeveloperWorkshop(project)
    assert restored.specifications().get(identifier)["title"] == payload()["title"]
    restored.close()


def test_session_bootstrap_does_not_scan_unselected_sources(project):
    # An unrelated file would be rejected by a project-wide source export.
    # Opening the UI must not inspect it or bypass the export's secret gate.
    (project / "unselected.py").write_text("TOKEN = '" + "sk-proj-" + "z" * 40 + "'\n")
    workshop = DeveloperWorkshop(project)
    app = FastAPI()
    app.include_router(create_developer_router(lambda: workshop))
    with TestClient(app) as client:
        session = client.get("/api/devkit/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert session.status_code == 200
        headers = {"X-Workshop-Token": session.json()["workshop_token"]}
        assert client.post("/api/devkit/specifications", json=payload(), headers=headers).status_code == 200
        assert client.post("/api/devkit/exports", headers=headers).status_code == 400
    workshop.close()


def test_handoff_quotes_test_paths_as_one_shell_argument(project):
    name = "tests/test_$(touch surprise) demo.py"
    (project / name).write_text("def test_synthetic():\n    assert True\n")
    store = SpecificationWorkshop(project, project / ".devkit")
    mission = store.create(**payload(targeted_tests=[name]))
    plan = store.get(mission["id"])["documents"]["plan.md"]
    command = next(line for line in plan.splitlines() if line.startswith("python -m pytest"))
    assert shlex.split(command) == ["python", "-m", "pytest", "-q", name]
    assert shlex.quote(name) in command


def test_spec_storage_error_is_a_controlled_http_error(project, tmp_path):
    workshop = DeveloperWorkshop(project)
    outside = tmp_path / "outside-specs"
    outside.mkdir()
    (project / ".devkit/specifications").symlink_to(outside)
    app = FastAPI()
    app.include_router(create_developer_router(lambda: workshop))
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/devkit/specifications", headers={"X-Workshop-Token": workshop.token})
        assert response.status_code == 400
        assert "local réel" in response.json()["detail"]
    workshop.close()
