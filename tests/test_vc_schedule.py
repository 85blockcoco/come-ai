from __future__ import annotations

import json
from pathlib import Path

from academics.vc.mastery import build_schedule, mastery_radar


def test_schedule_distributes_activities() -> None:
    from academics.vc.content import load_content

    content = load_content()
    records = mastery_radar(content, [], today="2026-11-02")
    schedule = build_schedule(content, records, today="2026-11-02", exam_date="2026-11-06", days=3, daily_minutes=30)
    assert schedule["days"] == 3
    assert schedule["total_minutes"] <= 90
    assert len(schedule["schedule"]) == 3
    assert all(day["minutes"] <= 30 for day in schedule["schedule"])


def test_schedule_cli(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    home = tmp_path / "vc"
    env = {**os.environ, "NAGE_VC_HOME": str(home)}
    result = subprocess.run(
        [sys.executable, "nage.py", "vc", "schedule", "--days", "2", "--daily-minutes", "20", "--json", "--home", str(home)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["days"] == 2
    assert len(data["schedule"]) == 2