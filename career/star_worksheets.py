"""STAR worksheets for interview preparation (N100-H02)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StarWorksheet:
    question_id: str
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    completeness: float = 0.0


def compute_completeness(ws: StarWorksheet) -> float:
    fields = [ws.situation, ws.task, ws.action, ws.result]
    filled = sum(1 for f in fields if str(f).strip())
    return round(filled / 4.0, 2)


def build_worksheet(question_id: str, situation: str = "", task: str = "",
                    action: str = "", result: str = "") -> StarWorksheet:
    ws = StarWorksheet(question_id=question_id, situation=situation, task=task,
                       action=action, result=result)
    ws.completeness = compute_completeness(ws)
    return ws


def ready_worksheets(worksheets: list[StarWorksheet], threshold: float = 0.8) -> list[StarWorksheet]:
    return [ws for ws in worksheets if ws.completeness >= threshold]