"""SK-10 — campagne adversariale n°2 (ordre cvboost-31-1792623192).

Cette campagne ne rejoue pas les six défauts déjà corrigés par la campagne
précédente (D1–D6 du rapport SPEC-SK10).  Elle attaque les zones que celle-ci
n'a pas couvertes :

- l'alignement des offsets sur **le texte réellement montré à la personne** ;
- la provenance fine d'une **date** (offsets qui pointent sur la date elle-même) ;
- les **collisions entre deux documents** distincts lors d'une nouvelle
  proposition ;
- les **bornes de champ** : un fait qui tient dans le champ ne doit pas être
  écarté parce qu'un fait plus long ne tenait pas ;
- l'**honnêteté de la citation** : la citation est le passage source, toujours.

Toutes les fixtures sont synthétiques : aucun document réel, aucun réseau,
aucune candidature envoyée.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

import pytest

from career.candidate_profile import (
    STATUS_APPROVED,
    STATUS_PROPOSED,
    Evidence,
    Fact,
    merge_usable_facts,
)
from career.profile_builder import build_fact_proposals
from career.service import CareerService


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "candidate_profile"
CV_SYNTHETIQUE = (FIXTURES / "cv_synthetique.txt").read_text(encoding="utf-8")
CV_OCR_SYNTHETIQUE = (FIXTURES / "cv_ocr_synthetique.txt").read_text(encoding="utf-8")


# ── Helpers ─────────────────────────────────────────────────────────────────


def fact_of(**changes: object) -> Fact:
    base = {
        "id": "fact_test",
        "kind": "skill",
        "label": "Excel",
        "value": "",
        "status": STATUS_APPROVED,
        "evidence": Evidence(source="embedded_text", page=1, page_confidence="exact", start_offset=0, end_offset=5, quote="Excel"),
    }
    base.update(changes)
    return Fact(**base)  # type: ignore[arg-type]


def import_text_document(service: CareerService, name: str, text: str) -> dict:
    """Store a synthetic document as a real local profile import."""
    payload = text.encode("utf-8")
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    return service.import_profile_document(
        source_kind="cv",
        original_name=name,
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def import_docx_document(service: CareerService, name: str, paragraphs: list[str]) -> dict:
    """Store a synthetic DOCX as a real local profile import."""
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = Path(service.documents_dir) / f"synthetic_{name}"
    document.save(buffer)
    payload = buffer.read_bytes()
    buffer.unlink()
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    return service.import_profile_document(
        source_kind="cv",
        original_name=name,
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def build_pdf(pages: list[list[str]]) -> bytes:
    """Build a minimal multi-page PDF holding one text line per row."""
    count = len(pages)
    page_ids = [5 + 2 * index for index in range(count)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode()
    for index, lines in enumerate(pages):
        content_id = 4 + 2 * index
        page_id = 5 + 2 * index
        parts = ["BT", "/F1 12 Tf", "72 720 Td"]
        for position, line in enumerate(lines):
            if position:
                parts.append("0 -14 Td")
            parts.append(f"({line}) Tj")
        parts.append("ET")
        stream = " ".join(parts).encode("latin-1")
        objects[content_id] = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_offset = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode()
    out += b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets.get(number, 0):010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    return bytes(out)


def import_bytes_document(service: CareerService, name: str, payload: bytes) -> dict:
    """Store a synthetic document as a real local profile import."""
    temporary = service.profile_upload_temp_path()
    temporary.write_bytes(payload)
    return service.import_profile_document(
        source_kind="cv",
        original_name=name,
        temporary_path=temporary,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def assert_quotes_match_the_visible_text(text: str, facts: list[dict]) -> None:
    """Every fact must be verifiable against the text the person was shown."""
    for fact in facts:
        evidence = fact["evidence"]
        excerpt = text[evidence["start_offset"] : evidence["end_offset"]]
        assert excerpt.strip(), fact["label"]
        assert evidence["quote"] == excerpt, fact["label"]


# ── 1. Les offsets doivent viser le texte montré à la personne ───────────────


def test_the_offsets_point_into_the_text_shown_in_the_import_preview(tmp_path):
    """Les offsets d'un fait doivent viser l'aperçu lu par la personne.

    Le service ré-extrait le document pour retrouver les pages, mais l'aperçu
    montre le texte stocké.  Si les deux diffèrent, les offsets ne désignent
    plus rien de vérifiable et la preuve est fausse.
    """
    service = CareerService(tmp_path)
    raw = "\n\n" + CV_SYNTHETIQUE + "\n\n   \n"
    profile_import = import_text_document(service, "cv-synthetique.txt", raw)
    preview = profile_import["preview"]
    assert preview == CV_SYNTHETIQUE.strip()  # the stored text is the stripped one

    result = service.build_candidate_facts(import_id=profile_import["id"])
    assert result["facts"]
    assert_quotes_match_the_visible_text(preview, result["facts"])


def test_a_docx_import_keeps_the_offsets_of_the_preview_text(tmp_path):
    """Un DOCX sans information de page garde des offsets vérifiables."""
    service = CareerService(tmp_path)
    profile_import = import_docx_document(
        service,
        "cv-synthetique.docx",
        ["", "Compétences", "Excel, SQL", "Langues", "Anglais - C1"],
    )
    preview = profile_import["preview"]

    result = service.build_candidate_facts(import_id=profile_import["id"])
    assert result["facts"]
    assert_quotes_match_the_visible_text(preview, result["facts"])


def test_the_page_is_still_reported_for_a_text_import(tmp_path):
    """Aligner les offsets ne doit pas perdre l'information de page."""
    service = CareerService(tmp_path)
    profile_import = import_text_document(service, "cv-synthetique.txt", CV_SYNTHETIQUE)
    result = service.build_candidate_facts(import_id=profile_import["id"])
    pages = {fact["evidence"]["page"] for fact in result["facts"]}
    assert pages == {1}
    assert result["source"]["pages_known"] is True


