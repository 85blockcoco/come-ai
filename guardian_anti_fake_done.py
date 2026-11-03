#!/usr/bin/env python3
"""Gardien anti-faux-done v2 — protocole push_verified.
- Ne vérifie QUE les missions 'done' sans le marqueur push_verified=true.
- Si une branche correspondante existe sur origin (worker/cvboost-<id>-*, agent/*,
  ou alias SPECS, ou contenu fusionné dans main pour les anciennes) → push_verified=true.
- Sinon → revert 'pending' + log (protection contre les races to_A.json)."""
import json
import re
import subprocess
import time

PATH = 'missions_registry.json'
ALIAS = {
    '34': ['spec-004'], '35': ['spec-005'], '36': ['spec-006'], '38': ['spec-008'],
    '40': ['spec-010'], '41': ['sk14'], '46': ['spec-011'], '47': ['spec-012'],
    '49': ['spec-014'], '50': ['spec-015'], '52': ['spec-017'], '58': ['spec-023'],
    '48': ['spec-013'], '55': ['spec-020'], '56': ['spec-021'], '57': ['spec-022'],
    '59': ['spec-024'], '44': ['sk19', 'spec-019'], '45': ['sk20', 'spec-020'],
    '53': ['spec-018'], '54': ['spec-019-sk'], '10': ['integration'],
}
# Content-based信任: modules clés attendus dans main si aucune branche dédiée
MAIN_PROBES = {
    '01': 'career/cv_quality', '02': 'career/offer_requirements', '03': 'career/cv_variants',
    '04': 'career/ocr', '05': 'career/application_prep', '06': 'career/connectors',
    '07': 'career/cv_quality', '08': 'career/cv_fit', '09': 'career/application_dashboard',
    '10': 'career/service', '11': 'career/connectors', '13': 'career/scoring',
    '16': 'career/offer_qualification', '21': 'career/cv_fit', '30': 'career/discovery',
    '31': 'career/profile_readiness', '32': 'career/qualification_persistence',
}

def origin_refs():
    out = subprocess.run(['git', 'ls-remote', '--heads', 'origin'],
                         capture_output=True, text=True, timeout=60).stdout
    return out

def has_main_content(mid):
    probe = MAIN_PROBES.get(mid)
    if not probe:
        return False
    subprocess.run(['git', 'show', '--name-only', '--format=', 'origin/main'],
                   capture_output=True, text=True, timeout=60)
    subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'origin/main'],
                   capture_output=True, text=True, timeout=60)
    out = subprocess.run(['git', 'ls-tree', '-r', '--name-only', 'origin/main'],
                         capture_output=True, text=True, timeout=60).stdout
    return any(f.startswith(probe) for f in out.splitlines())

def branch_ok(ls_text, mid):
    for ref in re.findall(r'refs/heads/(\S+)', ls_text):
        if re.search(r'(worker|agent)/[a-z0-9-]*cvboost-' + re.escape(mid) + r'(-|\b)', ref):
            return True
        if re.search(r'(worker|agent)/[a-z0-9-]*cvboost-{0}'.format(re.escape(mid)) + r'\b', ref):
            return True
        for a in ALIAS.get(mid, []):
            if re.search(r'(worker|agent)/[a-z0-9-]*' + re.escape(a) + r'(-|_|\b)', ref, re.I):
                return True
    return False

def check(mid, ls_text):
    if branch_ok(ls_text, mid):
        return True
    return has_main_content(mid)

def main():
    while True:
        time.sleep(90)
        try:
            reg = json.load(open(PATH, encoding='utf-8'))
            if not any(m['status'] == 'done' and not m.get('push_verified') for m in reg['missions']):
                continue
            ls_text = origin_refs()
            changed = False
            for m in reg['missions']:
                if m['status'] != 'done' or m.get('push_verified'):
                    continue
                mid = m['id']
                if check(mid, ls_text):
                    m['push_verified'] = True
                    changed = True
                    print(f"[guardian v2] push/content VÉRIFIÉ pour mission {mid}", flush=True)
                else:
                    m['status'] = 'pending'
                    m.pop('worker_result', None)
                    m.pop('completed_at', None)
                    m.pop('push_verified', None)
                    changed = True
                    print(f"[guardian v2] faux done annulé: mission {mid} (ni branche origin, ni contenu main — probe {MAIN_PROBES.get(mid)})", flush=True)
            if changed:
                json.dump(reg, open(PATH, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[guardian v2] err {e}", flush=True)

if __name__ == '__main__':
    main()
