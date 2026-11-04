"""Fresh, deterministic practice variants for the VC learning path.

The original lesson remains the source of truth.  Variants only change the
numbers (and the resulting correction), so the student must redo the method
instead of memorising the worked example.
"""

from __future__ import annotations

import random
import re
from typing import Any

from .models import FormulaDrill


def _money(rng: random.Random, low: int, high: int, step: int = 5) -> int:
    return rng.randrange(low // step, high // step + 1) * step


def lesson_variant(lesson: dict[str, Any], seed: int) -> dict[str, Any]:
    """Return a serialisable lesson overlay, stable for ``lesson + seed``."""
    if lesson.get("id") != "financing-stages":
        return {"variant_id": f"lesson-{lesson.get('id')}-{seed}", "quiz": lesson["quiz"], "example": lesson["example"]}
    rng = random.Random(seed)
    burn = _money(rng, 35, 95)
    months = rng.choice((9, 10, 12, 15, 18))
    founders = rng.choice((72, 78, 82, 85, 88))
    investor = rng.choice((12, 15, 18, 22, 25))
    funding = burn * months
    retained = round(founders * (1 - investor / 100), 1)
    return {
        "variant_id": f"lesson-financing-stages-{seed}",
        "example": {
            "label": "Fresh-number worked practice",
            "context": f"Founders own {founders}% before a seed round. The company burns €{burn}k per month, needs {months} months, and gives the seed investor {investor}% of post-round equity.",
            "steps": [
                f"Funding need = €{burn}k × {months} = €{funding}k.",
                f"Existing owners retain 1 − {investor}% = {100 - investor}% of their previous stake.",
                f"Founders after the round = {founders}% × {100 - investor}%.",
            ],
            "result": f"€{funding}k funding and {retained:g}% founder ownership.",
        },
        "quiz": [
            {
                "kind": "numeric",
                "prompt": f"At €{burn}k monthly burn, how many €k are needed for {months} months?",
                "answer": funding,
                "unit": "€k",
                "tolerance": 0.01,
                "explanation": f"{burn} × {months} = {funding} €k. Keep the units consistent.",
                "id": "financing-stages-v1-q1",
            },
            {
                "kind": "numeric",
                "prompt": f"What percentage do the founders retain after a {investor}% round? Start from {founders}% and apply proportional dilution.",
                "answer": retained,
                "unit": "%",
                "tolerance": 0.11,
                "explanation": f"{founders}% × (1 − {investor}%) = {retained:g}%. Do not subtract percentage points directly.",
                "id": "financing-stages-v1-q2",
            },
        ],
    }


def variant_seed(identifier: str) -> int | None:
    match = re.fullmatch(r"variant-vc(?:03|05)-(-?\d+)", identifier)
    return int(match.group(1)) if match else None


def generated_drill(topic_id: str | None, seed: int) -> FormulaDrill | None:
    """Create a new-number drill for the stages/dilution topics."""
    if topic_id not in {"VC03", "VC05"}:
        return None
    rng = random.Random(seed)
    burn = _money(rng, 30, 100)
    months = rng.choice((8, 10, 12, 14, 18))
    if topic_id == "VC03":
        answer = burn * months
        return FormulaDrill(
            id=f"variant-vc03-{seed}", topic_id="VC03",
            prompt=f"A startup burns €{burn}k per month and must reach its next milestone in {months} months. What funding need should it plan for (€k)?",
            variables={"monthly_burn_k": burn, "months": months}, answer=float(answer),
            answer_unit="k_eur", tolerance=0.01,
            steps=(
                {"label": "Funding need", "expression": f"{burn} × {months}", "result": f"{answer:g} k€"},
            ), difficulty=1, notice="Fresh-number variant: same method, new data.",
        )
    starting = rng.choice((70, 78, 82, 85, 90))
    dilution = rng.choice((12, 15, 18, 22, 25))
    answer = round(starting * (1 - dilution / 100), 2)
    return FormulaDrill(
        id=f"variant-vc05-{seed}", topic_id="VC05",
        prompt=f"Founders own {starting}% before a round. A new investor receives {dilution}% of post-money equity. What percentage do the founders retain?",
        variables={"starting_percent": starting, "new_investor_percent": dilution}, answer=answer,
        answer_unit="percent", tolerance=0.11,
        steps=(
            {"label": "Retained factor", "expression": f"1 − {dilution}%", "result": f"{100 - dilution}%"},
            {"label": "Founders after dilution", "expression": f"{starting}% × {100 - dilution}%", "result": f"{answer:g}%"},
        ), difficulty=1, notice="Fresh-number variant: same method, new data.",
    )
