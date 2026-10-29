"""End-to-end release gate for the local-first Career workspace.

The gate exercises the whole journey through a real HTTP client against an
ephemeral local server: profile import/review, exploration with
successful/partial/unavailable sources, admission, qualification, dedup,
matching, preparation, apply kit downloads, tracking, manual approval,
receipt, follow-up radar, interview coach, restart persistence and an optional
real-browser smoke test.

Metric classes stay separate on purpose:

* ``synthetic`` – deterministic fixture inputs (never evidence of live cover);
* ``app-verified`` – observed behaviour of the real application/HTTP surface;
* ``live`` – public network sources, only with explicit opt-in;
* ``unmeasured`` – real recruiters' quality, intentionally not scored here.

Nothing is submitted, sent, uploaded or resolved through a cloud provider.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

import httpx

from .discovery import DiscoveryPayload, PublicSourceError
from .service import CareerService

SCHEMA = "come-career-release-gate/1"

SYNTHETIC = "synthetic"
APP_VERIFIED = "app-verified"
LIVE = "live"
UNMEASURED = "unmeasured"

QUALITY_NOTE = (
    "La qualité réelle des candidatures (recruteur, entretien, embauche) n'est "
    "pas mesurée : le gate vérifie le parcours applicatif, pas un score métier."
)

SYNTHETIC_PROFILE_TEXT = """Profil synthétique de recette
Nom: Candidate Recette
Formation: MSc Finance, 2026
Expérience: Analyse financière et valorisation (projets synthétiques)
Compétences: Excel, Python, modélisation financière
Langues: Français, anglais
"""

SYNTHETIC_PROFILE = {
    "display_name": "Candidate Recette",
    "contact_email": "candidate.recette@example.test",
    "contact_phone": "+33 6 00 00 00 00",
    "linkedin_url": "https://www.linkedin.com/in/candidate-recette",
    "education": "MSc Finance — 2026",
    "experience": (
        "2025 | Analyste stagiaire | Banque Synthétique — Valorisation DCF de deux sociétés.\n"
        "2024 | Assistante | Cabinet Synthétique — Analyse de 120 dossiers, gain de 30 %."
    ),
    "skills": "Excel, Python, modélisation financière, valorisation",
    "languages": "Français natif ; anglais C1",
}

BRIEF = {
    "domains": ["M&A"],
    "countries": ["Germany"],
    "cities": ["Frankfurt"],
    "excluded_countries": [],
    "excluded_cities": [],
    "require_known_location": True,
    "start_months": [1],
    "minimum_stage_duration_months": 6,
    "contract_types": ["stage"],
}

_CURATED_SOURCES = (
    {
        "id": "synthetic-ok",
        "provider": "synthetic_ok",
        "company": "Synthetic Alpha Bank",
        "board_token": "alpha",
        "public_url": "https://boards.example.test/alpha",
        "provenance_url": "https://boards.example.test/alpha",
        "verified_at": "2026-10-20T08:00:00+00:00",
    },
    {
        "id": "synthetic-partial",
        "provider": "synthetic_partial",
        "company": "Synthetic Beta Bank",
        "board_token": "beta",
        "public_url": "https://boards.example.test/beta",
        "provenance_url": "https://boards.example.test/beta",
        "verified_at": "2026-10-20T08:00:00+00:00",
    },
    {
        "id": "synthetic-down",
        "provider": "synthetic_down",
        "company": "Synthetic Gamma Bank",
        "board_token": "gamma",
        "public_url": "https://boards.example.test/gamma",
        "provenance_url": "https://boards.example.test/gamma",
        "verified_at": "2026-10-20T08:00:00+00:00",
    },
    {
        "id": "synthetic-unsupported",
        "provider": "synthetic_missing",
        "company": "Synthetic Delta Bank",
        "board_token": "delta",
        "public_url": "https://boards.example.test/delta",
        "provenance_url": "https://boards.example.test/delta",
        "verified_at": "2026-10-20T08:00:00+00:00",
    },
    {
        "id": "synthetic-no-provenance",
        "provider": "synthetic_ok",
        "company": "Synthetic Epsilon Bank",
        "board_token": "epsilon",
        "public_url": "https://boards.example.test/epsilon",
        "provenance_url": "",
        "verified_at": "",
    },
)

_VERIFIED_AT = "2026-10-20T08:00:00+00:00"


def _synthetic_job(
    *, company: str, title: str, slug: str, source_name: str, source_id: str
) -> dict[str, Any]:
    domain = company.lower().replace(" ", "").replace("'", "")
    return {
        "company": company,
        "title": title,
        "source_name": source_name,
        "source_id": source_id,
        "official_url": f"https://careers.{domain}.test/{slug}",
        "job_family": "M&A / Investment Banking",
        "city": "Frankfurt",
        "country": "Germany",
        "posted_date": "2026-10-01",
        "start_date": "2027-01-04",
        "duration_months": 6,
        "source_status": "open",
        "employment_type": "Internship",
        "requirements": "Financial modeling, valuation and Excel required.",
        "description_original": (
            "This is an internship in mergers and acquisitions. "
            "The team builds valuation models and works on deal execution."
        ),
    }


class _FixtureConnector:
    """Deterministic connector used only by this gate (no network at all)."""

    def __init__(self, payload: Callable[[], DiscoveryPayload]) -> None:
        self._payload = payload
        self.calls = 0

    def discover_internships(
        self, source: Any, *, selection_brief: dict[str, Any], deadline: float | None = None
    ) -> DiscoveryPayload:
        self.calls += 1
        return self._payload()


def _ok_payload() -> DiscoveryPayload:
    jobs = (
        _synthetic_job(
            company="Synthetic Alpha Bank",
            title="M&A Internship — Frankfurt",
            slug="alpha-ma",
            source_name="synthetic_ok",
            source_id="alpha-1",
        ),
        _synthetic_job(
            company="Synthetic Alpha Bank",
            title="M&A Off-cycle Internship",
            slug="alpha-ma-2",
            source_name="synthetic_ok",
            source_id="alpha-2",
        ),
    )
    return DiscoveryPayload(
        jobs=jobs,
        verified_at=_VERIFIED_AT,
        truncated=False,
        evaluated_count=2,
        invalid_count=0,
        raw_count=2,
        confirmed_count=2,
        uncertain_count=0,
        excluded_count=0,
        relevant_count=2,
        filtered_criteria_count=0,
    )


def _partial_payload() -> DiscoveryPayload:
    job = _synthetic_job(
        company="Synthetic Beta Bank",
        title="M&A Internship — Partial Feed",
        slug="beta-ma",
        source_name="synthetic_partial",
        source_id="beta-1",
    )
    return DiscoveryPayload(
        jobs=(job,),
        verified_at=_VERIFIED_AT,
        truncated=False,
        evaluated_count=1,
        invalid_count=1,
        raw_count=2,
        confirmed_count=1,
        uncertain_count=0,
        excluded_count=0,
        relevant_count=1,
        filtered_criteria_count=0,
    )


def _down_payload() -> DiscoveryPayload:
    raise PublicSourceError("Synthetic source unavailable.", code="timeout")


def _build_service(base_dir: Path) -> CareerService:
    return CareerService(
        base_dir,
        curated_sources=_CURATED_SOURCES,
        exploration_connectors={
            "synthetic_ok": _FixtureConnector(_ok_payload),
            "synthetic_partial": _FixtureConnector(_partial_payload),
            "synthetic_fail": _FixtureConnector(_down_payload),
            "synthetic_down": _FixtureConnector(_down_payload),
        },
    )


class _LocalServer:
    """Run the real ASGI app on a loopback socket for a real HTTP client."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self.client: httpx.Client | None = None
        self.base_url = ""

    def __enter__(self) -> "_LocalServer":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()

    def start(self) -> None:
        import uvicorn

        from come_ai_web import create_app

        app = create_app(base_dir=self.base_dir, career_override=_build_service(self.base_dir))
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="error",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # type: ignore[assignment]
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Le serveur local de recette n'a pas démarré.")
            if not thread.is_alive():
                raise RuntimeError("Le serveur local de recette s'est arrêté au démarrage.")
            time.sleep(0.02)
        socket = server.servers[0].sockets[0]
        port = int(socket.getsockname()[1])
        self._server = server
        self._thread = thread
        self.base_url = f"http://127.0.0.1:{port}"
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0, follow_redirects=False)

    def stop(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)
        self._server = None
        self._thread = None


