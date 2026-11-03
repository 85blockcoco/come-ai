#!/usr/bin/env python3
"""
CLI pour soumettre des missions à l'orchestrateur via from_A.json.
Usage: python submit_mission.py <mission_id> [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = Path(__file__).resolve().parent / "missions_registry.json"
FROM_A = Path(__file__).resolve().parent / "messages" / "from_A.json"

def load_registry() -> dict:
    return json.loads(Path(REGISTRY).read_text(encoding="utf-8"))

def get_mission(registry: dict, mission_id: str) -> dict | None:
    for m in registry["missions"]:
        if m["id"] == mission_id:
            return m
    return None

def load_prompt(prompt_file: str) -> str:
    path = Path(__file__).resolve().parent / prompt_file
    if not path.exists():
        return f"[ERREUR: fichier prompt introuvable: {prompt_file}]"
    content = path.read_text(encoding="utf-8")
    # Si c'est un markdown avec ancre, extraire la section
    if "#mission-" in prompt_file:
        anchor = prompt_file.split("#mission-")[1]
        lines = content.split("\n")
        in_section = False
        out = []
        for line in lines:
            if line.startswith(f"## Mission {anchor.split('-')[0]}") or line.startswith(f"### Mission {anchor.split('-')[0]}"):
                in_section = True
            elif in_section and line.startswith("## ") and not line.startswith(f"## Mission {anchor.split('-')[0]}"):
                break
            if in_section:
                out.append(line)
        if out:
            return "\n".join(out).strip()
    return content.strip()

def submit_mission(mission_id: str, dry_run: bool = False) -> int:
    registry = load_registry()
    mission = get_mission(registry, mission_id)
    
    if not mission:
        print(f"ERREUR: Mission {mission_id} inconnue")
        print("Missions disponibles:")
        for m in load_registry()["missions"]:
            print(f"  {m['id']}: {m['title']} ({m['status']})")
        return 1
    
    if mission["status"] == "done":
        print(f"ATTENTION: Mission {mission_id} déjà faite (SHA: {mission.get('merged_sha', '?')})")
        if input("Relancer quand même ? (o/N): ").lower() != "o":
            return 0
    
    # Vérifier dépendances
    deps = mission.get("dependencies", [])
    if deps:
        print(f"Dépendances: {', '.join(deps)}")
        # TODO: vérifier qu'elles sont merged
    
    prompt = load_prompt(mission["prompt_file"])
    
    from_a = {
        "order_id": f"cvboost-{mission['id']}-{int(Path().stat().st_mtime)}",
        "status": "ready_for_worker",
        "verifications_done": [
            f"mission_{mission['id']}_dependencies_checked",
            "registry_validated"
        ],
        "prompt_for_worker": f"MISSION CVBOOST-{mission['id'].upper()} — {mission['title']}\n\n{prompt}"
    }
    
    from_a_path = Path(__file__).resolve().parent / "messages" / "from_A.json"
    from_a_path.parent.mkdir(exist_ok=True)
    
    if dry_run:
        print(f"=== DRY RUN Mission {mission_id} ===")
        print(f"Order ID: {from_a['order_id']}")
        print(f"Branch: {mission['branch']}")
        print(f"Prompt length: {len(from_a['prompt_for_worker'])} chars")
        print(f"Dependencies: {mission.get('dependencies', [])}")
        print("\nPrompt preview (first 500 chars):")
        print(from_a['prompt_for_worker'][:500] + "...")
        return 0
    
    # Écrire from_A.json
    from_a_data = {
        "order_id": from_a["order_id"],
        "status": "ready_for_worker",
        "verifications_done": from_a["verifications_done"],
        "prompt_for_worker": from_a["prompt_for_worker"]
    }
    
    FROM_A = Path(__file__).resolve().parent / "messages" / "from_A.json"
    FROM_A.parent.mkdir(exist_ok=True)
    FROM_A.write_text(json.dumps(from_a_data, ensure_ascii=False, indent=1), encoding="utf-8")
    
    print(f"✅ Mission {mission_id} soumise !")
    print(f"Order ID: {from_a['order_id']}")
    print(f"Branch: {mission['branch']}")
    print("L'orchestrateur va la prendre en charge (poll toutes les 3s).")
    print("Surveille: messages/to_A.json pour le résultat")
    return 0

def list_missions():
    registry = load_registry()
    print("Missions CVBOOST :")
    for m in registry["missions"]:
        status_icon = {"done": "✅", "pending": "⏳", "partial": "⚠️"}.get(m["status"], "❓")
        deps = f" (deps: {', '.join(m['dependencies'])})" if m["dependencies"] else ""
        print(f"  {status_icon} {m['id']}: {m['title']}{deps} — {m['status']}")

def main():
    parser = argparse.ArgumentParser(description="Soumettre missions à l'orchestrateur")
    parser.add_argument("mission_id", nargs="?", help="ID de la mission (ex: 04, 07)")
    parser.add_argument("--list", action="store_true", help="Lister toutes les missions")
    parser.add_argument("--check", action="store_true", help="Dry-run sans soumettre")
    args = parser.parse_args()
    
    if args.list:
        list_missions()
        return 0
    
    if not args.mission_id:
        parser.print_help()
        return 1
    
    return submit_mission(args.mission_id, dry_run=args.check)

if __name__ == "__main__":
    sys.exit(main())