# ── 2. Une date garde la source de la date elle-même ────────────────────────


def test_a_date_fact_points_at_the_date_itself():
    """La provenance d'une date doit désigner la date, pas toute la rubrique.

    La mission exige que chaque date garde sa source (page, offsets, citation).
    Une citation qui recouvre l'entrée entière ne désigne plus la date.
    """
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    dates = [fact for fact in facts if fact.kind == "date"]
    assert dates, "the synthetic CV must propose date facts"
    for fact in dates:
        excerpt = CV_SYNTHETIQUE[fact.evidence.start_offset : fact.evidence.end_offset]
        assert excerpt == fact.evidence.quote, fact.label
        assert len(excerpt) <= 40, f"a date fact must not quote a whole entry: {excerpt!r}"
        assert re.search(r"\d{4}", excerpt), excerpt


def test_a_date_fact_keeps_the_raw_date_of_the_source():
    """La citation d'une date est la date brute, pas une date reformatée."""
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    dates = [fact for fact in facts if fact.kind == "date"]
    raw_dates = re.findall(r"(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}", CV_SYNTHETIQUE)
    assert raw_dates
    quoted = {fact.evidence.quote for fact in dates}
    assert quoted & set(raw_dates), f"no raw date found in {quoted}"


# ── 3. Une phrase qui mentionne une rubrique n'est pas un fait ──────────────


def test_a_summary_line_mentioning_a_section_is_not_proposed_as_a_fact():
    """Une ligne de résumé n'est pas une compétence.

    Le moteur de structure de Mission 01 ancre une rubrique sur la première
    ligne qui *contient* le mot-clé.  Une phrase de profil comme
    « Compétences clés recherchées » deviendrait alors une compétence
    proposée à la personne : elle n'est pas un fait du CV.
    """
    document = (
        "PROFIL\n"
        "Compétences clés recherchées\n"
        "\n"
        "Compétences\n"
        "Excel, SQL\n"
        "\n"
        "Langues\n"
        "Anglais - C1\n"
    )
    facts = build_fact_proposals(document, filename="cv-resume.txt")
    labels = {fact.label for fact in facts}
    assert "Compétences clés recherchées" not in labels
    assert "Excel" in labels
    assert "Anglais" in labels


def test_the_real_section_content_is_still_proposed():
    """Le durcissement ne doit pas perdre les éléments d'une vraie rubrique."""
    document = (
        "PROFIL\n"
        "Compétences clés recherchées\n"
        "\n"
        "Compétences\n"
        "Excel, SQL\n"
        "\n"
        "Langues\n"
        "Anglais - C1\n"
    )
    facts = build_fact_proposals(document, filename="cv-resume.txt")
    labels = {fact.label for fact in facts}
    assert {"Excel", "SQL", "Anglais"} <= labels


def test_an_unusual_section_title_keeps_its_content():
    """Un titre inhabituel (« Langues et niveaux ») ne perd pas son contenu."""
    document = (
        "LANGUES ET NIVEAUX\n"
        "Anglais - C1\n"
        "\n"
        "COMPETENCES\n"
        "Excel\n"
    )
    facts = build_fact_proposals(document, filename="cv-unusual.txt")
    labels = {fact.label for fact in facts}
    assert "Anglais" in labels
    assert "Excel" in labels
    assert "LANGUES ET NIVEAUX" not in labels


