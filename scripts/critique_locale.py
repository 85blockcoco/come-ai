#!/usr/bin/env python3
"""Critique locale bornée : demander une seconde opinion au modèle Ollama local.

Le modèle local (`.local-ai`, réseau isolé) est utilisé UNIQUEMENT comme
critique de vérification sur des points bornés — jamais pour écrire du code de
production. Il ne peut répondre qu'OUI / NON / INCERTAIN et ne suppose rien.

Sécurité : l'URL doit pointer sur 127.0.0.1 ou localhost (refus explicite de
tout hôte externe), aucun envoi hors de la machine, aucun secret transporté.

Usage :
    python scripts/critique_locale.py --question "Le résumé contient-il une
    information absente de la source ?" --file extrait.txt --output verdict.json

Variables d'environnement :
    CRITIQUE_OLLAMA_URL (défaut http://127.0.0.1:11434)
    CRITIQUE_MODEL     (défaut qwen3.5:2b-q4_K_M)
    CRITIQUE_TIMEOUT   (défaut 60)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:2b-q4_K_M"

SYSTEM_PROMPT = (
    "Tu es un critique de vérification local et rigoureux. "
    "Réponds uniquement par l'un de ces mots en premier : OUI, NON ou INCERTAIN. "
    "Ne suppose jamais : si l'information n'est pas présente dans le texte fourni, "
    "réponds INCERTAIN. Ajoute ensuite une seule phrase d'explication factuelle."
)


def local_url(raw: str) -> str:
    """Refuse tout hôte autre que la machine locale."""
    value = (raw or DEFAULT_URL).strip()
    if not value.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        raise ValueError("L'URL de critique locale doit rester sur 127.0.0.1 ou localhost.")
    return value.rstrip("/")


def ask_local_model(*, question: str, text: str, url: str, model: str, timeout: int) -> dict[str, str]:
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": f"Question : {question}\n\nTEXTE FOURNI :\n{text}\n",
        "stream": False,
        # Le modèle local est un modèle « penseur » : sans cela il épuise son
        # budget de jetons en réflexion avant de répondre (réponse vide).
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 160},
    }
    request = urllib.request.Request(
        f"{url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec - hôte local uniquement
        body = json.loads(response.read(8 << 20).decode("utf-8"))
    raw = str(body.get("response", "")).strip()
    verdict = "INCERTAIN"
    head = raw.split("\n", 1)[0].strip().upper()
    for candidate in ("OUI", "NON", "INCERTAIN"):
        if head.startswith(candidate):
            verdict = candidate
            break
    return {"verdict": verdict, "explanation": raw, "model": model}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Critique locale bornée via Ollama.")
    parser.add_argument("--question", required=True, help="Question de vérification posée au modèle local.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--file", help="Fichier texte à soumettre à la critique.")
    source.add_argument("--text", help="Texte inline à soumettre à la critique.")
    parser.add_argument("--output", help="Écrire le verdict JSON dans ce fichier.")
    parser.add_argument("--url", default=os.environ.get("CRITIQUE_OLLAMA_URL", DEFAULT_URL))
    parser.add_argument("--model", default=os.environ.get("CRITIQUE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("CRITIQUE_TIMEOUT", "60")))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    text = arguments.text if arguments.text is not None else Path(arguments.file).read_text(encoding="utf-8")
    if not text.strip():
        print("Rien à soumettre à la critique.", file=sys.stderr)
        return 2
    try:
        verdict = ask_local_model(
            question=arguments.question, text=text,
            url=local_url(arguments.url), model=arguments.model, timeout=arguments.timeout,
        )
    except (ValueError, urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"verdict": "ERREUR", "explanation": str(error)}), file=sys.stderr)
        return 2
    rendered = json.dumps(verdict, ensure_ascii=False)
    print(rendered)
    if arguments.output:
        Path(arguments.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if verdict["verdict"] in {"OUI", "NON", "INCERTAIN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
