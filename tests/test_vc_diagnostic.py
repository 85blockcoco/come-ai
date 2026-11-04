from __future__ import annotations

import json
from pathlib import Path


def test_diagnostic_start_and_submit(tmp_path: Path) -> None:
    home = tmp_path / "vc"
    # start
    import os
    import subprocess
    import sys

    env = {**os.environ, "NAGE_VC_HOME": str(home)}
    out = subprocess.check_output(
        [sys.executable, "nage.py", "vc", "diagnostic", "start", "--questions", "5", "--minutes", "10", "--seed", "42", "--json", "--home", str(home)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
    )
    exam = json.loads(out)
    assert exam["diagnostic"] is True
    answers = {q["question_id"]: q.get("answer", "") for q in exam["questions"]}
    (tmp_path / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "nage.py", "vc", "diagnostic", "submit", exam["exam_id"], "--answers", str(tmp_path / "answers.json"), "--json", "--home", str(home)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "weakest_topics" in data
    assert "next_step" in data