# ── 4. Une borne de champ n'écarte pas un fait qui tient ────────────────────


def test_a_fact_that_fits_in_the_field_is_not_dropped_by_a_longer_one():
    """Un fait qui tient dans le champ restant doit être conservé.

    La boucle de bornage s'arrêtait au premier élément qui ne tenait pas :
    un fait long pouvait ainsi écarter tous les faits courts qui tenaient
    encore.
    """
    profile = {"skills": "X" * 3950}
    long_fact = fact_of(id="fact_long", label="L" * 80)
    short_fact = fact_of(id="fact_short", label="S" * 20)

    merged = merge_usable_facts(profile, [long_fact, short_fact])

    assert "S" * 20 in merged["skills"]
    assert len(merged["skills"]) <= 4000


# ── 5. Deux documents distincts ne s'effacent pas ───────────────────────────


def test_two_pasted_documents_do_not_delete_each_other_proposals(tmp_path):
    """Coller un second texte ne doit pas effacer la relecture du premier.

    L'interface envoie toujours le même nom « texte-profil » : deux collages
    différents partageaient donc la même clé d'effacement.
    """
    service = CareerService(tmp_path)
    first = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="texte-profil")
    assert first["facts"]

    second_document = (
        "Compétences\n"
        "Power BI, Tableau\n"
        "\n"
        "Langues\n"
        "Espagnol - B1\n"
    )
    second = service.build_candidate_facts(text=second_document, filename="texte-profil")
    assert second["facts"]

    labels = {fact["label"] for fact in service.list_candidate_facts()}
    assert "Excel" in labels, "the pending review of the first document was erased"
    assert "Power BI" in labels


def test_re_proposing_the_same_document_replaces_its_pending_proposals(tmp_path):
    """Relire le même document remplace ses propositions en attente."""
    service = CareerService(tmp_path)
    service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="texte-profil")
    again = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="texte-profil")
    stored = service.list_candidate_facts()
    assert len(stored) == len(again["facts"])


# ── 6. La citation est toujours le passage source ───────────────────────────


def test_the_quote_of_a_long_fact_is_still_the_verbatim_source_passage():
    """Une citation tronquée silencieusement n'est plus une preuve."""
    long_result = "Analyse financière " + ("avec un détail complet " * 60)
    document = (
        "Expérience\n"
        "2021-2023 | Analyste | Banque Synthetique\n"
        f"{long_result}\n"
    )
    facts = build_fact_proposals(document, filename="cv-long.txt")
    assert facts
    for fact in facts:
        excerpt = document[fact.evidence.start_offset : fact.evidence.end_offset]
        assert fact.evidence.quote == excerpt, fact.label


