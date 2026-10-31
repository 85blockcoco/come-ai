"""Tests for STAR worksheets (N100-H02)."""

from __future__ import annotations

import pytest

from career.star_worksheets import StarWorksheet, build_worksheet, compute_completeness, ready_worksheets


def test_compute_completeness_full() -> None:
    ws = StarWorksheet(question_id="q1", situation="s", task="t", action="a", result="r")
    assert compute_completeness(ws) == 1.0


def test_compute_completeness_empty() -> None:
    ws = StarWorksheet(question_id="q1")
    assert compute_completeness(ws) == 0.0


def test_compute_completeness_partial() -> None:
    ws = StarWorksheet(question_id="q1", situation="s", task="t")
    assert compute_completeness(ws) == 0.5


def test_build_worksheet() -> None:
    ws = build_worksheet("q1", situation="s", task="t", action="a", result="r")
    assert ws.completeness == 1.0


def test_ready_filter() -> None:
    ws1 = build_worksheet("q1", situation="s", task="t", action="a", result="r")
    ws2 = build_worksheet("q2", situation="s")
    ready = ready_worksheets([ws1, ws2], threshold=0.8)
    assert len(ready) == 1
    assert ready[0].question_id == "q1"


def test_threshold_custom() -> None:
    ws = build_worksheet("q1", situation="s", task="t")
    ready = ready_worksheets([ws], threshold=0.4)
    assert len(ready) == 1