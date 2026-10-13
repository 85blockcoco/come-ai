"""Bounded, local-first orchestration for the first Côme AI 5.0 vertical slice.

This is deliberately *not* a general code agent.  It turns a small set of
user intents into a short, inspectable plan and can invoke only the existing
controlled workspace tools and the local personal-memory service.  A remote
model can later propose a plan, but this executor remains the enforcement
point: opaque workspace IDs, bounded steps, explicit write confirmation and no
shell/Python/filesystem tool are exposed here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from workspace_core import LocalTools, UserFacingError, Workspace, to_jsonable


MAX_ORCHESTRATOR_MESSAGE_CHARS = 12_000
MAX_ORCHESTRATOR_FILES = 4
MAX_ORCHESTRATOR_STEPS = 6
MAX_MEMORY_RESULTS = 8


class PersonalMemoryPort(Protocol):
    """The narrow local-memory interface used by the executor.

    Keeping this protocol small makes it possible to test orchestration without
    a database and prevents the chat layer from gaining raw database access.
    """

    def import_file(
        self,
        path: Any,
        *,
        project_id: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]: ...

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        limit: int = MAX_MEMORY_RESULTS,
    ) -> Any: ...


@dataclass(frozen=True)
class PlanStep:
    """A serial, user-visible action in the local plan."""

    step_id: str
    tool: str
    label: str
    arguments: dict[str, Any]
    requires_confirmation: bool = False


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _query_from_message(message: str) -> str:
    """Get a conservative memory-search phrase without interpreting a prompt.

    A quoted phrase wins.  Otherwise only well-known request words are removed;
    the result is still sent to FTS as data, never executed as SQL.
    """

    quoted = re.search(r"[\"«]([^\"»]{2,240})[\"»]", message)
    if quoted:
        return quoted.group(1).strip()
    stripped = re.sub(
        r"\b(cherche|recherche|trouve|retrouve|dans|la|le|les|mes|ma|mon|"
        r"memoire|mémoire|notes?|documents?|document|s il te plait|svp|please)\b",
        " ",
        message,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", stripped).strip(" .,:;!?-")[:240]


class LocalOrchestrator:
    """Build and run short local plans over existing controlled services."""

    def __init__(
        self,
        workspace: Workspace,
        tools: LocalTools,
        memory: PersonalMemoryPort | None = None,
    ) -> None:
        self.workspace = workspace
        self.tools = tools
        self.memory = memory

    def build_plan(
        self,
        message: str,
        *,
        selected_file_ids: list[str] | None = None,
        allow_write: bool = False,
        memory_project_id: str | None = None,
        memory_query: str | None = None,
    ) -> list[PlanStep]:
        cleaned = self._validate_message(message)
        file_ids = self._validated_file_ids(selected_file_ids or [])
        folded = _fold(cleaned)
        wants_analysis = _contains_any(
            folded,
            ("analyse", "analys", "statistique", "finance", "financier", "anomal", "tableau"),
        )
        wants_inspection = wants_analysis or _contains_any(
            folded,
            ("inspect", "structure", "colonnes", "colonnes", "feuille", "valeurs manquantes"),
        )
        wants_report = _contains_any(
            folded,
            ("rapport", "export", "classeur", "fichier resultat", "fichier de resultat"),
        )
        wants_memory_import = _contains_any(
            folded,
            ("index", "memorise", "memoriser", "ajoute a la memoire", "ajouter a la memoire"),
        )
        inferred_query = (memory_query or "").strip() or _query_from_message(cleaned)
        wants_memory_search = bool(memory_query and memory_query.strip()) or (
            not file_ids
            and _contains_any(folded, ("cherche", "recherche", "trouve", "retrouve", "memoire", "souvenir"))
        )

        plan: list[PlanStep] = []
        for index, file_id in enumerate(file_ids):
            suffix = "" if len(file_ids) == 1 else f" ({index + 1}/{len(file_ids)})"
            if wants_inspection or wants_analysis or wants_report or wants_memory_import:
                plan.append(
                    PlanStep(
                        step_id=f"inspect-{index + 1}",
                        tool="inspect_file",
                        label=f"Inspecter le fichier sélectionné{suffix}",
                        arguments={"file_id": file_id},
                    )
                )
            if wants_analysis or wants_report:
                plan.append(
                    PlanStep(
                        step_id=f"analyze-{index + 1}",
                        tool="analyze_table",
                        label=f"Calculer les statistiques locales{suffix}",
                        arguments={"file_id": file_id, "sheet_name": ""},
                    )
                )
            if wants_memory_import:
                plan.append(
                    PlanStep(
                        step_id=f"memory-import-{index + 1}",
                        tool="index_memory",
                        label=f"Indexer le document dans la mémoire locale{suffix}",
                        arguments={"file_id": file_id, "project_id": memory_project_id},
                    )
                )
            if wants_report:
                plan.append(
                    PlanStep(
                        step_id=f"report-{index + 1}",
                        tool="create_analysis_workbook",
                        label=f"Créer un rapport Excel{suffix}",
                        arguments={"file_id": file_id, "sheet_name": ""},
                        requires_confirmation=True,
                    )
                )

        if wants_memory_search and inferred_query:
            plan.append(
                PlanStep(
                    step_id="memory-search",
                    tool="search_memory",
                    label="Rechercher dans la mémoire locale",
                    arguments={"query": inferred_query, "project_id": memory_project_id},
                )
            )

        if not plan:
            # A safe, useful fallback: show the chosen file's shape rather than
            # hallucinating that an ambiguous instruction was completed.
            if file_ids:
                plan.append(
                    PlanStep(
                        step_id="inspect-1",
                        tool="inspect_file",
                        label="Inspecter le fichier sélectionné",
                        arguments={"file_id": file_ids[0]},
                    )
                )
            elif wants_memory_search:
                raise UserFacingError("Indique un mot ou une expression à rechercher dans la mémoire.")
            else:
                raise UserFacingError(
                    "Choisis un document ou formule une action locale précise : analyser, rechercher, indexer ou créer un rapport."
                )
        if len(plan) > MAX_ORCHESTRATOR_STEPS:
            raise UserFacingError(
                f"Cette demande dépasse la limite de {MAX_ORCHESTRATOR_STEPS} étapes locales. Sélectionne moins de fichiers."
            )
        # The execution layer, not a prompt, has final authority over writes.
        if not allow_write:
            return plan
        return plan

    def run(
        self,
        message: str,
        *,
        selected_file_ids: list[str] | None = None,
        allow_write: bool = False,
        memory_project_id: str | None = None,
        memory_query: str | None = None,
        progress: Any | None = None,
        is_cancelled: Any | None = None,
    ) -> dict[str, Any]:
        """Execute a plan serially, reporting bounded events and no raw paths."""

        plan = self.build_plan(
            message,
            selected_file_ids=selected_file_ids,
            allow_write=allow_write,
            memory_project_id=memory_project_id,
            memory_query=memory_query,
        )
        events: list[dict[str, Any]] = []
        inspected: dict[str, dict[str, Any]] = {}
        analyses: dict[str, dict[str, Any]] = {}
        total = len(plan)

        for position, step in enumerate(plan, start=1):
            if callable(is_cancelled) and is_cancelled():
                events.append(self._event(step, "cancelled", "Tâche annulée avant cette étape."))
                break
            if callable(progress):
                progress((position - 1) / total, step.label)
            event = self._execute_step(
                step,
                inspected=inspected,
                analyses=analyses,
                allow_write=allow_write,
            )
            events.append(event)
            if callable(progress):
                progress(position / total, event["message"])

        citations = self._citations_from_events(events)
        answer = self._answer_from_events(events, allow_write=allow_write)
        return {
            "mode": "orchestrateur local V5",
            "remote_model_used": False,
            "plan": [asdict(item) for item in plan],
            "events": events,
            "citations": citations,
            "answer": answer,
        }

    def _execute_step(
        self,
        step: PlanStep,
        *,
        inspected: dict[str, dict[str, Any]],
        analyses: dict[str, dict[str, Any]],
        allow_write: bool,
    ) -> dict[str, Any]:
        file_id = str(step.arguments.get("file_id", ""))
        try:
            if step.tool == "inspect_file":
                result = to_jsonable(self.tools.inspect_file(file_id))
                inspected[file_id] = result
                return self._event(step, "done", self._inspect_message(result), result)
            if step.tool == "analyze_table":
                source = inspected.get(file_id)
                if source and source.get("kind") not in {"table", "spreadsheet"}:
                    return self._event(
                        step,
                        "skipped",
                        "Ce document n’est pas un tableau Excel/CSV : statistiques ignorées.",
                    )
                result = to_jsonable(self.tools.analyze_table(file_id, str(step.arguments.get("sheet_name", ""))))
                analyses[file_id] = result
                return self._event(step, "done", self._analysis_message(result), result)
            if step.tool == "create_analysis_workbook":
                if not allow_write:
                    return self._event(
                        step,
                        "needs_confirmation",
                        "Rapport non créé : active la confirmation de création pour cette demande.",
                    )
                source = inspected.get(file_id)
                if source and source.get("kind") not in {"table", "spreadsheet"}:
                    return self._event(step, "skipped", "Un rapport Excel nécessite un tableau Excel/CSV.")
                result = to_jsonable(
                    self.tools.create_analysis_workbook(file_id, str(step.arguments.get("sheet_name", "")))
                )
                return self._event(step, "done", self._report_message(result), result)
            if step.tool == "index_memory":
                if self.memory is None:
                    return self._event(step, "unavailable", "La mémoire locale n’est pas disponible.")
                path = self.workspace.get_path(file_id)
                result = to_jsonable(
                    self.memory.import_file(path, project_id=step.arguments.get("project_id") or None)
                )
                return self._event(step, "done", self._memory_import_message(result), result)
            if step.tool == "search_memory":
                if self.memory is None:
                    return self._event(step, "unavailable", "La mémoire locale n’est pas disponible.")
                result = to_jsonable(
                    self.memory.search(
                        str(step.arguments["query"]),
                        project_id=step.arguments.get("project_id") or None,
                        limit=MAX_MEMORY_RESULTS,
                    )
                )
                return self._event(step, "done", self._memory_search_message(result), result)
            return self._event(step, "error", "Outil local non autorisé.")
        except UserFacingError as error:
            return self._event(step, "error", str(error))
        except Exception:
            # Details are logged by the HTTP layer; never leak paths or document
            # content as an error response.
            return self._event(step, "error", "Cette étape locale n’a pas pu être terminée.")

    @staticmethod
    def _event(step: PlanStep, status: str, message: str, result: Any | None = None) -> dict[str, Any]:
        event: dict[str, Any] = {
            "step_id": step.step_id,
            "tool": step.tool,
            "label": step.label,
            "status": status,
            "message": message,
        }
        if result is not None:
            event["result"] = result
        return event

    @staticmethod
    def _inspect_message(result: dict[str, Any]) -> str:
        name = str(result.get("file", "Document"))
        if result.get("kind") == "table":
            return (
                f"{name} : {result.get('rows_sampled', result.get('rows', '?'))} lignes échantillonnées "
                f"et {result.get('columns', '?')} colonnes inspectées."
            )
        if result.get("kind") == "spreadsheet":
            sheets = result.get("sheets") if isinstance(result.get("sheets"), dict) else {}
            return f"{name} : {len(sheets)} feuille(s) inspectée(s) localement."
        return f"{name} : document inspecté localement."

    @staticmethod
    def _analysis_message(result: dict[str, Any]) -> str:
        count = len(result.get("numeric_statistics", {}) or {})
        missing = result.get("missing_values", {}) or {}
        missing_count = sum(int(value or 0) for value in missing.values())
        return f"Analyse locale terminée : {count} colonne(s) numérique(s), {missing_count} valeur(s) manquante(s)."

    @staticmethod
    def _report_message(result: dict[str, Any]) -> str:
        name = str(result.get("output_file", "rapport Excel"))
        return f"Rapport créé dans output : {name}."

    @staticmethod
    def _memory_import_message(result: dict[str, Any]) -> str:
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        title = str(result.get("title") or source.get("title") or "Document")
        chunks = result.get("chunk_count") or result.get("chunks") or source.get("chunk_count")
        return f"{title} indexé dans la mémoire locale" + (f" ({chunks} extrait(s))." if chunks else ".")

    @staticmethod
    def _memory_search_message(result: Any) -> str:
        if isinstance(result, dict):
            count = int(result.get("count", len(result.get("results", []) or [])))
        elif isinstance(result, list):
            count = len(result)
        else:
            count = 0
        return f"Recherche mémoire terminée : {count} passage(s) retrouvé(s)."

    @staticmethod
    def _citations_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for event in events:
            if event.get("tool") != "search_memory" or event.get("status") != "done":
                continue
            result = event.get("result")
            hits = result.get("results", []) if isinstance(result, dict) else result if isinstance(result, list) else []
            for hit in hits[:MAX_MEMORY_RESULTS]:
                if not isinstance(hit, dict):
                    continue
                raw_citation = hit.get("citation")
                if isinstance(raw_citation, dict):
                    citations.append(
                        {
                            "source_id": raw_citation.get("source_id") or hit.get("source_id"),
                            "source_title": raw_citation.get("title") or hit.get("source_title") or hit.get("title"),
                            "citation": raw_citation.get("label") or hit.get("title") or "Source locale",
                            "page": raw_citation.get("page"),
                            "line_start": raw_citation.get("line_start"),
                            "line_end": raw_citation.get("line_end"),
                            "excerpt": hit.get("excerpt", ""),
                        }
                    )
                else:
                    citations.append(
                        {
                            key: hit[key]
                            for key in ("source_id", "source_title", "citation", "page", "line_start", "line_end", "excerpt")
                            if key in hit
                        }
                    )
        return citations

    @staticmethod
    def _answer_from_events(events: list[dict[str, Any]], *, allow_write: bool) -> str:
        done = [item for item in events if item["status"] == "done"]
        blocked = [item for item in events if item["status"] == "needs_confirmation"]
        failed = [item for item in events if item["status"] in {"error", "unavailable"}]
        if not done and failed:
            return "Le plan local a été préparé, mais aucune étape n’a pu aboutir. Vérifie les messages de chaque étape."
        lines = ["Plan local exécuté sans modèle externe."]
        lines.extend(f"• {item['message']}" for item in done)
        if blocked:
            lines.append("• Un fichier de sortie reste à confirmer avant toute écriture.")
        if failed:
            lines.append(f"• {len(failed)} étape(s) demandent ton attention.")
        if not allow_write and any(item["tool"] == "create_analysis_workbook" for item in blocked):
            lines.append("Active l’autorisation de création seulement si tu souhaites produire ce rapport.")
        return "\n".join(lines)

    def _validated_file_ids(self, raw_ids: list[str]) -> list[str]:
        unique: list[str] = []
        for file_id in raw_ids:
            if not isinstance(file_id, str) or not file_id.startswith("f_"):
                raise UserFacingError("Identifiant de fichier invalide.")
            if file_id not in unique:
                unique.append(file_id)
        if len(unique) > MAX_ORCHESTRATOR_FILES:
            raise UserFacingError(f"Sélectionne au maximum {MAX_ORCHESTRATOR_FILES} fichiers à la fois.")
        # Resolving here proves each opaque ID still belongs to the controlled
        # workspace before the plan is shown or persisted.
        for file_id in unique:
            self.workspace.get_path(file_id)
        return unique

    @staticmethod
    def _validate_message(value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise UserFacingError("Écris une demande avant de l’envoyer.")
        if len(cleaned) > MAX_ORCHESTRATOR_MESSAGE_CHARS:
            raise UserFacingError("La demande est trop longue.")
        return cleaned
