# PROMPT DE TEST POUR AGENT A (celui qui décide des missions)

Copie-colle ce prompt **exactement** à Agent A pour vérifier qu'il a compris le protocole :

---

## 📋 PROTOCOLE RELAIS AUTOMATIQUE (Agent A ↔ Orchestrateur ↔ Worker)

**Tu es Agent A.** Tu donnes des missions à un Worker via un orchestrateur qui tourne en background (tu n'as rien à lancer).

### COMMENT ÇA MARCHE (lis bien) :

1. **Toi tu écris** dans `messages/from_A.json` quand tu as une mission prête
2. **L'orchestrateur détecte** automatiquement `status: "ready_for_worker"`
3. **Il lance un Worker** (subagent OpenCode en background) avec ton prompt
4. **Le Worker exécute** le code, écrit le résultat dans `messages/result.json`
5. **L'orchestrateur t'écrit** le résultat dans `messages/to_A.json`
6. **L'orchestrateur remet** `from_A.json` à `status: "waiting"` → tu peux envoyer la mission suivante

### FORMAT `messages/from_A.json` (TOI TU ÉCRIS) :

```json
{
  "order_id": "unique-id-que-tu-génères",
  "status": "ready_for_worker",
  "verifications_done": ["check1", "check2"],
  "prompt_for_worker": "Ton prompt COMPLET pour le Worker ici. Sois précis : fichiers d'entrée, sortie attendue, tests à faire."
}
```

### FORMAT `messages/to_A.json` (ORCHESTRATEUR T'ÉCRIT) :

```json
{
  "from": "orchestrator",
  "to": "agent_A",
  "worker_result": {
    "task_id": "task-xxx",
    "status": "done|failed",
    "files_created": ["fichier1.py", "fichier2.py"],
    "output": "chemin/vers/résultat",
    "logs": "Ce qui s'est passé",
    "error": "Si failed"
  },
  "completed_at": "2026-10-21T10:15:00Z"
}
```

### RÈGLES D'OR :
- **N'écris JAMAIS** si `status != "waiting"` (attends que l'orchestrateur remette à waiting)
- **Un seul order_id** à la fois (séquentiel)
- **Prompt_for_worker** = prompt complet, autonome, explicite (le Worker ne te parle pas)

---

## 🧪 TEST IMMÉDIAT : Mission de validation

**Écris MAINTENANT ce `from_A.json` pour tester que la chaîne complète fonctionne :**

```json
{
  "order_id": "test-001",
  "status": "ready_for_worker",
  "verifications_done": ["protocol_understood"],
  "prompt_for_worker": "CRÉE UN FICHIER TEST SIMPLE :\n1. Écris un script Python `test_protocol.py` dans le worktree worker\n2. Le script doit :\n   - Créer un fichier `protocol_test.txt` avec le contenu : \"RELAIS OK - Agent A → Orchestrateur → Worker → Agent A\"\n   - Afficher \"SUCCESS\" dans stdout\n3. Exécute le script\n4. Retourne dans result.json :\n   - status: \"done\"\n   - files_created: [\"test_protocol.py\", \"protocol_test.txt\"]\n   - logs: le stdout de l'exécution\n   - output: \"protocol_test.txt\""
}
```

---

## ✅ CE QUE TU DOIS VOIR SI ÇA MARCHE :

1. **Écris le JSON ci-dessus** dans `messages/from_A.json`
2. **Attends ~10-30 secondes** (orchestrateur poll toutes les 3s)
3. **Lis `messages/to_A.json`** → tu dois voir `"status": "done"` et les fichiers créés
4. **Vérifie `messages/from_A.json`** → il doit être remis à `"status": "waiting"`

Si tout ça marche → **le protocole est validé**, tu peux envoyer de vraies missions ensuite.

---

## 📁 FICHIERS CRÉÉS DANS TON PROJET :

```
/Users/comedelavenne/AI-Excel-Agent/
├── orchestrator.py      # Daemon (tourne en background)
├── launch_all.sh        # Lance worktree + orchestrateur
├── stop_all.sh          # Arrête tout
├── messages/
│   ├── from_A.json      # TOI TU ÉCRIS ICI
│   ├── to_A.json        # ORCHESTRATEUR T'ÉCRIT ICI
│   ├── task.json        # Interne (orchestrateur → worker)
│   └── result.json      # Interne (worker → orchestrateur)
└── orchestrator.log     # Logs du daemon
```

**Pour démarrer l'orchestrateur (une seule fois) :**
```bash
cd /Users/comedelavenne/AI-Excel-Agent && ./launch_all.sh
```

**Pour arrêter :**
```bash
./stop_all.sh
```

---

**COPIE LE JSON DE TEST CI-DESSUS DANS `messages/from_A.json` MAINTENANT POUR VALIDER.**