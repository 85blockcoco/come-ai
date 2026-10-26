#!/usr/bin/env python3
"""
Orchestrateur Agent A ↔ Workers — Version PARALLÈLE (ThreadPoolExecutor)
Gère jusqu'à 4 workers simultanés via un pool de threads.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
MESSAGES = ROOT / "messages"
FROM_A = MESSAGES / "from_A.json"
TO_A = MESSAGES / "to_A.json"
TASK_FILE = MESSAGES / "task.json"
RESULT_FILE = MESSAGES / "result.json"
LOG_FILE = ROOT / "orchestrator.log"

# File d'attente parallèle: une mission = un fichier.  Le driver dépose dans
# queue/, l'orchestrateur réclame atomiquement vers inflight/, puis publie le
# résultat dans results/<order_id>.json.  from_A.json reste alimenté pour la
# compatibilité (observabilité), mais n'est plus le seul slot disponible.
QUEUE_DIR = MESSAGES / "queue"
INFLIGHT_DIR = MESSAGES / "inflight"
RESULTS_DIR = MESSAGES / "results"

# Contrat de reporting ajouté à CHAQUE prompt worker: sans ce bloc, certains
# workers rendent le travail sans écrire result.json et la mission est comptée
# comme échouée alors que le code est livré.
WORKER_REPORTING_FOOTER = """

---

## CONTRAT DE SORTIE (OBLIGATOIRE, À FAIRE EN DERNIER)

### INTERDICTIONS (elles saturent la machine et te font échouer)
- **NE LANCE JAMAIS la suite complète** (`pytest -q` sans argument, 6000+ tests).
  Uniquement les fichiers de test liés à TA mission.
- **NE LANCE JAMAIS `find /` ni de recherche sur tout le disque.** Tout ce dont
  tu as besoin est déjà dans ce worktree.
- **N'INSTALLE RIEN** : pas de `pip install`, pas de `npm install`.

### À FAIRE
1. Tests ciblés uniquement :
   `.venv/bin/python -m pytest -q tests/test_<ta_feature>.py`
   puis `ruff check <fichiers modifiés>`.
2. Écris `messages/result.json` DANS CE WORKTREE avec exactement :

```json
{
  "status": "done",
  "files_created": ["chemin/relatif/fichier.py", "tests/test_x.py"],
  "output": "Résumé en 1-2 phrases de ce qui est livré",
  "logs": "dernières lignes de pytest ciblé / ruff",
  "error": null
}
```

