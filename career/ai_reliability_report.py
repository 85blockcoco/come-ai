"""AI reliability report (N100-I10)."""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ProviderStat:
    provider: str
    calls: int = 0
    failures: int = 0
    avg_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        return round(100.0 * (self.calls - self.failures) / self.calls, 1) if self.calls else 0.0


@dataclass
class AIReliabilityReport:
    generated_at: str = ""
    providers: list[dict[str, Any]] = field(default_factory=list)
    total_calls: int = 0
    total_failures: int = 0
    global_success_rate: float = 0.0
    degraded_inputs: int = 0  # fois où les guardrails ont tronqué/nettoyé
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    recommendations: list[str] = field(default_factory=list)


def build_reliability_report(
    stats: Iterable[Any],
    *,
    degraded_inputs: int = 0,
    cache_hits: int = 0,
    cache_misses: int = 0,
    at: str = "",
) -> AIReliabilityReport:

    providers: list[ProviderStat] = []
    for s in stats:
        if isinstance(s, dict):
            providers.append(ProviderStat(**s))
        else:
            providers.append(s)
    total_calls = sum(p.calls for p in providers)
    total_failures = sum(p.failures for p in providers)
    rate = round(100.0 * (total_calls - total_failures) / total_calls, 1) if total_calls else 0.0
    hits, misses = cache_hits, cache_misses
    hit_rate = round(100.0 * hits / (hits + misses), 1) if (hits + misses) else 0.0
    recs: list[str] = []
    for p in providers:
        if p.calls and p.success_rate < 80.0:
            recs.append(f"{p.provider}: taux {p.success_rate}% < 80% — réduire priorité ou activer circuit breaker")
    if hit_rate < 30.0 and misses:
        recs.append("cache IA sous-utilisé (<30% hits) — vérifier clé de hash et TTL")
    if degraded_inputs:
        recs.append(f"{degraded_inputs} sorties nettoyées par guardrails — vérifier les prompts")
    if not recs:
        recs.append("Aucune anomalie détectée")
    providers_out = [
        {
            "provider": p.provider,
            "calls": p.calls,
            "failures": p.failures,
            "avg_latency_ms": p.avg_latency_ms,
            "success_rate": p.success_rate,
        }
        for p in providers
    ]
    return AIReliabilityReport(
        generated_at=at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        providers=providers_out,
        total_calls=total_calls,
        total_failures=total_failures,
        global_success_rate=rate,
        degraded_inputs=degraded_inputs,
        cache_hits=hits,
        cache_misses=misses,
        cache_hit_rate=hit_rate,
        recommendations=recs,
    )


def write_reliability_report(report: AIReliabilityReport, target: str | Path) -> Path:
    import json

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def to_dict(r: AIReliabilityReport) -> dict[str, Any]:
    return asdict(r)
