"""Deterministic, local-only bundle export for one application dossier.

SPEC-051 asks for a grouped ZIP export and a one-click copy.  This module owns
the two pure building blocks so the HTTP layer only has to move bytes:

* :func:`render_bundle_text` turns the already-computed ``ApplyKit`` payload
  into a plain-text dossier that is safe to paste anywhere;
* :func:`write_bundle_archive` writes a byte-for-byte reproducible ZIP with
  fixed entry names and timestamps.

Nothing here performs a network call, submits an application or decides which
documents exist: the caller passes the explicit list of local files.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

# Fixed timestamp makes two exports of the same dossier byte-identical, which
# keeps tests and local backups comparable.
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _text(value: Any, limit: int = 20_000) -> str:
    return str(value or "").strip()[:limit]


def _answers_block(answers: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for key in sorted(answers):
        value = _text(answers.get(key))
        if value:
            lines.append(f"- {key} : {value}")
    return "\n".join(lines) if lines else "- Aucune réponse enregistrée."


def _checklist_block(checklist: Iterable[Any]) -> str:
    lines: list[str] = []
    for item in checklist:
        if not isinstance(item, Mapping):
            continue
        done = "x" if item.get("done") else " "
        label = _text(item.get("label") or item.get("id") or "Étape")
        note = _text(item.get("note"))
        lines.append(f"- [{done}] {label}" + (f" — {note}" if note else ""))
    return "\n".join(lines) if lines else "- Aucune checklist."


def render_bundle_text(kit: Mapping[str, Any], job: Mapping[str, Any] | None = None) -> str:
    """Render the dossier as plain text suitable for the clipboard.

    The text only repeats values already present in the kit.  In particular it
    never invents a fact and always carries the manual-submission disclaimer.
    """

    job = job if isinstance(job, Mapping) else {}
    title = _text(job.get("title")) or _text(kit.get("title")) or "Offre"
    company = _text(job.get("company")) or _text(kit.get("company")) or "Entreprise"
    variant = kit.get("variant") if isinstance(kit.get("variant"), Mapping) else {}
    letter = kit.get("letter") if isinstance(kit.get("letter"), Mapping) else {}
    answers = kit.get("answers") if isinstance(kit.get("answers"), Mapping) else {}
    checklist = kit.get("checklist") if isinstance(kit.get("checklist"), list) else []
    blocks = [str(item) for item in (kit.get("block_reasons") or []) if str(item).strip()]

    header = [
        f"DOSSIER DE CANDIDATURE — {title} — {company}",
        "Généré localement · aucun envoi automatique.",
        f"Readiness : {int(kit.get('readiness') or 0)} %",
    ]
    if variant:
        header.append(f"Variante : {_text(variant.get('label')) or _text(variant.get('id')) or '—'}")
    if kit.get("deep_link"):
        header.append(f"Lien officiel : {_text(kit.get('deep_link'), 2_000)}")
    if blocks:
        header.append("Points à vérifier :")
        header.extend(f"- {item}" for item in blocks)

    sections = [
        "\n".join(header),
        "RÉPONSES PRÉREMPLIES\n" + _answers_block(answers),
        "LETTRE DE MOTIVATION\n" + (_text(letter.get("letter_markdown") or letter.get("markdown")) or "[Lettre à compléter]"),
        "CV (Markdown)\n" + (_text(letter.get("cv_markdown")) or "[CV à compléter]"),
        "CHECKLIST HUMAINE\n" + _checklist_block(checklist),
        "RAPPEL\nLa candidature est déposée manuellement sur le site officiel. "
        "Relis chaque preuve chiffrée avant l’envoi.",
    ]
    return "\n\n".join(sections).strip() + "\n"


def write_bundle_archive(
    target: Path,
    entries: Mapping[str, bytes],
    *,
    text: str | None = None,
) -> Path:
    """Write ``entries`` (plus optional ``dossier.txt``) into a deterministic ZIP."""

    payload: dict[str, bytes] = {}
    for name, content in entries.items():
        normalized = str(name).replace("\\", "/").strip("/")
        if not normalized or "/" in normalized or normalized in (".", ".."):
            raise ValueError(f"Nom d’entrée de ZIP invalide : {name!r}")
        payload[normalized] = bytes(content)
    if text is not None:
        payload["dossier.txt"] = text.encode("utf-8")

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(payload):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload[name])
    try:
        target.chmod(0o600)
    except OSError:  # pragma: no cover - best effort on exotic filesystems
        pass
    return target
