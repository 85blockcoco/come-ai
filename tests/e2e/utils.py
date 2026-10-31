import json
from pathlib import Path


def load_fixture(name):
    path = Path(__file__).resolve().parent / "fixtures" / "offers" / name
    return json.loads(path.read_text(encoding="utf-8"))


def import_job(page, base_url, payload):
    response = page.request.post(base_url + "/api/career/jobs/import", data=payload)
    assert response.ok, response.text()
    return response.json()["id"]


def update_profile(page, base_url, payload):
    response = page.request.put(base_url + "/api/career/profile", data=payload)
    assert response.ok, response.text()
    return response.json()