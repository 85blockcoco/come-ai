from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_importing_nage_does_not_import_the_tutor(tmp_path: Path) -> None:
    marker = tmp_path / "tutor-imported"
    (tmp_path / "vc_tutor.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
        "raise RuntimeError('vc_tutor must not be imported by nage')\n",
        encoding="utf-8",
    )
    repo = _repo_root()
    env = {
        **os.environ,
        "PYTHONPATH": f"{tmp_path}{os.pathsep}{repo}",
    }

    result = subprocess.run(
        [sys.executable, "-c", "import nage"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_importing_nage_has_no_tutor_side_effect(tmp_path: Path) -> None:
    repo = _repo_root()
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}

    result = subprocess.run(
        [sys.executable, "-c", "import nage"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not (home / ".nage" / "vc" / "tutor_config.json").exists()