@dataclass
class GateCheck:
    id: str
    label: str
    status: str  # pass | fail | skip
    metric: str
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"pass", "skip"}


@dataclass
class ReleaseReport:
    checks: list[GateCheck]
    generated_at: str
    schema: str = SCHEMA

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    @property
    def counts(self) -> dict[str, int]:
        totals = {"pass": 0, "fail": 0, "skip": 0}
        for check in self.checks:
            totals[check.status] = totals.get(check.status, 0) + 1
        return totals

    @property
    def metrics(self) -> dict[str, Any]:
        by_class: dict[str, dict[str, int]] = {}
        for check in self.checks:
            bucket = by_class.setdefault(check.metric, {"pass": 0, "fail": 0, "skip": 0})
            bucket[check.status] = bucket.get(check.status, 0) + 1
        return {
            "classes": by_class,
            "fixtures": {
                "class": SYNTHETIC,
                "note": (
                    "Profil et offres d'entrée sont synthétiques ; les checks "
                    "app-verified observent l'application réelle sur ces entrées."
                ),
            },
            "quality_measurement": {"status": UNMEASURED, "note": QUALITY_NOTE},
            "submission": {
                "automatic": False,
                "sent": 0,
                "note": "Aucune candidature, lettre ou relance n'est envoyée par ce gate.",
            },
            "network": {
                "default": "offline",
                "live_enabled": by_class.get(LIVE, {}).get("pass", 0) > 0,
                "note": "Les sources publiques ne sont contactées que sur demande explicite.",
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "ok": self.ok,
            "counts": self.counts,
            "metrics": self.metrics,
            "checks": [asdict(check) for check in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        counts = self.counts
        lines = [
            "# Career release gate",
            "",
            f"- Schema: `{self.schema}`",
            f"- Genere: {self.generated_at}",
            f"- Resultat: **{'PASS' if self.ok else 'FAIL'}** "
            f"({counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip)",
            "",
            "| Verdict | Classe | Check | Detail |",
            "| --- | --- | --- | --- |",
        ]
        icons = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}
        for check in self.checks:
            detail = check.detail.replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {icons.get(check.status, check.status)} | `{check.metric}` | "
                f"`{check.id}` — {check.label} | {detail} |"
            )
        lines.extend(["", f"> {QUALITY_NOTE}"])
        return "\n".join(lines) + "\n"


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _json(response: httpx.Response, *, expected: int = 200) -> Any:
    _require(
        response.status_code == expected,
        f"{response.request.method} {response.request.url.path} -> "
        f"{response.status_code} (attendu {expected}) : {response.text[:300]}",
    )
    return response.json()


def _get(client: httpx.Client, path: str, **params: Any) -> Any:
    return _json(client.get(path, params=params or None))


def _post(client: httpx.Client, path: str, payload: Any, *, expected: int = 200) -> Any:
    return _json(client.post(path, json=payload), expected=expected)


def _check(
    checks: list[GateCheck],
    ident: str,
    label: str,
    metric: str,
    fn: Callable[[], tuple[str, dict[str, Any]]],
) -> None:
    try:
        detail, evidence = fn()
    except AssertionError as error:
        checks.append(GateCheck(ident, label, "fail", metric, str(error)))
    except Exception as error:  # noqa: BLE001 - a gate must report, never crash
        checks.append(
            GateCheck(ident, label, "fail", metric, f"{type(error).__name__}: {error}")
        )
    else:
        checks.append(GateCheck(ident, label, "pass", metric, detail, evidence))


def _skip(checks: list[GateCheck], ident: str, label: str, metric: str, reason: str) -> None:
    checks.append(GateCheck(ident, label, "skip", metric, reason))


def run_release_gate(
    base_dir: Path,
    *,
    browser: bool = True,
    live: bool = False,
) -> ReleaseReport:
    """Run the complete Career acceptance journey and return its report."""
    base_dir = Path(base_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    checks: list[GateCheck] = []
    state: dict[str, Any] = {}

    with _LocalServer(base_dir) as server:
        client = server.client
        assert client is not None

        def health() -> tuple[str, dict[str, Any]]:
            payload = _get(client, "/api/career/health")
            _require(payload.get("automated_submission") is False, "soumission automatique annoncée")
            _require(
                payload.get("profile_imports", {}).get("review_required") is True,
                "l'import de profil ne demande pas de relecture",
            )
            _require(payload.get("mode") == "local par défaut", "mode local non annoncé")
            return "health local, aucune soumission automatique, relecture obligatoire", {
                "automated_submission": payload["automated_submission"],
            }

        _check(checks, "health_local_only", "Santé et absence de soumission", APP_VERIFIED, health)

        def profile_import() -> tuple[str, dict[str, Any]]:
            imported = _post(
                client,
                "/api/career/profile-imports/text",
                {
                    "source_kind": "cv",
                    "text": SYNTHETIC_PROFILE_TEXT,
                    "original_name": "profil-recette.txt",
                },
                expected=201,
            )
            _require(
                imported.get("status") in {"pending", "applied"},
                "l'import n'est ni en attente de relecture ni déjà appliqué",
            )
            detail = _get(client, f"/api/career/profile-imports/{imported['id']}")
            _require(bool(detail.get("preview")), "aucun aperçu de relecture")
            if imported.get("status") == "pending":
                updates = [
                    {"field": field, "value": value, "mode": "replace"}
                    for field, value in SYNTHETIC_PROFILE.items()
                ]
                applied = _post(
                    client,
                    f"/api/career/profile-imports/{imported['id']}/apply",
                    {
                        "updates": updates,
                        "base_profile_updated_at": imported.get("base_profile_updated_at", ""),
                    },
                )
                _require(
                    applied.get("profile_import", {}).get("status") == "applied",
                    "l'import n'a pas été appliqué après relecture",
                )
                profile = applied.get("profile") or {}
            else:
                # A repeated gate run reuses the same reviewed import instead
                # of silently accepting a new one.
                profile = _get(client, "/api/career/profile")
            _require(profile.get("display_name") == SYNTHETIC_PROFILE["display_name"], "profil non appliqué")
            state["profile_import_id"] = imported["id"]
            return "import texte -> relecture -> application explicite", {
                "import_id": imported["id"],
                "suggested_fields": len(imported.get("suggested_fields") or []),
            }

        _check(checks, "profile_import_review_apply", "Profil approuvé", APP_VERIFIED, profile_import)

        def eligibility() -> tuple[str, dict[str, Any]]:
            current = _get(client, "/api/career/profile")
            payload = {field: current.get(field, "") for field in SYNTHETIC_PROFILE}
            payload["eligibility"] = "compatible"
            updated = _json(client.put("/api/career/profile", json=payload))
            _require(updated.get("eligibility") == "compatible", "éligibilité non enregistrée")
            return "autorisation de travail déclarée explicitement", {"eligibility": "compatible"}

        _check(checks, "profile_eligibility", "Éligibilité déclarée", APP_VERIFIED, eligibility)

        def brief() -> tuple[str, dict[str, Any]]:
            saved = _json(client.put("/api/career/stage-search", json=BRIEF))
            _require(saved.get("configured") is True, "brief d'exploration non configuré")
            return "critères d'exploration enregistrés localement", {"configured": True}

        _check(checks, "search_brief", "Critères d'exploration", APP_VERIFIED, brief)

        def exploration() -> tuple[str, dict[str, Any]]:
            result = _post(client, "/api/career/stage-search/explore", {"force": True})
            outcomes = result.get("outcomes") or []
            statuses = {item.get("status") for item in outcomes}
            summary = result.get("summary") or {}
            _require("success" in statuses, "aucune source réussie")
            _require("partial" in statuses, "source partielle non signalée")
            _require("error" in statuses, "source indisponible non signalée")
            _require("unsupported" in statuses, "source sans connecteur non signalée")
            _require(summary.get("partial") is True, "le résumé ne signale pas un parcours partiel")
            _require(summary.get("sources_failed", 0) >= 1, "aucun échec de source compté")
            _require(summary.get("retained_count", 0) >= 1, "aucune offre retenue")
            _require(result.get("disclaimer"), "aucun avertissement d'absence d'envoi")
            state["exploration"] = result
            return (
                "succès + partiel + indisponible + non supporté, résultats conservés",
                {
                    "statuses": sorted(item for item in statuses if item),
                    "retained_count": summary.get("retained_count"),
                    "sources_failed": summary.get("sources_failed"),
                },
            )

        _check(checks, "exploration_sources", "Exploration multi-sources", APP_VERIFIED, exploration)

        def matching() -> tuple[str, dict[str, Any]]:
            jobs = _get(client, "/api/career/jobs", query="Synthetic Alpha")["jobs"]
            _require(len(jobs) >= 1, "les offres explorées ne sont pas persistées")
            state["job_id"] = jobs[0]["id"]
            matches = _get(client, "/api/career/stage-search/matches").get("matches") or []
            target = next(
                (item for item in matches if (item.get("job") or {}).get("id") == state["job_id"]),
                None,
            )
            _require(target is not None, "l'offre explorée n'est pas classée")
            _require(target.get("stage_match", {}).get("score") is not None, "aucun score de matching")
            job = _get(client, f"/api/career/jobs/{state['job_id']}")
            trust = (job.get("offer_intelligence") or {}).get("trust") or {}
            _require(trust.get("status") == "verified", "la source officielle de l'offre n'est pas vérifiée")
            return "offre explorée classée, source officielle vérifiée", {
                "job_id": state["job_id"],
                "score_present": True,
                "source_trust": trust.get("status"),
            }

        _check(checks, "matching", "Matching", APP_VERIFIED, matching)

        def dedup() -> tuple[str, dict[str, Any]]:
            payload = _synthetic_job(
                company="Synthetic Dedup Bank",
                title="M&A Internship — Dedup",
                slug="dedup-ma",
                source_name="manual",
                source_id="dedup-1",
            )
            first = _post(client, "/api/career/jobs/import", payload, expected=201)
            second = _post(client, "/api/career/jobs/import", payload, expected=201)
            _require(first["id"] == second["id"], "un doublon a été créé")
            _require(second.get("duplicate") is True, "le doublon n'est pas signalé")
            _post(
                client,
                f"/api/career/jobs/{first['id']}/shortlist",
                {"shortlisted": True, "note": "Note locale conservée"},
            )
            third = _post(client, "/api/career/jobs/import", payload, expected=201)
            kept = _get(client, f"/api/career/jobs/{third['id']}")
            _require(kept.get("shortlisted") is True, "la sélection a été écrasée par la réimportation")
            _require(kept.get("personal_note") == "Note locale conservée", "la note a été écrasée")
            state["dedup_job_id"] = first["id"]
            return "réimport idempotent, sélection et note conservées", {"job_id": first["id"]}

        _check(checks, "dedup_reimport", "Déduplication et état utilisateur", APP_VERIFIED, dedup)

        def adversarial() -> tuple[str, dict[str, Any]]:
            contradictory = _post(
                client,
                "/api/career/jobs/import",
                {
                    "company": "Synthetic Contradiction Bank",
                    "title": "Finance Internship",
                    "official_url": "https://careers.example.test/contradictory",
                    "source_status": "open",
                    "employment_type": "Internship",
                    "description_original": "This is an internship. Contract: permanent.",
                },
                expected=201,
            )
            expired = _post(
                client,
                "/api/career/jobs/import",
                {
                    "company": "Synthetic Expired Bank",
                    "title": "M&A Internship",
                    "official_url": "https://careers.example.test/expired",
                    "source_status": "open",
                    "deadline_date": "2020-01-01",
                    "employment_type": "Internship",
                    "description_original": "This is an internship in mergers and acquisitions.",
                },
                expected=201,
            )
            undated = _post(
                client,
                "/api/career/jobs/import",
                {
                    "company": "Synthetic Undated Bank",
                    "title": "M&A Internship",
                    "official_url": "https://careers.example.test/undated",
                    "employment_type": "Internship",
                    "description_original": "This is an internship in mergers and acquisitions.",
                },
                expected=201,
            )
            contradictory_job = _get(client, f"/api/career/jobs/{contradictory['id']}")
            expired_job = _get(client, f"/api/career/jobs/{expired['id']}")
            undated_job = _get(client, f"/api/career/jobs/{undated['id']}")
            contradiction = (
                (contradictory_job.get("offer_intelligence") or {}).get("qualifications") or {}
            )
            _require(
                contradiction.get("contract_type") in {"ambiguous", "permanent"},
                "une offre contradictoire a été présentée comme un stage certain",
            )
            _require(expired_job.get("deadline_status") == "closed", "une offre expirée n'est pas close")
            undated = (undated_job.get("offer_intelligence") or {}).get("qualifications") or {}
            _require(
                undated.get("verification_status") == "unverified",
                "une offre sans date est présentée comme vérifiée",
            )
            _require(bool(undated.get("missing_fields")), "les faits manquants ne sont pas listés")
            return "contradictoire, expirée et sans date restent prudentes", {
                "contradictory_contract": contradiction.get("contract_type"),
                "expired_status": expired_job.get("deadline_status"),
                "undated_verification": undated.get("verification_status"),
            }

        _check(checks, "adversarial_offers", "Offres contradictoires / expirées / sans date", APP_VERIFIED, adversarial)

        def prep() -> tuple[str, dict[str, Any]]:
            payload = _get(client, f"/api/career/jobs/{state['job_id']}/prep")
            _require(payload.get("recommended_variant"), "aucune variante recommandée")
            _require(payload.get("variant_coverage"), "aucune couverture de variantes")
            _require(isinstance(payload.get("gaps"), list), "aucun écart de CV")
            _require(payload.get("automatic_submission") is False, "la préparation annonce un envoi")
            return "variante, couverture et écarts calculés localement", {
                "variant": payload.get("recommended_variant"),
                "gaps": len(payload.get("gaps") or []),
            }

        _check(checks, "job_prep", "Fiche et adaptation CV", APP_VERIFIED, prep)

        def apply_kit() -> tuple[str, dict[str, Any]]:
            kit = _post(client, f"/api/career/apply-kit/{state['job_id']}", {"language": "fr"})
            export_urls = kit.get("export_urls") or {}
            _require(kit.get("letter"), "aucune lettre générée")
            _require(kit.get("variant"), "aucune variante dans le kit")
            _require(bool(kit.get("checklist")), "aucune checklist de kit")
            _require(
                any(item.get("id") == "submit" and item.get("done") is False for item in kit["checklist"]),
                "la checklist ne rappelle pas l'action manuelle",
            )
            _require("cv_pdf" in export_urls and "letter_pdf" in export_urls, "exports PDF manquants")
            _require("cv_docx" in export_urls or "letter_docx" in export_urls, "export DOCX manquant")
            downloads = 0
            for key in ("cv_pdf", "letter_pdf", "letter_docx"):
                if key not in export_urls:
                    continue
                response = client.get(export_urls[key])
                _require(response.status_code == 200, f"téléchargement {key} échoué")
                _require(len(response.content) > 100, f"téléchargement {key} vide")
                if key.endswith("pdf"):
                    _require(response.content.startswith(b"%PDF"), f"{key} n'est pas un PDF")
                else:
                    _require(response.content.startswith(b"PK"), f"{key} n'est pas un DOCX")
                downloads += 1
            _require(downloads >= 3, "moins de trois documents téléchargeables")
            state["kit_export_urls"] = export_urls
            return "kit prêt à relire, checklist manuelle, trois téléchargements valides", {
                "downloads": downloads,
                "readiness": kit.get("readiness"),
            }

        _check(checks, "apply_kit_downloads", "Kit de candidature et exports", APP_VERIFIED, apply_kit)

        def pipeline() -> tuple[str, dict[str, Any]]:
            payload = _get(client, "/api/career/application-pipeline")
            _require(payload.get("automatic_submission") is False, "pipeline avec envoi automatique")
            item = next(
                (row for row in payload.get("pipeline") or [] if row.get("job_id") == state["job_id"]),
                None,
            )
            _require(item is not None, "le suivi du kit est absent du pipeline")
            _require(item.get("kit_ready") is True, "le pipeline ne voit pas le kit")
            return "pipeline local dérivé du kit", {
                "stage": item.get("stage"),
                "next_action_code": item.get("next_action_code"),
            }

        _check(checks, "pipeline", "Pipeline local", APP_VERIFIED, pipeline)

        def tracking() -> tuple[str, dict[str, Any]]:
            application = _post(
                client, "/api/career/applications", {"job_id": state["job_id"]}, expected=201
            )
            state["application_id"] = application["id"]
            if application.get("receipt_status") == "confirmed":
                # Repeated gate run: receipt already confirmed, so approval
                # cannot be replayed; the earlier explicit approval is kept.
                approved = application
            else:
                approved = _post(
                    client,
                    f"/api/career/applications/{application['id']}/approve",
                    {"approved": True, "note": "Dépôt manuel approuvé"},
                )
            _require(approved.get("approval_granted") is True, "approbation manuelle non enregistrée")
            checklist = _post(
                client,
                f"/api/career/applications/{application['id']}/checklist",
                {"checked": ["cv_reviewed", "letter_customized", "documents_checked"]},
            )
            _require(
                checklist.get("checklist", {}).get("checked_keys")
                == ["cv_reviewed", "documents_checked", "letter_customized"],
                "checklist locale non enregistrée",
            )
            return "suivi créé, dépôt manuel approuvé, checklist cochée", {
                "application_id": application["id"]
            }

        _check(checks, "tracking_approval_checklist", "Suivi et approbation manuelle", APP_VERIFIED, tracking)

        def receipt_and_radar() -> tuple[str, dict[str, Any]]:
            before = _get(client, "/api/career/applications/dashboard")
            entry = next(
                (row for row in before.get("entries") or [] if row.get("application_id") == state["application_id"]),
                None,
            )
            _require(entry is not None, "la candidature approuvée n'apparaît pas au tableau de bord")
            if entry.get("receipt_status") == "confirmed":
                # Repeated gate run: the receipt is already recorded, and no
                # second confirmation may overwrite it.
                confirmed = _get(
                    client, f"/api/career/applications/{state['application_id']}"
                )
            else:
                confirmed = _post(
                    client,
                    f"/api/career/applications/{state['application_id']}/confirm-receipt",
                    {"confirmation_reference": "RECETTE-SYNTHETIQUE-001"},
                )
            _require(confirmed.get("receipt_status") == "confirmed", "réception non confirmée")
            after = _get(client, "/api/career/applications/dashboard")
            entry = next(
                (row for row in after.get("entries") or [] if row.get("application_id") == state["application_id"]),
                None,
            )
            _require(entry is not None, "candidature absente après confirmation")
            _require(entry.get("receipt_status") == "confirmed", "tableau de bord non mis à jour")
            _require(entry.get("sent_declared") is True, "un dépôt confirmé n'est pas déclaré")
            _require("jamais un envoi" in (after.get("honesty") or ""), "note d'honnêteté absente")
            radar = after.get("radar") or []
            _require(all(item.get("is_email") is False for item in radar), "relance assimilée à un e-mail")
            return "réception confirmée par référence, radar de relance purement local", {
                "radar_items": len(radar),
                "receipt_status": "confirmed",
            }

        _check(checks, "receipt_followup_radar", "Réception et relance", APP_VERIFIED, receipt_and_radar)

        def interview() -> tuple[str, dict[str, Any]]:
            session = _post(
                client,
                "/api/career/interview-sessions",
                {
                    "mode": "technical",
                    "difficulty": "intermediate",
                    "language": "fr",
                    "application_id": state["application_id"],
                },
                expected=201,
            )
            _require(session.get("current_question"), "aucune question d'entretien")
            answered = _post(
                client,
                f"/api/career/interview-sessions/{session['id']}/answers",
                {"answer": "J'ai construit un modèle DCF et défendu mes hypothèses."},
            )
            _require(len(answered.get("turns") or []) == 1, "réponse non enregistrée")
            completed = _post(
                client, f"/api/career/interview-sessions/{session['id']}/complete", {}
            )
            _require(completed.get("status") == "completed", "séance non terminée")
            state["interview_id"] = session["id"]
            return "séance locale, retour et clôture", {"turns": 1}

        _check(checks, "interview_coach", "Préparation entretien", APP_VERIFIED, interview)

        def no_hidden_send() -> tuple[str, dict[str, Any]]:
            pipeline_payload = _get(client, "/api/career/application-pipeline")
            dashboard = _get(client, "/api/career/applications/dashboard")
            _require(pipeline_payload.get("automatic_submission") is False, "envoi automatique détecté")
            _require(dashboard.get("totals", {}).get("sent_declared", 0) >= 1, "aucun envoi déclaré")
            return "aucun envoi automatique ; seul un dépôt déclaré existe", {
                "sent_declared": dashboard.get("totals", {}).get("sent_declared"),
            }

        _check(checks, "no_hidden_send", "Barrière anti-envoi", APP_VERIFIED, no_hidden_send)

        if browser:
            def browser_smoke() -> tuple[str, dict[str, Any]]:
                try:
                    from playwright.sync_api import sync_playwright
                except Exception as error:  # noqa: BLE001
                    raise AssertionError(f"Playwright indisponible : {type(error).__name__}") from error
                try:
                    with sync_playwright() as playwright:
                        launched = playwright.chromium.launch(headless=True)
                        page = launched.new_page()
                        errors: list[str] = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(f"{server.base_url}/career", wait_until="networkidle", timeout=20_000)
                        page.wait_for_selector("h1", state="visible", timeout=10_000)
                        title = page.title()
                        heading = page.inner_text("h1")
                        # A real user action: open the Stage Hunter view from
                        # the dashboard instead of only loading HTML.
                        page.click('[data-view-action="stagehunter"]')
                        page.wait_for_selector("#stagehunter-title", state="visible", timeout=10_000)
                        panel = page.inner_text("#stagehunter-title")
                        launched.close()
                except AssertionError:
                    raise
                except Exception as error:  # noqa: BLE001
                    raise AssertionError(
                        f"navigateur réel indisponible : {type(error).__name__}: {error}"
                    ) from error
                _require("Career" in title, "titre de page inattendu")
                _require("Career" in heading, "en-tête Career non rendu")
                _require("Stage Hunter" in panel, "panneau Stage Hunter non rendu après action")
                _require(not errors, f"erreurs JavaScript : {errors[:3]}")
                return "page Career rendue dans Chromium, panneau Stage Hunter ouvert par action", {
                    "title": title,
                    "panel": panel,
                    "page_errors": 0,
                }

            _check(checks, "browser_smoke", "Navigateur réel", APP_VERIFIED, browser_smoke)
        else:
            _skip(
                checks,
                "browser_smoke",
                "Navigateur réel",
                APP_VERIFIED,
                "désactivé explicitement (--no-browser) : aucune preuve navigateur revendiquée",
            )

    # Restart on the same data directory, then prove persistence through HTTP.
    with _LocalServer(base_dir) as restarted:
        client = restarted.client
        assert client is not None

        def persistence() -> tuple[str, dict[str, Any]]:
            job = _get(client, f"/api/career/jobs/{state['job_id']}")
            application = _get(client, f"/api/career/applications/{state['application_id']}")
            interview = _get(client, f"/api/career/interview-sessions/{state['interview_id']}")
            _require(job.get("id") == state["job_id"], "offre perdue au redémarrage")
            _require(application.get("receipt_status") == "confirmed", "candidature perdue au redémarrage")
            _require(interview.get("status") == "completed", "entretien perdu au redémarrage")
            return "offre, candidature et entretien retrouvés après redémarrage", {
                "job_id": state["job_id"],
                "application_id": state["application_id"],
            }

        _check(checks, "restart_persistence", "Persistance après redémarrage", APP_VERIFIED, persistence)

        def offline_reads() -> tuple[str, dict[str, Any]]:
            _require(restarted.base_url.startswith("http://127.0.0.1:"), "serveur non local")
            profile = _get(client, "/api/career/profile")
            dashboard = _get(client, "/api/career/applications/dashboard")
            _require(profile.get("display_name") == SYNTHETIC_PROFILE["display_name"], "profil illisible hors ligne")
            _require(dashboard.get("totals", {}).get("total", 0) >= 1, "candidatures illisibles hors ligne")
            return "lectures locales complètes sans source externe", {
                "applications": dashboard.get("totals", {}).get("total"),
            }

        _check(checks, "offline_reads", "Fonctionnement hors ligne", APP_VERIFIED, offline_reads)

    def privacy() -> tuple[str, dict[str, Any]]:
        text = json.dumps([asdict(check) for check in checks], ensure_ascii=False)
        forbidden = (
            SYNTHETIC_PROFILE["contact_email"],
            SYNTHETIC_PROFILE["contact_phone"],
            "RECETTE-SYNTHETIQUE-001",
        )
        leaked = [value for value in forbidden if value and value in text]
        _require(not leaked, f"données privées dans le rapport : {leaked}")
        _require("[ERREUR" not in text, "erreur brute dans le rapport")
        return "aucune coordonnée ni référence privée dans le rapport", {"checked": len(forbidden)}

    _check(checks, "privacy_scan", "Rapport sans données privées", APP_VERIFIED, privacy)

    if live:
        def live_source() -> tuple[str, dict[str, Any]]:
            started = time.monotonic()
            response = httpx.get(
                "https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
                timeout=15.0,
                follow_redirects=False,
            )
            _require(response.status_code == 200, f"source publique -> {response.status_code}")
            payload = response.json()
            _require(isinstance(payload.get("jobs"), list), "réponse publique invalide")
            return "source publique joignable (aucune offre importée par ce check)", {
                "status": response.status_code,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }

        _check(checks, "live_public_source", "Source publique réelle", LIVE, live_source)
    else:
        _skip(
            checks,
            "live_public_source",
            "Source publique réelle",
            LIVE,
            "non demandée : aucune mesure live revendiquée (relancer avec --live)",
        )

    return ReleaseReport(checks=checks, generated_at=date.today().isoformat())


def render_report(report: ReleaseReport, *, as_json: bool = False) -> str:
    return report.to_json() if as_json else report.to_markdown()


__all__ = [
    "APP_VERIFIED",
    "LIVE",
    "SYNTHETIC",
    "UNMEASURED",
    "GateCheck",
    "ReleaseReport",
    "render_report",
    "run_release_gate",
]
