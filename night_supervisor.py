#!/usr/bin/env python3
"""Superviseur de nuit — maintient la flotte en vie sans intervention.

Toutes les 45 s :
  - relance orchestrator / mission_driver / guardian / watchdog s'ils meurent ;
  - tue tout `find /` (scan disque complet = machine à genoux) ;
  - tue les pytest en surnombre (> 6) en gardant les plus anciens ;
  - écrit une ligne d'état dans night_supervisor.log.

Toutes les 10 min : snapshot du registre + missions done dans night_report.log.
"""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path("/Users/comedelavenne/AI-Excel-Agent")
MAX_WORKERS = "4"
POLL = 45
STATE_EVERY = 600

COMPONENTS = {
    "orchestrator.py": f"MAX_WORKERS={MAX_WORKERS} python3 -u orchestrator.py >> orchestrator.log 2>&1",
    "mission_driver.py": f"MAX_WORKERS={MAX_WORKERS} python3 -u mission_driver.py >> mission_driver.log 2>&1",
    "guardian_anti_fake_done.py": "python3 -u guardian_anti_fake_done.py >> guardian.log 2>&1",
    "watchdog_hangs.py": "python3 -u watchdog_hangs.py >> watchdog_hangs.log 2>&1",
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(ROOT / "night_supervisor.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def pgrep(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
    return [int(x) for x in out.split() if x.strip().isdigit()]


def ps_table() -> list[tuple[int, str]]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_s, _, cmd = line.partition(" ")
        if pid_s.isdigit():
            rows.append((int(pid_s), cmd))
    return rows


def keep_components_alive() -> None:
    for script, cmd in COMPONENTS.items():
        if not pgrep(script):
            log(f"relance {script}")
            subprocess.Popen(cmd, shell=True, cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)


def kill_disk_scans() -> None:
    for pid, cmd in ps_table():
        if "find /" in cmd and ("-name" in cmd or "WORKER_TEMPLATE" in cmd):
            try:
                os.kill(pid, 9)
                log(f"tué scan disque pid={pid}")
            except Exception:
                pass


def kill_pytest_excess(limit: int = 10) -> None:
    rows = [(p, c) for p, c in ps_table() if "pytest" in c and "python" in c]
    if len(rows) <= limit:
        return
    # garder les plus anciens (pid les plus petits en général = lancés avant)
    rows.sort(key=lambda r: r[0])
    for pid, _ in rows[limit:]:
        try:
            os.kill(pid, 9)
            log(f"pytest en surnombre tué pid={pid}")
        except Exception:
            pass


def live_worker_orders() -> set[str]:
    """Ordres actuellement pilotés par un process opencode vivant."""
    orders = set()
    for _, cmd in ps_table():
        if "opencode run --auto" in cmd and "--title Worker-" in cmd:
            tail = cmd.split("--title Worker-", 1)[1].strip()
            tail = tail.split()[0] if tail else ""
            if tail:
                orders.add(tail)
    return orders


def cwd_of(pid: int) -> str:
    try:
        out = subprocess.run(["lsof", "-p", str(pid)], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""
    for line in out.splitlines():
        if " cwd " in line:
            return line.split()[-1]
    return ""


def kill_orphan_pytest() -> None:
    """Tue les pytest dont le worktree n'a plus de worker vivant.

    Ce sont eux qui saturent la machine : un worker tué laisse ses suites
    tourner indéfiniment (jusqu'à 6-8 pytest simultanés dans le même dossier).
    """
    live = live_worker_orders()
    for pid, cmd in ps_table():
        if "pytest" not in cmd or "python" not in cmd:
            continue
        cwd = cwd_of(pid)
        marker = "AI-Excel-Agent-worker-cvboost-"
        if marker not in cwd:
            continue  # Codex ou autre: ne pas toucher
        order = "cvboost-" + cwd.split(marker, 1)[1].split("/")[0]
        if order not in live:
            try:
                os.kill(pid, 9)
                log(f"pytest orphelin tué pid={pid} worktree={order}")
            except Exception:
                pass


_last_kick = 0.0


def ensure_parallelism(min_workers: int = 3, cooldown: float = 300.0) -> None:
    """Si des slots sont vides et que des missions sont prêtes, relance le driver.

    Le driver attend un résultat (wait_for_any_result) : quand un worker meurt
    sans publier, le slot reste vide jusqu'au prochain résultat. On secoue.
    """
    global _last_kick
    workers = len(pgrep("opencode run --auto"))
    if workers >= min_workers or time.time() - _last_kick < cooldown:
        return
    reg = json.load(open(ROOT / "missions_registry.json", encoding="utf-8"))
    done = {m["id"] for m in reg["missions"] if m["status"] == "done"}
    ready = [m for m in reg["missions"]
             if m["status"] == "pending" and all(d in done for d in m.get("dependencies", []))]
    if not ready:
        return
    _last_kick = time.time()
    log(f"slots vides ({workers} workers, {len(ready)} missions prêtes) → relance du driver")
    for pid in pgrep("mission_driver.py"):
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def kill_stalled_workers(min_age_min: float = 12.0, min_cpu_s: float = 8.0) -> None:
    """Tue les workers bloqués en attente d'API.

    Symptôme observé : 55 min écoulées, 11 s de CPU cumulé, 0,2 % CPU, aucun
    fichier écrit. Ces workers ne produiront jamais : ils consomment un slot.
    """
    for pid, cmd in ps_table():
        if "opencode run --auto" not in cmd or "--title Worker-" not in cmd:
            continue
        try:
            out = subprocess.run(["ps", "-o", "etime=,time=", "-p", str(pid)],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            continue
        if not out:
            continue
        etime_s, _, cputime_s = out.partition(" ")
        elapsed = _parse_etime(etime_s.strip())
        used = _parse_cputime(cputime_s.strip())
        if elapsed is not None and used is not None and elapsed > min_age_min * 60 and used < min_cpu_s:
            order = cmd.split("--title Worker-", 1)[1].split()[0]
            try:
                os.kill(pid, 9)
                log(f"worker figé tué pid={pid} order={order} ({elapsed/60:.0f} min, {used:.0f} s CPU)")
            except Exception:
                pass


def _parse_etime(txt: str) -> float | None:
    """'01:23:45' ou '12:34' ou '45' -> secondes."""
    try:
        if "-" in txt:
            days, _, rest = txt.partition("-")
            base = int(days) * 86400
        else:
            base, rest = 0, txt
        parts = [int(x) for x in rest.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        return base + parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        return None


def _parse_cputime(txt: str) -> float | None:
    """'0:11.49' -> secondes."""
    try:
        parts = txt.split(":")
        while len(parts) < 3:
            parts.insert(0, "0")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except Exception:
        return None


def snapshot() -> None:
    reg = json.load(open(ROOT / "missions_registry.json", encoding="utf-8"))
    counts: dict[str, int] = {}
    for m in reg["missions"]:
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    workers = len(pgrep("opencode run --auto"))
    line = (f"[{time.strftime('%H:%M')}] done={counts.get('done', 0)} "
            f"pending={counts.get('pending', 0)} workers={workers} "
            f"load={os.getloadavg()[0]:.0f}")
    log(line)
    with open(ROOT / "night_report.log", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main() -> None:
    log("superviseur de nuit démarré")
    last_state = 0.0
    while True:
        try:
            keep_components_alive()
            kill_disk_scans()
            kill_stalled_workers()
            kill_orphan_pytest()
            kill_pytest_excess()
            ensure_parallelism()
            if time.time() - last_state >= STATE_EVERY:
                snapshot()
                last_state = time.time()
        except Exception as exc:  # ne jamais mourir
            log(f"erreur superviseur: {exc}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
