from __future__ import annotations

import json
from pathlib import Path


def test_predict_cli(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    home = tmp_path / "vc"
    env = {**os.environ, "NAGE_VC_HOME": str(home)}
    result = subprocess.run(
        [sys.executable, "nage.py", "vc", "predict", "--count", "3", "--json", "--home", str(home)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["count"] == 3
    assert len(data["questions"]) == 3