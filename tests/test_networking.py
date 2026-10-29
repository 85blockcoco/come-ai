"""SPEC-040 — local networking address book and drafts.

Synthetic exports only: no real LinkedIn data, no network, no hidden state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from career import networking
from career.networking import (
    DRAFT_KINDS,
    DraftNotApplicable,
    LinkedInExport,
    NetworkingStore,
    ProfileFact,
    PublicFact,
    build_networking_draft,
    classify_desk,
    draft_for_contact,
    export_drafts,
    import_linkedin_export,
    parse_linkedin_export,
    recommend_from_store,
    recommend_targets,
    record_public_fact,
    record_public_facts,
    select_draft_kind,
)
from career.networking_schema import (
    Contact,
    NetworkingValidationError,
    Provenance,
    contact_identifier,
    init_networking_schema,
    mark_alumni,
    merge_contacts,
    normalize_relation,
    same_person,
)


PROFILE_CSV = (
    "First Name,Last Name,Headline,Industry,Geo Location,Education\n"
    "Côme,De La Venne,Étudiant en finance,Financial Services,Paris,HEC Paris\n"
)

CONNECTIONS_CSV = (
    "Notes:\n"
    "\"When exporting your connections, you will receive a CSV file.\"\n"
    "\n"
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Alice,Martin,https://www.linkedin.com/in/alice-martin,alice@example.com,Goldman Sachs,Analyst M&A,12 Jan 2021\n"
    "Bob,Leroy,https://www.linkedin.com/in/bob-leroy,,Lazard,Campus Recruiter,03 Feb 2022\n"
    "\"Jean, Jr\",Durand,https://www.linkedin.com/in/jean-durand,,BNP Paribas,Analyst TMT Coverage,04 Mar 2022\n"
)


def make_contact(**overrides) -> Contact:
    values = {
        "name": "Alice Martin",
        "role": "Analyst M&A",
        "company": "Goldman Sachs",
        "school": "HEC Paris",
        "relation": "first",
        "provenance": [Provenance(source="manual", detail="Saisie manuelle — test")],
    }
    values.update(overrides)
    return Contact(**values)


def write_export(tmp_path: Path, *, profile: str = PROFILE_CSV, connections: str = CONNECTIONS_CSV,
                 education: str | None = None) -> Path:
    folder = tmp_path / "linkedin-export"
    folder.mkdir()
    (folder / "Profile.csv").write_text(profile, encoding="utf-8-sig")
    (folder / "Connections.csv").write_text(connections, encoding="utf-8-sig")
    if education is not None:
        (folder / "Education.csv").write_text(education, encoding="utf-8-sig")
    return folder


@pytest.fixture()
def store(tmp_path: Path) -> NetworkingStore:
    return NetworkingStore(tmp_path / "career" / "networking.sqlite3")


FACTS = (
    ProfileFact(fact_id="f1", text="Stage M&A chez Lazard en 2025"),
    ProfileFact(fact_id="f2", text="Licence à HEC Paris, majeure finance"),
    {"id": "f3", "text": "Certification Java non approuvée", "approved": False},
    "Chaîne brute sans statut d’approbation",
)


# ---------------------------------------------------------------------------
# LinkedIn export parsing
# ---------------------------------------------------------------------------


def test_parse_connections_returns_contacts():
    export = parse_linkedin_export({
        "Profile.csv": PROFILE_CSV,
        "Connections.csv": CONNECTIONS_CSV,
    })
    assert len(export.contacts) == 3
    assert export.contacts[0].name == "Alice Martin"
    assert export.contacts[0].company == "Goldman Sachs"


def test_parsed_contacts_are_tagged_linkedin_export():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert all(contact.provenance[0].source == "linkedin_export" for contact in export.contacts)


def test_provenance_names_the_file_and_line():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    detail = export.contacts[0].provenance[0].detail
    assert "Connections.csv" in detail
    assert "ligne 5" in detail


def test_profile_csv_populates_viewer_and_schools():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert export.viewer["name"] == "Côme De La Venne"
    assert export.viewer_schools == ("HEC Paris",)


def test_optional_education_file_adds_schools():
    education = "School Name,Start Date\nHEC Paris,2023\n"
    export = parse_linkedin_export({
        "Profile.csv": "First Name,Last Name\nCôme,De La Venne\n",
        "Connections.csv": CONNECTIONS_CSV,
        "Education.csv": education,
    })
    assert "HEC Paris" in export.viewer_schools
    assert "Education.csv" in export.files_read


def test_bom_is_stripped():
    export = parse_linkedin_export({
        "Profile.csv": "\ufeff" + PROFILE_CSV,
        "Connections.csv": "\ufeff" + CONNECTIONS_CSV,
    })
    assert export.contacts


def test_notes_preamble_before_header_is_skipped():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert export.contacts[1].name == "Bob Leroy"


def test_quoted_comma_in_name_is_preserved():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert any(contact.name == "Jean, Jr Durand" for contact in export.contacts)


def test_localized_headers_are_recognized():
    connections = (
        "Prénom,Nom,Société,Poste,URL\n"
        "Alice,Martin,Goldman Sachs,Analyste M&A,https://www.linkedin.com/in/alice-martin\n"
    )
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": connections})
    assert export.contacts[0].company == "Goldman Sachs"
    assert export.contacts[0].role == "Analyste M&A"


def test_missing_connections_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_linkedin_export({"Profile.csv": PROFILE_CSV})


def test_missing_profile_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_linkedin_export({"Connections.csv": CONNECTIONS_CSV})


def test_unrecognized_header_produces_a_warning():
    export = parse_linkedin_export({
        "Profile.csv": PROFILE_CSV,
        "Connections.csv": "Notes:\nrien d’exploitable\n",
    })
    assert export.contacts == ()
    assert any("en-tête" in warning for warning in export.warnings)


def test_row_without_name_is_skipped_with_a_warning():
    connections = (
        "First Name,Last Name,Company,Position\n"
        ",Martin,Goldman Sachs,Analyst\n"
        "Alice,Martin,Goldman Sachs,Analyst\n"
    )
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": connections})
    assert len(export.contacts) == 1
    assert export.skipped_rows == 1
    assert any("nom absent" in warning for warning in export.warnings)


def test_duplicate_rows_are_merged_with_all_provenance():
    connections = (
        "First Name,Last Name,Company,Position\n"
        "Alice,Martin,Goldman Sachs,Analyst M&A\n"
        "Alice,Martin,Goldman Sachs,Analyst M&A\n"
    )
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": connections})
    assert len(export.contacts) == 1
    assert len(export.contacts[0].provenance) == 2


def test_school_column_equal_to_viewer_school_marks_alumni():
    connections = (
        "First Name,Last Name,Company,Position,School\n"
        "Alice,Martin,Goldman Sachs,Analyst,HEC Paris\n"
    )
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": connections})
    assert export.contacts[0].relation == "alumni"


def test_school_column_different_never_marks_alumni():
    connections = (
        "First Name,Last Name,Company,Position,School\n"
        "Alice,Martin,Goldman Sachs,Analyst,ESSEC\n"
    )
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": connections})
    assert export.contacts[0].relation == "first"


def test_missing_school_never_infers_alumni():
    export = parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert all(contact.relation != "alumni" for contact in export.contacts)


def test_oversized_export_is_refused(monkeypatch):
    monkeypatch.setattr(networking, "MAX_EXPORT_BYTES", 60)
    with pytest.raises(NetworkingValidationError):
        parse_linkedin_export({"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})


def test_directory_source_is_read(tmp_path: Path):
    folder = write_export(tmp_path)
    export = parse_linkedin_export(folder)
    assert isinstance(export, LinkedInExport)
    assert len(export.contacts) == 3


# ---------------------------------------------------------------------------
# Import into the local store
# ---------------------------------------------------------------------------


def test_import_saves_contacts(store: NetworkingStore):
    report = import_linkedin_export(store, {"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert report.imported == 3
    assert store.count_contacts() == 3


def test_reimport_is_idempotent(store: NetworkingStore):
    source = {"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV}
    import_linkedin_export(store, source)
    second = import_linkedin_export(store, source)
    assert second.imported == 0
    assert second.updated == 3
    assert store.count_contacts() == 3


def test_import_keeps_viewer_schools(store: NetworkingStore):
    report = import_linkedin_export(store, {"Profile.csv": PROFILE_CSV, "Connections.csv": CONNECTIONS_CSV})
    assert report.viewer_schools == ("HEC Paris",)


# ---------------------------------------------------------------------------
# Schema and validation
# ---------------------------------------------------------------------------


def test_contact_requires_a_name():
    with pytest.raises(NetworkingValidationError):
        make_contact(name="   ").validated()


def test_contact_requires_provenance():
    with pytest.raises(NetworkingValidationError):
        make_contact(provenance=[]).validated()


def test_unknown_relation_is_rejected():
    with pytest.raises(NetworkingValidationError):
        make_contact(relation="cousin").validated()


def test_relation_aliases_are_normalized():
    assert normalize_relation("1er") == "first"
    assert normalize_relation("2nd") == "second"
    assert normalize_relation("ancien élève") == "alumni"


def test_control_characters_are_removed_and_lengths_bounded():
    contact = make_contact(name="Alice\x00 Martin", notes="x" * 10_000).validated()
    assert "\x00" not in contact.name
    assert len(contact.notes) == 4_000


def test_web_provenance_requires_a_url():
    with pytest.raises(NetworkingValidationError):
        Provenance(source="web_research", detail="Page carrières").validated()


def test_web_provenance_keeps_its_url():
    provenance = Provenance(source="web_research", detail="Page carrières", source_url="https://example.com/team").validated()
    assert provenance.source_url == "https://example.com/team"


def test_contact_identifier_is_deterministic():
    first = contact_identifier(name="Alice Martin", company="Goldman Sachs")
    second = contact_identifier(name="alice  martin", company="goldman sachs")
    assert first == second


def test_same_person_requires_more_than_a_name():
    left = make_contact(company="Goldman Sachs")
    other = make_contact(company="Lazard")
    assert not same_person(left, other)


def test_same_person_matches_url_even_if_company_changed():
    left = make_contact(linkedin_url="https://www.linkedin.com/in/alice/")
    right = make_contact(company="Lazard", linkedin_url="https://www.linkedin.com/in/alice")
    assert same_person(left, right)


def test_merge_contacts_keeps_both_provenance():
    left = make_contact()
    right = make_contact(role="Associate", provenance=[Provenance(source="linkedin_export", detail="Export ligne 2")])
    merged = merge_contacts(left, right)
    assert merged.role == "Associate"
    assert len(merged.provenance) == 2


def test_mark_alumni_requires_an_explicit_school():
    with pytest.raises(NetworkingValidationError):
        mark_alumni(make_contact(), school="")
    assert mark_alumni(make_contact(), school="HEC Paris").relation == "alumni"


def test_schema_initialization_is_idempotent(store: NetworkingStore):
    with store._connection() as connection:
        init_networking_schema(connection)
    assert store.count_contacts() == 0


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------


def test_store_roundtrip(store: NetworkingStore):
    saved = store.save_contact(make_contact())
    loaded = store.get_contact(saved.contact_id)
    assert loaded is not None
    assert loaded.name == "Alice Martin"
    assert loaded.provenance[0].detail == "Saisie manuelle — test"


def test_store_persists_across_instances(tmp_path: Path):
    path = tmp_path / "networking.sqlite3"
    first = NetworkingStore(path).save_contact(make_contact())
    assert NetworkingStore(path).get_contact(first.contact_id) is not None


def test_list_contacts_filters(store: NetworkingStore):
    store.save_contact(make_contact(name="Alice Martin"))
    store.save_contact(make_contact(name="Bob Leroy", relation="second", company="Lazard"))
    assert len(store.list_contacts()) == 2
    assert [c.name for c in store.list_contacts(relation="second")] == ["Bob Leroy"]
    assert [c.name for c in store.list_contacts(company="goldman sachs")] == ["Alice Martin"]
    assert len(store.list_contacts(limit=1)) == 1


def test_list_contacts_rejects_invalid_limit(store: NetworkingStore):
    with pytest.raises(NetworkingValidationError):
        store.list_contacts(limit=0)


def test_update_contact(store: NetworkingStore):
    saved = store.save_contact(make_contact())
    updated = store.update_contact(saved.contact_id, next_action="Envoyer un message lundi", relation="2nd")
    assert updated.next_action == "Envoyer un message lundi"
    assert updated.relation == "second"


def test_update_unknown_field_is_rejected(store: NetworkingStore):
    saved = store.save_contact(make_contact())
    with pytest.raises(NetworkingValidationError):
        store.update_contact(saved.contact_id, salary="100k")


def test_update_unknown_contact_raises(store: NetworkingStore):
    with pytest.raises(KeyError):
        store.update_contact("net_missing", notes="x")


def test_delete_contact(store: NetworkingStore):
    saved = store.save_contact(make_contact())
    assert store.delete_contact(saved.contact_id) is True
    assert store.get_contact(saved.contact_id) is None
    assert store.delete_contact(saved.contact_id) is False


def test_purge_removes_contacts_and_provenance(store: NetworkingStore):
    store.save_contact(make_contact())
    assert store.purge_all() == 1
    assert store.count_contacts() == 0
    with store._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM networking_provenance").fetchone()[0] == 0


def test_sql_metacharacters_are_stored_literally(store: NetworkingStore):
    name = "Robert'); DROP TABLE networking_contacts;--"
    store.save_contact(make_contact(name=name))
    assert store.count_contacts() == 1
    assert store.list_contacts()[0].name == name


def test_store_dedupes_same_person_across_sources(store: NetworkingStore):
    store.save_contact(make_contact(linkedin_url=""))
    store.save_contact(make_contact(
        linkedin_url="https://www.linkedin.com/in/alice-martin",
        provenance=[Provenance(source="linkedin_export", detail="Export ligne 5")],
    ))
    assert store.count_contacts() == 1
    assert len(store.list_contacts()[0].provenance) == 2


def test_saving_the_same_provenance_twice_does_not_duplicate_it(store: NetworkingStore):
    contact = make_contact()
    store.save_contact(contact)
    stored = store.save_contact(contact)
    assert len(stored.provenance) == 1


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def test_role_match_is_recommended_with_provenance():
    items = recommend_targets([make_contact()], target_role="Analyst M&A")
    assert len(items) == 1
    assert items[0].contact.provenance
    assert all(item["detail"] for item in items[0].as_dict()["provenance"])
    assert any("métier" in reason or "M&A" in reason for reason in items[0].reasons)


def test_alumni_outranks_a_similar_non_alumni():
    alumni = make_contact(name="Alice Alumni", relation="alumni", role="Analyst")
    other = make_contact(name="Bob Analyst", relation="first", role="Analyst")
    items = recommend_targets([other, alumni], target_role="Analyst")
    assert items[0].contact.name == "Alice Alumni"


def test_target_department_gives_a_boost():
    tmt = make_contact(name="TMT Contact", role="Analyst TMT Coverage")
    unrelated = make_contact(name="Other Contact", role="Analyst", company="Lazard")
    items = recommend_targets(
        [unrelated, tmt], target_role="Analyst", target_departments=["tmt"], min_score=1
    )
    assert items[0].contact.name == "TMT Contact"


def test_unrelated_contact_is_not_recommended():
    items = recommend_targets(
        [make_contact(role="Barista", company="Café", school="", relation="second")],
        target_role="Analyst M&A",
    )
    assert items == []


def test_recommendations_are_deduplicated_by_person():
    first = make_contact(name="Alice Martin")
    duplicate = make_contact(name="Alice Martin", role="Associate M&A", contact_id="net_other")
    items = recommend_targets([first, duplicate], target_role="M&A")
    assert len(items) == 1


def test_per_company_limit_is_enforced():
    contacts = [
        make_contact(name=f"Person {index}", contact_id=f"net_{index}")
        for index in range(4)
    ]
    items = recommend_targets(contacts, target_role="M&A", limit=10, per_company_limit=2)
    assert len(items) == 2


def test_limit_is_enforced():
    contacts = [
        make_contact(name=f"Person {index}", company=f"Bank {index}", contact_id=f"net_{index}")
        for index in range(5)
    ]
    assert len(recommend_targets(contacts, target_role="M&A", limit=3)) == 3


def test_recommendations_are_deterministic():
    contacts = [
        make_contact(name="Alice Martin", company="Goldman Sachs"),
        make_contact(name="Bob Leroy", company="Lazard", contact_id="net_bob"),
    ]
    first = [item.contact.contact_id for item in recommend_targets(contacts, target_role="M&A")]
    second = [item.contact.contact_id for item in recommend_targets(contacts, target_role="M&A")]
    assert first == second


def test_target_role_is_required():
    with pytest.raises(NetworkingValidationError):
        recommend_targets([make_contact()], target_role="  ")


def test_unknown_target_department_is_rejected():
    with pytest.raises(NetworkingValidationError):
        recommend_targets([make_contact()], target_role="Analyst", target_departments=["astrophysique"])


def test_recommendation_cites_a_web_source(store: NetworkingStore):
    record_public_fact(store, PublicFact(
        person_name="Claire Dubois",
        company="Rothschild & Co",
        role="Analyst M&A",
        source_name="Page équipe Rothschild",
        source_url="https://www.rothschildandco.com/team/claire-dubois",
        excerpt="Claire Dubois est analyste au sein de l’équipe M&A.",
    ))
    items = recommend_from_store(store, target_role="Analyst M&A")
    assert items
    provenance = items[0].as_dict()["provenance"][0]
    assert provenance["source"] == "web_research"
    assert provenance["source_url"].startswith("https://")


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def test_alumni_draft_uses_only_approved_segments():
    contact = make_contact(relation="alumni")
    draft = build_networking_draft(
        contact, kind="alumni_first_contact", profile_facts=FACTS,
        viewer_schools=["HEC Paris"], viewer_name="Côme", target_role="M&A",
    )
    assert [segment.fact_id for segment in draft.segments] == ["f1", "f2"]
    assert "Java" not in draft.body
    assert "HEC Paris" in draft.body
    assert draft.can_send is False


def test_draft_without_approved_fact_is_refused():
    contact = make_contact(relation="alumni")
    with pytest.raises(DraftNotApplicable):
        build_networking_draft(
            contact, kind="alumni_first_contact",
            profile_facts=[{"id": "f1", "text": "Fait non approuvé", "approved": False}],
        )


def test_alumni_draft_is_contingent_on_an_explicit_school():
    with pytest.raises(DraftNotApplicable):
        build_networking_draft(
            make_contact(relation="first", school=""),
            kind="alumni_first_contact", profile_facts=FACTS,
        )


def test_recruiter_draft_requires_a_recruiter_role():
    contact = make_contact(role="Campus Recruiter", relation="first", school="")
    draft = build_networking_draft(contact, kind="school_recruiter", profile_facts=FACTS)
    assert draft.kind == "school_recruiter"
    with pytest.raises(DraftNotApplicable):
        build_networking_draft(
            make_contact(role="Analyst", relation="first", school=""), kind="school_recruiter",
            profile_facts=FACTS,
        )


def test_coverage_draft_requires_a_known_desk():
    contact = make_contact(role="Analyst TMT Coverage")
    draft = build_networking_draft(contact, kind="coverage_desk", profile_facts=FACTS)
    assert "TMT" in draft.body
    with pytest.raises(DraftNotApplicable):
        build_networking_draft(
            make_contact(role="Analyst", company="Café"), kind="coverage_desk", profile_facts=FACTS
        )


def test_draft_kind_is_selected_by_priority():
    alumni = make_contact(relation="alumni", role="Analyst TMT Coverage")
    assert select_draft_kind(alumni, viewer_schools=["HEC Paris"]) == "alumni_first_contact"
    assert select_draft_kind(make_contact(role="Analyst TMT Coverage", school="", relation="first")) == "coverage_desk"
    assert select_draft_kind(make_contact(role="Campus Recruiter", school="", relation="first")) == "school_recruiter"
    assert select_draft_kind(make_contact(role="Analyst", school="", relation="first")) is None


def test_draft_for_contact_returns_none_when_nothing_fits():
    assert draft_for_contact(make_contact(role="Analyst", school="", relation="first"), profile_facts=FACTS) is None


def test_unknown_draft_kind_is_rejected():
    with pytest.raises(NetworkingValidationError):
        build_networking_draft(make_contact(), kind="cold_call", profile_facts=FACTS)


def test_export_drafts_json_is_local_and_never_sends(tmp_path: Path):
    contact = make_contact(relation="alumni")
    draft = build_networking_draft(contact, kind="alumni_first_contact", profile_facts=FACTS)
    path = export_drafts([draft], tmp_path / "drafts.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["can_send"] is False
    assert payload["drafts"][0]["contact_id"] == contact.validated().contact_id
    assert path.stat().st_mode & 0o777 == 0o600


def test_export_drafts_text(tmp_path: Path):
    contact = make_contact(relation="alumni")
    draft = build_networking_draft(contact, kind="alumni_first_contact", profile_facts=FACTS)
    path = export_drafts([draft], tmp_path / "drafts.txt")
    content = path.read_text(encoding="utf-8")
    assert "Objet :" in content
    assert contact.name in content


def test_draft_has_no_send_function():
    assert not hasattr(networking, "send_draft")
    assert all(draft_kind in DRAFT_KINDS for draft_kind in DRAFT_KINDS)


# ---------------------------------------------------------------------------
# Public facts (Web Researcher evidence)
# ---------------------------------------------------------------------------


def test_public_fact_requires_an_excerpt(store: NetworkingStore):
    with pytest.raises(NetworkingValidationError):
        record_public_fact(store, PublicFact(
            person_name="Claire Dubois", company="Rothschild",
            source_name="Page équipe", source_url="https://example.com/team", excerpt="court",
        ))


def test_public_fact_requires_an_http_url(store: NetworkingStore):
    with pytest.raises(NetworkingValidationError):
        record_public_fact(store, PublicFact(
            person_name="Claire Dubois", company="Rothschild",
            source_name="Page équipe", source_url="file:///tmp/team",
            excerpt="Claire Dubois est analyste M&A chez Rothschild.",
        ))


def test_one_page_per_company_per_research(store: NetworkingStore):
    base = dict(person_name="Claire Dubois", company="Rothschild", source_name="Page équipe",
                excerpt="Claire Dubois est analyste M&A chez Rothschild.")
    with pytest.raises(NetworkingValidationError):
        record_public_facts(store, [
            PublicFact(source_url="https://example.com/a", **base),
            PublicFact(source_url="https://example.com/b", **base),
        ])
    # The batch is validated before the first write: nothing is half-imported.
    assert store.count_contacts() == 0


def test_public_fact_school_matching_viewer_marks_alumni(store: NetworkingStore):
    contact = record_public_fact(store, PublicFact(
        person_name="Claire Dubois", company="Rothschild", role="Analyst",
        school="HEC Paris", source_name="Page équipe",
        source_url="https://example.com/team", excerpt="Claire Dubois, HEC Paris, analyste M&A.",
    ))
    assert contact.relation == "second"
    contact = record_public_facts(store, [PublicFact(
        person_name="Claire Dubois", company="Rothschild", role="Analyst",
        school="HEC Paris", source_name="Page équipe",
        source_url="https://example.com/team", excerpt="Claire Dubois, HEC Paris, analyste M&A.",
    )], viewer_schools=["HEC Paris"])[0]
    assert contact.relation == "alumni"


def test_public_facts_are_tagged_web_research(store: NetworkingStore):
    contact = record_public_fact(store, PublicFact(
        person_name="Claire Dubois", company="Rothschild", role="Analyst M&A",
        source_name="Page équipe", source_url="https://example.com/team",
        excerpt="Claire Dubois est analyste M&A chez Rothschild.",
    ))
    assert contact.provenance[0].source == "web_research"
    assert contact.provenance[0].detail.startswith("Page équipe")


def test_public_fact_school_not_shared_never_marks_alumni(store: NetworkingStore):
    contact = record_public_facts(store, [PublicFact(
        person_name="Claire Dubois", company="Rothschild", role="Analyst",
        school="HEC Paris", source_name="Page équipe",
        source_url="https://example.com/team", excerpt="Claire Dubois, HEC Paris, analyste M&A.",
    )], viewer_schools=["ESSEC"])[0]
    assert contact.relation == "second"


# ---------------------------------------------------------------------------
# Desk classification and security guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "desk"),
    [
        ("Analyst M&A", "ma"),
        ("TMT Coverage", "tmt"),
        ("Investment Banking Coverage", "ibc"),
        ("Coverage desk", "coverage"),
        ("Leveraged Finance", "leveraged_finance"),
        ("Private Equity", "private_equity"),
        ("Equity Capital Markets", "ecm"),
        ("Debt Capital Markets", "dcm"),
        ("Barista", None),
    ],
)
def test_classify_desk(text: str, desk: str | None):
    assert classify_desk(text) == desk


def test_module_has_no_network_client():
    source = Path(networking.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "import requests", "from requests", "import urllib.request", "from urllib.request",
        "import http.client", "import socket", "import selenium", "from selenium",
        "import playwright", "from playwright",
    ):
        assert forbidden not in source


def test_address_book_cannot_be_exported():
    assert not hasattr(networking, "export_contacts")
    assert not hasattr(networking, "export_address_book")
