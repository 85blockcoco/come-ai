"""SPEC-035 — Journal d'audit des décisions : unitaires, adversarial et smoke REST."""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from career.audit_journal import (
    AuditEntry,
    AuditEntryNotFoundError,
    AuditJournal,
    AuditJournalError,
)
from career.service import CareerService
from come_ai_web import create_app


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "audit_synthetic.json"
GENESIS = "0" * 64


def _fixture_entries(count: int | None = None) -> list[AuditEntry]:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    entries = [AuditEntry(**item) for item in raw["entries"]]
    return entries if count is None else entries[:count]


def _seed(journal: AuditJournal, count: int | None = None) -> list[AuditEntry]:
    entries = _fixture_entries(count)
    for entry in entries:
        journal.record(entry)
    return entries


# ---------------------------------------------------------------- contrat


def test_audit_entry_contract_fields_are_stable() -> None:
    names = [field.name for field in dataclass_fields(AuditEntry)]
    assert names == ["decision_id", "decision_type", "context", "outcome", "at"]


def test_fixture_contains_only_synthetic_entries() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert len(raw["entries"]) >= 6
    for item in raw["entries"]:
        assert set(item) == {"decision_id", "decision_type", "context", "outcome", "at"}
        assert item["decision_id"].startswith("dec-syn-")


# ------------------------------------------------------------- enregistrement


