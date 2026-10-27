"""Conformité, dérive et rapport de la Constitution exécutable.

SPEC-014.  Ce module observe le stockage sans jamais le modifier : il
répond à trois questions.

1. *La Constitution est-elle conforme ?* — signatures vérifiées, règles
   approuvées, expressions valides, jeux de règles cohérents.
2. *La Constitution dérive-t-elle ?* — modifications non relues, couverture
   de tests, violations critiques, règles jamais revues depuis un an.
3. *Que doit-on montrer à une revue ?* — un rapport lisible, déterministe,
   utilisable aussi bien dans un rapport Markdown que dans l'interface web.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .constitution import Rule, validate_rule_payload


#: Seuils d'alerte (issus du contrat SPEC-014).
UNREVIEWED_MODIFICATION_RATE_THRESHOLD = 0.05
TEST_COVERAGE_THRESHOLD = 0.90
CRITICAL_VIOLATIONS_THRESHOLD = 0
STALE_REVIEW_DAYS = 365


def _now(now: datetime | None = None) -> datetime:
    if now is not None:
        return now
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_since(value: Any, reference: datetime) -> float | None:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return (reference - parsed).total_seconds() / 86400.0


def audit_store(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Audit de conformité du stockage : intégrité, gouvernance, couverture."""
    reference = _now(now)
    rules = store.list_rules()
    rulesets = store.list_rulesets()
    by_status: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    invalid_expressions: list[str] = []
    unsigned: list[str] = []
    active_without_approval: list[str] = []
    tested = 0
    for payload in rules:
        status = str(payload.get("status", ""))
        domain = str(payload.get("domain", ""))
        by_status[status] = by_status.get(status, 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1
        rule = Rule.from_dict(payload)
        for problem in validate_rule_payload(rule.to_dict()):
            invalid_expressions.append(f"{rule.rule_id} : {problem}")
        if not store.verify_rule(payload):
            unsigned.append(rule.rule_id)
        if status == "active" and not payload.get("approved_by"):
            active_without_approval.append(rule.rule_id)
        if payload.get("has_test"):
            tested += 1
    active_rules = [payload for payload in rules if payload.get("status") == "active"]
    coverage = (tested / len(active_rules)) if active_rules else 1.0
    return {
        "checked_at": reference.isoformat(timespec="microseconds"),
        "rules": {
            "total": len(rules),
            "by_status": by_status,
            "by_domain": by_domain,
            "active": len(active_rules),
            "draft": by_status.get("draft", 0),
            "deprecated": by_status.get("deprecated", 0),
            "archived": by_status.get("archived", 0),
            "tested": tested,
            "test_coverage": round(coverage, 4),
        },
        "rulesets": {
            "total": len(rulesets),
            "ids": [ruleset.get("ruleset_id") for ruleset in rulesets],
        },
        "integrity": {
            "unsigned_rules": unsigned,
            "invalid_rules": invalid_expressions,
            "active_without_approval": active_without_approval,
            "signature_algorithm": "hmac-sha256",
        },
        "audit_trail": {
            "entries": len(store.list_audit(limit=1_000)),
            "recent": store.list_audit(limit=10),
        },
    }


def detect_drift(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Détecte la dérive de la Constitution et déclenche les alertes prévues."""
    reference = _now(now)
    rules = store.list_rules()
    total = len(rules)
    modified_without_review: list[str] = []
    stale_rules: list[str] = []
    for payload in rules:
        rule_id = str(payload.get("rule_id", ""))
        history = store.list_rule_versions(rule_id)
        approved_versions = [item for item in history if item.get("approved_by")]
        if payload.get("status") == "draft" and approved_versions:
            modified_without_review.append(rule_id)
        reference_date = payload.get("approved_at") or payload.get("updated_at") or payload.get("created_at")
        age = _days_since(reference_date, reference)
        if age is not None and age > STALE_REVIEW_DAYS:
            stale_rules.append(f"{rule_id} ({int(age)} jours)")
    unreviewed_rate = (len(modified_without_review) / total) if total else 0.0
    active_rules = [payload for payload in rules if payload.get("status") == "active"]
    tested = sum(1 for payload in active_rules if payload.get("has_test"))
    coverage = (tested / len(active_rules)) if active_rules else 1.0
    history = store.conformance_history(limit=500)
    critical_violations = 0
    for entry in history:
        for violation in entry.get("violations", []) or []:
            if str(violation.get("severity")) == "critical":
                critical_violations += 1
    alerts: list[dict[str, Any]] = []

    def add_alert(metric: str, value: float, threshold: float, breached: bool, message: str) -> None:
        alerts.append(
            {
                "metric": metric,
                "value": round(float(value), 4),
                "threshold": round(float(threshold), 4),
                "status": "alert" if breached else "ok",
                "message": message,
            }
        )

    add_alert(
        "unreviewed_modification_rate",
        unreviewed_rate,
        UNREVIEWED_MODIFICATION_RATE_THRESHOLD,
        unreviewed_rate > UNREVIEWED_MODIFICATION_RATE_THRESHOLD,
        f"{len(modified_without_review)} règle(s) modifiée(s) sans relecture sur {total}.",
    )
    add_alert(
        "test_coverage",
        coverage,
        TEST_COVERAGE_THRESHOLD,
        bool(active_rules) and coverage < TEST_COVERAGE_THRESHOLD,
        f"{tested}/{len(active_rules)} règle(s) active(s) couverte(s) par un test.",
    )
    add_alert(
        "critical_violations",
        critical_violations,
        CRITICAL_VIOLATIONS_THRESHOLD,
        critical_violations > CRITICAL_VIOLATIONS_THRESHOLD,
        f"{critical_violations} violation(s) critique(s) enregistrée(s) sur les entités contrôlées.",
    )
    add_alert(
        "stale_review",
        len(stale_rules),
        0,
        bool(stale_rules),
        f"{len(stale_rules)} règle(s) non revue(s) depuis plus de {STALE_REVIEW_DAYS} jours.",
    )
    unsigned = [rule.get("rule_id") for rule in rules if not store.verify_rule(rule)]
    add_alert(
        "signature_integrity",
        len(unsigned),
        0,
        bool(unsigned),
        f"{len(unsigned)} règle(s) dont la signature ne correspond plus au contenu.",
    )
    return {
        "checked_at": reference.isoformat(timespec="microseconds"),
        "metrics": {
            "unreviewed_modification_rate": round(unreviewed_rate, 4),
            "unreviewed_rules": modified_without_review,
            "test_coverage": round(coverage, 4),
            "tested_rules": tested,
            "active_rules": len(active_rules),
            "critical_violations": critical_violations,
            "stale_reviews": stale_rules,
            "unsigned_rules": unsigned,
        },
        "alerts": alerts,
        "drifting": any(alert["status"] == "alert" for alert in alerts),
    }


def build_audit_report(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Rapport complet : conformité + dérive + dernières entités contrôlées."""
    reference = _now(now)
    conformity = audit_store(store, now=reference)
    drift = detect_drift(store, now=reference)
    history = store.conformance_history(limit=20)
    scores = [float(entry.get("compliance_score", 0.0)) for entry in reversed(history)]
    return {
        "generated_at": reference.isoformat(timespec="microseconds"),
        "conformity": conformity,
        "drift": drift,
        "entities": {
            "checked": len(history),
            "latest_score": round(scores[-1], 4) if scores else None,
            "average_score": round(sum(scores) / len(scores), 4) if scores else None,
            "history": history,
        },
        "alerts": drift["alerts"],
    }


def render_report_markdown(report: Mapping[str, Any]) -> str:
    """Rend un rapport d'audit lisible en Markdown."""
    conformity = report.get("conformity", {}) or {}
    drift = report.get("drift", {}) or {}
    rules = conformity.get("rules", {}) or {}
    metrics = drift.get("metrics", {}) or {}
    alerts = drift.get("alerts", []) or []
    entities = report.get("entities", {}) or {}
    lines: list[str] = [
        "# Rapport de conformité — Constitution exécutable",
        "",
        f"Généré le {report.get('generated_at', '')}.",
        "",
        "## Règles",
        "",
        f"- Total : {rules.get('total', 0)} (dont {rules.get('active', 0)} actives)",
        f"- Brouillons en attente d'approbation : {rules.get('draft', 0)}",
        f"- Dépréciées : {rules.get('deprecated', 0)} — archivées : {rules.get('archived', 0)}",
        f"- Couverture de tests : {rules.get('test_coverage', 0.0) * 100:.1f} %",
        "",
        "## Dérive",
        "",
        f"- Modifications sans relecture : {metrics.get('unreviewed_modification_rate', 0.0) * 100:.1f} %",
        f"- Violations critiques enregistrées : {metrics.get('critical_violations', 0)}",
        f"- Règles non revues depuis plus d'un an : {len(metrics.get('stale_reviews', []) or [])}",
        "",
        "## Alertes",
        "",
    ]
    if alerts:
        lines.append("| Métrique | Valeur | Seuil | État |")
        lines.append("| --- | --- | --- | --- |")
        for alert in alerts:
            lines.append(
                f"| {alert.get('metric')} | {alert.get('value')} | {alert.get('threshold')} | {alert.get('status')} |"
            )
    else:
        lines.append("Aucune alerte.")
    lines.extend(
        [
            "",
            "## Entités contrôlées",
            "",
            f"- Entités suivies : {entities.get('checked', 0)}",
            f"- Dernier score : {entities.get('latest_score')}",
            f"- Score moyen : {entities.get('average_score')}",
            "",
        ]
    )
    return "\n".join(lines)


def build_entity_report(store: Any, entity_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Rapport de conformité d'une entité, à partir de l'historique stocké."""
    reference = _now(now)
    history = store.conformance_history(entity_id, limit=20)
    scores = [float(entry.get("compliance_score", 0.0)) for entry in reversed(history)]
    latest = history[0] if history else None
    return {
        "entity_id": entity_id,
        "generated_at": reference.isoformat(timespec="microseconds"),
        "checked": bool(history),
        "latest": latest,
        "trend": {
            "scores": [round(score, 4) for score in scores],
            "delta": round(scores[-1] - scores[-2], 4) if len(scores) >= 2 else 0.0,
            "direction": (
                "stable"
                if len(scores) < 2 or abs(scores[-1] - scores[-2]) < 0.005
                else ("up" if scores[-1] > scores[-2] else "down")
            ),
        },
        "history": history,
    }
