#!/usr/bin/env python3
"""Watchdog anti-hang pour la flotte workers cvboost.

Détecte les workers opencode figés à 0% CPU prolongé et les tue pour que
le driver les réap (reaper) et relance la mission — sans intervention humaine.

Signaux:
  - CPU TIME (accumulateur, pas %CPU) : si inchangé sur 2 échantillons
    successifs espacés de 90s → worker figé.
  - Seulement si etime > 6 min (un vrai worker peut penser/reseauter lentement
    au démarrage ; les 2 échantillons = ~4 min d'inactivité réelle cumulée).
  - Ne touche jamais aux processus non-opencode et jamais 2 fois le même worker.
"""
# -*- coding: utf-8 -*-
# Watchdog v2 — détection workers figés par DEUX signaux:
# 1. ACTIVITÉ fichiers: aucun fichier (hors .git) modifié dans le worktree
#    depuis STALL_MIN_MINUTES et etime > MIN_ETIME → kill (le signal fort).
# 2. CPU TIME immobile sur 2 échantillons → kill (signal secondaire).
# Le driver reaper détecte la mort, met cooldown et relance seul.
import os
import signal
import subprocess
import time
from pathlib import Path

SAMPLE_DT = 90
MIN_ETIME = 900          # 15 min de vie minimum
STALL_MIN_MINUTES = 20   # silence d'écriture 20 min → stall (le burst de checkout initial fait m negatively un faux positif sinon)
WORKER_ROOT = Path("/Users/comedelavenne")  # worktrees: ROOT/AI-Excel-Agent-worker-cvboost-*
LOG_PREFIX = "[watchdog2"

def now(): return time.strftime("%H:%M:%S")

def log(msg): print(f"{LOG_PREFIX} {now()}] {msg}", flush=True)

def list_workers():
    out = {}
    ps = subprocess.run(["ps", "-ax", "-o", "pid=,cputime=,etime=,command="],
                        capture_output=True, text=True).stdout
    for line in ps.splitlines():
        if "opencode" not in line or "Worker-cvboost-" not in line:
            continue
        try:
            parts = line.strip().split(None, 3)
            pid = int(parts[0])
            ct_s = sum(int(x) * m for x, m in zip(parts[1].split(":"), (3600, 60, 1)))
            if ct_s:
                out[pid] = {"cmd": parts[3], "cputime": ct_s}
        except Exception:
            continue
    return out

def worktree_for(cmd):
    """Extrait le chemin du worktree depuis la commande opencode --title Worker-cvboost-..."""
    import re
    m = re.search(r"Worker-cvboost-(\d+)-(\d+)", cmd)
    if not m:
        return None
    p = WORKER_ROOT / f"AI-Excel-Agent-worker-cvboost-{m.group(1)}-{m.group(2)}"
    return p if p.is_dir() else None

def recent_writes(wt, minutes):
    """Fichiers (hors .git) modifiés dans les N dernières minutes."""
    try:
        r = subprocess.run(["find", str(wt), "-type", "f", "-not", "-path", "*/.git/*",
                            "-newermt", f"-{minutes} minutes"],
                           capture_output=True, text=True, timeout=20)
        return len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:
        return -1  # inconnu → ne pas kill sur signal douteux

def etime_secs(pid):
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "etime="], capture_output=True, text=True)
        bits = [int(x) for x in r.stdout.strip().split(":")]
        if len(bits) == 3:
            return bits[0]*3600 + bits[1]*60 + bits[2]
        return bits[0]*60 + bits[1]
    except Exception:
        return 0

prev_cpu = {}
log("watchdog v2 démarré — signal=fichier-activité (20 min) + CPU (90s)")
while True:
    try:
        cur = list_workers()
        for pid, w in cur.items():
            wt = worktree_for(w["cmd"])
            et = etime_secs(pid)
            if et < MIN_ETIME or not wt:
                continue
            writes = recent_writes(wt, STALL_MIN_MINUTES)
            reason = None
            if writes == 0:
                reason = f"0 fichier écrit depuis {STALL_MIN_MINUTES} min (worktree {wt.name})"
            else:
                pc = prev_cpu.get(pid)
                if pc is not None and w["cputime"] == pc:
                    reason = f"cputime figé à {w['cputime']}s sur {SAMPLE_DT*2}s"
            if reason:
                log(f"⚠️ KILL pid {pid} ({w['cmd'][:60]}...): {reason}")
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception as e:
                    log(f"kill échoué: {e}")
        prev_cpu = {p: w["cputime"] for p, w in cur.items()}
        time.sleep(SAMPLE_DT)
    except KeyboardInterrupt:
        break
    except Exception as e:
        log(f"erreur: {e}")
        time.sleep(30)

