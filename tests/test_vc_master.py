from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(repo: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "nage.py"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_master_status_uses_the_deterministic_exam_date(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    vc_home = tmp_path / "vc"
    home.mkdir()
    vc_home.mkdir()
    (vc_home / "settings.json").write_text(
        json.dumps(
            {
                "language": "fr",
                "exam_date": "2026-11-06",
                "exam_time": "16:00",
                "exam_duration_minutes": 90,
                "daily_capacity": 60,
            }
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(home), "NAGE_VC_HOME": str(vc_home)}

    result = _run(repo, env, "vc", "master", "status")

    assert result.returncode == 0
    assert "2026-11-06 16:00 (90 min)" in result.stdout
    assert "2026-11-07" not in result.stdout


def test_master_set_exam_persists_the_same_settings(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    vc_home = tmp_path / "vc"
    home.mkdir()
    vc_home.mkdir()
    (vc_home / "settings.json").write_text(
        json.dumps({"language": "fr", "daily_capacity": 60, "custom": "keep"}),
        encoding="utf-8",
    )
    env = {**os.environ, "HOME": str(home), "NAGE_VC_HOME": str(vc_home)}

    result = _run(
        repo,
        env,
        "vc",
        "master",
        "set-exam",
        "2026-12-01",
        "09:30",
        "--duration",
        "120",
    )

    assert result.returncode == 0
    settings = json.loads((vc_home / "settings.json").read_text(encoding="utf-8"))
    assert settings["exam_date"] == "2026-12-01"
    assert settings["exam_time"] == "09:30"
    assert settings["exam_duration_minutes"] == 120
    assert settings["language"] == "fr"
    assert settings["custom"] == "keep"
