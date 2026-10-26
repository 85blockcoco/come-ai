# -*- coding: utf-8 -*-
"""Gestionnaire de santé du pool de modèles workers.

Rôles:
1. PROBE: tester chaque modèle avec un ping minimal → OK / LIMIT / UNAVAIL / SLOW.
2. SCORE: modèle OK → score = 60/latence (plus vite = meilleur).
3. COOLDOWN ADAPTATIF: modèle LIMIT → mis DE CÔTÉ (jamais oublié), retesté à
   cooldown_until. Base 90 min; ajustée par la latence de reset OBSERVÉE
   (si reset vu après 40 min réelles, prochain cooldown ≈ EMA observé borné).
4. pick_pool(): rend le pool ordonné du MEILLEUR au pire (OK triés par score,
   puis cooling arrivés à échéance).
État persistant: model_health.json. Probes: log model_health.log.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path("/Users/comedelavenne/AI-Excel-Agent")
STATE = ROOT / "model_health.json"
LOGF = ROOT / "model_health.log"

ALL_MODELS = [
    # Modèles gratuits réellement disponibles (vérifiés le 25/10: répondent OK).
    # Ils étaient absents du pool: la flotte ne tentait que des opencode-go/*
    # à quota épuisé, d'où des échecs instantanés en série.
    "opencode/big-pickle",
    "opencode/nemotron-3.5-super-vl-free",
    "opencode/mimo-v2.6-flash-free",
    "opencode/deepseek-v4.1-flash-free",
    "google/gemma-4-26b-a4b-it",
    "google/gemini-3.1-flash-lite",
    "opencode-go/minimax-m3.1-flash", "opencode-go/gemini-4-argon-contributor",
    "opencode-go/claude-haiku-5-5", "opencode-go/beam-free", "opencode-go/mimo-v2.6-flash",
    "opencode-go/gpt-6-luna", "opencode-go/grok-4.7", "opencode-go/step-5-preview",
    "opencode-go/deepseek-v4.1-flash", "opencode-go/muse-spark-1.3-contributor",
    "opencode-go/hy4-preview", "opencode-go/glm-5.3-flash", "opencode-go/qwen3.8-flash",
    "opencode-go/glm-5.3", "opencode-go/qwen3.8-max", "opencode-go/kimi-k3",
    "opencode-go/longcat-2.0", "opencode-go/kimi-k2.7-code", "opencode-go/qwen3.7-plus",
    "opencode-go/minimax-m3", "opencode-go/deepseek-v4-pro", "opencode-go/mimo-v2.5-pro",
    "opencode-go/mimo-v2.5",
]

# Seuls ces modèles sont utilisés par la flotte : ils ont été vérifiés un par un
# (réponse réelle + latence). Les opencode-go/* se bloquent en attente d'API
# (60 min à 0,2 % CPU, aucun fichier écrit) : exclus.
VERIFIED_MODELS = [
    # demandé par Côme le 26/10 (GLM 5.3 Flash "roule bien") — pool mixte :
    # Go d'abord (choix utilisateur), puis gratuits quand ils reviennent de froid.
    "opencode-go/glm-5.3-flash",
    "opencode/deepseek-v4.1-flash-free",
    "opencode/big-pickle",
    "opencode/mimo-v2.6-flash-free",
    "opencode/nemotron-3.5-super-vl-free",
    "google/gemma-4-26b-a4b-it",
]
ALL_MODELS = list(VERIFIED_MODELS)

LIMIT_PAT = re.compile(r"429|quota|rate limit|limit|credit|insufficient|balance|exhaust|usage cap|billing", re.I)
UNAVAIL_PAT = re.compile(r"unavailable|not found|error|failed|no such model", re.I)

def log(msg):
    line = f"[mh {time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOGF.open("a") as f:
        f.write(line + "\n")

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"models": {}, "observations": {}, "updated_at": 0}

def save_state(s):
    s["updated_at"] = time.time()
    STATE.write_text(json.dumps(s, indent=1))

def probe_once(model, timeout=40):
    """Ping minimal. Renvoie (verdict, latence_s, extrait)."""
    start = time.time()
    try:
        r = subprocess.run(
            ["opencode", "run", "-m", model, "--title", f"probe-{int(time.time())}",
             "Réponds uniquement avec le mot: OK"],
            capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        out = (r.stdout or "") + (r.stderr or "")
        lat = round(time.time() - start, 1)
        # Un message d'erreur peut contenir \"OK\" par hasard (ANSI, nom de
        # modèle...). On classe d'abord les erreurs, ensuite on exige un vrai
        # \"OK\" isolé.  Sans ça, un modèle à quota épuisé était marqué OK et
        # brûlait tous les slots de la flotte.
        limit = LIMIT_PAT.search(out)
        if limit:
            return "LIMIT", lat, limit.group(0) + " | " + out[:120].replace("\n", " ")
        if re.search(r"(?<![A-Za-z])OK(?![A-Za-z])", out):
            return "OK", lat, out[:150].replace("\n", " ")
        return "UNAVAIL", lat, out[:150].replace("\n", " ")
    except subprocess.TimeoutExpired:
        return "SLOW", round(time.time() - start, 1), "timeout sans réponse"

def probe_all(models=None, workers=6):
    s = load_state()
    models = models or ALL_MODELS
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(probe_once, m): m for m in models}
        for f in as_completed(futs):
            m = futs[f]
            v, lat, extra = f.result()
            results[m] = (v, lat, extra)
            log(f"{m}: {v} ({lat}s) {extra[:80]}")
    apply_results(s, results)
    save_state(s)
    return results

def apply_results(s, results):
    now = time.time()
    for m, (v, lat, extra) in results.items():
        st = s["models"].setdefault(m, {"verdict": "UNAVAIL", "score": 0, "cooldown_until": 0,
                                        "fails": 0, "last_reset_wait": None, "ok_count": 0})
        st["last_probe"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if v == "OK":
            st["verdict"] = "OK"
            st["score"] = round(60.0 / max(lat, 1.5), 2)
            st["ok_count"] = st.get("ok_count", 0) + 1
            # LEÇON du reset observé: si le modèle revient AVANT/AUTOUR du cooldown,
            # enregistrer le vrai temps de recharge (plafonné à la sortie du cooldown).
            cdu = st.get("cooldown_until", 0)
            if cdu and st.get("cooldown_set_at"):
                observed = round(min((now - st["cooldown_set_at"]) / 60.0, 180.0), 0)
                obs = st.setdefault("observed_resets", [])
                obs.append((st["last_limit_reason"] or "?", observed))
                obs = obs[-6:]
                st["observed_resets"] = obs
                # EMA du temps de recharge par raison de limite
                k = st["last_limit_reason"] or "limit"
                ema = s["observations"].setdefault(k, {"wait_min": 90, "n": 0})
                ema["n"] += 1
                ema["wait_min"] = round(0.6 * ema["wait_min"] + 0.4 * observed, 1)
            st["cooldown_until"] = 0
            st["cooldown_set_at"] = 0
            st["fails"] = 0
        elif v == "LIMIT":
            if st.get("verdict") == "OK":
                st["fails"] = 0
            st["verdict"] = "LIMIT"
            st["fails"] = st.get("fails", 0) + 1
            st["last_limit_reason"] = (extra.split("|")[0].strip().lower()[:24]) or "limit"
            base = s["observations"].get(st["last_limit_reason"], {}).get("wait_min", 90.0)
            wait = max(30.0, min(150.0, base * (1.25 if st["fails"] > 1 else 1.0)))
            st["cooldown_until"] = now + wait * 60
            st["cooldown_set_at"] = now
            st["cooldown_next_min"] = wait
        else:  # UNAVAIL / SLOW
            st["verdict"] = v
            st["score"] = 0
            if v == "SLOW":
                # régime dégradé: de côté, retest court (~20 min)
                st["cooldown_until"] = now + 20 * 60
                st["cooldown_set_at"] = now
            st["fails"] = st.get("fails", 0) + 1

def record_limit(model, reason="limit"):
    """Le runtime constate une limite/indispo → cooldown adaptatif immédiat."""
    s = load_state()
    apply_results(s, {model: ("LIMIT", 0.0, f"{reason} (runtime)")})
    save_state(s)

def mark_run_ok(model, duration_s=0.0):
    """Un run réel réussi (travail vrai) confirme la santé du modèle."""
    s = load_state()
    st = s["models"].setdefault(model, {"verdict": "OK", "score": 0, "cooldown_until": 0,
                                        "fails": 0, "ok_count": 0})
    if st["verdict"] != "OK":
        st["verdict"] = "OK"
        st["fails"] = 0
        st["cooldown_until"] = 0
        st["cooldown_set_at"] = 0
        log(f"{model} réconfirmé OK par run runtime ({duration_s}s)")
    save_state(s)

def pick_pool(exclude_local_dormant=True):
    """Pool ordonné: meilleurs OK d'abord, puis cooling dont le cooldown est écoulé."""
    s = load_state()
    now = time.time()
    ok = [(m, st) for m, st in s["models"].items()
          if st["verdict"] == "OK" and m in VERIFIED_MODELS]
    ok.sort(key=lambda x: -x[1]["score"])
    pool = [m for m, _ in ok]
    for m, st in s["models"].items():
        if (st["verdict"] in ("LIMIT", "SLOW") and m in VERIFIED_MODELS
                and st.get("cooldown_until", 0) <= now):
            pool.append(m)
    return pool

def refresh_due():
    """Reteste uniquement les modèles en cooldown arrivés à échéance."""
    s = load_state()
    now = time.time()
    due = [m for m, st in s["models"].items()
           if st.get("verdict") in ("LIMIT", "SLOW") and st.get("cooldown_until", 0) - 240 <= now]
    if due:
        log(f"retest échus: {due}")
        probe_all(due, workers=len(due))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    if cmd == "probe":
        probe_all()
    elif cmd == "pool":
        for i, m in enumerate(pick_pool(), 1):
            print(f"{i}. {m}")
    else:  # cycle: retester les échus puis afficher le pool
        refresh_due()
        for i, m in enumerate(pick_pool(), 1):
            print(f"{i}. {m}")
