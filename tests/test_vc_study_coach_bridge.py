from __future__ import annotations

import json
from pathlib import Path

from academics.vc.storage import VcStore
from academics.vc.study_coach_bridge import build_study_coach_payload, write_study_coach_payload


def test_study_coach_bridge_payload(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    payload = build_study_coach_payload(store)
    assert payload["source"] == "nage-vc"
    assert "documents" in payload
    assert len(payload["documents"]) == len(payload["documents"])
    assert payload["stats"]["topics"] > 0
    assert "radar" in payload


def test_study_coach_bridge_write(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    destination = tmp_path / "out.json"
    result = write_study_coach_payload(store, destination)
    assert result == destination
    data = json.loads(destination.read_text(encoding="utf-8"))
    assert data["source"] == "nage-vc"
    assert len(data["documents"]) > 0