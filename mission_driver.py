#!/usr/bin/env python3
"""
Mission Driver — Automatise l'enchaînement des missions CVBOOST.
Version PARALLÈLE : batch submit, max_parallel workers, détection done malgré kill.
"""
import json
import os
import time
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "missions_registry.json"
FROM_A = ROOT / "messages" / "from_A.json"
TO_A = ROOT / "messages" / "to_A.json"
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
    prompt = load_prompt(mission["prompt_file"])
    order_id = f"cvboost-{mission['id']}-{int(time.time())}"
    
    from_a_data = {
        "order_id": order_id,
        "status": "ready_for_worker",
        "verifications_done": [
            f"mission_{mission['id']}_dependencies_checked",
            "registry_validated"
        ],
        "prompt_for_worker": f"MISSION CVBOOST-{mission['id'].upper()} — {mission['title']}\n\n{prompt}"
    }
    
    FROM_A.parent.mkdir(exist_ok=True)
    
    # Attendre que l'orchestrateur soit libre (status == "waiting")
    for _ in range(120):  # max 2 min
        if FROM_A.exists():
            try:
                data = json.loads(FROM_A.read_text(encoding="utf-8"))
                if data.get("status") == "waiting":
                    break
            except:
                pass
        time.sleep(1)
    
    FROM_A.write_text(json.dumps(from_a_data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"📤 Mission {mission['id']} soumise (order: {order_id})")
    
    # Attendre que l'orchestrateur prenne la mission (status -> "processing")
    for _ in range(60):  # max 60s
        if FROM_A.exists():
            try:
                data = json.loads(FROM_A.read_text(encoding="utf-8"))
                if data.get("status") == "processing" and data.get("order_id") == order_id:
                    log(f"🔄 Orchestrateur a pris la mission {mission['id']}")
                    return order_id
            except:
                pass
        time.sleep(1)
    
    log(f"⚠️ Timeout attente prise en charge {mission['id']}, on continue quand même")
    return order_id

def wait_for_any_result(active: dict[str, dict], timeout: int = 14400) -> Optional[tuple[str, dict]]:
    """Attend qu'UNE des missions actives finisse. Retourne (order_id, result) ou None si timeout global.
    Vérifie aussi result.json dans le worktree si to_A.json n'est pas mis à jour."""
    start = time.time()
    last_log = 0
    log(f"⏳ wait_for_any_result: debut, timeout={timeout}, running={running}, active={list(active.keys())}")
    while time.time() - start < timeout and running:
        # Vérifier si on a encore des missions actives
        if not active:
            return None

        # 1a. Vérifier si l'orchestrateur a avancé (from_A en waiting/ready_for_worker ou nouvel order_id)
        #     → la mission précédente est terminée (succès ou échec)
        if FROM_A.exists():
            try:
                from_data = json.loads(FROM_A.read_text(encoding="utf-8"))
                from_status = from_data.get("status", "")
                from_order = from_data.get("order_id", "")
                # Cas 1: from_A en waiting ou ready_for_worker → orchestrator a fini UNE mission
                if from_status in ("waiting", "ready_for_worker"):
                    # Vérifier si from_order correspond à une mission active
                    if from_order and from_order in active:
                        # L'orchestrateur a vraiment fini cette mission
                        if TO_A.exists():
                            try:
                                to_content = TO_A.read_text(encoding="utf-8").strip()
                                if to_content:
                                    to_data = json.loads(to_content)
                                    wr = to_data.get("worker_result", {})
                                    task_id = wr.get("task_id", "") if isinstance(wr, dict) else ""
                                    for oid in list(active.keys()):
                                        if task_id and (oid in task_id or task_id in oid):
                                            log(f"🎯 Résultat trouvé via from_A avancé pour {oid}")
                                            return oid, to_data
                            except Exception:
                                pass
                        log(f"⚠️ from_A status={from_status}, mission {from_order} considérée échouée (pas de result)")
                        return from_order, {"from_": "orchestrator", "to": "agent_A",
                                       "worker_result": {"task_id": from_order, "status": "failed",
                                                        "files_created": [], "output": "", "logs": "worker failed (no result)",
                                                        "error": "no result.json"}, "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                    # Si from_order ne correspond à aucune mission active, from_A est juste idle → ne rien faire
                # Cas 2: from_A processing mais worker mort → échec
                if from_status == "processing" and from_order and from_order in active:
                    import subprocess as _sp3
                    ps_out = _sp3.run(["ps", "-ax", "-o", "command="], capture_output=True, text=True, timeout=10).stdout
                    if f"Worker-{from_order}" not in ps_out:
                        log(f"⚠️ Worker mort pour {from_order} (from_A processing mais pas de process) → échec")
                        return from_order, {"from_": "orchestrator", "to": "agent_A",
                                       "worker_result": {"task_id": from_order, "status": "failed",
                                                        "files_created": [], "output": "", "logs": "worker process dead",
                                                        "error": "process dead"}, "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            except Exception:
                pass

        # 1. Vérifier to_A.json (standard)
        if TO_A.exists():
            try:
                content = TO_A.read_text(encoding="utf-8").strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        wr = data.get("worker_result") or {}
                        task_id = wr.get("task_id", "") if isinstance(wr, dict) else ""
                        for order_id in list(active.keys()):
                            if task_id and (order_id in task_id or task_id in order_id or 
                                            order_id.split("-")[-1] in task_id or task_id.split("-")[-1] in order_id):
                                result = data
                                return order_id, result
            except Exception as e:
                log(f"⚠️ Erreur lecture to_A.json: {e}")
        
        # 2. Vérifier result.json dans les worktrees (fallback si orchestrateur n'a pas écrit to_A.json)
        for order_id in list(active.keys()):
            # Chercher le worktree correspondant
            worktree_path = ROOT.parent / f"AI-Excel-Agent-worker-{order_id}"
            result_file = worktree_path / "messages" / "result.json"
            if result_file.exists():
                try:
                    worker_result = json.loads(result_file.read_text(encoding="utf-8"))
                    if worker_result.get("status") == "done":
                        log(f"🎯 Résultat trouvé dans worktree pour {order_id} (fallback result.json)")
                        # Construire un result_data compatible
                        result_data = {
                            "from_": "orchestrator",
                            "to": "agent_A",
                            "worker_result": {
                                "task_id": order_id,
                                "status": "done",
                                "files_created": worker_result.get("files_created", []),
                                "output": worker_result.get("output", ""),
                                "logs": worker_result.get("logs", ""),
                                "error": worker_result.get("error", "")
                            },
                            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        }
                        return order_id, result_data
                except Exception as e:
                    log(f"⚠️ Erreur lecture worktree result.json: {e}")
        
        if time.time() - last_log > 30:
            elapsed = int(time.time() - min(v['submitted_at'] for v in active.values()))
            log(f"⏳ {len(active)} missions en cours... ({elapsed}s) — {list(active.keys())}")
            last_log = time.time()
        time.sleep(3)
    
    log(f"⏰ TIMEOUT global après {timeout}s")
    return None

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
    """Libère les orders dont le worker est mort sans result.json."""
    import subprocess as _sub
    for order in list(active.keys()):
        res = Path(ROOT.parent) / f"AI-Excel-Agent-worker-{order}" / "messages" / "result.json"
        if res.exists():
            continue
        pid = active[order].get("pid")
        still = False
        if pid:
            try:
                r = _sub.run(["ps", "-p", str(pid)], capture_output=True, text=True, timeout=5)
                still = str(pid) in r.stdout
            except Exception:
                still = False
        if not still:
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
                # Aussi vérifier from_A (seulement si processing activement)
                try:
                    from_data = json.loads(FROM_A.read_text(encoding="utf-8"))
                    from_order = from_data.get("order_id", "")
                    from_status = from_data.get("status", "")
                    if from_status == "processing" and from_order:
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
                
                if check_result_success(result_data):
                    log(f"✅ Mission {mission_id} RÉUSSIE")
                    reg = load_registry()
                    mission = get_mission(reg, mission_id)
                    if mission:
                        mission["status"] = "done"
                        mission["completed_at"] = datetime.now().isoformat()
                        mission["worker_result"] = result_data.get("worker_result", {})
                        save_registry(reg)
                        log("📝 Registry mis à jour → done")
                else:
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
                        # Resoumettre avec attempt+1
                        time.sleep(10)
                        reg = load_registry()
                        mission = get_mission(reg, mission_id)
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