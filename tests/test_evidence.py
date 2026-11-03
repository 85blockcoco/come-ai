"""SPEC-008 — Centre de preuves unifié.

Toutes les données sont synthétiques : aucune vraie entreprise, aucun vrai
candidat, aucune donnée personnelle, aucun appel réseau.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career.evidence import (
    EVIDENCE_TYPES,
    CONFIDENCE_LEVELS,
    EvidenceCenter,
    EvidenceItem,
    EvidenceUsage,
    evidence_from_candidate_fact,
    evidence_from_fit_verdict,
)
from career.evidence_store import InMemoryEvidenceStore, SqliteEvidenceStore
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


FIXTURES = Path(__file__).parent / "fixtures" / "evidence" / "synthetic_evidence.json"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("network is forbidden in synthetic evidence tests")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    for name in ("connect", "connect_ex", "sendto", "sendmsg"):
        if hasattr(socket.socket, name):
            monkeypatch.setattr(socket.socket, name, blocked)


@pytest.fixture
def center() -> EvidenceCenter:
    """A center backed by the volatile store: the rules are exercised alone."""
    return EvidenceCenter(InMemoryEvidenceStore())


@pytest.fixture
def frozen_center() -> EvidenceCenter:
    """A center with a deterministic clock."""
    moment = "2026-10-22T09:00:00+00:00"
    return EvidenceCenter(InMemoryEvidenceStore(), clock=lambda: moment)


def make_item(**overrides) -> EvidenceItem:
    payload = {
        "id": "",
        "claim": "Analyse financière et valorisation",
        "source_document": "stage_transaction_services.pdf",
        "source_location": "page 2, lignes 14-17",
        "quote": "Participation à l'analyse financière et à la valorisation des actifs.",
        "evidence_type": "skill",
        "confidence": "direct",
        "approved": False,
        "created_at": "",
        "updated_at": "",
        "tags": ["finance"],
    }
    payload.update(overrides)
    return EvidenceItem(**payload)


def synthetic_payload() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def evidence_client(service: CareerService) -> TestClient:
    """App minimale avec le même contrat d'erreur que l'application réelle."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


# --- 1. Modèle et validation -------------------------------------------------


def test_add_evidence_returns_a_stable_identifier(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    assert identifier.startswith("evidence_")
    assert center.get_evidence(identifier) is not None


def test_add_evidence_rejects_an_unknown_type(center: EvidenceCenter) -> None:
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(evidence_type="gossip"))


def test_add_evidence_rejects_an_unknown_confidence(center: EvidenceCenter) -> None:
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(confidence="certain"))


def test_add_evidence_requires_a_claim(center: EvidenceCenter) -> None:
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(claim="   "))


def test_add_evidence_requires_a_source_or_a_quote(center: EvidenceCenter) -> None:
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(source_document="", source_location="", quote=""))


def test_add_evidence_normalizes_and_bounds_the_tags(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item(tags=["Finance", "finance", " Excel ", "", "x" * 200]))
    item = center.get_evidence(identifier)
    assert item is not None
    assert item.tags == ["finance", "excel", "x" * 60]


def test_add_evidence_refuses_a_duplicated_identifier(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(id=identifier))


def test_get_evidence_returns_none_for_an_unknown_id(center: EvidenceCenter) -> None:
    assert center.get_evidence("evidence_unknown") is None
    assert center.get_evidence("") is None