`status` vaut `"done"` seulement si les tests pertinents passent et que le code
est réellement écrit. Sinon `"failed"` avec `error` renseigné.
Ne termine jamais sans avoir écrit ce fichier.
Budget : 25 minutes maximum. Au-delà, écris `result.json` avec ce qui marche
et `status: "done"` si le code est utilisable, sinon `"failed"` + la cause.
"""

POLL_INTERVAL = 3  # secondes# MAX_WORKERS permet de limiter la machine secondaire (ex: 2) sans toucher
# au registre partagé. Absent = 4 (comportement historique).
MAX_PARALLEL_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))

# Lock pour accès thread-safe aux fichiers partagés
file_lock = threading.RLock()  # Reentrant lock pour éviter deadlock dans write_from_a_status

@dataclass
class FromA:
    order_id: str
    status: str  # "waiting" | "ready_for_worker" | "processing"
    verifications_done: list[str]
    prompt_for_worker: str

@dataclass
class ToA:
    from_: str = "orchestrator"
    to: str = "agent_A"
    worker_result: dict = None
    completed_at: str = ""

@dataclass
class Task:
    order_id: str
    prompt: str
    worktree_path: str
    branch: str

def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def read_from_a() -> Optional[FromA]:
    with file_lock:
        if not FROM_A.exists():
            return None
        try:
            data = json.loads(FROM_A.read_text(encoding="utf-8"))
            return FromA(**data)
        except Exception as e:
            log(f"ERREUR lecture from_A.json: {e}")
            return None

def write_from_a_status(status: str, order_id: str = "") -> None:
    """Écrit le status dans from_A.json de façon thread-safe."""
    with file_lock:
        if not FROM_A.exists():
            return
        try:
            data = json.loads(FROM_A.read_text(encoding="utf-8"))
            data["status"] = status
            if order_id:
                data["order_id"] = order_id
            FROM_A.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            log(f"ERREUR écriture from_A.json: {e}")

def write_to_a(to_a: ToA) -> None:
    with file_lock:
        MESSAGES.mkdir(exist_ok=True)
        TO_A.write_text(json.dumps(asdict(to_a), ensure_ascii=False, indent=1), encoding="utf-8")


def publish_result(order_id: str, mission_id: str | None, result: dict) -> None:
    """Publie le résultat d'une mission dans results/<order_id>.json.

    Un fichier par mission: indispensable pour que plusieurs workers en
    parallèle ne s'écrasent pas mutuellement (l'ancien to_A.json unique ne
    pouvait porter qu'un seul résultat).
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    worker_result = result.get("worker_result") or {}
    payload = {
        "from_": "orchestrator",
        "to": "agent_A",
        "mission_id": mission_id,
        "worker_result": {
            "task_id": order_id,
            "status": result.get("status", "failed"),
            "files_created": worker_result.get("files_created", []),
            "output": worker_result.get("output", ""),
            "logs": worker_result.get("logs", "")
            or ((result.get("stdout", "") or "") + "\n" + (result.get("stderr", "") or ""))[-4000:],
            "error": result.get("error") or worker_result.get("error") or "",
        },
        "duration_sec": result.get("duration_sec"),
        "model_used": result.get("model_used", ""),
        "pushed": bool(result.get("pushed")),
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    target = RESULTS_DIR / f"{order_id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)

def write_task(task: Task) -> None:
    with file_lock:
        MESSAGES.mkdir(exist_ok=True)
        TASK_FILE.write_text(json.dumps(asdict(task), ensure_ascii=False, indent=1), encoding="utf-8")

def read_result() -> Optional[dict]:
    with file_lock:
        if not RESULT_FILE.exists():
            return None
        try:
            return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None

def clear_result() -> None:
    with file_lock:
        if RESULT_FILE.exists():
            RESULT_FILE.unlink()

def set_from_a_waiting() -> None:
    """Remet from_A.json à status=waiting pour signaler qu'on peut envoyer la prochaine mission."""
    write_from_a_status("waiting", "")

def set_from_a_processing(order_id: str) -> None:
    """Marque from_A.json comme processing pour éviter le double traitement."""
    write_from_a_status("processing", order_id)

def create_worktree(order_id: str, base_branch: str | None = None) -> tuple[str, str]:
    """Crée un worktree dédié pour le worker. Retourne (path, branch_name)."""
    branch = f"worker/{order_id}"
    worktree_path = ROOT.parent / f"AI-Excel-Agent-worker-{order_id}"
    base_branch = base_branch or os.environ.get("WORKER_BASE_BRANCH", "main")

    # Nettoyer si existe déjà
    if worktree_path.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)],
                       cwd=ROOT, capture_output=True)

    # Supprimer la branche si elle existe (force delete)
    subprocess.run(["git", "branch", "-D", branch], cwd=ROOT, capture_output=True, check=False)

    # Créer la branche depuis la base
    subprocess.run(["git", "branch", branch, base_branch], cwd=ROOT, check=True)
    subprocess.run(["git", "worktree", "add", str(worktree_path), branch], cwd=ROOT, check=True)

    log(f"Worktree créé: {worktree_path} (branche {branch})")
    return str(worktree_path), branch

def remove_worktree(worktree_path: str, branch: str) -> None:
    """Nettoie le worktree et la branche."""
    subprocess.run(["git", "worktree", "remove", "--force", worktree_path],
                   cwd=ROOT, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=ROOT, capture_output=True)
    log(f"Worktree nettoyé: {worktree_path}")

