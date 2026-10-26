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

REPORT_EVERY = 900  # rapport flotte toutes les 15 min


def best_pool() -> str:
    """Sélection DYNAMIQUE des meilleurs modèles à l'instant t (santé+score)."""
    try:
        import model_health as mh
        pool = mh.pick_pool()
        if pool:
            return ",".join(pool[:6])
    except Exception as exc:
        log(f"pool dynamique indisponible: {exc}")
    return "opencode-go/glm-5.3-flash"


def component_cmd(script: str) -> str:
    """Commande de relance avec la sélection modèle à l'instant t."""
    env = f"MAX_WORKERS={MAX_WORKERS}"
    if script == "orchestrator.py":
        env += f' WORKER_POOL="{best_pool()}"'
    return f"{env} python3 -u {script} >> {script.replace('.py', '.log')} 2>&1"


def relaunch_mapping() -> dict[str, str]:
    mapping = {
        "orchestrator.py": component_cmd("orchestrator.py"),
        "mission_driver.py": component_cmd("mission_driver.py"),
        "guardian_anti_fake_done.py": "python3 -u guardian_anti_fake_done.py >> guardian.log 2>&1",
    }
    if Path(ROOT / "watchdog_hangs.py").exists():
        mapping["watchdog_hangs.py"] = "python3 -u watchdog_hangs.py >> watchdog_hangs.log 2>&1"
    return mapping


def _last_origin_commit(branch: str) -> str:
    try:
        out = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                             capture_output=True, text=True, timeout=20).stdout
        return out.split()[0][:7] if out.strip() else "absente"
    except Exception:
        return "?"


def _pipeline_latency() -> str:
    try:
        t0 = time.time()
        code = subprocess.run(["curl", "-sf", "-o", "/dev/null", "-m", "30",
                               "http://127.0.0.1:8765/api/career/application-pipeline"],
                              capture_output=True, timeout=35).returncode
        dt = time.time() - t0
        return f"{int(dt)}s" if code == 0 else "erreur"
    except Exception:
        return "?"


def write_report() -> None:
    """Rapport flotte régulier avec indicateurs (KPI) : effet panneau de supervision."""
    from collections import Counter
    reg = json.load(open(ROOT / "missions_registry.json", encoding="utf-8"))
    counts = Counter(m["status"] for m in reg["missions"])
    workers = []
    try:
        out = subprocess.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "opencode run --auto" in line:
                import re
                mm = re.search(r"-m\s+(\S+)\s+--title Worker-(cvboost-\d+-\d+)", line)
                if mm:
                    workers.append((mm.group(2), mm.group(1)))
    except Exception:
        pass
    heures = time.strftime("%Y-%m-%d %H:%M")
    # /24 h results: success rate + average duration of OK
    ok = fail = 0
    durs = []
    total_results = 0
    try:
        for path in (ROOT / "messages/results").glob("*.json"):
            total_results += 1
            d = json.loads(path.read_text(encoding="utf-8"))
            status_w = (d.get("worker_result") or {}).get("status")
            if status_w == "done":
                ok += 1
            elif status_w:
                fail += 1
            if status_w == "done" and d.get("duration_sec"):
                durs.append(float(d["duration_sec"]))
    except Exception:
        pass
    total = ok + fail
    taux = f"{ok}/{total} ({round(100*ok/max(total,1))} %)" if total else "n/d"
    moy = f"{round(sum(durs)/len(durs))}s" if durs else "n/d"
    d_today = sum(1 for m in reg["missions"] if m.get("status") == "done" and str(m.get("done_at","")).startswith(time.strftime("%Y-%m-%d")))
    p0 = [m["id"] for m in reg["missions"] if str(m.get("priority","")) == "P0" and m["status"] == "pending"]
    lines = [
        f"# Rapport flotte — {heures}",
        "",
        "## Indicateurs",
        f"- Missions : done={counts.get('done',0)} pending={counts.get('pending',0)} failed={counts.get('failed',0)} · livrées aujourd'hui={d_today}",
        f"- Taux OK (historique résultats) : {taux} · durée moyenne OK : {moy}",
        f"- Workers actifs : {len(workers)} · charge : {round(__import__('os').getloadavg()[0])}",
        f"- Missions P0 restantes : {','.join(p0) if p0 else 'aucune'}",
        f"- API application-pipeline : {_pipeline_latency()} (objectif Codex : < 3 s)",
        f"- Codex origin : {_last_origin_commit('codex/v3-stable-consolidation')}",
        "",
        "## workers",
        "\n".join(f"- {w} → {m}" for w, m in workers) if workers else "- aucun worker actif",
        "",
    ]
    recent = sorted((ROOT / "messages/results").glob("*.json"), key=lambda p: p.stat().st_mtime)[-8:]
    for path in reversed(recent):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            w = d.get("worker_result", {})
            lines.append(f"- {d.get('completed_at')} {d.get('mission_id')} {w.get('status')} {d.get('model_used')} ({d.get('duration_sec')}s)")
        except Exception:
            continue
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "fleet_rapport.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"rapport écrit ({len(workers)} workers, {counts})")


COMPONENTS = {}  # construit dynamiquement (best_pool) juste avant usage


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
    for script, cmd in relaunch_mapping().items():
        if not pgrep(script):
            log(f"relance {script} avec WORKER_POOL={best_pool()[:40]}…")
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


_last_report = 0.0


def main() -> None:
    global _last_report
    log("superviseur démarré (rapport toutes les 15 min)")
    last_state = 0.0
    write_report()
    _last_report = time.time()
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
            if time.time() - _last_report >= REPORT_EVERY:
                write_report()
                _last_report = time.time()
        except Exception as exc:  # ne jamais mourir
            log(f"erreur superviseur: {exc}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
