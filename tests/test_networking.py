"""Offline coverage for the local networking directory (SPEC-040 / CVBOOST-75)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from career.networking import (
    DRAFT_KINDS,
    MissingFactError,
    detect_desk_families,
    draft_message,
    export_drafts,
    format_linkedin_date,
    import_linkedin_export,
    is_recruiter,
    parse_linkedin_connections_csv,
    parse_linkedin_profile_csv,
    recommend_targets,
)
from career.networking_schema import (
    RELATION_FIRST,
    RELATION_SECOND,
    SOURCE_LINKEDIN_EXPORT,
    NetworkingStore,
)

CONNECTIONS_CSV = (
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Marie,Dupont,https://linkedin.test/in/marie,marie@example.test,Banque Exemple,M&A Analyst,2024-01-12\n"
    "Karim,Benali,,,Conseil Exemple,Talent Acquisition Partner,12 mars 2023\n"
    "\n"
    ",,,,\n"
    "Sophie,Martin,https://linkedin.test/in/sophie,sophie@example.test,\"Banque Exemple, division TMT\",Coverage Banker,12 Jan 2024\n"
)

PROFILE_CSV = (
    "First Name,Last Name,Headline,Schools,Positions,Favorite Color\n"
    "Côme,Delavenne,Étudiant finance cible corporate,HEC Paris;ESSEC,Stage M&A Analyst;Assistant coverage,bleu\n"
)


@pytest.fixture()
def store(tmp_path: Path) -> NetworkingStore:
    return NetworkingStore(tmp_path / "networking.sqlite3")


def _import(store: NetworkingStore):
    return import_linkedin_export(store, profile_csv=PROFILE_CSV, connections_csv=CONNECTIONS_CSV)


# --------------------------------------------------------------------- CSV parsing
def test_connections_csv_parses_names_company_position() -> None:
    rows = parse_linkedin_connections_csv(CONNECTIONS_CSV)
    assert [row["full_name"] for row in rows] == ["Marie Dupont", "Karim Benali", "Sophie Martin"]
    assert rows[0]["company"] == "Banque Exemple"
    assert rows[0]["headline"] == "M&A Analyst"


def test_connections_csv_skips_rows_without_name() -> None:
    rows = parse_linkedin_connections_csv(CONNECTIONS_CSV)
    assert len(rows) == 3


def test_connections_csv_handles_quoted_company_with_comma() -> None:
    rows = parse_linkedin_connections_csv(CONNECTIONS_CSV)
    assert rows[2]["company"] == "Banque Exemple, division TMT"


def test_connections_csv_handles_bom_and_missing_optional_columns() -> None:
    rows = parse_linkedin_connections_csv("﻿First Name,Last Name\nAna,Exemple")
    assert rows == [
        {
            "full_name": "Ana Exemple",
            "profile_url": "",
            "email": "",
            "company": "",
            "headline": "",
            "connected_on": "",
            "last_contact_at": "",
        }
    ]


def test_connections_csv_empty_content() -> None:
    assert parse_linkedin_connections_csv("") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024-01-12", "2024-01-12"),
        ("12 Jan 2024", "2024-01-12"),
        ("12 mars 2023", "2023-03-12"),
        ("02/05/2023", "2023-05-02"),
        ("date inconnue", ""),
        ("", ""),
    ],
)
def test_format_linkedin_date_supports_locale_formats(raw: str, expected: str) -> None:
    assert format_linkedin_date(raw) == expected


def test_profile_csv_extracts_schools_roles_and_headline() -> None:
    facts = parse_linkedin_profile_csv(PROFILE_CSV)
    by_kind = {kind: [fact["value"] for fact in facts if fact["kind"] == kind] for kind in ("school", "role", "headline")}
    assert by_kind["school"] == ["HEC Paris", "ESSEC"]
    assert by_kind["role"] == ["Stage M&A Analyst", "Assistant coverage"]
    assert by_kind["headline"] == ["Étudiant finance cible corporate"]


def test_profile_csv_with_unknown_columns_yields_no_facts() -> None:
    assert parse_linkedin_profile_csv("A,B\n1,2") == []


def test_profile_csv_empty_content() -> None:
    assert parse_linkedin_profile_csv("") == []


# ------------------------------------------------------------------------- import
def test_import_summary_reports_counts_and_source(store: NetworkingStore) -> None:
    summary = _import(store)
    assert summary.connections_imported == 3
    assert summary.profile_facts == 5
    assert summary.source == SOURCE_LINKEDIN_EXPORT
    assert summary.files == ("Connections.csv", "Profile.csv")


def test_imported_contacts_are_tagged_linkedin_export_and_first_degree(store: NetworkingStore) -> None:
    _import(store)
    contacts = store.list_contacts()
    assert len(contacts) == 3
    assert all(contact.source == SOURCE_LINKEDIN_EXPORT for contact in contacts)
    assert all(contact.relation == RELATION_FIRST for contact in contacts)


def test_profile_facts_are_tagged_linkedin_export(store: NetworkingStore) -> None:
    _import(store)
    facts = store.list_profile_facts()
    assert len(facts) == 5
    assert all(fact.source == SOURCE_LINKEDIN_EXPORT for fact in facts)
    assert all(fact.origin == "Profile.csv" for fact in facts)


def test_imported_contact_provenance_cites_connections_csv(store: NetworkingStore) -> None:
    _import(store)
    contact = store.list_contacts()[0]
    assert any(item["where"] == "Connections.csv" and item["source"] == SOURCE_LINKEDIN_EXPORT for item in contact.provenance)


def test_reimport_does_not_duplicate_contacts(store: NetworkingStore) -> None:
    _import(store)
    summary = import_linkedin_export(store, connections_csv=CONNECTIONS_CSV)
    assert summary.connections_imported == 0
    assert summary.contacts_updated == 3
    assert len(store.list_contacts()) == 3


def test_reimport_preserves_user_notes_and_actions(store: NetworkingStore) -> None:
    _import(store)
    contact = store.list_contacts()[0]
    store.update_contact_fields(
        contact.id, notes="Déjà échangé au forum", next_action="Relancer après le 15", last_contact_at="2026-10-01"
    )
    import_linkedin_export(store, connections_csv=CONNECTIONS_CSV)
    refreshed = store.get_contact(contact.id)
    assert refreshed is not None
    assert refreshed.notes == "Déjà échangé au forum"
    assert refreshed.next_action == "Relancer après le 15"
    assert refreshed.last_contact_at == "2026-10-01"


def test_import_records_audit_rows(store: NetworkingStore) -> None:
    _import(store)
    records = store.list_imports()
    assert [(record.kind, record.rows_imported) for record in records] == [("connections", 3), ("profile", 5)]
    assert all(record.source == SOURCE_LINKEDIN_EXPORT for record in records)


def test_duplicate_rows_within_one_import_are_deduplicated(store: NetworkingStore) -> None:
    csv_content = (
        "First Name,Last Name,Company,Position\n"
        "Lea,Bernard,Banque Exemple,Analyst\n"
        "Lea,Bernard,Banque Exemple,Analyst\n"
    )
    summary = import_linkedin_export(store, connections_csv=csv_content)
    assert summary.connections_imported == 1
    assert summary.contacts_updated == 1
    assert len(store.list_contacts()) == 1


# -------------------------------------------------------------------------- store
def test_manual_contact_defaults_and_relation_normalization(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Paul Exemple", relation="1er")
    store.upsert_contact(full_name="Léa Exemple", relation="2nd")
    by_name = {contact.full_name: contact for contact in store.list_contacts()}
    assert by_name["Paul Exemple"].relation == RELATION_FIRST
    assert by_name["Léa Exemple"].relation == RELATION_SECOND
    assert by_name["Paul Exemple"].source == "manual"


def test_upsert_contact_requires_a_name(store: NetworkingStore) -> None:
    with pytest.raises(ValueError):
        store.upsert_contact(full_name="   ")


def test_update_contact_fields_edits_user_fields(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Paul Exemple", headline="Analyst")
    contact = store.list_contacts()[0]
    updated = store.update_contact_fields(contact.id, notes="Priorité", next_action="Appeler", relation="alumni")
    assert updated.notes == "Priorité"
    assert updated.next_action == "Appeler"
    assert updated.relation == "alumni"


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "networking.sqlite3"
    NetworkingStore(db_path).upsert_contact(full_name="Paul Exemple", company="Banque Exemple")
    reopened = NetworkingStore(db_path)
    assert [contact.full_name for contact in reopened.list_contacts()] == ["Paul Exemple"]


def test_add_profile_fact_is_deduplicated(store: NetworkingStore) -> None:
    for _ in range(2):
        store.add_profile_fact(kind="school", value="HEC Paris", source=SOURCE_LINKEDIN_EXPORT, origin="Profile.csv")
    assert len(store.list_profile_facts(kind="school")) == 1


def test_full_purge_requires_force(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Paul Exemple")
    with pytest.raises(ValueError):
        store.purge()


def test_full_purge_with_force_wipes_everything(store: NetworkingStore) -> None:
    _import(store)
    deleted = store.purge(force=True)
    assert deleted == 3
    assert store.counts() == {
        "networking_contacts": 0,
        "networking_profile_facts": 0,
        "networking_imports": 0,
    }


def test_retention_purge_only_removes_old_contacts(store: NetworkingStore) -> None:
    _import(store)
    old_id = store.list_contacts()[0].id
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE networking_contacts SET last_contact_at = '2020-01-01T00:00:00+00:00', updated_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (old_id,),
        )
    deleted = store.purge(older_than_days=30)
    assert deleted == 1
    assert [contact.id for contact in store.list_contacts()] != [old_id]


def test_retention_purge_rejects_negative_windows(store: NetworkingStore) -> None:
    with pytest.raises(ValueError):
        store.purge(older_than_days=-1)


# ----------------------------------------------------------------- recommendations
def _store_with_contacts(store: NetworkingStore) -> None:
    store.upsert_contact(
        full_name="Marie Dupont",
        headline="M&A Analyst",
        company="Banque Exemple",
        school="HEC Paris",
        source=SOURCE_LINKEDIN_EXPORT,
        provenance=[{"field": "poste", "source": SOURCE_LINKEDIN_EXPORT, "where": "Connections.csv"}],
    )
    store.upsert_contact(full_name="Bruno Nulle", headline="Boulanger", company="Boulangerie du Coin")
    store.upsert_contact(
        full_name="Claire Web",
        headline="Coverage Banker",
        company="Banque Exemple",
        source="web_researcher",
        provenance=[{"field": "poste", "source": "web_researcher", "where": "https://banque-exemple.test/team"}],
    )


def test_recommendations_match_target_role_and_desks(store: NetworkingStore) -> None:
    _store_with_contacts(store)
    contacts = store.list_contacts()
    recommendations = recommend_targets(contacts, target_role="Analyste M&A", schools=["HEC Paris"])
    assert recommendations[0].full_name == "Marie Dupont"
    assert "m&a" in recommendations[0].families


def test_recommendation_reasons_cite_provenance(store: NetworkingStore) -> None:
    _store_with_contacts(store)
    recommendations = recommend_targets(store.list_contacts(), target_role="Analyste M&A", schools=["HEC Paris"])
    top = recommendations[0]
    assert any(item["where"] == "Connections.csv" and item["source"] == SOURCE_LINKEDIN_EXPORT for item in top.provenance)
    assert any("Connections.csv" in reason for reason in top.reasons)


def test_web_researcher_contact_cites_public_proof_url(store: NetworkingStore) -> None:
    _store_with_contacts(store)
    recommendations = recommend_targets(store.list_contacts(), target_role="Coverage")
    web_rec = next(rec for rec in recommendations if rec.full_name == "Claire Web")
    assert any(item["where"] == "https://banque-exemple.test/team" for item in web_rec.provenance)


def test_alumni_school_match_is_accent_insensitive(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Elena Exemple", headline="Analyste couverture", company="Banque Exemple", school="Hec Paris")
    recommendations = recommend_targets(store.list_contacts(), schools=["HÉC Paris"], target_role="couverture")
    assert recommendations[0].full_name == "Elena Exemple"
    assert any("Alumni" in reason for reason in recommendations[0].reasons)


def test_recruiter_contacts_are_boosted(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Karim Benali", headline="Talent Acquisition Partner", company="Conseil Exemple")
    recommendations = recommend_targets(store.list_contacts(), target_role="stage conseil")
    assert recommendations[0].full_name == "Karim Benali"
    assert is_recruiter("Talent Acquisition Partner")


def test_recommendations_are_deduplicated_by_person() -> None:
    duplicate = {
        "id": 1,
        "full_name": "Marie Dupont",
        "company": "Banque Exemple",
        "headline": "M&A Analyst",
        "provenance": [{"field": "poste", "source": SOURCE_LINKEDIN_EXPORT, "where": "Connections.csv"}],
    }
    recommendations = recommend_targets([dict(duplicate), dict(duplicate)], target_role="M&A")
    assert len(recommendations) == 1


def test_recommendations_respect_limit() -> None:
    contacts = [
        {
            "id": index,
            "full_name": f"Analyste {index}",
            "company": "Banque Exemple",
            "headline": "M&A Analyst",
            "provenance": [{"field": "poste", "source": SOURCE_LINKEDIN_EXPORT, "where": "Connections.csv"}],
        }
        for index in range(5)
    ]
    assert len(recommend_targets(contacts, target_role="M&A", limit=2)) == 2


def test_unrelated_contacts_are_not_recommended(store: NetworkingStore) -> None:
    store.upsert_contact(full_name="Bruno Nulle", headline="Boulanger", company="Boulangerie du Coin")
    assert recommend_targets(store.list_contacts(), target_role="Analyste M&A") == []


def test_detect_desk_families_covers_ibc_ma_tmt_coverage() -> None:
    assert set(detect_desk_families("M&A Analyst", "Banque Exemple")) == {"m&a"}
    assert "coverage" in detect_desk_families("Coverage Banker")
    assert "tmt" in detect_desk_families("Head of TMT")
    assert "ibc" in detect_desk_families("Institutional Banking Intern")


# ------------------------------------------------------------------------- drafts
def _contact(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 42,
        "full_name": "Marie Dupont",
        "headline": "M&A Analyst",
        "company": "Banque Exemple",
        "school": "HEC Paris",
        "provenance": [{"field": "poste", "source": SOURCE_LINKEDIN_EXPORT, "where": "Connections.csv"}],
    }
    payload.update(changes)
    return payload


def test_alumni_draft_mentions_shared_school_and_is_segmented() -> None:
    draft = draft_message(
        _contact(),
        "alumni_first_contact",
        sender_name="Côme",
        sender_role="étudiant en finance",
        sender_school="HEC Paris",
        approved_facts=["Stage M&A validé chez Conseil Exemple"],
    )
    assert "HEC Paris" in draft.subject
    assert "HEC Paris" in draft.body
    assert "Marie Dupont" in draft.body
    assert "Stage M&A validé chez Conseil Exemple" in draft.body
    assert draft.facts_used == ("Stage M&A validé chez Conseil Exemple",)


def test_alumni_draft_without_shared_school_is_refused() -> None:
    with pytest.raises(MissingFactError):
        draft_message(
            _contact(school="ESSEC"),
            "alumni_first_contact",
            sender_name="Côme",
            sender_school="HEC Paris",
        )


def test_school_recruiter_draft_requires_sender_school() -> None:
    with pytest.raises(MissingFactError):
        draft_message(_contact(headline="Campus Manager"), "school_recruiter", sender_name="Côme", target_role="Analyste M&A")


def test_school_recruiter_draft_requires_target_role() -> None:
    with pytest.raises(MissingFactError):
        draft_message(_contact(headline="Campus Manager"), "school_recruiter", sender_name="Côme", sender_school="HEC Paris")


def test_school_recruiter_draft_mentions_school_and_role() -> None:
    draft = draft_message(
        _contact(headline="Campus Recruiter"),
        "school_recruiter",
        sender_name="Côme",
        sender_school="HEC Paris",
        target_role="Analyste M&A",
    )
    assert "Côme" in draft.body and "HEC Paris" in draft.body
    assert "Analyste M&A" in draft.subject


def test_coverage_desk_draft_requires_detected_desk() -> None:
    with pytest.raises(MissingFactError):
        draft_message(_contact(headline="Community Manager", company="Studio X"), "coverage_desk", sender_name="Côme", target_role="M&A")


def test_coverage_desk_draft_mentions_desk_and_target_role() -> None:
    draft = draft_message(_contact(), "coverage_desk", sender_name="Côme", sender_school="HEC Paris", target_role="Analyste M&A")
    assert "M&A" in draft.subject or "M&A" in draft.body
    assert "Banque Exemple" in draft.body
    assert "Analyste M&A" in draft.body


def test_drafts_use_only_approved_facts() -> None:
    draft = draft_message(
        _contact(),
        "alumni_first_contact",
        sender_name="Côme",
        sender_school="HEC Paris",
        approved_facts=["Recherche stage M&A"],
    )
    assert "Recherche stage M&A" in draft.body
    assert "fictif" not in draft.body


def test_draft_message_unknown_kind() -> None:
    with pytest.raises(ValueError):
        draft_message(_contact(), "spam_email", sender_name="Côme")


def test_draft_message_requires_sender_name() -> None:
    with pytest.raises(MissingFactError):
        draft_message(_contact(), "alumni_first_contact", sender_name="  ", sender_school="HEC Paris")


def test_export_drafts_writes_a_local_file_without_sending(tmp_path: Path) -> None:
    drafts = [
        draft_message(
            _contact(),
            "alumni_first_contact",
            sender_name="Côme",
            sender_school="HEC Paris",
            approved_facts=["Recherche stage M&A"],
        )
    ]
    output = export_drafts(drafts, tmp_path / "exports" / "networking_drafts.md")
    content = output.read_text(encoding="utf-8")
    assert output.exists()
    assert "Objet :" in content
    assert "Aucun envoi automatique" in content
    assert "Recherche stage M&A" in content


def test_draft_kinds_are_the_three_segmented_templates() -> None:
    assert set(DRAFT_KINDS) == {"alumni_first_contact", "school_recruiter", "coverage_desk"}


# ------------------------------------------------------------------- adversarial
def test_networking_modules_never_import_network_libraries() -> None:
    for module_path in (
        Path("career/networking.py"),
        Path("career/networking_schema.py"),
    ):
        source = module_path.read_text(encoding="utf-8")
        for forbidden in ("import requests", "import socket", "import urllib", "urlopen", "smtplib", "http.client"):
            assert forbidden not in source, f"{module_path} ne doit pas utiliser {forbidden}"