def run_worker(worktree_path: str, prompt: str, order_id: str) -> dict:
    """Lance le worker (opencode run --auto) dans le worktree."""
    env = os.environ.copy()
    env["WORKER_ORDER_ID"] = order_id

    # Écrire le prompt dans un fichier temporaire pour éviter les problèmes d'échappement
    prompt_file = Path(worktree_path) / "WORKER_PROMPT.md"
    prompt_file.write_text(prompt + WORKER_REPORTING_FOOTER, encoding="utf-8")

    # Copier les fichiers référencés dans le worktree AVANT le lancement :
    # sans eux, l'agent lance `find / -name WORKER_TEMPLATE.md` (scan disque
    # complet, x8 workers = load average > 300 et machine à genoux).
    # Empêcher Spotlight d'indexer le worktree : chaque nouveau worktree
    # déclenche sinon un orage mdworker (load average > 300, CPU système 36%).
    try:
        _ni = Path(worktree_path) / ".metadata_never_index"
        if not _ni.exists():
            _ni.write_text("", encoding="utf-8")
    except Exception:
        pass

    for _name in ("WORKER_TEMPLATE.md",):
        _src = Path(__file__).resolve().parent / _name
        _dst = Path(worktree_path) / _name
        try:
            if _src.exists() and not _dst.exists():
                _dst.write_bytes(_src.read_bytes())
        except Exception as _copy_err:
            log(f"copie {_name} impossible: {_copy_err}")

    # Pool DYNAMIQUE trié par santé/performance (model_health.py):
    # les modèles OK d'abord (score = 60/latence), les LIMIT/SLOW reviennent
    # quand leur cooldown adaptatif échu (base 90 min, ajustée sur le reset
    # observé). Un modèle plafonné n'est jamais oublié, juste de côté.
    try:
        import model_health as mh
        _FREE_POOL = mh.pick_pool() or [
            "opencode/big-pickle",
            "opencode/nemotron-3.5-super-vl-free",
            "opencode/mimo-v2.6-flash-free",
            "opencode/deepseek-v4.1-flash-free",
        ]
    except Exception as pool_err:
        log(f"pool fallback (model_health indisponible: {pool_err})")
        _FREE_POOL = [
            "opencode/deepseek-v4.1-flash-free",
            "opencode/big-pickle",
            "opencode/mimo-v2.6-flash-free",
            "opencode/nemotron-3.5-super-vl-free",
        ]
    model = os.environ.get("WORKER_MODEL")
    # Pool personnalisé possible plusieurs modèles, séparés par des virgules.
    custom_pool = os.environ.get("WORKER_POOL")
    if custom_pool:
        _FREE_POOL[:] = [m.strip() for m in custom_pool.split(",") if m.strip()]
        model = None
    # Sélection du modèle de départ + retry auto sur les autres du pool si
    # quota/indisponibilité instantanée (429, "Model unavailable", ...).
    start_idx = 0
    if not model:
        start_idx = sum(int(c) for c in order_id if c.isdigit()) % len(_FREE_POOL)
    else:
        _FREE_POOL[:] = [model]

    log(f"Lancement worker dans {worktree_path}")
    start = time.time()

    for attempt, current_model in enumerate(list(_FREE_POOL)):
        idx = (start_idx + attempt) % len(_FREE_POOL)
        model = _FREE_POOL[idx]
        cmd = [
            "opencode", "run", "--auto",
            "-m", model,
            "--title", f"Worker-{order_id}",
            "@WORKER_PROMPT.md"
        ]
        log(f"Modèle: {model} (essai {attempt+1}/{len(_FREE_POOL)})")
        try:
            result = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=7200,  # 120 min max
                env=env
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "error": "Timeout (120 min)",
                "duration_sec": 7200
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "duration_sec": time.time() - start
            }

        duration = time.time() - start
        blob = (result.stdout or "") + (result.stderr or "")
        instant_death = duration < 60 and "opencode" not in blob.lower()[:200]
        quota_like = any(k in blob.lower() for k in (
            "quota", "rate limit", "exceeded your current", "model unavailable",
            "unavailable:", "too many requests"))
        if result.returncode == 0:
            try:
                mh.mark_run_ok(model, round(duration, 1))
            except Exception:
                pass
            break
        if quota_like or instant_death:
            try:
                mh.record_limit(model, "quota" if quota_like else "unavailable")
            except Exception:
                pass
            if attempt < len(_FREE_POOL) - 1:
                log(f"⚠️ Modèle {model} a échoué instantanément (quota/indisponible) → cooldown, essai suivant")
                continue
        break

    # Lire le fichier de résultat si le worker en a écrit un
    worker_result_file = Path(worktree_path) / "messages" / "result.json"
    worker_result = {}
    if worker_result_file.exists():
        try:
            worker_result = json.loads(worker_result_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    final_status = "done" if result.returncode == 0 else "failed"
    _worker_status = str(worker_result.get("status") or "").strip().lower()
    if _worker_status in ("done", "failed"):
        # Le worker est la source de vérité: un code retour 0 sans travail
        # réel ne doit jamais être compté comme un succès.
        final_status = _worker_status
    elif result.returncode == 0 and not worker_result:
        final_status = "failed"
    if result.returncode == 0 and duration < 90 and not worker_result:
        # "Polite exit": le worker a répondu une phrase de courtoisie et sorti
        # code 0 sans aucun travail (jamais vu après 90s de vrai travail).
        log(f"⚠️ {order_id}: sortie précoce sans travail ({duration:.1f}s) → traité comme ÉCHEC")
        final_status = "failed"

    return {
        "status": final_status,
        "exit_code": result.returncode,
        "stdout": result.stdout[-5000:] if result.stdout else "",
        "stderr": result.stderr[-5000:] if result.stderr else "",
        "duration_sec": round(duration, 1),
        "worker_result": worker_result,
        "model_used": model
    }

def process_mission(order_id: str, prompt: str, mission_id: str | None = None) -> tuple[str, dict]:
    """Traite une mission complète. Retourne (order_id, result)."""
    log(f"=== DÉBUT MISSION {order_id} ===")

    # Marquer immédiatement comme "processing" pour éviter le double traitement
    set_from_a_processing(order_id)

    # 1. Créer worktree
    worktree_path, branch = create_worktree(order_id)

    if not prompt.strip():
        # Un prompt vide produit un worker qui sort immédiatement: on échoue
        # tout de suite plutôt que de brûler un slot.
        log(f"⚠️ {order_id}: prompt vide → échec immédiat")
        result = {"status": "failed", "error": "prompt vide", "duration_sec": 0.0}
        publish_result(order_id, mission_id, result)
        with file_lock:
            (INFLIGHT_DIR / f"{order_id}.json").unlink(missing_ok=True)
        return order_id, result

    try:
        # 2. Écrire task.json pour le worker
        task = Task(
            order_id=order_id,
            prompt=prompt,
            worktree_path=worktree_path,
            branch=branch
        )
        write_task(task)

        # 3. Lancer worker
        result = run_worker(worktree_path, prompt, order_id)

        # 4. Écrire to_A.json pour Agent A
        to_a = ToA(
            worker_result={
                "task_id": order_id,
                "status": result.get("status", "failed"),
                "files_created": [],  # À remplir par le worker via result.json
                "output": "",
                "logs": result.get("stdout", "") + "\n" + result.get("stderr", ""),
                "error": result.get("error", "")
            },
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        )
        write_to_a(to_a)

        # 5. Pousser la branche AVANT de publier: un statut "done" sans
        #    branche sur origin n'est pas une preuve (règle du projet).
        pushed = False
        if result.get("status") == "done":
            try:
                _p = subprocess.run(["git", "push", "-u", "origin", branch],
                                    cwd=worktree_path, capture_output=True, text=True, timeout=180)
                if _p.returncode == 0:
                    pushed = True
                else:
                    log(f"⚠️ push {branch} refusé: {(_p.stderr or '')[-300:]}")
            except Exception as e:
                log(f"⚠️ push {branch} erreur: {e}")
            result["pushed"] = pushed

        # 6. Publier le résultat par mission (source de vérité en parallèle)
        publish_result(order_id, mission_id, result)

        log(f"Mission {order_id} terminée: {result.get('status')}")

    finally:
        # Marquer la fin: le fichier inflight disparaît une fois le résultat publié.
        try:
            (INFLIGHT_DIR / f"{order_id}.json").unlink(missing_ok=True)
        except Exception:
            pass
        # Nettoyage SÉCURISÉ: on ne supprime JAMAIS le worktree d'office.  On vérifie
        # d'abord sur origin que la branche du worker a bien été poussée. Sinon on
        # garde tout (protectino anti-race sur to_A.json / faux-dones).
        _pushed = False
        try:
            _r = subprocess.run(["git", "ls-remote", "--heads", "origin", branch],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
            _pushed = bool(_r.stdout.strip())
        except Exception:
            _pushed = False
        if result.get("status") == "done" and _pushed:
            remove_worktree(worktree_path, branch)
            log(f"Worktree nettoyé (push vérifié sur origin): {worktree_path}")
        else:
            log(f"Worktree CONSERVÉ ({'pas pousse' if not _pushed else 'resultat non-done'}): {worktree_path}")
        # 6. from_A.json redevient "waiting" seulement si plus rien n'est en vol
        try:
            still_inflight = list(INFLIGHT_DIR.glob("*.json"))
        except Exception:
            still_inflight = []
        if not still_inflight:
            set_from_a_waiting()
        log(f"=== FIN MISSION {order_id} ===")

    return order_id, result

def main_loop():
    log(f"=== ORCHESTRATEUR PARALLÈLE DÉMARRÉ (max {MAX_PARALLEL_WORKERS} workers) ===")
    log(f"Surveillance de {FROM_A}")

    # Initialiser from_A.json si absent
    with file_lock:
        if not FROM_A.exists():
            MESSAGES.mkdir(exist_ok=True)
            FROM_A.write_text(json.dumps({
                "order_id": "",
                "status": "waiting",
                "verifications_done": [],
                "prompt_for_worker": ""
            }, ensure_ascii=False, indent=1), encoding="utf-8")

    # Pool de threads pour paralléliser les workers
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        futures = {}  # future -> order_id

        while True:
            try:
                log(f"🔄 Boucle principale: {len(futures)} futures actifs")
                # 1. Vérifier les missions terminées
                done_futures = []
                for future, order_id in futures.items():
                    if future.done():
                        try:
                            order_id, result = future.result()
                            log(f"Mission {order_id} terminée: {result.get('status')} (durée: {result.get('duration_sec', 0)}s)")
                        except Exception as e:
                            log(f"ERREUR future {order_id}: {e}")
                        done_futures.append(future)

                # Nettoyer les futures terminés
                for f in done_futures:
                    futures.pop(f, None)

                # 2. Soumettre de nouvelles missions si slots disponibles
                slots_available = MAX_PARALLEL_WORKERS - len(futures)
                log(f"🔧 Slots disponibles: {slots_available}, futures: {len(futures)}")

                if slots_available > 0:
                    claimed = 0
                    for qfile in sorted(QUEUE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
                        if claimed >= slots_available:
                            break
                        try:
                            entry = json.loads(qfile.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        order_id = str(entry.get("order_id") or "").strip()
                        if not order_id:
                            qfile.unlink(missing_ok=True)
                            continue
                        # Réclamation atomique: queue/ -> inflight/
                        INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
                        dest = INFLIGHT_DIR / qfile.name
                        try:
                            qfile.replace(dest)
                        except Exception:
                            continue
                        with file_lock:
                            write_from_a_status("processing", order_id)
                        future = executor.submit(
                            process_mission,
                            order_id,
                            entry.get("prompt_for_worker", ""),
                            entry.get("mission_id"),
                        )
                        futures[future] = order_id
                        claimed += 1
                        log(f"🚀 Mission {order_id} réclamée depuis queue/ ({len(futures)}/{MAX_PARALLEL_WORKERS} workers)")
                    step_started = claimed > 0

                    # Compatibilité: ancien protocole mono-slot via from_A.json,
                    # uniquement si la queue parallèle est vide.
                    if not step_started and not any(QUEUE_DIR.glob("*.json")):
                        with file_lock:
                            if FROM_A.exists():
                                try:
                                    data = json.loads(FROM_A.read_text(encoding="utf-8"))
                                    log(f"🔍 from_A lu: status={data.get('status')}, order_id={data.get('order_id')}")
                                    if data.get("status") == "ready_for_worker" and data.get("order_id"):
                                        order_id = data["order_id"]
                                        log(f"✅ Condition remplie, soumission mission {order_id}")

                                        # Marquer comme processing immédiatement
                                        write_from_a_status("processing", order_id)
                                        log("📝 Status mis à jour: processing")

                                        # Soumettre au pool de threads
                                        future = executor.submit(process_mission, order_id, data.get("prompt_for_worker", ""))
                                        futures[future] = order_id
                                        log(f"🚀 Mission {order_id} soumise au pool ({len(futures)}/{MAX_PARALLEL_WORKERS} workers)")
                                except Exception as e:
                                    log(f"ERREUR lecture from_A.json: {e}")

                time.sleep(POLL_INTERVAL)
                # Heartbeat log every 30 seconds
                if int(time.time()) % 30 == 0:
                    log(f"💓 Heartbeat: {len(futures)}/{MAX_PARALLEL_WORKERS} workers actifs")

            except KeyboardInterrupt:
                log("Arrêt demandé")
                break
            except Exception as e:
                log(f"ERREUR boucle principale: {e}")
                time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    # Thread rafraîchisseur de santé modèles: toutes les 4 min, retest des
    # modèles en cooldown arrivés à échéance (détection du reset de quota)
    # et ré-ordre du pool. Jamais bloquant pour la boucle principale.
    import threading
    def _mh_refresh_loop():
        import model_health as mh
        while True:
            try:
                mh.refresh_due()
            except Exception as e:
                print(f"[mh-refresh] erreur: {e}", flush=True)
            time.sleep(240)
    threading.Thread(target=_mh_refresh_loop, daemon=True).start()
    main_loop()