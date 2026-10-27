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


def _local(ts: str) -> str:
    try:
        import datetime as _dt
        t = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        return t.astimezone().strftime("%H:%M")
    except Exception:
        return ts


def _load_24h():
    ok, fails, durs, rows = 0, 0, [], []
    try:
        for path in sorted((ROOT / "messages/results").glob("*.json")):
            d = json.loads(path.read_text(encoding="utf-8"))
            w = d.get("worker_result") or {}
            status = w.get("status")
            dur = d.get("duration_sec")
            rows.append(dict(
                at=_local(str(d.get("completed_at", ""))), mission=str(d.get("mission_id", "")),
                model=str(d.get("model_used", "")), status=status, dur=dur,
                pushed=bool(d.get("pushed"))))
            if status == "done":
                ok += 1
            elif status:
                fails += 1
            if status == "done" and dur:
                durs.append(float(dur))
    except Exception as exc:
        log(f"lecture résultats: {exc}")
    return ok, fails, durs, rows


def _running_workers():
    out = subprocess.run(["ps", "-ax", "-o", "pid=,etime=,command="], capture_output=True, text=True, timeout=10).stdout
    import re as _re
    rows = []
    for line in out.splitlines():
        if "opencode run --auto" not in line:
            continue
        o = _re.search(r"--title Worker-cvboost-(\d+)-", line)
        mdl = _re.search(r"-m (\S+)", line)
        et = _re.search(r"^\s*\d+\s+(\S+)", line)
        if not o:
            continue
        secs = 0
        if et:
            t = et.group(1)
            if "-" in t:
                d, t = t.split("-")
                secs += int(d) * 86400
            parts = t.split(":")
            if len(parts) == 3:
                secs += int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                secs += int(parts[0]) * 60 + int(parts[1])
        rows.append(dict(start=secs, mission=o.group(1), model=mdl.group(1) if mdl else "?"))
    return rows


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
        return f"{int(time.time()-t0)}s" if code == 0 else "erreur"
    except Exception:
        return "?"


def write_report() -> None:
    import datetime as _dt
    from collections import Counter, defaultdict
    reg = json.load(open(ROOT / "missions_registry.json", encoding="utf-8"))
    counts = Counter(m["status"] for m in reg["missions"])
    p0_left = [m["id"] for m in reg["missions"] if str(m.get("priority", "")) == "P0" and m["status"] == "pending"]
    pend = [m["id"] for m in reg["missions"] if m["status"] == "pending"]

    ok, fails, durs, rows = _load_24h()
    total = ok + fails
    med = sorted(durs)[len(durs)//2] if durs else 1500.0
    okpct = round(100 * ok / max(total, 1))
    workers = _running_workers()
    now = _dt.datetime.now()

    L = [f"# RAPPORT FLOTTE — {now.strftime('%d/%m %H:%M')}", ""]
    L += ["## 1. Introduceurs clés", "",
          "| Indicateur | Valeur |", "|---|---|",
          f"| Missions livrées (total) | {counts.get('done',0)}/{len(reg['missions'])} · **{round(100*counts.get('done',0)/max(len(reg['missions']),1))} %** |",
          f"| Taux succès (résultats) | **{okpct} %** ({ok} OK / {fails} KO) |",
          f"| Durée médiane mission OK | **{int(med//60)} min** |",
          f"| Workers actifs | **{len(workers)}/4** |",
          f"| File d'attente | {len(pend)} mission(s) |",
          f"| P0 restantes | {','.join(p0_left) or 'aucune'} |",
          f"| Charge machine | {round(__import__('os').getloadavg()[0])} |", ""]

    # Table livrées/fail 24h (8 dernieres)
    L += ["## 2. Dernières livraisons (24 h)", "",
          "| Heure | Mission | Modèle | Durée | Résultat | Push |", "|---|---|---|---|---|---|"]
    for r in reversed(rows[-8:]):
        L.append(f"| {r['at']} | #{r['mission']} | {r['model'].replace('opencode-go/','')} | "
                 f"{int((r['dur'] or 0)//60)} min | {r['status'] or '?'} | {'✓' if r['pushed'] else '—'} |")
    L.append("")

    # En ce moment
    def stats_model():
        per = defaultdict(lambda: dict(n=0, ok=0, sec=0))
        for r in rows:
            per[r["model"]]["n"] += 1
            if r["status"] == "done":
                per[r["model"]]["ok"] += 1
                per[r["model"]]["sec"] += r["dur"] or 0
        return per
    per = stats_model()

    L += ["## 3. En train de tourner", ""]
    if workers:
        L += ["| Mission | Modèle | Démarré | Écoulé | Avancement est. | ETA | Risque |",
              "|---|---|---|---|---|---|---|"]
        for w in workers:
            el = w["start"]
            pct = min(99, int(100 * el / max(med, 60)))
            eta = max(0, med - el)
            risk = "long (>2×médiane)" if el > 2 * med else "normal"
            L.append(f"| #{w['mission']} | {w['model'].replace('opencode-go/','')} | démarré il y a {int(el//60)} min | "
                     f"{int(el//60)} min | {pct} % | t+{int(eta//60)} min | {risk} |")
    else:
        L.append("- aucun worker actif")
    L.append("")

    # per model
    L += ["## 4. Qui a fait quoi (par modèle)", "",
          "| Modèle | Tâches | OK | Taux OK | Temps total OK |", "|---|---|---|---|---|"]
    for model, st in sorted(per.items(), key=lambda kv: -kv[1]["ok"]):
        L.append(f"| {model.replace('opencode-go/','')} | {st['n']} | {st['ok']} | "
                 f"{round(100*st['ok']/max(st['n'],1))} % | {int(st['sec']//60)} min |")
    L.append("")

    # Codex
    L += ["## 5. Codex (branche consolidation)", "",
          f"- dernier commit sur origin : `{_last_origin_commit('codex/v3-stable-consolidation')}`",
          f"- latence /api/career/application-pipeline : **{_pipeline_latency()}** (objectif < 3 s)",
          "- périmètre : `career/**` + perf ; ne touche ni l'UI bureau ni l'orchestrateur", ""]

    # ETA global
    slots = max(0, 4 - len(workers))
    remaining = len(pend)
    eta_min = int((remaining / max(slots + len(workers), 1)) * med // 60) if remaining else 0
    L += ["## 6. Estimation délai avant résultats", "",
          f"- file restante : {remaining} mission(s) → **vidée de la file dans ≈ {eta_min} min** "
          f"(4 slots, médiane {int(med//60)} min)",
          f"- P0 (candidature facile) : ETA ≈ {(len(p0_left)*(med//60))//max(slots+len(workers),1) or 1} h après leur lancement",
          "- pipeline < 3 s : blocée sur Codex", ""]
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "fleet_rapport.md").write_text("\n".join(L) + "\n", encoding="utf-8")
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