def test_the_fact_text_is_the_whole_quoted_passage():
    """Le libellé du fait doit se retrouver dans le passage qu'il cite."""
    facts = build_fact_proposals(CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    for fact in facts:
        excerpt = CV_SYNTHETIQUE[fact.evidence.start_offset : fact.evidence.end_offset]
        assert fact.label[:30] in excerpt or fact.value[:30] in excerpt


# ── 7. Robustesse des décisions ────────────────────────────────────────────


def test_an_impossible_transition_gives_a_readable_error(tmp_path):
    """Une transition impossible est une erreur lisible, jamais un plantage."""
    from workspace_core import UserFacingError

    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    fact_id = result["facts"][0]["id"]
    service.decide_candidate_fact(fact_id, "approve")

    with pytest.raises(UserFacingError):
        service.decide_candidate_fact(fact_id, "approve")

    with pytest.raises(UserFacingError):
        service.decide_candidate_fact(fact_id, "decision_inconnue")


def test_a_fact_stays_proposed_until_a_decision_is_made(tmp_path):
    """Aucun chemin automatique n'écrit un statut décidé."""
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv_synthetique.txt")
    stored = service.list_candidate_facts()
    assert {fact["status"] for fact in stored} == {STATUS_PROPOSED}
    assert result["counts"][STATUS_PROPOSED] == len(stored)


# ── 8. Le cas le plus courant : un PDF de plusieurs pages ───────────────────


def test_a_multi_page_pdf_keeps_the_offsets_of_the_preview_text(tmp_path):
    """Un PDF multipage : les offsets désignent l'aperçu, pas une autre lecture.

    La lecture stockée joint les pages avec un seul retour à la ligne, la
    relecture du parseur les joint avec deux : sans alignement, chaque fait
    des pages suivantes était décalé.
    """
    service = CareerService(tmp_path)
    payload = build_pdf(
        [
            [
                "PAGE ONE",
                "Camille Exemple",
                "camille.exemple@example.test",
                "COMPETENCES",
                "Excel, SQL, Power BI",
            ],
            [
                "PAGE TWO",
                "LANGUES",
                "Anglais - C1",
                "EXPERIENCE",
                "2023-2025 | Analyste | Groupe Synthetique",
            ],
        ]
    )
    profile_import = import_bytes_document(service, "cv-multipage.pdf", payload)
    preview = profile_import["preview"]

    result = service.build_candidate_facts(import_id=profile_import["id"])

    assert result["facts"]
    assert result["source"]["from_ocr"] is False
    assert_quotes_match_the_visible_text(preview, result["facts"])


def test_a_multi_page_pdf_reports_the_page_of_each_fact(tmp_path):
    """Le fait de la seconde page reste annoncé sur la seconde page."""
    service = CareerService(tmp_path)
    payload = build_pdf(
        [
            [
                "PAGE ONE",
                "Camille Exemple",
                "camille.exemple@example.test",
                "COMPETENCES",
                "Excel, SQL, Power BI",
            ],
            [
                "PAGE TWO",
                "LANGUES",
                "Anglais - C1",
                "EXPERIENCE",
                "2023-2025 | Analyste | Groupe Synthetique",
            ],
        ]
    )
    profile_import = import_bytes_document(service, "cv-multipage.pdf", payload)
    result = service.build_candidate_facts(import_id=profile_import["id"])

    pages = {fact["label"]: fact["evidence"]["page"] for fact in result["facts"]}
    assert pages.get("Anglais") == 2, pages
    assert pages.get("Excel") == 1, pages


def test_an_ocr_import_keeps_the_offsets_of_the_stored_reading(tmp_path):
    """La lecture OCR stockée reste la référence des offsets."""
    service = CareerService(tmp_path)
    profile_import = service._create_profile_import(
        source_kind="cv",
        original_name="cv-scan.pdf",
        stored_filename="",
        content_sha256="2" * 64,
        size_bytes=len(CV_OCR_SYNTHETIQUE),
        extracted_text=CV_OCR_SYNTHETIQUE,
        extraction_method="macos_vision",
        ocr_pages=1,
    )
    stored = service.get_profile_import(profile_import["id"])
    preview = stored["preview"]

    result = service.build_candidate_facts(import_id=profile_import["id"])

    assert result["facts"]
    assert result["source"]["from_ocr"] is True
    assert_quotes_match_the_visible_text(preview, result["facts"])


# ── 9. La migration vers la v11 ─────────────────────────────────────────────


def test_the_migration_to_v11_keeps_the_existing_facts(tmp_path):
    """La v11 n'efface aucun fait déjà décidé."""
    service = CareerService(tmp_path)
    result = service.build_candidate_facts(text=CV_SYNTHETIQUE, filename="cv.txt")
    fact_id = result["facts"][0]["id"]
    service.decide_candidate_fact(fact_id, "approve")

    with sqlite3.connect(service.db_path) as connection:
        connection.execute("PRAGMA user_version = 10")

    reopened = CareerService(tmp_path)
    stored = reopened.get_candidate_fact(fact_id)
    assert stored["status"] == STATUS_APPROVED
    assert reopened.candidate_fact_counts()[STATUS_APPROVED] == 1


def test_the_migration_to_v11_adds_the_source_key(tmp_path):
    """La colonne de source existe après la migration."""
    service = CareerService(tmp_path)
    with sqlite3.connect(service.db_path) as connection:
        connection.execute("PRAGMA user_version = 10")
    reopened = CareerService(tmp_path)
    with sqlite3.connect(reopened.db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(candidate_facts)")}
    assert "source_key" in columns


# ── 10. Le profil écrit à la main n'est jamais perdu ────────────────────────


def test_the_manual_content_of_a_field_is_never_dropped(tmp_path):
    """Borner un champ ne doit jamais effacer ce que la personne a écrit."""
    service = CareerService(tmp_path)
    service.update_profile({"skills": "Compétence écrite à la main"})
    result = service.build_candidate_facts(text="Compétences\nExcel\n", filename="cv.txt")
    fact_id = [fact["id"] for fact in result["facts"] if fact["kind"] == "skill"][0]
    service.decide_candidate_fact(fact_id, "approve")

    service.apply_candidate_facts([fact_id])

    skills = service.get_profile()["skills"]
    assert "Compétence écrite à la main" in skills
    assert "Excel" in skills
