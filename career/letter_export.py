"""Controlled export of cover letters (N100-F07).

Exports to DOCX / PDF via ``document_export`` and to text/Markdown natively.
NEVER sends anything; the caller must have validated the letter (see
``letter_approval``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ALLOWED_FORMATS = ("docx", "pdf", "md", "txt")


def export_letter(
    *,
    letter_body: str,
    title: str,
    language: str,
    target: str | Path,
    fmt: str,
    approved: bool = False,
) -> dict[str, Any]:
    from career.letter_approval import is_approved

    fmt = (fmt or "").lower()
    if fmt not in ALLOWED_FORMATS:
        return {"ok": False, "error": f"format non supporté: {fmt} (autorisés: {ALLOWED_FORMATS})"}
    if not (letter_body or "").strip():
        return {"ok": False, "error": "corps de lettre vide"}
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt in ("docx", "pdf") and not approved and not is_approved(title):
        return {"ok": False, "error": "export DOCX/PDF bloqué : lettre non approuvée par un humain"}

    if fmt == "txt":
        target_path.write_text(letter_body, encoding="utf-8")
    elif fmt == "md":
        md = f"# {title}\n\n{letter_body}"
        target_path.write_text(md, encoding="utf-8")
    else:
        markdown = f"# {title}\n\n{letter_body}"
        if fmt == "docx":
            from career.document_export import write_docx

            write_docx(markdown=markdown, title=title, language=language, target=target_path)
        else:
            from career.document_export import write_pdf

            write_pdf(markdown=markdown, title=title, language=language, target=target_path)
    return {"ok": True, "path": str(target_path), "format": fmt}
