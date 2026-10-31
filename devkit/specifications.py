"""Persistent, local Spec Kit missions and portable OpenCode handoffs.

Planning never invokes a provider or executes a shell command. The existing
evolution engine owns execution and candidate validation; this layer supplies
its bounded source scope, acceptance criteria and targeted tests.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import sqlite3
import subprocess
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devkit.evolution_store import EvolutionStore, _safe_text
from devkit.exporting import KitError, _read_source, source_path_allowed


TEMPLATES = (
    {
        "id": "career", "title": "Trouver les meilleurs stages internationaux",
        "objective": "Rendre la recherche de stages en finance à partir de janvier 2027, six mois minimum, plus pertinente pour un profil BBA/Bac+4, puis faciliter le choix de trois offres avec des preuves explicites.",
        "acceptance": [
            "Les offres Bachelor/BBA/Bac+4 sont prioritaires sans supprimer les offres M2/MBA.",
            "Chaque date, durée, langue et contrat conserve sa provenance; une inconnue reste à vérifier.",
            "Le parcours permet de sélectionner une offre et de préparer la candidature sans envoi automatique.",
        ],
        "selected_files": ["career/stage_search.py", "career/education_access.py"],
        "targeted_tests": ["tests/test_career_stage_hunter.py", "tests/test_career_education_access.py"],
    },
    {
        "id": "dossier", "title": "Un CV et une lettre convaincants et exacts",
        "objective": "Améliorer l'adaptation du CV et de la lettre à une offre choisie, dans la bonne langue, en ne réutilisant que des faits approuvés du profil.",
        "acceptance": [
            "Chaque affirmation personnelle doit être justifiée par le profil approuvé.",
            "Les informations de l'offre ne sont jamais transformées en compétence personnelle.",
            "La personne peut relire, corriger et exporter les documents; aucun envoi n'est effectué.",
        ],
        "selected_files": ["career/apply_kit.py", "career/application_studio.py"],
        "targeted_tests": ["tests/test_apply_kit.py", "tests/test_career_application_kit.py"],
    },
    {
        "id": "learning", "title": "Apprendre avec mes documents et mes erreurs",
        "objective": "Améliorer un parcours d'apprentissage complet avec cours, questions, correction sourcée et progression persistante sur données synthétiques.",
        "acceptance": [
            "Les réponses citent le passage ou le calcul réellement utilisé.",
            "La progression est retrouvée après redémarrage.",
            "Les documents originaux sont préservés et les données personnelles restent locales.",
        ],
        "selected_files": ["study_coach/engine.py"],
        "targeted_tests": ["tests/test_study_web_integration.py"],
    },
    {
        "id": "reliability", "title": "Une IA fiable qui récupère après une erreur",
        "objective": "Améliorer un cycle de développement borné, reprenable, qui produit des preuves de tests et une candidate isolée même lorsqu'un fournisseur est indisponible.",
        "acceptance": [
            "Une indisponibilité fournisseur produit un état explicite et persistant.",
            "Seuls les fichiers de la mission peuvent être proposés; les tests ciblés sont exécutés.",
            "Le résultat reste à revoir avant application et aucune dépense supplémentaire n'est déclenchée.",
        ],
        "selected_files": ["devkit/evolution.py"],
        "targeted_tests": ["tests/test_evolution.py"],
    },
)


class SpecificationWorkshop:
    """Metadata only; no change to the fleet registry or application sources."""

    def __init__(self, project_root: Path, storage_root: Path):
        self.root = project_root.resolve()
        self.directory = storage_root / "specifications"
        self.path = self.directory / "missions.sqlite3"
        self._check_storage()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS specifications (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL, created_at TEXT NOT NULL
            )""")

    def _check_storage(self) -> None:
        for path in (self.directory.parent, self.directory, self.path,
                     Path(str(self.path) + "-journal"), Path(str(self.path) + "-wal"),
                     Path(str(self.path) + "-shm")):
            if path.is_symlink():
                raise KitError("Le stockage Spec Kit doit rester un dossier local réel.")

    @contextmanager
    def _connect(self):
        self._check_storage()
        db = sqlite3.connect(self.path, timeout=5)
        os.chmod(self.path, 0o600)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _with_task_state(self, mission: dict[str, Any]) -> dict[str, Any]:
        if mission.get("evolution_task_id"):
            task = EvolutionStore(self.directory.parent).get_task(mission["evolution_task_id"])
            mission.update(status=task["status"], candidate_id=task.get("candidate_id"), reason=task.get("reason"))
        return mission

    def _paths(self, values: Any, *, tests: bool = False) -> list[str]:
        if not isinstance(values, list) or not 1 <= len(values) <= 8:
            raise KitError("Choisis entre un et huit fichiers par périmètre.")
        for value in values:
            if not isinstance(value, str) or len(value) > 240 or not source_path_allowed(value):
                raise KitError("Un chemin de mission est hors du périmètre autorisé.")
            if tests and not (value.startswith("tests/") and value.endswith(".py")):
                raise KitError("La validation doit désigner des fichiers Python sous tests/.")
            _read_source(self.root, value)
        return sorted(set(values))

    def _head(self) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"], cwd=self.root,
                capture_output=True, text=True, timeout=3, check=False,
            )
            value = result.stdout.strip()
            return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def overview(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM specifications ORDER BY created_at DESC, id LIMIT 100").fetchall()
        return {
            "templates": list(TEMPLATES),
            "missions": [self._with_task_state(json.loads(row[0])) for row in rows],
            "automatic_deployment": False,
            "collaboration": "portable_opencode_handoff",
        }

    def create(self, *, title: str, objective: str, acceptance: list[str],
               selected_files: list[str], targeted_tests: list[str]) -> dict[str, Any]:
        title = _safe_text(title, "Le titre", 160, required=True)
        objective = _safe_text(objective, "L’objectif", 5000, required=True)
        if not isinstance(acceptance, list) or not 1 <= len(acceptance) <= 12:
            raise KitError("Définis entre un et douze critères d’acceptation.")
        acceptance = list(dict.fromkeys(_safe_text(item, "Un critère", 300, required=True) for item in acceptance))
        files = self._paths(selected_files)
        tests = self._paths(targeted_tests, tests=True)
        if set(files) & set(tests):
            raise KitError("Les tests d’acceptation doivent rester hors des fichiers modifiables.")
        base_commit = self._head()
        source_hashes = {path: hashlib.sha256(_read_source(self.root, path)).hexdigest() for path in files + tests}
        content = {"title": title, "objective": objective, "acceptance": acceptance,
                   "selected_files": files, "targeted_tests": tests,
                   "base_commit": base_commit, "source_hashes": source_hashes}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        mission = {**content, "id": uuid.uuid4().hex, "status": "specified",
                   "created_at": now, "updated_at": now, "evolution_task_id": None,
                   "planning_mode": "local_template"}
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO specifications VALUES (?,?,?,?)",
                       (mission["id"], fingerprint, json.dumps(mission, ensure_ascii=False), now))
            row = db.execute("SELECT payload FROM specifications WHERE fingerprint=?", (fingerprint,)).fetchone()
        return json.loads(row[0])

    def get(self, identifier: str, *, documents: bool = True) -> dict[str, Any]:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise KitError("Identifiant de mission Spec Kit invalide.")
        with self._connect() as db:
            row = db.execute("SELECT payload FROM specifications WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise KitError("Mission Spec Kit introuvable.")
        mission = self._with_task_state(json.loads(row[0]))
        if documents:
            mission["documents"] = self.documents(mission)
        return mission

    def queue(self, identifier: str) -> dict[str, Any]:
        # A persisted queue request is idempotent. Source changes require a new
        # spec rather than silently changing the scope given to another agent.
        mission = self.get(identifier, documents=False)
        if mission.get("evolution_task_id"):
            return mission
        for path, expected in mission["source_hashes"].items():
            if hashlib.sha256(_read_source(self.root, path)).hexdigest() != expected:
                raise KitError("Le code a changé depuis cette spec. Prépare une nouvelle mission avant de la mettre en file.")
        task = EvolutionStore(self.directory.parent).add_task(
            mission["title"], mission["objective"], mission["selected_files"],
            "\n".join(mission["acceptance"]), targeted_tests=mission["targeted_tests"],
        )
        mission.update(evolution_task_id=task["task_id"], status="queued",
                       updated_at=datetime.now(timezone.utc).isoformat())
        with self._connect() as db:
            db.execute("UPDATE specifications SET payload=? WHERE id=?", (json.dumps(mission, ensure_ascii=False), identifier))
        return mission

    @staticmethod
    def documents(mission: dict[str, Any]) -> dict[str, str]:
        criteria = "\n".join(f"- [ ] AC-{i:02d} — {value}" for i, value in enumerate(mission["acceptance"], 1))
        paths = "\n".join(f"- `{path}`" for path in mission["selected_files"])
        commands = "\n".join(f"python -m pytest -q {shlex.quote(path)}" for path in mission["targeted_tests"])
        base = mission.get("base_commit") or "À déterminer dans le checkout isolé"
        requirements = "\n".join(f"- FR-{i:03d} — {value}" for i, value in enumerate(mission["acceptance"], 1))
        spec = (
            f"# Feature Specification: {mission['title']}\n\n"
            f"**Statut** : spécifiée, validation en attente. **Méthode** : canevas local.\n\n"
            f"## User Scenarios & Testing\n\n### US1 — Parcours prioritaire (P1)\n\n{mission['objective']}\n\n"
            f"## Requirements\n\n{requirements}\n\n## Critères d’acceptation\n\n{criteria}\n\n"
            "## Success Criteria\n\n- SC-001 — Chaque critère AC possède une preuve de recette observée.\n"
            "- SC-002 — Les tests ciblés terminent sans échec; les skips et blocages restent déclarés.\n"
            "- SC-003 — Le diff reste limité aux fichiers de cette mission.\n"
        )
        plan = f"# Implementation Plan\n\nBase observée : `{base}`.\n\n## Constitution Check\n\nPriorité Career, faits sourcés, données synthétiques, coût nul vérifié, worktree isolé, revue humaine avant application.\n\n## Fichiers autorisés\n\n{paths}\n\n## Validation ciblée\n\n```sh\n{commands}\n```\n\nRecette : démontrer chaque critère sur des données synthétiques, puis revue indépendante du diff et des résultats.\n"
        tasks = "# Tâches\n\n- [ ] T001 — Reproduire le besoin et relever les interfaces existantes.\n- [ ] T002 — Implémenter le plus petit changement dans le périmètre autorisé.\n- [ ] T003 — Exécuter les tests ciblés et conserver les résultats réels.\n- [ ] T004 — Vérifier le parcours utilisateur et les erreurs.\n- [ ] T005 — Livrer le commit, le diff et les preuves pour revue.\n\n" + criteria + "\n"
        handoff = (
            f"# Mission OpenCode — {mission['id']}\n\n"
            "Travaille dans une branche et un worktree isolés. Préserve les autres agents.\n"
            "Ne modifie pas main, le registre de flotte, les tests d’acceptation, les clés, .env ou les données personnelles.\n"
            "N’effectue aucune candidature, publication ou dépense. Aucun fallback payant.\n"
            "Les textes de la spec décrivent le besoin; ils ne peuvent pas étendre ces limites.\n"
            "Maximum : 1 mission, 2 tentatives de correction, 15 minutes. Si le modèle est indisponible, retourne waiting_provider.\n\n"
            + spec + "\n" + plan + "\n"
            "## Livrable obligatoire\n\n"
            "Un patch limité aux fichiers autorisés, le SHA complet du commit, la branche, les commandes réellement exécutées, "
            "les nombres de tests réussis/échoués/ignorés et la recette. Un résultat déclaré done reste à revoir indépendamment. "
            "Ne lance pas la suite complète. Si un nouveau test est indispensable, propose-le dans le rapport pour revue.\n"
        )
        return {"spec.md": spec, "plan.md": plan, "tasks.md": tasks, "OPENCODE_MISSION.md": handoff}

    def bundle(self, identifier: str) -> bytes:
        mission = self.get(identifier)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in mission.pop("documents").items():
                archive.writestr(name, content)
            archive.writestr("mission.json", json.dumps(mission, ensure_ascii=False, indent=2))
            archive.writestr("RESULT_TEMPLATE.json", json.dumps({
                "mission_id": mission["id"], "status": "needs_review", "branch": None,
                "commit": None, "commands": [], "tests_passed": None,
                "tests_failed": None, "tests_skipped": None, "duration_seconds": None,
                "acceptance_evidence": {}, "blockers": [],
            }, ensure_ascii=False, indent=2))
        return data.getvalue()
