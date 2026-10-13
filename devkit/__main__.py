"""One-command maintenance interface using the project's existing venv."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from devkit.diagnostics import run_diagnostics
from devkit.exporting import build_issue_bundle, export_snapshot
from devkit.patching import PatchWorkspace


def read_input(path: Path, *, limit: int = 500_000) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Le fichier de correctif doit être un fichier texte réel et borné.")
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintenance Côme AI : diagnostics et exports sans IA ; cycles IA bornés sur lancement explicite.")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--python", type=Path, help="Python existant pour valider une copie isolée.")
    commands = parser.add_subparsers(dest="command", required=True)
    credential = commands.add_parser("configure-gemini", help="Renseigner la clé localement avec saisie masquée.")
    credential.add_argument("--confirm-free-project", action="store_true", help="Déclaration : projet gratuit, aucune facturation activée.")
    commands.add_parser("configure-openrouter", help="Renseigner la clé OpenRouter localement avec saisie masquée.")
    evolution = commands.add_parser("evolution", help="Backlog et cycles de développement bornés.")
    evolution_actions = evolution.add_subparsers(dest="evolution_action", required=True)
    evolution_actions.add_parser("status")
    demo = evolution_actions.add_parser("demo", help="Cycle réel sur une fonction Côme copiée, sans modifier le noyau.")
    demo.add_argument("--max-requests", type=int, choices=[1, 2], default=2)
    configure = evolution_actions.add_parser("configure")
    configure.add_argument("--provider", choices=["gemini", "openrouter", "ollama"], required=True)
    configure.add_argument("--model", default="auto")
    configure.add_argument("--allow-remote", action="store_true")
    configure.add_argument("--confirm-free-project", action="store_true")
    task = evolution_actions.add_parser("add")
    task.add_argument("--title", required=True)
    task.add_argument("--description", required=True)
    task.add_argument("--file", action="append", required=True, dest="files")
    task.add_argument("--acceptance", default="")
    run = evolution_actions.add_parser("run")
    run.add_argument("--task")
    run.add_argument("--max-requests", type=int, default=2)
    run.add_argument("--max-attempts", type=int, default=2)
    check = commands.add_parser("check", help="Tous les tests et diagnostics, avec rapport local.")
    check.add_argument("--candidate", help="Valider un correctif préparé, dans la sandbox du Mac.")
    check.add_argument("--timeout", type=int, default=600, help="Durée totale maximale en secondes.")
    export = commands.add_parser("export", help="Archive filtrée du projet et du dernier diagnostic.")
    export.add_argument("--output", type=Path)
    issue = commands.add_parser("issue", help="Demande de correction portable pour une IA.")
    issue.add_argument("--title", required=True)
    issue.add_argument("--description", required=True)
    issue.add_argument("--errors-file", type=Path)
    issue.add_argument("--file", action="append", default=[], dest="files")
    issue.add_argument("--output", type=Path)
    stage = commands.add_parser("stage", help="Importer un patch ou des fichiers ; afficher leur aperçu.")
    mode = stage.add_mutually_exclusive_group(required=True)
    mode.add_argument("--patch", type=Path)
    mode.add_argument("--file", action="append", dest="files", help="chemin/source.py=/chemin/du/fichier-corrigé.py")
    preview = commands.add_parser("preview", help="Relire un correctif enregistré.")
    preview.add_argument("candidate")
    apply = commands.add_parser("apply", help="Appliquer un correctif validé et sauvegarder les originaux.")
    apply.add_argument("candidate")
    apply.add_argument("--confirm", action="store_true")
    rollback = commands.add_parser("rollback", help="Restaurer les fichiers d’une transaction sans écraser une nouvelle édition.")
    rollback.add_argument("transaction")
    rollback.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    storage = root / ".devkit"
    try:
        if storage.is_symlink():
            raise ValueError("Le stockage de l’atelier ne peut pas être un lien symbolique.")
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.command == "configure-gemini":
            from devkit.credentials import configure_gemini

            result = configure_gemini(root, confirm_free_project=args.confirm_free_project)
            print("Configuration Gemini enregistrée localement. La clé n’est jamais affichée.")
            return 0
        if args.command == "configure-openrouter":
            from devkit.credentials import configure_openrouter

            configure_openrouter(root)
            print("Configuration OpenRouter enregistrée et chargeable localement. Aucun appel API envoyé ; la clé n’est jamais affichée.")
            return 0
        if args.command == "evolution":
            from devkit.evolution_manager import EvolutionManager

            manager = EvolutionManager(root, storage)
            if args.evolution_action == "status":
                result = manager.overview()
            elif args.evolution_action == "configure":
                result = manager.configure({"provider": args.provider, "model": args.model,
                                            "allow_remote": args.allow_remote, "gemini_free_project_confirmed": args.confirm_free_project})
            elif args.evolution_action == "add":
                result = manager.engine.store.add_task(args.title, args.description, args.files, args.acceptance)
            elif args.evolution_action == "demo":
                result = manager.run_demo(max_requests=args.max_requests)
            else:
                result = manager.run(args.task, max_requests=args.max_requests, max_attempts=args.max_attempts)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("status") not in {"failed", "waiting_provider"} else 1
        patches = PatchWorkspace(root, storage)
        if args.command == "check":
            candidate = args.candidate
            target = patches.candidate_path(candidate) if candidate else root
            result = run_diagnostics(
                target,
                report_dir=storage / "candidate_reports" / candidate if candidate else storage / "diagnostics",
                python_executable=args.python or root / ".venv" / "bin" / "python",
                timeout_seconds=max(10, min(args.timeout, 1800)),
                require_sandbox=bool(candidate),
            )
            if candidate:
                try:
                    patches.mark_validation(candidate, result)
                except ValueError:
                    if result["status"] == "passed":
                        result["status"] = "blocked"
            print(f"Diagnostic : {result['status']}")
            for item in result.get("checks", []):
                print(f"  {item['name']}: {item['status']}")
            print("Rapport :", storage / (f"candidate_reports/{candidate}" if candidate else "diagnostics") / "latest.md")
            return 0 if result["status"] == "passed" else 2 if result["status"] == "blocked" else 1
        if args.command in {"export", "issue"}:
            from datetime import datetime, timezone
            import uuid

            report_path = storage / "diagnostics" / "latest.json"
            report = None
            if not report_path.is_symlink() and report_path.is_file() and report_path.stat().st_size <= 2_000_000:
                try:
                    loaded = json.loads(report_path.read_text(encoding="utf-8"))
                    report = loaded if isinstance(loaded, dict) else None
                except (OSError, ValueError):
                    pass
            destination = args.output or storage / "exports" / f"{args.command}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}.zip"
            if args.command == "export":
                result = export_snapshot(root, destination, diagnostic_report=report)
            else:
                if not args.files:
                    raise ValueError("Choisis au moins un fichier source avec --file pour la demande de correction.")
                result = build_issue_bundle(root, destination, title=args.title, description=args.description,
                                            errors=read_input(args.errors_file, limit=32_000) if args.errors_file else "",
                                            selected_files=args.files, diagnostic_report=report)
            print(f"Archive créée : {destination}")
            print(f"Fichiers source : {result.get('file_count', '?')}. Aucun envoi automatique.")
            return 0
        if args.command == "stage":
            if args.patch:
                result = patches.stage_patch(read_input(args.patch))
            else:
                files = {}
                for entry in args.files:
                    target, separator, source = entry.partition("=")
                    if not separator or target in files:
                        raise ValueError("Utilise --file chemin/source.py=/chemin/fichier-corrigé.py, sans doublon.")
                    files[target] = read_input(Path(source))
                result = patches.stage_files(files)
        elif args.command == "preview":
            result = patches.preview(args.candidate)
        elif args.command == "apply":
            if not args.confirm:
                raise ValueError("Relis l’aperçu puis utilise --confirm pour appliquer le correctif testé.")
            result = patches.apply(args.candidate)
        else:
            if not args.confirm:
                raise ValueError("Utilise --confirm pour restaurer les originaux de cette transaction.")
            result = patches.rollback(args.transaction)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        from workspace_core import safe_error

        print(f"Maintenance interrompue : {safe_error(error)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
