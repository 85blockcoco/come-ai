#!/usr/bin/env python3
"""
Mission Driver — Automatise l'enchaînement des missions CVBOOST.
Version PARALLÈLE : batch submit, max_parallel workers, détection done malgré kill.
"""
import json
import os
import time
import signal
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "missions_registry.json"
FROM_A = ROOT / "messages" / "from_A.json"
TO_A = ROOT / "messages" / "to_A.json"
QUEUE_DIR = ROOT / "messages" / "queue"
INFLIGHT_DIR = ROOT / "messages" / "inflight"
RESULTS_DIR = ROOT / "messages" / "results"
LOG_FILE = ROOT / "mission_driver.log"

running = True
active_orders: dict[str, dict] = {}  # order_id -> {mission_id, submitted_at}

# Config par défaut (peut être overridée par registry.rules)
DEFAULT_MAX_PARALLEL = 4
DEFAULT_POLL_INTERVAL = 3
DEFAULT_TIMEOUT = 3600

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))

def save_registry(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

def get_mission(reg: dict, mid: str) -> dict | None:
    for m in reg["missions"]:
        if m["id"] == mid:
            return m
    return None

def get_max_parallel(reg: dict) -> int:
    """Parallélisme: MAX_WORKERS env (machine B) sinon règle du registre."""
    env = os.environ.get("MAX_WORKERS", "").strip()
    if env.isdigit():
        return int(env)
    return reg.get("rules", {}).get("max_parallel_workers", 4)

def get_allowlist() -> set[str] | None:
    """Répartition inter-machines: MISSION_ALLOWLIST="73,74,75,76".

    Une machine ne prend QUE les missions de sa liste. Absent = toutes
    (comportement historique d'une machine unique).
    """
    raw = os.environ.get("MISSION_ALLOWLIST", "").strip()
    if not raw:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}

def find_all_ready_missions(reg: dict, max_count: int) -> list[dict]:
    """Trouve TOUTES les missions prêtes (dépendances OK, status=pending) jusqu'à max_count"""
    allowlist = get_allowlist()
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()
    for group in reg.get("execution_order", []):
        for mid in group:
            if mid not in seen_ids:
                seen_ids.add(mid)
                ordered_ids.append(mid)
    for m in reg["missions"]:
        if m["id"] not in seen_ids:
            seen_ids.add(m["id"])
            ordered_ids.append(m["id"])
    
    ready = []
    for mid in ordered_ids:
        if allowlist is not None and mid not in allowlist:
            continue
        m = get_mission(reg, mid)
        if m and m.get("status") == "pending" and deps_met(reg, m):
            ready.append(m)
            if len(ready) >= max_count:
                break
    log(f"🔍 find_all_ready_missions: found {len(ready)} ready missions (max_count={max_count})")
    for m in ready:
        log(f"  📋 Ready: {m['id']} - {m['title'][:40]}")
    return ready

def load_prompt(prompt_file: str) -> str:
    if "#mission-" in prompt_file:
        file_part, anchor = prompt_file.split("#mission-", 1)
        path = ROOT / file_part
        if not path.exists():
            return f"[ERREUR: fichier introuvable: {file_part}]"
        content = path.read_text(encoding="utf-8")
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
    else:
        path = ROOT / prompt_file
        if not path.exists():
            return f"[ERREUR: fichier introuvable: {prompt_file}]"
        return path.read_text(encoding="utf-8").strip()

def deps_met(reg: dict, mission: dict) -> bool:
    for dep_id in mission.get("dependencies", []):
        dep = get_mission(reg, dep_id)
        if not dep or dep.get("status") != "done":
            return False
    return True

