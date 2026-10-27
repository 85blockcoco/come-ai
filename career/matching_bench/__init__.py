"""Public API of the adversarial CV/offer matching bench (CVBOOST-08).

The bench measures what the product really does with a synthetic CV/offer
couple.  It is a harness: it calls the existing Career code paths, confronts
them with a hand-written ground truth, and reports the gaps.  It never
changes a business rule.

    >>> from career.matching_bench import run_bench, render_markdown
    >>> run = run_bench()                      # doctest: +SKIP
    >>> print(render_markdown(run))            # doctest: +SKIP

Command line::

    PYTHONPATH=. python -m career.matching_bench list
    PYTHONPATH=. python -m career.matching_bench run --out .devkit/bench
    PYTHONPATH=. python -m career.matching_bench compare base.json candidat.json
"""

from __future__ import annotations

from . import contracts, thresholds, validators
from .fixtures import Case, FixtureError, load_cases, summarize_cases
from .report import build_report, cross_axis_flags, render_markdown, write_reports
from .runner import BenchRun, CaseOutcome, build_observation, observation_hash, run_bench, run_case
from .thresholds import Evaluation, compare_runs, evaluate, load_thresholds

__all__ = [
    "BenchRun",
    "Case",
    "CaseOutcome",
    "Evaluation",
    "FixtureError",
    "build_observation",
    "build_report",
    "compare_runs",
    "contracts",
    "cross_axis_flags",
    "evaluate",
    "load_cases",
    "load_thresholds",
    "observation_hash",
    "render_markdown",
    "run_bench",
    "run_case",
    "summarize_cases",
    "thresholds",
    "validators",
    "write_reports",
]
