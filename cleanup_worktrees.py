#!/usr/bin/env python3
"""Nettoyage des worktrees worker périmés.

Motif : 1 593 worktrees = ~1,5 M fichiers -> Spotlight/APFS saturent le Mac
(CPU système 45 %, load average > 400). On supprime les worktrees inactifs
en gardant :
  - ceux des workers en cours d'exécution,
  - les 25 plus récents (travail interrompu récemment, éventuellement à sauver).
Les branches restent intactes (git worktree remove ne touche pas aux refs).
"""
import subprocess
import time
from pathlib import Path

ROOT = Path("/Users/comedelavenne/AI-Excel-Agent")
LOG = ROOT / "worktree_cleanup.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def live_orders() -> set[str]:
    out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    orders = set()
    for line in out.splitlines():
        if "opencode run --auto" in line and "--title Worker-" in line:
            tail = line.split("--title Worker-", 1)[1].strip().split()
            if tail:
                orders.add(tail[0])
    return orders


def main() -> None:
    live = live_orders()
    log(f"workers vivants: {sorted(live)}")
    out = run(["git", "worktree", "list", "--porcelain"]).stdout
    paths = [l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("worktree ")]
    workers = [p for p in paths if "AI-Excel-Agent-worker-" in p]
    log(f"{len(workers)} worktrees worker au total")

    workers.sort(key=lambda p: Path(p).stat().st_mtime if Path(p).exists() else 0, reverse=True)
    keep = set(workers[:25])
    removed = skipped = errors = 0
    for path in workers:
        order = Path(path).name.split("AI-Excel-Agent-worker-", 1)[1]
        if order in live or path in keep:
            skipped += 1
            continue
        r = run(["git", "worktree", "remove", "--force", path])
        if r.returncode == 0:
            removed += 1
            if removed % 100 == 0:
                log(f"{removed} supprimés...")
        else:
            errors += 1
            if errors <= 5:
                log(f"échec {order}: {r.stderr.strip()[:120]}")
    run(["git", "worktree", "prune"])
    log(f"terminé: {removed} supprimés, {skipped} gardés, {errors} erreurs")


if __name__ == "__main__":
    main()