def test_delete_evidence_reports_whether_it_existed(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    assert center.delete_evidence(identifier) is True
    assert center.delete_evidence(identifier) is False
    assert center.get_evidence(identifier) is None


def test_update_evidence_only_changes_the_allowed_fields(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    updated = center.update_evidence(identifier, {"claim": "Analyse financière", "tags": ["a"], "created_at": "1999-01-01"})
    assert updated.claim == "Analyse financière"
    assert updated.tags == ["a"]
    assert updated.created_at != "1999-01-01"


def test_update_evidence_refuses_an_invalid_type(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.update_evidence(identifier, {"evidence_type": "gossip"})


def test_evidence_item_round_trips_through_its_serialized_form() -> None:
    item = make_item(id="evidence_abc12345", tags=["finance"])
    item.usage.append(EvidenceUsage(target="cv", context="Dossier 1", at="2026-10-22T09:00:00+00:00"))
    restored = EvidenceItem.from_dict(item.to_dict())
    assert restored.id == item.id
    assert restored.usage[0].target == "cv"
    assert restored.tags == ["finance"]


# --- 2. Recherche et regroupement par affirmation ----------------------------


def test_search_evidence_ignores_accents_and_case(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(claim="Analyse financière et valorisation"))
    found = center.search_evidence("FINANCIERE")
    assert len(found) == 1


def test_search_evidence_looks_into_the_quote_and_the_source(center: EvidenceCenter) -> None:
    center.add_evidence(make_item())
    assert len(center.search_evidence("valorisation des actifs")) == 1
    assert len(center.search_evidence("transaction_services")) == 1


def test_search_evidence_filters_by_type(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(evidence_type="skill"))
    center.add_evidence(make_item(claim="Master en finance", evidence_type="education"))
    assert len(center.search_evidence("", "skill")) == 1
    assert len(center.search_evidence("", "education")) == 1


def test_search_evidence_returns_an_empty_list_when_nothing_matches(center: EvidenceCenter) -> None:
    center.add_evidence(make_item())
    assert center.search_evidence("nothing-matches-here") == []


def test_get_evidence_for_claim_groups_the_duplicates(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(claim="Analyse financière"))
    center.add_evidence(make_item(claim="analyse  Financiere", source_location="page 5"))
    assert len(center.get_evidence_for_claim("Analyse financière")) == 2


def test_get_evidence_for_claim_ignores_an_empty_claim(center: EvidenceCenter) -> None:
    assert center.get_evidence_for_claim("  ") == []


def test_claim_coverage_reports_an_unproven_claim_without_failing_it(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(claim="Excel avancé", approved=False))
    coverage = center.get_claim_coverage(["Excel avancé", "Power BI"])
    assert coverage[0]["proven"] is False
    assert coverage[0]["evidence_count"] == 1
    assert coverage[1]["proven"] is False
    assert coverage[1]["evidence_count"] == 0


# --- 3. Décision, blocage, expiration ---------------------------------------


def test_mark_approved_records_the_person_decision(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item())
    frozen_center.mark_approved(identifier, True)
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.approved is True
    assert item.updated_at == "2026-10-22T09:00:00+00:00"


def test_an_unapproved_evidence_is_never_a_proof(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item())
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.is_proven("2026-10-22T09:00:00+00:00") is False


def test_a_blocked_evidence_is_never_a_proof(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item(approved=True))
    frozen_center.set_blocked(identifier, True)
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.is_proven("2026-10-22T09:00:00+00:00") is False


def test_a_blocked_evidence_refuses_a_new_usage(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item())
    frozen_center.set_blocked(identifier, True)
    with pytest.raises(UserFacingError):
        frozen_center.record_usage(identifier, "cv", "Dossier 1")


def test_an_expired_evidence_is_counted_and_is_not_a_proof(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item(approved=True, expires_at="2026-10-01"))
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.is_expired("2026-10-22T09:00:00+00:00") is True
    assert item.is_proven("2026-10-22T09:00:00+00:00") is False


def test_a_date_only_expiry_covers_the_whole_day(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item(expires_at="2026-10-22"))
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.is_expired("2026-10-22T09:00:00+00:00") is False
    assert item.is_expired("2026-10-23T09:00:00+00:00") is True


def test_an_evidence_without_expiry_never_expires(frozen_center: EvidenceCenter) -> None:
    identifier = frozen_center.add_evidence(make_item())
    item = frozen_center.get_evidence(identifier)
    assert item is not None
    assert item.is_expired("2030-01-01T00:00:00+00:00") is False


# --- 4. Usage dans les CV et les lettres -------------------------------------


def test_record_usage_counts_the_cv_and_the_letters(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    center.record_usage(identifier, "cv", "Dossier 1")
    center.record_usage(identifier, "letter", "Dossier 1")
    item = center.get_evidence(identifier)
    assert item is not None
    assert item.used_in("cv") is True
    assert item.used_in("letter") is True
    assert len(item.usage) == 2


def test_record_usage_refuses_an_unknown_target(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.record_usage(identifier, "twitch")


# --- 5. Pièces jointes --------------------------------------------------------


def test_attach_document_copies_the_file_and_records_its_checksum(center: EvidenceCenter, tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    center = EvidenceCenter(InMemoryEvidenceStore(), attachments_dir=attachments)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    identifier = center.add_evidence(make_item())
    center.attach_document(identifier, str(source))
    item = center.get_evidence(identifier)
    assert item is not None
    assert len(item.attachments) == 1
    entry = item.attachments[0]
    assert entry["original_name"] == "source.pdf"
    assert entry["size_bytes"] == len(b"%PDF-1.4 synthetic")
    assert len(entry["sha256"]) == 64
    assert (attachments / entry["name"]).is_file()


def test_attach_document_never_persists_the_original_path(center: EvidenceCenter, tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    center = EvidenceCenter(InMemoryEvidenceStore(), attachments_dir=attachments)
    source = tmp_path / "secret-folder" / "source.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-1.4 synthetic")
    identifier = center.add_evidence(make_item())
    center.attach_document(identifier, str(source))
    payload = json.dumps(center.export_payload(), ensure_ascii=False)
    assert str(tmp_path) not in payload


def test_attach_document_refuses_a_missing_file(center: EvidenceCenter, tmp_path: Path) -> None:
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.attach_document(identifier, str(tmp_path / "absent.pdf"))


# --- 6. Fusion des doublons ---------------------------------------------------


def test_merge_keeps_one_id_and_merges_the_provenance(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item(claim="Analyse financière", source_location="page 2"))
    other = center.add_evidence(
        make_item(claim="Analyse financière", source_location="page 7", quote="Citation de la page 7.", tags=["excel"])
    )
    center.merge_evidence([keeper, other], keeper)
    assert center.get_evidence(other) is None
    item = center.get_evidence(keeper)
    assert item is not None
    assert item.additional_sources[0]["source_location"] == "page 7"
    assert "excel" in item.tags
    assert other in item.merged_from


def test_merge_keeps_the_snapshots_of_the_merged_proofs(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item(claim="Analyse financière"))
    other = center.add_evidence(make_item(claim="Analyse financière", quote="Citation de la page 7."))
    center.merge_evidence([keeper, other], keeper)
    merges = center.export_payload()["merges"]
    assert len(merges) == 1
    assert merges[0]["keep_id"] == keeper
    assert merges[0]["merged_ids"] == [other]
    assert merges[0]["snapshots"][0]["quote"] == "Citation de la page 7."


def test_merge_refuses_a_keep_id_outside_the_list(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item())
    other = center.add_evidence(make_item(claim="Autre preuve"))
    with pytest.raises(UserFacingError):
        center.merge_evidence([keeper, other], "evidence_unknown")


def test_merge_keeps_the_most_restrictive_expiry_and_the_block(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item(expires_at="2026-12-31"))
    other = center.add_evidence(make_item(claim="Analyse financière", expires_at="2026-06-30", blocked=True))
    center.merge_evidence([keeper, other], keeper)
    item = center.get_evidence(keeper)
    assert item is not None
    assert item.expires_at == "2026-06-30"
    assert item.blocked is True


def test_merge_keeps_an_approval_on_its_own_citation(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item(approved=False))
    other = center.add_evidence(make_item(claim="Analyse financière", approved=True))
    center.merge_evidence([keeper, other], keeper)
    item = center.get_evidence(keeper)
    assert item is not None
    # L'approbation ne change pas de citation : la citation du gardien
    # reste « non approuvée ».
    assert item.approved is False
    assert item.additional_sources[0]["approved"] is True
    # L'affirmation reste pourtant prouvée : une source approuvée la couvre.
    assert item.is_proven() is True


def test_merge_refuses_an_unknown_identifier(center: EvidenceCenter) -> None:
    keeper = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.merge_evidence([keeper, "evidence_unknown"], keeper)


# --- 7. Statistiques ----------------------------------------------------------


def test_usage_stats_count_the_evidence(center: EvidenceCenter) -> None:
    first = center.add_evidence(make_item(approved=True))
    center.add_evidence(make_item(claim="Master en finance", evidence_type="education", approved=False))
    center.record_usage(first, "cv")
    stats = center.get_usage_stats()
    assert stats.total_evidence == 2
    assert stats.approved == 1
    assert stats.unapproved == 1
    assert stats.used_in_cv == 1
    assert stats.used_in_letters == 0
    assert stats.by_type["skill"] == 1
    assert stats.by_type["education"] == 1
    assert stats.by_confidence["direct"] == 2


def test_usage_stats_separate_the_proven_claims(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(claim="Analyse financière", approved=True))
    center.add_evidence(make_item(claim="Excel", approved=False))
    stats = center.get_usage_stats()
    assert stats.claims == 2
    assert stats.proven_claims == 1
    assert stats.unproven_claims == 1


def test_stats_expose_every_documented_confidence_level(center: EvidenceCenter) -> None:
    stats = center.get_usage_stats()
    assert set(stats.by_confidence) == set(CONFIDENCE_LEVELS)
    assert set(stats.by_type) == set(EVIDENCE_TYPES)


# --- 8. Export portable --------------------------------------------------------


def test_export_payload_is_json_serializable(center: EvidenceCenter) -> None:
    center.add_evidence(make_item())
    payload = center.export_payload()
    assert json.loads(json.dumps(payload, ensure_ascii=False))["items"]
    assert payload["schema_version"] == 1


def test_export_markdown_shows_the_claim_and_its_source(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(approved=True))
    markdown = center.export_markdown()
    assert "Analyse financière et valorisation" in markdown
    assert "stage_transaction_services.pdf" in markdown


# --- 9. Persistance SQLite -----------------------------------------------------


def test_sqlite_store_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    store = SqliteEvidenceStore(path)
    item = make_item(id="evidence_abc12345")
    store.save(item)
    reopened = SqliteEvidenceStore(path)
    restored = reopened.get("evidence_abc12345")
    assert restored is not None
    assert restored.claim == item.claim
    assert restored.tags == ["finance"]


def test_sqlite_store_keeps_the_merge_history(tmp_path: Path) -> None:
    store = SqliteEvidenceStore(tmp_path / "evidence.sqlite3")
    store.record_merge("evidence_abc12345", ["evidence_def67890"], [{"claim": "Analyse financière"}])
    merges = store.merges()
    assert len(merges) == 1
    assert merges[0]["merged_ids"] == ["evidence_def67890"]


def test_service_keeps_the_evidence_between_two_runs(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    created = service.add_evidence(
        {
            "claim": "Analyse financière",
            "source_document": "stage.pdf",
            "source_location": "page 2",
            "quote": "Citation synthétique",
            "evidence_type": "skill",
            "confidence": "direct",
        }
    )
    reopened = CareerService(tmp_path)
    assert reopened.get_evidence(created["id"])["claim"] == "Analyse financière"


def test_service_keeps_the_evidence_directory_private(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    assert service.evidence_dir.is_dir()
    assert service.evidence_db_path.is_file()
    assert oct(service.evidence_dir.stat().st_mode)[-3:] == "700"
    assert oct(service.evidence_db_path.stat().st_mode)[-3:] == "600"


def test_reset_personal_data_removes_the_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    created = service.add_evidence(
        {
            "claim": "Analyse financière",
            "source_document": "stage.pdf",
            "quote": "Citation synthétique",
            "evidence_type": "skill",
            "confidence": "direct",
        }
    )
    source = tmp_path / "preuve.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    service.attach_evidence_document(created["id"], source, "preuve.pdf")
    assert list(service.evidence_attachments_dir.glob("*"))

    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    assert service.list_evidence() == []
    assert not list(service.evidence_attachments_dir.glob("*"))
    assert not list(service.evidence_uploads_dir.glob("*"))


def test_service_rejects_an_invalid_evidence_type(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with pytest.raises(UserFacingError):
        service.add_evidence(
            {
                "claim": "Analyse financière",
                "source_document": "stage.pdf",
                "quote": "Citation synthétique",
                "evidence_type": "gossip",
                "confidence": "direct",
            }
        )


# --- 10. API locale ------------------------------------------------------------


def test_api_creates_lists_and_returns_one_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    response = client.post(
        "/api/career/evidence",
        json={
            "claim": "Analyse financière",
            "source_document": "stage.pdf",
            "source_location": "page 2",
            "quote": "Citation synthétique",
            "evidence_type": "skill",
            "confidence": "direct",
        },
    )
    assert response.status_code == 201
    identifier = response.json()["id"]
    listing = client.get("/api/career/evidence")
    assert listing.status_code == 200
    assert len(listing.json()["evidence"]) == 1
    assert client.get(f"/api/career/evidence/{identifier}").status_code == 200


def test_api_refuses_an_evidence_without_claim(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    response = client.post("/api/career/evidence", json={"claim": "", "quote": "Citation"})
    assert response.status_code == 422


def test_api_returns_a_readable_error_for_an_unknown_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    response = client.get("/api/career/evidence/evidence_unknown")
    assert response.status_code == 400
    assert "preuve" in response.json()["detail"]


def test_api_approves_updates_and_deletes_an_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    created = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    identifier = created["id"]
    assert client.post(f"/api/career/evidence/{identifier}/approve", json={"approved": True}).json()["approved"] is True
    assert client.post(f"/api/career/evidence/{identifier}/block", json={"blocked": True}).json()["blocked"] is True
    patched = client.patch(f"/api/career/evidence/{identifier}", json={"tags": ["finance"]})
    assert patched.status_code == 200
    assert patched.json()["tags"] == ["finance"]
    assert client.delete(f"/api/career/evidence/{identifier}").json() == {"deleted": True}


def test_api_records_the_usage_of_an_evidence(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    created = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    identifier = created["id"]
    response = client.post(f"/api/career/evidence/{identifier}/usage", json={"target": "cv", "context": "Dossier 1"})
    assert response.status_code == 200
    assert response.json()["used_in_cv"] is True


def test_api_merges_two_duplicates(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    first = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q1", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    second = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q2", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    response = client.post(
        "/api/career/evidence/merge",
        json={"ids": [first["id"], second["id"]], "keep_id": first["id"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert len(client.get("/api/career/evidence").json()["evidence"]) == 1


def test_api_exposes_the_stats_and_the_export(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    )
    stats = client.get("/api/career/evidence/stats")
    assert stats.status_code == 200
    assert stats.json()["total_evidence"] == 1
    export = client.get("/api/career/evidence/export")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/json")
    markdown = client.get("/api/career/evidence/export?export_format=markdown")
    assert markdown.status_code == 200
    assert "Analyse financière" in markdown.text


def test_api_filters_the_listing(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    approved = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    client.post(
        "/api/career/evidence",
        json={"claim": "Master en finance", "source_document": "s.pdf", "quote": "q", "evidence_type": "education", "confidence": "declared"},
    )
    client.post(f"/api/career/evidence/{approved['id']}/approve", json={"approved": True})
    assert len(client.get("/api/career/evidence?approved=true").json()["evidence"]) == 1
    assert len(client.get("/api/career/evidence?evidence_type=education").json()["evidence"]) == 1
    assert len(client.get("/api/career/evidence?q=finance").json()["evidence"]) == 2
    assert client.get("/api/career/evidence?approved=peut-être").status_code == 422


def test_api_attaches_a_document(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    created = client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    ).json()
    response = client.post(
        f"/api/career/evidence/{created['id']}/attach",
        files={"file": ("preuve.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
    )
    assert response.status_code == 200
    attachments = response.json()["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["original_name"] == "preuve.pdf"
    assert (service.evidence_attachments_dir / attachments[0]["name"]).is_file()


def test_api_covers_the_profile_skills_in_the_stats(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Analyse financière, Excel"})
    client = evidence_client(service)
    client.post(
        "/api/career/evidence",
        json={"claim": "Analyse financière", "source_document": "s.pdf", "quote": "q", "evidence_type": "skill", "confidence": "direct"},
    )
    coverage = client.get("/api/career/evidence/stats").json()["profile_coverage"]
    assert coverage[0]["claim"] == "Analyse financière"
    assert coverage[0]["proven"] is False
    assert coverage[1]["claim"] == "Excel"
    assert coverage[1]["proven"] is False


# --- 11. Interface locale ------------------------------------------------------


def test_the_career_page_links_the_evidence_center() -> None:
    index = (Path(__file__).parent.parent / "career_static" / "index.html").read_text(encoding="utf-8")
    assert '<script src="/career-static/js/evidence-center.js" defer></script>' in index
    assert 'id="tab-evidence"' in index
    assert 'id="view-evidence"' in index


def test_the_evidence_view_offers_the_expected_actions() -> None:
    index = (Path(__file__).parent.parent / "career_static" / "index.html").read_text(encoding="utf-8")
    for marker in (
        "evidence-stat-proven",
        "evidence-stat-unproven",
        "evidence-stat-expired",
        "evidence-stat-used",
        "evidence-filter-type",
        "evidence-filter-confidence",
        "evidence-filter-approved",
        "evidence-create-form",
    ):
        assert marker in index


def test_the_evidence_script_exposes_its_loader() -> None:
    script = (Path(__file__).parent.parent / "career_static" / "js" / "evidence-center.js").read_text(encoding="utf-8")
    assert "window.loadEvidenceCenter" in script
    assert "/api/career/evidence" in script
    assert "réseau" in script.lower()


def test_the_career_view_registry_knows_the_evidence_view() -> None:
    script = (Path(__file__).parent.parent / "career_static" / "career.js").read_text(encoding="utf-8")
    assert '"evidence"' in script
    assert "loadEvidenceCenter" in script


# --- 12. Intégration SK-03 / SK-10 --------------------------------------------


def test_a_candidate_fact_becomes_an_approved_evidence() -> None:
    item = evidence_from_candidate_fact(
        {
            "id": "fact_1",
            "kind": "skill",
            "label": "Analyse financière",
            "value": "Modélisation sur Excel",
            "status": "approved",
            "evidence": {"source": "embedded_text", "filename": "cv.pdf", "page": 2, "quote": "Participation à l’analyse financière."},
        }
    )
    assert item is not None
    assert item.evidence_type == "skill"
    assert item.confidence == "direct"
    assert item.approved is True
    assert item.source_document == "cv.pdf"
    assert item.source_location == "page 2"
    assert item.quote == "Participation à l’analyse financière."


def test_a_proposed_fact_stays_unapproved() -> None:
    item = evidence_from_candidate_fact({"kind": "skill", "label": "Analyse financière", "status": "proposed"})
    assert item is not None
    assert item.approved is False
    assert item.confidence == "declared"


def test_a_fact_that_is_not_a_proof_is_skipped() -> None:
    assert evidence_from_candidate_fact({"kind": "contact", "label": "Email", "status": "approved"}) is None
    assert evidence_from_candidate_fact({"kind": "date", "label": "Naissance", "status": "approved"}) is None
    assert evidence_from_candidate_fact({}) is None


def test_a_supported_verdict_becomes_an_unapproved_evidence() -> None:
    item = evidence_from_fit_verdict(
        {
            "requirement_id": "req_1",
            "requirement_text": "Maîtrise d’Excel",
            "verdict": "supported",
            "profile_evidence": "Modélisation financière sur Excel",
            "confidence": 0.92,
        }
    )
    assert item is not None
    assert item.confidence == "direct"
    assert item.approved is False
    assert item.source_document == "requirements_fit"
    assert item.source_location == "req_1"


def test_an_unsupported_verdict_is_not_an_evidence() -> None:
    assert evidence_from_fit_verdict({"verdict": "unsupported", "profile_evidence": "rien"}) is None
    assert evidence_from_fit_verdict({"verdict": "supported"}) is None


def test_the_service_ingests_candidate_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    result = service.ingest_candidate_facts(
        [
            {"kind": "skill", "label": "Analyse financière", "status": "approved", "evidence": {"quote": "Citation"}},
            {"kind": "contact", "label": "Email", "status": "approved"},
        ]
    )
    assert len(result["added"]) == 1
    assert result["skipped"] == 1
    assert len(service.list_evidence()) == 1


def test_the_service_ingests_fit_verdicts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    result = service.ingest_fit_verdicts(
        [
            {"requirement_id": "req_1", "verdict": "supported", "profile_evidence": "Excel", "confidence": 0.6},
            {"requirement_id": "req_2", "verdict": "to_verify", "profile_evidence": "Excel"},
        ]
    )
    assert len(result["added"]) == 1
    assert result["skipped"] == 1
    assert service.list_evidence()[0]["confidence"] == "inferred"


# --- 13. Durcissement (revue adversariale) -------------------------------------


def test_deleting_a_proof_erases_its_attached_document(tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    center = EvidenceCenter(InMemoryEvidenceStore(), attachments_dir=attachments)
    source = tmp_path / "diplome.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    identifier = center.add_evidence(make_item())
    center.attach_document(identifier, str(source), "diplome.pdf")
    stored = list(attachments.glob("*"))
    assert len(stored) == 1
    assert center.delete_evidence(identifier) is True
    assert not list(attachments.glob("*"))


def test_an_attached_document_is_private(tmp_path: Path) -> None:
    attachments = tmp_path / "attachments"
    center = EvidenceCenter(InMemoryEvidenceStore(), attachments_dir=attachments)
    source = tmp_path / "diplome.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    identifier = center.add_evidence(make_item())
    center.attach_document(identifier, str(source), "diplome.pdf")
    stored = list(attachments.glob("*"))[0]
    assert oct(stored.stat().st_mode)[-3:] == "600"


def test_a_refused_update_leaves_the_stored_proof_untouched(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.update_evidence(identifier, {"evidence_type": "gossip"})
    item = center.get_evidence(identifier)
    assert item is not None
    assert item.evidence_type == "skill"
    assert item.claim == "Analyse financière et valorisation"


def test_an_invalid_expiry_is_refused(center: EvidenceCenter) -> None:
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(expires_at="2026-13-45"))
    with pytest.raises(UserFacingError):
        center.add_evidence(make_item(expires_at="demain"))
    identifier = center.add_evidence(make_item())
    with pytest.raises(UserFacingError):
        center.update_evidence(identifier, {"expires_at": "31/12/2026"})
    with pytest.raises(UserFacingError):
        center.set_expires_at(identifier, "hier")


def test_a_valid_expiry_is_accepted(center: EvidenceCenter) -> None:
    identifier = center.add_evidence(make_item(expires_at="2026-12-31"))
    item = center.get_evidence(identifier)
    assert item is not None
    assert item.expires_at == "2026-12-31"


def test_the_import_of_a_candidate_fact_is_idempotent(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    fact = {
        "id": "fact_1",
        "kind": "skill",
        "label": "Analyse financière",
        "status": "approved",
        "evidence": {"filename": "cv.pdf", "quote": "Citation synthétique"},
    }
    first = service.ingest_candidate_facts([fact])
    second = service.ingest_candidate_facts([fact])
    assert len(first["added"]) == 1
    assert second["added"] == []
    assert len(second["refreshed"]) == 1
    assert len(service.list_evidence()) == 1


def test_the_import_never_revokes_an_approval(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    fact = {
        "id": "fact_1",
        "kind": "skill",
        "label": "Analyse financière",
        "status": "approved",
        "evidence": {"filename": "cv.pdf", "quote": "Citation synthétique"},
    }
    service.ingest_candidate_facts([fact])
    identifier = service.list_evidence()[0]["id"]
    service.mark_evidence_approved(identifier, True)
    downgraded = {**fact, "status": "proposed"}
    service.ingest_candidate_facts([downgraded])
    assert service.get_evidence(identifier)["approved"] is True


def test_the_merge_history_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    store = SqliteEvidenceStore(path)
    center = EvidenceCenter(store)
    keeper = center.add_evidence(make_item(claim="Analyse financière"))
    other = center.add_evidence(make_item(claim="Analyse financière", quote="Citation de la page 7."))
    center.merge_evidence([keeper, other], keeper)
    reopened = EvidenceCenter(SqliteEvidenceStore(path))
    merges = reopened.export_payload()["merges"]
    assert len(merges) == 1
    assert merges[0]["snapshots"][0]["quote"] == "Citation de la page 7."


def test_a_damaged_evidence_database_does_not_break_the_career_space(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.add_evidence(
        {
            "claim": "Analyse financière",
            "source_document": "stage.pdf",
            "quote": "Citation synthétique",
            "evidence_type": "skill",
            "confidence": "direct",
        }
    )
    service.evidence_db_path.write_bytes(b"this is not a database")
    reopened = CareerService(tmp_path)
    assert reopened.list_evidence() == []
    assert list(reopened.evidence_dir.glob("*.corrupt-*"))


def test_the_evidence_database_uses_the_write_ahead_log(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    with sqlite3.connect(service.evidence_db_path) as connection:
        assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"


def test_the_expired_filter_only_keeps_the_expired_proofs(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    fresh = service.add_evidence(
        {
            "claim": "Analyse financière",
            "source_document": "s.pdf",
            "quote": "q",
            "evidence_type": "skill",
            "confidence": "direct",
            "expires_at": "2099-01-01",
        }
    )
    service.add_evidence(
        {
            "claim": "Master en finance",
            "source_document": "s.pdf",
            "quote": "q",
            "evidence_type": "education",
            "confidence": "direct",
            "expires_at": "2020-01-01",
        }
    )
    expired = service.list_evidence(expired=True)
    assert len(expired) == 1
    assert expired[0]["id"] != fresh["id"]
    assert len(service.list_evidence(expired=False)) == 1


def test_the_search_finds_a_word_by_its_prefix(center: EvidenceCenter) -> None:
    center.add_evidence(make_item(claim="Analyse financière"))
    assert len(center.search_evidence("financ")) == 1
    assert len(center.search_evidence("VALORI")) == 1


def test_the_export_of_markdown_is_served_as_markdown(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    client = evidence_client(service)
    response = client.get("/api/career/evidence/export?export_format=Markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")


def test_the_upload_body_is_capped_before_it_is_parsed(tmp_path: Path) -> None:
    from come_ai_web import create_app

    app = create_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    oversized = b"%PDF-1.4 synthetic" + b"0" * (10 * 1024 * 1024 + 1024)
    response = client.post(
        "/api/career/evidence/evidence_abc12345/attach",
        files={"file": ("gros.pdf", oversized, "application/pdf")},
    )
    # Le corps est refusé avant d'être analysé : 413 quand la taille est
    # annoncée dans l'en-tête, 400 quand elle est dépassée pendant l'envoi.
    assert response.status_code in {400, 413}


# --- 14. Jeu synthétique --------------------------------------------------------


@pytest.mark.parametrize("entry", synthetic_payload(), ids=lambda item: item["id"])
def test_every_synthetic_evidence_is_accepted_and_stays_citable(entry: dict) -> None:
    center = EvidenceCenter(InMemoryEvidenceStore())
    identifier = center.add_evidence(
        make_item(
            claim=entry["claim"],
            source_document=entry["source_document"],
            source_location=entry["source_location"],
            quote=entry["quote"],
            evidence_type=entry["evidence_type"],
            confidence=entry["confidence"],
        )
    )
    item = center.get_evidence(identifier)
    assert item is not None
    assert item.quote == entry["quote"]
    assert item.source_document == entry["source_document"]
    assert item.created_at


def test_the_synthetic_fixture_only_contains_documented_types() -> None:
    for entry in synthetic_payload():
        assert entry["evidence_type"] in EVIDENCE_TYPES
        assert entry["confidence"] in CONFIDENCE_LEVELS