def submit_mission(mission: dict) -> str:
    """Dépose la mission dans la file parallèle (un fichier = une mission).

    Ne bloque plus sur le mono-slot from_A.json: l'orchestrateur réclame les
    fichiers de queue/ tant qu'il a des slots libres.
    """
    prompt = load_prompt(mission["prompt_file"])
    order_id = f"cvboost-{mission['id']}-{int(time.time() * 1000)}"

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "order_id": order_id,
        "mission_id": mission["id"],
        "status": "ready_for_worker",
        "prompt_for_worker": f"MISSION CVBOOST-{mission['id'].upper()} — {mission['title']}\n\n{prompt}",
        "submitted_at": time.time(),
    }
    target = QUEUE_DIR / f"{order_id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)

    # Observabilité: refléter la dernière soumission dans from_A.json sans
    # écraser un "processing" en cours.
    try:
        current = json.loads(FROM_A.read_text(encoding="utf-8")) if FROM_A.exists() else {}
    except Exception:
        current = {}
    if current.get("status") != "processing":
        FROM_A.parent.mkdir(exist_ok=True)
        FROM_A.write_text(
            json.dumps(
                {
                    "order_id": order_id,
                    "status": "ready_for_worker",
                    "verifications_done": [
                        f"mission_{mission['id']}_dependencies_checked",
                        "registry_validated",
                    ],
                    "prompt_for_worker": entry["prompt_for_worker"],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    log(f"📤 Mission {mission['id']} déposée dans queue/ (order: {order_id})")
    return order_id

def _read_result_for(order_id: str) -> Optional[dict]:
    """Résultat d'une mission: results/<order_id>.json puis result.json du worktree."""
    res = RESULTS_DIR / f"{order_id}.json"
    if res.exists():
        try:
            return json.loads(res.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Fallback interdit tant que le worker vit: il peut écrire result.json au
    # milieu de son travail (faux done constaté sur la mission 61).  En
    # revanche un marqueur inflight périmé (orchestrateur redémarré) ne doit
    # pas bloquer éternellement la récupération du travail déjà livré.
    if order_id in _alive_worker_orders():
        return None
    worktree = ROOT.parent / f"AI-Excel-Agent-worker-{order_id}"
    fallback = worktree / "messages" / "result.json"
    if fallback.exists():
        try:
            worker_result = json.loads(fallback.read_text(encoding="utf-8"))
            return {
                "from_": "orchestrator",
                "to": "agent_A",
                "worker_result": {
                    "task_id": order_id,
                    "status": worker_result.get("status", "failed"),
                    "files_created": worker_result.get("files_created", []),
                    "output": worker_result.get("output", ""),
                    "logs": worker_result.get("logs", ""),
                    "error": worker_result.get("error", ""),
                },
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except Exception:
            pass
    return None


def _alive_worker_orders() -> set[str]:
    """Order ids dont le process opencode est réellement vivant (via ps)."""
    import re as _re
    import subprocess as _sub
    alive: set[str] = set()
    try:
        out = _sub.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            m = _re.search(r"--title\s+Worker-(cvboost-\d+-\d+)", line)
            if m:
                alive.add(m.group(1))
    except Exception:
        pass
    return alive


def wait_for_any_result(active: dict[str, dict], timeout: int = 14400) -> Optional[tuple[str, dict]]:
    """Attend qu'UNE des missions actives finisse. Retourne (order_id, result).

    Sources de vérité, dans l'ordre: results/<order_id>.json, puis
    result.json du worktree.  Un worker n'est déclaré mort qu'après une
    période de grâce: pendant les premières minutes, l'orchestrateur peut
    être en train de créer le worktree ou de démarrer opencode, et le déclarer
    mort trop tôt provoquait des échecs/retries en cascade.
    """
    start = time.time()
    last_log = 0
    grace_sec = float(os.environ.get("WORKER_GRACE_SEC", "180"))
    log(f"⏳ wait_for_any_result: debut, timeout={timeout}, active={list(active.keys())}")
    while time.time() - start < timeout and running:
        if not active:
            return None

        # 1. Résultat publié (succès ou échec explicite)
        for order_id in list(active.keys()):
            data = _read_result_for(order_id)
            if data:
                log(f"🎯 Résultat trouvé pour {order_id}")
                return order_id, data

        # 2. Détection de mort, avec grâce et sans tuer une mission en file
        alive = _alive_worker_orders()
        now = time.time()
        for order_id, info in list(active.items()):
            age = now - info.get("submitted_at", now)
            if age < grace_sec:
                continue
            if order_id in alive:
                continue
            queued = (QUEUE_DIR / f"{order_id}.json").exists()
            inflight_file = INFLIGHT_DIR / f"{order_id}.json"
            if inflight_file.exists():
                # Ne court-circuite que si le marqueur est récent: après un
                # redémarrage de l'orchestrateur il reste des marqueurs orphelins
                # qui bloquaient la flotte pendant des heures.
                try:
                    if now - inflight_file.stat().st_mtime < 300:
                        continue
                except Exception:
                    pass
            if queued and age < max(grace_sec * 2, 600):
                # Pas encore réclamé: laisser le temps à un slot de se libérer.
                continue
            log(f"⚠️ Worker mort pour {order_id} (aucun process, aucun résultat, âge {int(age)}s) → échec")
            try:
                (QUEUE_DIR / f"{order_id}.json").unlink(missing_ok=True)
            except Exception:
                pass
            return order_id, {
                "from_": "orchestrator",
                "to": "agent_A",
                "worker_result": {
                    "task_id": order_id,
                    "status": "failed",
                    "files_created": [],
                    "output": "",
                    "logs": "worker process dead",
                    "error": "process dead",
                },
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        if now - last_log > 30:
            elapsed = int(now - min(v.get("submitted_at", now) for v in active.values()))
            log(f"⏳ {len(active)} missions en cours... ({elapsed}s) — {list(active.keys())}")
            last_log = now
        time.sleep(3)

    log(f"⏰ TIMEOUT global après {timeout}s")
    return None




def update_mission(mission_id: str, **fields) -> bool:
    """Mutation atomique du registre: recharge puis écrit tout de suite.

    L'ancien code chargeait le registre en début de boucle puis le réécrivait
    plus tard, ce qui écrasait les statuts 'done' avec un snapshot périmé
    (mission 61 vérifiée repassée en pending).
    """
    reg = load_registry()
    mission = get_mission(reg, mission_id)
    if not mission:
        return False
    mission.update(fields)
    save_registry(reg)
    return True


def verify_mission(order_id: str, mission_id: str, result_data: dict) -> tuple[bool, str]:
    """Preuve avant de marquer une mission done: branche poussée + tests verts.

    Un result.json qui dit "done" ne suffit jamais (règle projet: jamais de
    done sur parole).  On vérifie la branche sur origin, la présence réelle
    des fichiers déclarés et l'exécution des tests déclarés.
    """
    import subprocess as _sp
    import tempfile
    branch = f"worker/{order_id}"
    wr = result_data.get("worker_result", {}) or {}

    if wr.get("status") != "done":
        return False, f"statut worker={wr.get('status')}"

    # 1. pousser la branche si le worker ne l'a pas fait (le worktree local
    #    contient les commits; on ne dépend pas du bon vouloir du worker).
    wt_path = ROOT.parent / f"AI-Excel-Agent-worker-{order_id}"
    if wt_path.exists():
        try:
            _sp.run(["git", "push", "-u", "origin", branch], cwd=str(wt_path),
                    capture_output=True, text=True, timeout=180)
        except Exception:
            pass

    # 2. branche réellement sur origin
    try:
        r = _sp.run(["git", "ls-remote", "--heads", "origin", branch], cwd=ROOT,
                    capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, f"ls-remote impossible: {e}"
    if not (r.stdout or "").strip():
        return False, f"branche {branch} absente sur origin (pas de push)"

    files = [f for f in (wr.get("files_created") or []) if isinstance(f, str)]
    if not files:
        return False, "files_created vide"

    # 2. les fichiers déclarés existent dans la branche poussée
    missing = []
    for f in files:
        if _sp.run(["git", "cat-file", "-e", f"origin/{branch}:{f}"], cwd=ROOT,
                   capture_output=True, timeout=30).returncode != 0:
            missing.append(f)
    if missing:
        return False, "fichiers absents de la branche: " + ", ".join(missing[:5])

    # 3. les tests déclarés passent dans un worktree temporaire de la branche
    test_files = [f for f in files if f.startswith("tests/") and f.endswith(".py")]
    if not test_files:
        return False, "aucun test livré"
    tmpdir = Path(tempfile.mkdtemp(prefix=f"verify-{order_id}-"))
    wt = tmpdir / "wt"
    try:
        add = _sp.run(["git", "worktree", "add", "--detach", str(wt), f"origin/{branch}"],
                      cwd=ROOT, capture_output=True, text=True, timeout=180)
        if add.returncode != 0:
            # worktree add refuse parfois un chemin hors repo: fallback clone local
            add = _sp.run(["git", "clone", "--quiet", "--depth", "1", "--branch", branch,
                           str(ROOT), str(wt)], capture_output=True, text=True, timeout=300)
            if add.returncode != 0:
                return False, f"worktree/clone impossible: {add.stderr[-200:]}"
        run = _sp.run([sys.executable, "-m", "pytest", "-q", *test_files], cwd=str(wt),
                      capture_output=True, text=True, timeout=900)
        tail = (run.stdout or "")[-300:]
        if run.returncode != 0:
            return False, f"tests rouges: {tail}"
        return True, "push vérifié + tests verts"
    finally:
        _sp.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT,
                capture_output=True, timeout=120)
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def check_result_success(result: dict | None) -> bool:
    if not result:
        return False
    wr = result.get("worker_result", {})
    return wr.get("status") == "done"

def signal_handler(sig, frame):
    global running
    log(f"🛑 Signal {sig} reçu, arrêt propre...")
    running = False


def worker_procs() -> dict[str, dict[str, int]]:
    """Carte mission_id -> {order_id: pid} des workers opencode vivants (par --title)."""
    import re as _re
    import subprocess as _sub
    out = {}
    try:
        r = _sub.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=10)
        for line in r.stdout.splitlines():
            if "--title" in line and "Worker-cvboost-" in line and " -m " in line:
                m = _re.search(r"--title\s+Worker-cvboost-(\d+)-(\d+)\b", line)
                if m:
                    pid = int(line.split()[0])
                    out.setdefault(m.group(1), {})[f"cvboost-{m.group(1)}-{m.group(2)}"] = pid
    except Exception:
        pass
    return out

def adopt_alive_workers(reg: dict) -> None:
    """Au boot: adopte les workers réellement vivants pour éviter les doublons de soumission."""
    for mid, orders in worker_procs().items():
        for order, pid in orders.items():
            if order in active_orders:
                continue
            if any(v.get("mission_id") == mid for v in active_orders.values()):
                log(f"⏭ Doublon worker {order} (mission {mid} déjà adoptée) — ignoré")
                continue
            m = get_mission(reg, mid)
            if not m or m.get("status") != "pending":
                continue
            active_orders[order] = {"mission_id": mid, "pid": pid, "adopted": True, "submitted_at": time.time(), "attempt": 1, "max_attempts": 3}
            log(f"🧲 Worker adopté: {order} (pid {pid}) — mission {mid} en vol, pas de re-soumission")

def reap_active(active: dict) -> None:
    """Libère les orders dont le worker est mort sans result.json.

    Ne libère jamais un order encore en file (queue/) ou réclamé
    (inflight/): l'orchestrateur peut n'avoir pas encore démarré le process.
    """
    import subprocess as _sub
    alive = _alive_worker_orders()
    for order in list(active.keys()):
        res = Path(ROOT.parent) / f"AI-Excel-Agent-worker-{order}" / "messages" / "result.json"
        if res.exists():
            continue
        if (QUEUE_DIR / f"{order}.json").exists() or (INFLIGHT_DIR / f"{order}.json").exists():
            continue
        if order in alive:
            continue
        pid = active[order].get("pid")
        still = False
        if pid:
            try:
                r = _sub.run(["ps", "-p", str(pid)], capture_output=True, text=True, timeout=5)
                still = str(pid) in r.stdout
            except Exception:
                still = False
        age = time.time() - active[order].get("submitted_at", time.time())
        if not still and age > 180:
            log(f"🪦 Reap: {order} worker mort sans result.json — slot libéré")
            active.pop(order, None)

def main_loop():
    log("🚀 Mission Driver PARALLÈLE démarré")
    log(f"   Registry: {REGISTRY}")
    log(f"   Logs: {LOG_FILE}")
    
    while running:
        try:
            reg = load_registry()
            max_parallel = get_max_parallel(reg)
            if not active_orders:
                adopt_alive_workers(reg)
            reap_active(active_orders)
            
            # Nettoyer les orders terminés (depuis from_A.json status processing/waiting)
            # Note: l'orchestrateur remet from_A.json à "waiting" après traitement
            
            # Compter missions actives
            active_count = len(active_orders)
            slots_available = max_parallel - active_count
            
            if slots_available > 0:
                inflight = {v.get("mission_id") for v in active_orders.values()}
                # Aussi vérifier les workers opencode vivants (anti-doublon après reap)
                import subprocess as _sp2
                import re as _re2
                try:
                    ps_out = _sp2.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=10).stdout
                    for line in ps_out.splitlines():
                        if "Worker-cvboost-" in line and "opencode run" in line:
                            m = _re2.search(r"Worker-cvboost-(\d+)-", line)
                            if m:
                                inflight.add(m.group(1))
                except Exception:
                    pass
                # from_A n'est qu'un miroir d'observabilité: ne compter une
                # mission comme "en vol" que si son process vit réellement
                # (sinon un from_A périmé bloque une mission pour toujours).
                try:
                    from_data = json.loads(FROM_A.read_text(encoding="utf-8"))
                    from_order = from_data.get("order_id", "")
                    from_status = from_data.get("status", "")
                    if from_status == "processing" and from_order and from_order in _alive_worker_orders():
                        m = _re2.search(r"cvboost-(\d+)-", from_order)
                        if m:
                            inflight.add(m.group(1))
                except Exception:
                    pass
                # Cooldown: ne pas re-soumettre une mission qui vient d'échouer (5 min)
                _cooldown = getattr(main_loop, "_cooldown", {})
                _now = time.time()
                _cooldown = {k: v for k, v in _cooldown.items() if _now - v < 300}
                main_loop._cooldown = _cooldown

                ready = find_all_ready_missions(reg, slots_available)
                for mission in ready:
                    if mission["id"] in inflight:
                        log(f"⏭ Mission {mission['id']} déjà en vol (worker vivant ou active) — pas de re-soumission")
                        continue
                    if mission["id"] in _cooldown:
                        _remaining = int(300 - (_now - _cooldown[mission["id"]]))
                        log(f"⏳ Mission {mission['id']} en cooldown ({_remaining}s restants) — pas de re-soumission")
                        continue
                    order_id = submit_mission(mission)
                    active_orders[order_id] = {
                        "mission_id": mission["id"],
                        "submitted_at": time.time(),
                        "attempt": 1,
                        "max_attempts": 3
                    }
                    inflight.add(mission["id"])
                    log(f"🎯 Mission {mission['id']} lancée ({len(active_orders)}/{max_parallel} slots)")
            
            # Vérifier si on a des missions actives à surveiller
            if not active_orders:
                # Aucune mission active, vérifier si tout est fini
                reg = load_registry()
                all_done = all(m.get("status") == "done" for m in reg["missions"])
                if all_done:
                    log("🎉 TOUTES LES MISSIONS TERMINÉES !")
                    break
                else:
                    log("⏸ Aucune mission active ni prête. Attente 30s...")
                    time.sleep(30)
                    continue
            
            # Attendre qu'UNE mission finisse
            log(f"⏳ Surveillance de {len(active_orders)} mission(s) active(s)...")
            result = wait_for_any_result(active_orders)
            
            if result:
                order_id, result_data = result
                mission_info = active_orders.pop(order_id)
                mission_id = mission_info["mission_id"]
                attempt = mission_info.get("attempt", 1)
                max_attempts = mission_info.get("max_attempts", 3)
                
                verified, why = (False, "résultat non exploitable")
                if check_result_success(result_data):
                    verified, why = verify_mission(order_id, mission_id, result_data)
                if check_result_success(result_data) and verified:
                    log(f"✅ Mission {mission_id} RÉUSSIE — {why}")
                    update_mission(
                        mission_id,
                        status="done",
                        completed_at=datetime.now().isoformat(),
                        worker_result=result_data.get("worker_result", {}),
                        verified=why,
                    )
                    log("📝 Registry mis à jour → done (vérifié)")
                else:
                    if check_result_success(result_data):
                        log(f"🚫 Mission {mission_id} ANNONCÉE done mais NON VÉRIFIÉE: {why}")
                    # Échec : retry si attempts restants
                    if attempt < max_attempts:
                        log(f"🔄 Mission {mission_id} ÉCHOUÉE (tentative {attempt}/{max_attempts}), retry...")
                        reg = load_registry()
                        mission = get_mission(reg, mission_id)
                        if mission:
                            mission["status"] = "pending"
                            save_registry(reg)
                            # Cooldown 5 min pour cette mission
                            _cd = getattr(main_loop, "_cooldown", {})
                            _cd[mission_id] = time.time()
                            main_loop._cooldown = _cd
                        # Resoumettre avec attempt+1, sauf si la mission a été
                        # marquée done entre-temps (doublon d'order id).
                        time.sleep(10)
                        reg = load_registry()
                        mission = get_mission(reg, mission_id)
                        if mission and mission.get("status") == "done":
                            log(f"⏭ Mission {mission_id} déjà done — retry annulé")
                            mission = None
                        if mission:
                            new_order_id = submit_mission(mission)
                            active_orders[new_order_id] = {
                                "mission_id": mission_id,
                                "submitted_at": time.time(),
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts
                            }
                            log(f"🔄 Retry {attempt+1}/{max_attempts} pour mission {mission_id}")
                    else:
                        log(f"❌ Mission {mission_id} ÉCHOUÉE DÉFINITIVEMENT après {max_attempts} tentatives")
                        reg = load_registry()
                        mission = get_mission(reg, mission_id)
                        if mission:
                            mission["status"] = "failed"
                            save_registry(reg)
            else:
                # Timeout global ou plus de missions actives
                log("⏸ Attente terminée sans résultat clair, réévaluation...")
                time.sleep(10)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            log(f"❌ Erreur boucle: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)
    
    log("🛑 Mission Driver arrêté")

if __name__ == "__main__":
    import time  # pour submit_mission
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    main_loop()