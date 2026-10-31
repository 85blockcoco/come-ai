"""Dashboard helpers for controlled automation (SPEC-016)."""

from __future__ import annotations

from typing import Any

from .controlled_automation import AutomationOrchestrator, DashboardData, to_dict


def build_dashboard(orchestrator: AutomationOrchestrator) -> dict[str, Any]:
    data = orchestrator.get_dashboard_data()
    return to_dict(data)


def dashboard_to_dict(data: DashboardData) -> dict[str, Any]:
    return to_dict(data)


__all__ = ["build_dashboard", "dashboard_to_dict", "DashboardData"]
