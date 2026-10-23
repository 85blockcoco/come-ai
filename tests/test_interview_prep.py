"""SPEC-010 — Assistant d'entretien ciblé : préparation, simulation, persistance.

Toutes les fixtures sont synthétiques : aucune vraie offre, aucune vraie
entreprise, aucune donnée personnelle. Rien n'appelle le réseau. Ce qui est
vérifié : les quatre catégories de questions, la fiche entreprise bornée à ce
que l'offre dit, les banques finance et leurs sources pédagogiques, le retour
structuré de simulation, l'historique persistant, les exports Markdown/PDF et
la preuve statique qu'aucun appel externe n'existe dans les nouveaux modules.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from career import interview_prep
from career.interview_prep import (
    FINANCE_BANKS,
    CompanyFactsheet,
    InterviewPrepSession,
    InterviewQuestion,
    SimulationFeedback,
)
from career.interview_store import InterviewPrepStore
from career.router import create_career_router
from career.service import CareerService
from workspace_core import UserFacingError


ROOT = Path(__file__).resolve().parents[1]
UI_SCRIPT = ROOT / "career_static" / "js" / "interview-prep.js"


def _node() -> str:
    executable = shutil.which("node")
    if executable:
        return executable
    for candidate in ("/usr/local/bin/node", "/opt/homebrew/bin/node"):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("Node absent : impossible d'exécuter les gardes JavaScript")


def synthetic_job(**changes: object) -> dict[str, object]:
    """Offre clairement synthétique, sans référence à une vraie entreprise."""
    payload: dict[str, object] = {
        "company": "Banque de Démo",
        "title": "Stagiaire M&A",
        "source_name": "manual",
        "source_id": "REF-DEMO-2027-014",
        "official_url": "https://careers.example.test/jobs/demo-42",
        "job_family": "M&A / Investment Banking",
        "city": "Paris",
        "country": "France",
        "deadline_date": (date.today() + timedelta(days=14)).isoformat(),
        "start_date": "2027-02-01",
        "end_date": "2027-05-31",
        "duration_months": 4,
        "source_status": "open",
        "requirements": (
            "Modélisation LBO avancée et valorisation DCF.\n"
            "Maîtrise de SAP et des présentations.\n"
            "Anglais professionnel C1."
        ),
        "description_original": (
            "Stage de démonstration, données synthétiques. "
            "Le poste s'inscrit dans une équipe de six personnes."
        ),
    }
    payload.update(changes)
    return payload


def synthetic_profile(**changes: object) -> dict[str, str]:
    payload: dict[str, str] = {
        "display_name": "Personne Démo",
        "education": "Master Finance (démo)",
        "experience": "Projet étudiant de modélisation sur 6 mois.",
        "skills": "Excel, analyse financière",
        "languages": "Français, anglais C1",
        "eligibility": "compatible",
    }
    payload.update(changes)
    return payload


def prep_client(service: CareerService) -> TestClient:
    """App minimale avec le même contrat d'erreur que l'application réelle."""
    app = FastAPI()
    app.include_router(create_career_router(service))

    @app.exception_handler(UserFacingError)
    async def known_error(_: object, error: UserFacingError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    return TestClient(app)


def prepared_service(tmp_path: Path, **profile_changes: object) -> tuple[CareerService, dict]:
    service = CareerService(tmp_path)
    service.update_profile(synthetic_profile(**profile_changes))
    job = service.import_job(synthetic_job())
    return service, job


# --- 1. Contrat de génération ------------------------------------------------


def test_generate_returns_a_session_with_the_four_categories(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")

    assert isinstance(session["session_id"], str) and session["session_id"]
    assert session["offer_id"] == job["id"]
    assert session["profile_id"] == "user_profile"
    assert session["technical_questions"], "des questions techniques doivent être préparées"
    assert session["behavioral_questions"], "des questions comportementales doivent être préparées"
    assert session["gap_questions"], "les exigences non étayées doivent produire des questions d'écart"
    assert session["recruiter_questions"], "des questions à poser au recruteur doivent être préparées"
    assert session["sensitive_points"], "les points sensibles du CV doivent être listés"
    assert session["company_factsheet"]["name"] == "Banque de Démo"

    for question in session["technical_questions"]:
        assert question["category"] == "technical"
        assert question["expected_elements"]
        assert question["difficulty"] in {"easy", "medium", "hard"}
        assert question["time_estimate_seconds"] > 0
    for question in session["behavioral_questions"]:
        assert question["category"] == "behavioral"
    for question in session["gap_questions"]:
        assert question["category"] == "gap"
        assert question["related_requirement"], "une question d'écart cite l'exigence d'origine"


def test_generate_is_deterministic_for_the_same_offer(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    first = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    second = service.create_interview_prep_session(job["id"], "user_profile", "standard")

    def signature(session: dict) -> list[str]:
        return [
            question["question"]
            for key in ("technical_questions", "behavioral_questions", "gap_questions")
            for question in session[key]
        ]

    assert signature(first) == signature(second)
    assert first["session_id"] != second["session_id"]


def test_module_entry_point_generate_resolves_the_local_records(tmp_path: Path) -> None:
    """`interview_prep.generate(offer_id, profile_id, mode)` doit fonctionner seul."""
    service, job = prepared_service(tmp_path)
    interview_prep.bind_default_context(service.interview_prep_context())
    try:
        session = interview_prep.generate(job["id"], "user_profile", "standard")
    finally:
        interview_prep.bind_default_context(None)
    assert isinstance(session, InterviewPrepSession)
    assert session.technical_questions
    assert isinstance(session.company_factsheet, CompanyFactsheet)


def test_unknown_profile_and_mode_are_rejected(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    with pytest.raises(UserFacingError):
        service.create_interview_prep_session(job["id"], "profil_inexistant", "standard")
    with pytest.raises(UserFacingError):
        service.create_interview_prep_session(job["id"], "user_profile", "physique")


# --- 2. La fiche entreprise n'invente rien -----------------------------------


def test_company_factsheet_stays_within_what_the_offer_states(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    factsheet = session["company_factsheet"]

    assert factsheet["size"] == "Non renseignée par l’offre"
    assert factsheet["recent_news"] == [], "aucune actualité ne peut être affirmée sans source"
    assert factsheet["interview_process"] is None
    assert "https://careers.example.test/jobs/demo-42" in factsheet["sources"]
    assert "équipe" in factsheet["culture_keywords"], "les mots-clés viennent du texte de l'offre"


# --- 3. Le mode finance : huit banques et leurs sources -----------------------


def test_finance_mode_exposes_the_eight_specialised_banks() -> None:
    assert set(FINANCE_BANKS) == {
        "m_and_a",
        "valuation",
        "lbo",
        "markets",
        "derivatives",
        "fpa",
        "controle_gestion",
        "probabilites",
    }
    for bank, questions in FINANCE_BANKS.items():
        assert questions, f"la banque {bank} doit contenir des questions"
        for question in questions:
            assert question.source, "chaque correction cite sa source pédagogique"
            assert question.question.strip()
            assert question.expected_elements


def test_finance_session_cites_a_pedagogical_source_for_every_bank_question(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "finance")
    bank_questions = [question for question in session["questions"] if question["bank"]]
    assert bank_questions, "le mode finance doit utiliser les banques spécialisées"
    for question in bank_questions:
        assert question["pedagogical_source"], "chaque question de banque cite sa source"
        assert question["bank_label"]
    used_banks = {question["bank"] for question in bank_questions}
    assert "m_and_a" in used_banks or "valuation" in used_banks


def test_standard_mode_never_uses_the_finance_banks(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    assert all(not question["bank"] for question in session["questions"])


def test_every_finance_question_carries_a_pedagogical_source(tmp_path: Path) -> None:
    """En mode finance, chaque question préparée cite sa source pédagogique."""
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "finance")
    for key in ("technical_questions", "behavioral_questions", "gap_questions"):
        for question in session[key]:
            assert question["pedagogical_source"], f"{key} : chaque question finance cite sa source"
            assert len(question["pedagogical_source"]) > 20


# --- 4. Les écarts et les points sensibles ------------------------------------


def test_gap_questions_target_the_requirements_without_profile_evidence(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    texts = " ".join(question["question"] for question in session["gap_questions"])
    assert "SAP" in texts, "l'exigence absente du profil doit produire une question d'écart"


def test_sensitive_points_flag_the_missing_profile_facts(tmp_path: Path) -> None:
    service = CareerService(tmp_path)
    service.update_profile({"display_name": "Personne Démo"})
    job = service.import_job(synthetic_job())
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    joined = " ".join(session["sensitive_points"])
    assert "compétence" in joined.lower()
    assert "formation" in joined.lower()
    assert "éligibilité" in joined.lower()


def test_a_complete_profile_removes_the_blank_sensitive_points(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    joined = " ".join(session["sensitive_points"])
    assert "Aucune compétence" not in joined
    assert "Aucune formation" not in joined


# --- 5. La simulation renvoie un retour structuré ----------------------------


def test_simulation_returns_the_documented_feedback(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    question = session["technical_questions"][0]
    feedback = service.simulate_interview_prep(
        session["session_id"],
        question["id"],
        "D'abord je cadre l'exigence, ensuite je construis un modèle, enfin je vérifie avec des sensibilités.",
    )
    assert isinstance(feedback, dict)
    assert feedback["question_id"] == question["id"]
    assert feedback["score"] in {"excellent", "good", "needs_improvement", "insufficient"}
    assert feedback["suggested_structure"]
    assert feedback["retry_prompt"]
    assert isinstance(feedback["strengths"], list)
    assert isinstance(feedback["missing_elements"], list)
    assert isinstance(feedback["unproven_claims"], list)


def test_simulation_flags_claims_without_a_local_proof(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    question = session["technical_questions"][0]
    feedback = service.simulate_interview_prep(
        session["session_id"],
        question["id"],
        "J'ai dirigé une équipe de 12 personnes et j'ai augmenté la marge de 30 % lors de mon stage.",
    )
    assert feedback["unproven_claims"], "une affirmation sans preuve locale doit être signalée"
    assert "12" in feedback["unproven_claims"][0]


def test_simulation_rejects_an_unknown_question_and_an_empty_answer(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    with pytest.raises(UserFacingError):
        service.simulate_interview_prep(session["session_id"], "question_inexistante", "une réponse")
    with pytest.raises(UserFacingError):
        service.simulate_interview_prep(session["session_id"], session["technical_questions"][0]["id"], "")


def test_simulate_returns_the_dataclass_contract(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    preparation = interview_prep.build_preparation(
        job["id"],
        "user_profile",
        "standard",
        offer=service.get_job(job["id"]),
        profile=service.get_profile(),
    )
    question = preparation.session.technical_questions[0]
    feedback = interview_prep.simulate(
        preparation,
        question.id,
        "Je commence par le contexte, puis je détaille ma méthode, enfin je conclus.",
        profile=service.get_profile(),
    )
    assert isinstance(feedback, SimulationFeedback)
    assert isinstance(question, InterviewQuestion)


# --- 6. Persistance et historique --------------------------------------------


def test_session_and_history_survive_a_new_service_instance(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    question = session["technical_questions"][0]
    service.simulate_interview_prep(
        session["session_id"], question["id"], "Une réponse structurée avec un outil et une limite."
    )

    reopened = CareerService(tmp_path)
    restored = reopened.get_interview_prep_session(session["session_id"])
    assert restored["session_id"] == session["session_id"]
    assert restored["technical_questions"][0]["id"] == question["id"]
    history = reopened.list_interview_prep_simulations(session["session_id"])
    assert len(history["simulations"]) == 1
    assert history["simulations"][0]["feedback"]["question_id"] == question["id"]


def test_the_store_keeps_its_file_private(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    service.create_interview_prep_session(job["id"], "user_profile", "standard")
    store_path = tmp_path / "career_data" / "interview_prep.sqlite3"
    assert store_path.is_file()
    assert store_path.stat().st_mode & 0o077 == 0, "le fichier local ne doit pas être lisible par le groupe"


def test_the_store_can_be_cleared(tmp_path: Path) -> None:
    store = InterviewPrepStore(tmp_path / "career_data")
    store.save_session(
        session_id="session_1",
        offer_id="job_1",
        profile_id="user_profile",
        mode="standard",
        payload={"session": {}},
    )
    assert store.get_session("session_1") is not None
    store.clear()
    assert store.get_session("session_1") is None


def test_the_career_reset_removes_the_preparations(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    service.reset_personal_data("SUPPRIMER MES DONNÉES CAREER")
    with pytest.raises(UserFacingError):
        service.get_interview_prep_session(session["session_id"])


# --- 7. Exports ---------------------------------------------------------------


def test_markdown_export_contains_the_sections(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    path = service.export_interview_prep(session["session_id"], "md")
    markdown = path.read_text(encoding="utf-8")
    assert "Préparation d'entretien" in markdown
    assert "Questions techniques" in markdown
    assert "Fiche entreprise" in markdown
    assert "Questions à poser au recruteur" in markdown


def test_pdf_export_is_a_real_pdf(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    path = service.export_interview_prep(session["session_id"], "pdf")
    assert path.read_bytes()[:4] == b"%PDF"


def test_an_unknown_export_format_is_rejected(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    session = service.create_interview_prep_session(job["id"], "user_profile", "standard")
    with pytest.raises(UserFacingError):
        service.export_interview_prep(session["session_id"], "docx")


# --- 8. Les routes HTTP -------------------------------------------------------


def test_http_routes_expose_the_documented_contract(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    client = prep_client(service)

    created = client.post(
        "/api/career/interview-prep/generate",
        json={"offer_id": job["id"], "profile_id": "user_profile", "mode": "standard"},
    )
    assert created.status_code == 201
    session = created.json()
    assert session["technical_questions"]
    assert session["company_factsheet"]["name"] == "Banque de Démo"

    fetched = client.get(f"/api/career/interview-prep/{session['session_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == session["session_id"]

    question = session["technical_questions"][0]
    simulated = client.post(
        "/api/career/interview-prep/simulate",
        json={
            "session_id": session["session_id"],
            "question_id": question["id"],
            "user_answer": "Je cadre l'exigence, je construis un modèle, puis je teste des sensibilités.",
        },
    )
    assert simulated.status_code == 200
    assert simulated.json()["score"] in {"excellent", "good", "needs_improvement", "insufficient"}

    history = client.get(f"/api/career/interview-prep/{session['session_id']}/history")
    assert history.status_code == 200
    assert len(history.json()["simulations"]) == 1

    exported = client.post(
        f"/api/career/interview-prep/{session['session_id']}/export",
        json={"export_format": "md"},
    )
    assert exported.status_code == 200
    assert "Préparation d'entretien" in exported.text

    listed = client.get("/api/career/interview-prep")
    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["id"] == session["session_id"]


def test_http_routes_report_unknown_offers_and_sessions(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    client = prep_client(service)

    unknown_offer = client.post(
        "/api/career/interview-prep/generate",
        json={"offer_id": "job_inexistant", "profile_id": "user_profile", "mode": "standard"},
    )
    assert unknown_offer.status_code == 400
    assert "existe pas" in unknown_offer.json()["detail"]

    unknown_session = client.get("/api/career/interview-prep/session_inexistante")
    assert unknown_session.status_code == 400


def test_an_invalid_mode_is_rejected_by_the_payload_contract(tmp_path: Path) -> None:
    service, job = prepared_service(tmp_path)
    client = prep_client(service)
    response = client.post(
        "/api/career/interview-prep/generate",
        json={"offer_id": job["id"], "profile_id": "user_profile", "mode": "physique"},
    )
    assert response.status_code == 422


# --- 9. Preuves statiques ------------------------------------------------------

BANNED_PATTERNS = ("subprocess", "socket", "urllib", "requests", "httpx", "eval(", "exec(", "pickle")


def test_the_new_modules_never_reach_the_network() -> None:
    for relative in ("career/interview_prep.py", "career/interview_store.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        for pattern in BANNED_PATTERNS:
            assert pattern not in source, f"{relative} ne doit pas contenir {pattern}"


def test_the_static_ui_module_is_served_and_wired() -> None:
    script = UI_SCRIPT
    html = (ROOT / "career_static" / "index.html").read_text(encoding="utf-8")
    assert script.is_file()
    source = script.read_text(encoding="utf-8")
    assert "/career-static/js/interview-prep.js" in html
    for hook in (
        "loadInterviewPrep",
        "interviewPrepStartSimulation",
        "interviewPrepStartTimer",
        "interviewPrepRenderFeedback",
    ):
        assert hook in source, f"le module UI doit exposer {hook}"
    assert "innerHTML" not in source, "le module UI construit le DOM sans innerHTML"
    for tab in ("technical", "behavioral", "gap", "recruiter", "company"):
        assert f'data-prep-tab="{tab}"' in html


def test_the_chrono_and_the_feedback_render_in_a_browser_like_context() -> None:
    """Le chrono et le retour structuré sont exécutés, pas seulement relus."""
    source = UI_SCRIPT.read_text(encoding="utf-8")
    helpers = "const interviewPrepState = {" + source.split("const interviewPrepState = {", 1)[1].split(
        "function interviewPrepStartSimulation", 1
    )[0]
    script = r'''
const assert = require("assert");
const elements = {
  "#interview-prep-timer": {textContent: ""},
  "#interview-prep-timer-limit": {textContent: ""},
  "#interview-prep-timer-alert": {textContent: "", hidden: true},
  "#interview-prep-feedback": {hidden: true, children: [], replaceChildren() { this.children = []; }, append(node) { this.children.push(node); }},
};
global.document = { querySelector: (selector) => elements[selector] || null };
function make(tag, text = "", className = "") {
  return {tagName: tag, textContent: text, className, children: [], append(...nodes) { this.children.push(...nodes); }};
}
global.window = { setInterval: () => 42, clearInterval: () => {} };
let clock = 1000;
const realNow = Date.now;
Date.now = () => clock;
HELPERS
assert.strictEqual(interviewPrepFormatSeconds(90), "1:30");
assert.strictEqual(interviewPrepFormatSeconds(0), "0:00");
interviewPrepStartTimer(90);
assert.strictEqual(elements["#interview-prep-timer-limit"].textContent, "1:30");
assert.strictEqual(elements["#interview-prep-timer"].textContent, "0:00");
clock = 1000 + 95000;
interviewPrepTick();
assert.strictEqual(elements["#interview-prep-timer"].textContent, "1:35");
assert.strictEqual(elements["#interview-prep-timer-alert"].hidden, false);
assert.match(elements["#interview-prep-timer-alert"].textContent, /dépassé/i);
clock = 1000 + 10000;
interviewPrepTick();
assert.strictEqual(elements["#interview-prep-timer-alert"].hidden, true);
const feedback = {
  score: "good",
  strengths: ["Un point fort"],
  missing_elements: ["Un point manquant"],
  unproven_claims: ["Une affirmation non prouvée"],
  suggested_structure: "Structure STAR",
  retry_prompt: "Reprends la réponse",
  pedagogical_source: "Rosenbaum & Pearl, Investment Banking",
};
interviewPrepRenderFeedback(feedback);
const box = elements["#interview-prep-feedback"];
assert.strictEqual(box.hidden, false);
const flatten = (node) => [node.textContent || ""].concat((node.children || []).flatMap(flatten)).join(" | ");
const rendered = flatten(box);
assert.match(rendered, /Bonne/);
assert.match(rendered, /Un point manquant/);
assert.match(rendered, /Une affirmation non prouvée/);
assert.match(rendered, /Structure STAR/);
assert.match(rendered, /Reprends la réponse/);
assert.match(rendered, /Rosenbaum & Pearl/);
Date.now = realNow;
'''.replace("HELPERS", helpers)
    completed = subprocess.run([_node(), "-e", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
