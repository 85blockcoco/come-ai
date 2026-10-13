"""Explicit, small real-model benchmark on synthetic data; loopback only."""
from __future__ import annotations

import ast
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MODEL = "qwen3.5:2b-q4_K_M"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(endpoint, data=None, timeout=180):
    request = Request("http://127.0.0.1:11434/api/" + endpoint,
                      data=json.dumps(data).encode() if data is not None else None,
                      headers={"Content-Type": "application/json"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
        return json.loads(response.read(2_000_000))


def resources(root):
    # comm, not command-line arguments: credentials can never appear here.
    result = subprocess.run(["/bin/ps", "-axo", "pid=,rss=,pcpu=,comm="], capture_output=True, text=True, timeout=5)
    rows = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) == 4 and str(root / ".local-ai" / "ollama") in fields[3]:
            rows.append({"pid": int(fields[0]), "rss_bytes": int(fields[1]) * 1024, "cpu_percent": float(fields[2])})
    return {"ollama_processes": rows, "ollama_rss_bytes": sum(row["rss_bytes"] for row in rows),
            "ollama_cpu_percent": sum(row["cpu_percent"] for row in rows),
            "measurement": "ps RSS sum after request; CPU is ps lifetime average, not peak"}


def request_case(case):
    payload = {"model": MODEL, "messages": [{"role": "user", "content": case["prompt"]}],
               "think": False, "stream": True, "keep_alive": "5m",
               "options": {"num_ctx": 4096, "num_thread": 4, "num_predict": 128, "temperature": 0, "seed": 7}}
    if "format" in case:
        payload["format"] = case["format"]
    if "tools" in case:
        payload["tools"] = case["tools"]
    request = Request("http://127.0.0.1:11434/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    started = time.monotonic()
    first = None
    content, calls = [], []
    final = {}
    received = 0
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=180) as response:
        for line in response:
            received += len(line)
            if received > 2_000_000 or time.monotonic() - started > 180:
                raise ValueError("Benchmark response budget exceeded")
            item = json.loads(line)
            if item.get("error"):
                raise ValueError("Local model returned an error")
            message = item.get("message", {})
            if message.get("content") or message.get("tool_calls"):
                if first is None:
                    first = time.monotonic() - started
                content.append(message.get("content", ""))
                calls.extend(message.get("tool_calls", []))
            if item.get("done"):
                final = item
    duration = time.monotonic() - started
    rate = final.get("eval_count", 0) / (final.get("eval_duration", 0) / 1e9) if final.get("eval_duration") else None
    return {"name": case["name"], "output": "".join(content), "tool_calls": calls, "seconds": round(duration, 3),
            "first_response_seconds": round(first, 3) if first is not None else None,
            "tokens_per_second": round(rate, 3) if rate is not None else None,
            "input_tokens": final.get("prompt_eval_count"), "output_tokens": final.get("eval_count"),
            "load_seconds": final.get("load_duration", 0) / 1e9, "done_reason": final.get("done_reason")}


def check(result):
    name, output = result["name"], result["output"].strip()
    if name == "french":
        return "bonjour" in output.casefold() and len(output) > 12
    if name == "english":
        return "hello" in output.casefold() and len(output) > 12
    if name == "instructions":
        return output == "OK"
    if name == "summary":
        return "12" in output and "jeudi" in output.casefold() and "oral" in output.casefold()
    if name == "reasoning":
        return "42" in output
    if name == "json":
        return json.loads(output) == {"language": "fr", "total": 42}
    if name == "tools":
        calls = result["tool_calls"]
        return bool(calls) and calls[0].get("function", {}).get("name") == "calculate" and calls[0]["function"].get("arguments", {}).get("expression") == "6*7"
    if name == "code":
        code = output.removeprefix("```python").removeprefix("```").removesuffix("```").strip()
        tree = ast.parse(code)
        return any(isinstance(n, ast.FunctionDef) and n.name == "square" and
                   any(isinstance(r, ast.Return) and isinstance(r.value, ast.BinOp) and isinstance(r.value.op, ast.Mult)
                       for r in n.body) for n in tree.body)
    return False


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / ".devkit" / "intelligence"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    tool = {"type": "function", "function": {"name": "calculate", "description": "Compute an exact arithmetic expression.",
             "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}}
    cases = [
        {"name": "french", "prompt": "Réponds en français en une phrase commençant par Bonjour. Présente-toi comme un assistant local pour les cours."},
        {"name": "english", "prompt": "Reply in English in one sentence starting with Hello. Introduce yourself as a local study assistant."},
        {"name": "instructions", "prompt": "Réponds uniquement avec les deux lettres OK, sans ponctuation ni explication."},
        {"name": "summary", "prompt": "Résume en une phrase ces notes fictives : Le groupe doit remettre 12 diapositives jeudi. Lina prépare les chiffres. Hugo organise l'oral. Il ne faut ajouter aucun fait."},
        {"name": "code", "prompt": "Return only Python code, no markdown: def square(x) returning x multiplied by itself. No imports, no examples."},
        {"name": "reasoning", "prompt": "Dans un exercice fictif, 6 boîtes contiennent chacune 9 cartes. On retire 12 cartes au total. Combien reste-t-il ? Réponds par le nombre seulement."},
        {"name": "json", "prompt": "Return exactly a JSON object with language equal to fr and total equal to 42.",
         "format": {"type": "object", "properties": {"language": {"type": "string"}, "total": {"type": "integer"}}, "required": ["language", "total"], "additionalProperties": False}},
        {"name": "tools", "prompt": "Call the calculate tool with expression 6*7. Do not calculate mentally or write text.", "tools": [tool]},
    ]
    report = {"date": datetime.now(timezone.utc).isoformat(), "model": MODEL, "synthetic_only": True,
              "network": "Ollama server OS sandbox denies non-loopback networking", "settings": {"num_ctx": 4096, "num_thread": 4, "num_predict": 128, "think": False},
              "baseline_resources": resources(root), "cases": [], "scope": "Small smoke checks, not a general capability or comparative benchmark"}
    show = api("show", {"model": MODEL})
    report["details"] = show.get("details")
    report["capabilities"] = show.get("capabilities")
    started = time.monotonic()
    for case in cases:
        if time.monotonic() - started > 600:
            report["stopped_reason"] = "total_time_budget"
            break
        try:
            result = request_case(case)
            try:
                result["passed"] = check(result)
            except (ValueError, KeyError, SyntaxError, TypeError):
                result["passed"] = False
            result["resources"] = resources(root)
        except (OSError, ValueError):
            result = {"name": case["name"], "passed": False, "error_category": "local_request_failed"}
        report["cases"].append(result)
        from devkit.patching import _atomic_write
        _atomic_write(directory / "benchmark-local.json", json.dumps(report, ensure_ascii=False, indent=2).encode(), 0o600)
        print(json.dumps({k: result.get(k) for k in ("name", "passed", "seconds", "first_response_seconds", "tokens_per_second")}), flush=True)
        if result.get("resources", {}).get("ollama_rss_bytes", 0) > 8 * 1024**3:
            report["stopped_reason"] = "memory_budget"
            break
    rates = [c["tokens_per_second"] for c in report["cases"] if c.get("tokens_per_second")]
    report["median_tokens_per_second"] = statistics.median(rates) if rates else None
    report["passed"] = sum(bool(c["passed"]) for c in report["cases"])
    report["running_models"] = api("ps")
    _atomic_write(directory / "benchmark-local.json", json.dumps(report, ensure_ascii=False, indent=2).encode(), 0o600)
    lines = ["# Qwen local — mesures réelles", "", f"Modèle : {MODEL}", f"Contrôles réussis : {report['passed']}/{len(report['cases'])}",
             f"Débit médian : {report['median_tokens_per_second']} tokens/s", "", "Données exclusivement fictives. Un seul modèle testé ; aucun classement comparatif.", "",
             "| Contrôle | Réussi | Durée (s) | Première réponse (s) | Tokens/s |", "|---|---|---|---|---|"]
    lines += [f"| {c['name']} | {c['passed']} | {c.get('seconds', 'inconnu')} | {c.get('first_response_seconds', 'inconnu')} | {c.get('tokens_per_second', 'inconnu')} |" for c in report["cases"]]
    _atomic_write(directory / "benchmark-local.md", ("\n".join(lines) + "\n").encode(), 0o600)


if __name__ == "__main__":
    main()