def test_record_hash_chains_entries_from_genesis(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    previous = GENESIS
    for entry in _fixture_entries():
        record = journal.record(entry)
        assert record.prev_hash == previous
        assert len(record.entry_hash) == 64
        previous = record.entry_hash
    assert journal.path.exists()


def test_record_rejects_duplicate_decision_id(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    entry = _fixture_entries(1)[0]
    journal.record(entry)
    with pytest.raises(AuditJournalError, match="déjà enregistrée"):
        journal.record(entry)


@pytest.mark.parametrize(
    "mutation",
    [
        {"decision_id": ""},
        {"decision_id": "   "},
        {"decision_type": ""},
    ],
)
def test_record_rejects_empty_mandatory_fields(tmp_path: Path, mutation: dict) -> None:
    journal = AuditJournal(tmp_path)
    base = {
        "decision_id": "dec-x",
        "decision_type": "offer_ranked",
        "context": {},
        "outcome": {},
        "at": "2026-10-20T09:00:00+00:00",
    }
    base.update(mutation)
    entry = AuditEntry(**base)
    with pytest.raises(AuditJournalError):
        journal.record(entry)


def test_record_rejects_non_dict_context_and_unserializable_payload(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    with pytest.raises(AuditJournalError, match="objet JSON"):
        journal.record(AuditEntry("dec-1", "offer_ranked", ["pas un dict"], {}, "2026-10-20T09:00:00+00:00"))
    with pytest.raises(AuditJournalError, match="sérialisable"):
        journal.record(AuditEntry("dec-2", "offer_ranked", {"bad": {1, 2}}, {}, "2026-10-20T09:00:00+00:00"))


def test_record_fills_missing_timestamp(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    record = journal.record(AuditEntry("dec-now", "arena_verdict", {"arena_run_id": "run-1"}, {"winner": "cv_a"}, ""))
    assert record.entry.at  # horodatage local posé par le journal


# ------------------------------------------------------------------ recherche


def test_search_filters_by_decision_type_and_free_text(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    ranked = journal.search(decision_type="offer_ranked")
    assert ranked["total"] == 3
    assert all(item["entry"]["decision_type"] == "offer_ranked" for item in ranked["entries"])
    assert journal.search(query="Delta")["total"] == 1
    assert journal.search(query="delta")["total"] == 1  # insensible à la casse
    assert journal.search(query="aucune-correspondance-xyz")["total"] == 0


def test_search_returns_newest_first_with_pagination(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    entries = _seed(journal)
    result = journal.search(limit=2)
    assert [item["entry"]["decision_id"] for item in result["entries"]] == [
        entries[-1].decision_id,
        entries[-2].decision_id,
    ]
    page_two = journal.search(limit=2, offset=2)
    assert page_two["entries"][0]["entry"]["decision_id"] == entries[-3].decision_id
    assert result["total"] == page_two["total"] == len(entries)


# ---------------------------------------------------------------- explication


def test_explain_builds_french_narrative_with_sorted_factors(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    explanation = journal.explain("dec-syn-001")
    assert explanation.entry.decision_type == "offer_ranked"
    assert "Décision « offer_ranked »" in explanation.narrative
    assert "Société Fictive Alpha" in explanation.narrative
    weights = [weight for _, weight in explanation.contributing_factors]
    assert weights == sorted(weights, reverse=True)
    assert explanation.contributing_factors[0][0] == "localisation"
    assert any(name == "score" for name, _ in explanation.contributing_factors)
    # Déterministe : deux appels donnent la même explication.
    assert journal.explain("dec-syn-001").narrative == explanation.narrative


def test_explain_uses_textual_reasons_as_full_weight_factors(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    explanation = journal.explain("dec-syn-003")
    names = [name for name, _ in explanation.contributing_factors]
    assert "aucune réponse après 10 jours" in names
    weights = [weight for _, weight in explanation.contributing_factors]
    assert all(weight == 1.0 for weight in weights)


def test_explain_unknown_decision_id_raises(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal, count=2)
    with pytest.raises(AuditEntryNotFoundError):
        journal.explain("dec-inconnu")


# ---------------------------------------------------------------- persistance


def test_journal_survives_a_new_instance(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal, count=3)
    reopened = AuditJournal(tmp_path)
    assert reopened.search()["total"] == 3
    assert reopened.explain("dec-syn-002").entry.decision_id == "dec-syn-002"


# ---------------------------------------------------------- integrité (adv.)


def test_verify_integrity_accepts_untouched_journal(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    report = journal.verify_integrity()
    assert report["valid"] is True
    assert report["entries"] == 8
    assert report["first_broken_sequence"] is None


def test_verify_integrity_detects_outcome_tampering(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["outcome"]["score"] = 99  # modification discrète d'un score
    lines[1] = json.dumps(tampered, ensure_ascii=False)
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = AuditJournal(tmp_path).verify_integrity()
    assert report["valid"] is False
    assert report["first_broken_sequence"] == 2
    assert "hash d'entrée invalide" in report["reason"]


def test_verify_integrity_detects_forged_appended_entry(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal, count=2)
    forged = json.loads(journal.path.read_text(encoding="utf-8").splitlines()[0])
    forged["sequence"] = 3
    forged["decision_id"] = "dec-forge"
    forged["entry_hash"] = "f" * 64  # hash inventé, non recalculé
    with journal.path.open("a", encoding="utf-8") as destination:
        destination.write(json.dumps(forged, ensure_ascii=False) + "\n")
    report = AuditJournal(tmp_path).verify_integrity()
    assert report["valid"] is False
    assert report["first_broken_sequence"] == 3


def test_verify_integrity_detects_corrupted_line(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal, count=2)
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{corrupted"
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = AuditJournal(tmp_path).verify_integrity()
    assert report["valid"] is False
    assert "illisible" in report["reason"]


def test_verify_integrity_detects_removed_middle_line(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal, count=3)
    lines = journal.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    journal.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = AuditJournal(tmp_path).verify_integrity()
    assert report["valid"] is False
    assert report["first_broken_sequence"] == 3


def test_stats_summarizes_counts_and_integrity(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path)
    _seed(journal)
    stats = journal.stats()
    assert stats["entries"] == 8
    assert stats["by_decision_type"] == {
        "arena_verdict": 1,
        "cv_variant_selected": 1,
        "followup_scheduled": 2,
        "letter_reviewed": 1,
        "offer_ranked": 3,
    }
    assert stats["integrity"] == {"valid": True}


# ------------------------------------------------------------------ smoke REST


def test_audit_journal_rest_is_read_only(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    journal = AuditJournal(service.data_dir / "audit")  # même emplacement que le routeur
    _seed(journal)
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        listing = client.get("/api/career/audit-journal")
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] == 8
        assert len(body["entries"]) == 8
        assert body["stats"]["integrity"] == {"valid": True}

        filtered = client.get("/api/career/audit-journal", params={"decision_type": "followup_scheduled"})
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 2

        paged = client.get("/api/career/audit-journal", params={"limit": 2, "offset": 0})
        assert paged.status_code == 200
        assert len(paged.json()["entries"]) == 2

        explanation = client.get("/api/career/audit-journal/dec-syn-001/explanation")
        assert explanation.status_code == 200
        payload = explanation.json()["explanation"]
        assert payload["entry"]["decision_id"] == "dec-syn-001"
        assert "Décision « offer_ranked »" in payload["narrative"]
        assert payload["contributing_factors"][0] == ["localisation", 0.9]

        missing = client.get("/api/career/audit-journal/dec-inconnu/explanation")
        assert missing.status_code == 404

        integrity = client.get("/api/career/audit-journal/integrity")
        assert integrity.status_code == 200
        assert integrity.json()["valid"] is True


def test_audit_journal_rest_has_no_write_endpoint(tmp_path: Path) -> None:
    service = CareerService(tmp_path, curated_sources=())
    app = create_app(base_dir=tmp_path, career_override=service)
    with TestClient(app) as client:
        for method, path in (
            ("post", "/api/career/audit-journal"),
            ("put", "/api/career/audit-journal"),
            ("patch", "/api/career/audit-journal"),
            ("post", "/api/career/audit-journal/dec-syn-001/explanation"),
        ):
            response = getattr(client, method)(path, json={})
            assert response.status_code == 405, f"{method.upper()} {path} doit rester interdit"
        # Le journal étant append-only, aucune suppression n'existe non plus.
        assert client.delete("/api/career/audit-journal").status_code == 405
