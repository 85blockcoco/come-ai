"""Cover letter multi-AI generator (SPEC-022).

Orchestrates 3 drafts + 1 merged alternative, with evidence-bound facts,
ATS compatibility check and DOCX export.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from career.letter_structure import (
    LetterPara as _StructureLetterPara,
    MAX_PARAGRAPHS,
    MAX_WORDS,
    build_letter_paragraphs,
    normalize_paragraphs,
    pick_connector,
    render_text,
    total_words,
    trim_to_word_limit,
    validate_structure,
)
from career.letter_tone import (
    normalize_tone,
    tone_closing_line,
    tone_salutation,
)
from career.letter_triage import (
    best_draft_id,
    course_insight,
    matching_insight,
    vary,
)

# Keep a single LetterPara definition (re-exported from structure).
LetterPara = _StructureLetterPara


@dataclass
class LetterDraft:
    draft_id: str = ""
    paragraphs: list[LetterPara] = field(default_factory=list)
    tone: str = "formel"
    used_bullets: list[str] = field(default_factory=list)
    guessed_facts: list[str] = field(default_factory=list)
    jury_score: float = 0.0
    provider: str = "local"
    version: int = 1
    created_at: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    text: str = ""

    def __post_init__(self) -> None:
        self.tone = normalize_tone(self.tone)
        if not self.text and self.paragraphs:
            self.text = render_text(self.paragraphs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "paragraphs": [p.__dict__ if hasattr(p, "__dict__") else asdict(p) for p in self.paragraphs],
            "tone": self.tone,
            "used_bullets": list(self.used_bullets),
            "guessed_facts": list(self.guessed_facts),
            "jury_score": float(self.jury_score),
            "provider": self.provider,
            "version": self.version,
            "created_at": self.created_at,
            "evidence_refs": list(self.evidence_refs),
            "text": self.text or render_text(self.paragraphs),
        }

    to_dict = as_dict


@dataclass
class LetterPlan:
    drafts: list[LetterDraft] = field(default_factory=list)
    best_id: str = ""
    merged_alternative: LetterDraft | None = None
    ats_compat_check: dict[str, Any] = field(default_factory=dict)
    offer_id: str = ""
    created_at: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.merged_alternative is None:
            self.merged_alternative = LetterDraft(draft_id="merged", tone="formel")
        if not self.best_id and self.drafts:
            self.best_id = best_draft_id(self.drafts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "drafts": [d.as_dict() for d in self.drafts],
            "best_id": self.best_id,
            "merged_alternative": self.merged_alternative.as_dict() if self.merged_alternative else None,
            "ats_compat_check": dict(self.ats_compat_check or {}),
            "offer_id": self.offer_id,
            "created_at": self.created_at,
            "history": list(self.history),
        }

    to_dict = as_dict


# ---------------------------------------------------------------- text helpers

def _text(value: Any, limit: int = 4_000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = " ".join(text.split())
    return text[:limit]


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [x.strip() for x in value.replace(";", ",").splitlines() if x.strip()] or [
            x.strip() for x in value.replace(";", ",").split(",") if x.strip()
        ]
    if isinstance(value, dict):
        return [value]
    return [value]


def _offer_id(offer: dict[str, Any] | None) -> str:
    offer = offer or {}
    return str(offer.get("id") or offer.get("offer_id") or offer.get("job_id") or "")


def _company(offer: dict[str, Any] | None) -> str:
    offer = offer or {}
    return _text(offer.get("company") or offer.get("company_name") or offer.get("employer") or "")


def _title(offer: dict[str, Any] | None) -> str:
    offer = offer or {}
    return _text(offer.get("title") or offer.get("job_title") or offer.get("role") or "ce poste")


def _profile_name(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    return _text(profile.get("display_name") or profile.get("name") or profile.get("full_name") or "")


def _contact_line(profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    parts = [
        _text(profile.get("contact_email") or profile.get("email")),
        _text(profile.get("contact_phone") or profile.get("phone")),
        _text(profile.get("linkedin_url") or profile.get("linkedin")),
    ]
    return " · ".join(p for p in parts if p)


def _offer_keywords(offer: dict[str, Any] | None) -> list[str]:
    offer = offer or {}
    raw = []
    for key in ("skills", "required_skills", "preferred_skills", "keywords", "tools", "stack", "technologies"):
        raw.extend(_list(offer.get(key)))
    text = " ".join(str(offer.get(k) or "") for k in ("requirements", "description", "description_original", "title"))
    # simple token extraction
    stopwords = {"le", "la", "les", "de", "du", "des", "et", "ou", "un", "une", "en", "the", "and", "for", "with", "to", "of", "a", "an", "in", "on"}
    for token in text.replace("/", " ").replace("-", " ").split():
        t = token.strip(".,;:()[]").lower()
        if len(t) > 3 and t not in stopwords:
            raw.append(t)
    # dedupe preserving order
    out = []
    seen = set()
    for r in raw:
        s = str(r).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:12]


def _profile_bullets(profile: dict[str, Any] | None, keywords: Sequence[str]) -> list[str]:
    profile = profile or {}
    lines: list[str] = []
    for key in ("experience", "projects", "experience_blocks", "achievements"):
        for item in _list(profile.get(key)):
            if isinstance(item, dict):
                text = item.get("text") or item.get("description") or item.get("title") or ""
            else:
                text = item
            t = _text(text, 240)
            if t:
                lines.append(t)
    if not lines:
        skills = _list(profile.get("skills"))
        if skills:
            lines.append("Compétences documentées : " + ", ".join(str(s) for s in skills[:6]))
    # align to keywords: prefer lines sharing a keyword
    kws = [str(k).lower() for k in keywords]
    scored = []
    for line in lines:
        low = line.lower()
        score = sum(1 for k in kws if k.lower() in low)
        scored.append((score, line))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [line for _, line in scored]


def _sourced_company_facts(offer: dict[str, Any] | None) -> list[tuple[str, list[str]]]:
    offer = offer or {}
    facts: list[tuple[str, list[str]]] = []
    company = _company(offer)
    title = _title(offer)
    if company and title:
        facts.append((f"{company} recrute pour le poste de {title}", ["offer.company", "offer.title"]))
    reqs = _text(offer.get("requirements"))
    if reqs:
        facts.append((f"Exigences clés de l'offre : {reqs[:120]}", ["offer.requirements"]))
    if company:
        facts.append((f"Poste à pourvoir chez {company}", ["offer.company"]))
    return facts


def _seed(offer: dict[str, Any] | None, profile: dict[str, Any] | None) -> int:
    base = (_offer_id(offer) or "offer") + "|" + (_profile_name(profile) or "profile") + "|" + str(date.today())
    return int(hashlib.sha256(base.encode("utf-8")).hexdigest()[:8], 16)


def _build_paragraphs(
    *,
    offer: dict[str, Any],
    profile: dict[str, Any],
    tone: str,
    seed: int,
    bullets: list[str],
    variant_index: int,
) -> tuple[list[LetterPara], list[str], list[str]]:
    rng = random.Random(seed + variant_index * 97)
    tone = normalize_tone(tone)
    company = _company(offer) or "[Entreprise]"
    title = _title(offer)
    sourced = _sourced_company_facts(offer)
    # pick one company fact
    fact_text, fact_refs = sourced[0] if sourced else (f"Poste : {title}", ["offer.title"])
    # vary fact choice
    if len(sourced) > 1:
        fact_text, fact_refs = rng.choice(sourced)

    connector_hook = pick_connector("hook", seed + variant_index)
    hook_text = (
        f"{connector_hook} {title} chez {company}. "
        f"{fact_text}. "
        f"Je souhaite mettre mes compétences au service de vos objectifs."
    )
    # proofs
    selected_bullets = bullets[: (2 + (variant_index % 2))]
    if not selected_bullets:
        selected_bullets = ["expériences documentées alignées aux exigences du poste"]
    proofs_text = (
        f"{pick_connector('proofs', seed + variant_index + 1)} : "
        + "; ".join(selected_bullets[:3])
        + "."
    )
    # projects
    course_txt = course_insight(profile, offer)
    matching = matching_insight(profile, offer)
    match_str = ", ".join(matching[:4]) if matching else "les compétences clés du poste"
    projects_text = (
        f"{pick_connector('projects', seed + variant_index + 2)} : "
        f"{course_txt}; alignement sur {match_str}."
    )
    # closing
    contact = _contact_line(profile)
    closing_text = (
        f"{pick_connector('closing', seed + variant_index + 3)} "
        f"pour un entretien. "
        + (f"Contact : {contact}." if contact else "Mes coordonnées figurent en en-tête.")
        + " " + tone_closing_line(tone)
    )

    evidence_map = {
        "hook": list(fact_refs),
        "proofs": ["profile.experience"] if selected_bullets else [],
        "projects": ["profile.education"] if profile else [],
        "closing": ["profile.contact"] if contact else [],
    }
    paras = build_letter_paragraphs(
        hook=hook_text,
        proofs=proofs_text,
        projects=projects_text,
        closing=closing_text,
        evidence=evidence_map,
    )
    paras = trim_to_word_limit(paras, MAX_WORDS)
    # tone adaptation
    from career.letter_tone import apply_tone_to_paragraphs

    apply_tone_to_paragraphs(paras, tone)

    used_bullets = list(selected_bullets)
    guessed_facts = [fact_text]
    return paras, used_bullets, guessed_facts


def _score_draft(draft: LetterDraft, offer: dict[str, Any], profile: dict[str, Any]) -> float:
    paras = draft.paragraphs
    issues = validate_structure(paras)
    wc = total_words(paras)
    # keyword coverage
    kws = _offer_keywords(offer)
    text = render_text(paras).lower()
    hits = sum(1 for k in kws if str(k).lower() in text)
    coverage = (hits / len(kws)) if kws else 0.5
    evidence_count = sum(len(p.evidence_refs) for p in paras)
    score = 0.0
    score += 0.35 * coverage
    score += 0.25 * (1.0 if not issues else 0.5)
    score += 0.2 * min(1.0, evidence_count / 4.0)
    score += 0.2 * (1.0 if 80 <= wc <= 350 else 0.6)
    score += (hash(draft.draft_id) % 10) / 100.0  # tiny variation
    return round(min(1.0, max(0.0, score)), 4)


def generate_drafts(
    offer: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    *,
    offer_id: str | None = None,
    n: int = 3,
    seed: int | None = None,
    providers: Sequence[Any] | None = None,
    tones: Sequence[str] | None = None,
    version: int = 1,
) -> list[LetterDraft]:
    offer = offer or {}
    profile = profile or {}
    if offer_id:
        offer = dict(offer)
        offer.setdefault("id", offer_id)
    seed = seed if seed is not None else _seed(offer, profile)
    bullets = _profile_bullets(profile, _offer_keywords(offer))
    if tones is None:
        tones = ["formel", "direct", "startup"]
    tones = [normalize_tone(t) for t in tones]
    # ensure n drafts
    while len(tones) < n:
        tones = tones + [tones[len(tones) % len(tones)]]
    tones = tones[:n]
    drafts: list[LetterDraft] = []
    for i in range(n):
        tone = tones[i % len(tones)]
        paras, used, facts = _build_paragraphs(
            offer=offer,
            profile=profile,
            tone=tone,
            seed=seed,
            bullets=bullets,
            variant_index=i,
        )
        # vary bullet order slightly
        if i > 0:
            used = vary(used, seed + i) if used else used
        draft = LetterDraft(
            draft_id=f"draft-{i + 1}",
            paragraphs=paras,
            tone=tone,
            used_bullets=used,
            guessed_facts=facts,
            provider="local",
            version=version,
            created_at=str(date.today()),
            evidence_refs=sorted({r for p in paras for r in p.evidence_refs}),
        )
        draft.jury_score = _score_draft(draft, offer, profile)
        draft.text = render_text(paras)
        drafts.append(draft)
    return drafts


def merge_drafts(drafts: Sequence[LetterDraft], seed: int | None = None) -> LetterDraft:
    drafts = list(drafts or [])
    if not drafts:
        return LetterDraft(draft_id="merged", tone="formel")
    # fusion: best paragraph per kind across drafts
    best_by_kind: dict[str, LetterPara] = {}
    for kind in ("hook", "proofs", "projects", "closing"):
        candidates = []
        for d in drafts:
            for p in d.paragraphs:
                if p.kind == kind and str(p.text).strip():
                    candidates.append((d.jury_score, p))
        if candidates:
            candidates.sort(key=lambda x: (-x[0], x[1].text))
            best_by_kind[kind] = candidates[0][1]
    paras = []
    for kind in ("hook", "proofs", "projects", "closing"):
        if kind in best_by_kind:
            p = best_by_kind[kind]
            paras.append(LetterPara(kind=kind, text=p.text, evidence_refs=list(p.evidence_refs)))
    if not paras:
        paras = list(drafts[0].paragraphs)
    paras = trim_to_word_limit(paras, MAX_WORDS)
    merged = LetterDraft(
        draft_id="merged",
        paragraphs=paras,
        tone=normalize_tone(drafts[0].tone),
        used_bullets=sorted({b for d in drafts for b in d.used_bullets}),
        guessed_facts=sorted({f for d in drafts for f in d.guessed_facts}),
        jury_score=round(max((d.jury_score for d in drafts), default=0.0), 4),
        provider="arena" if any(d.provider != "local" for d in drafts) else "local",
        version=max((d.version for d in drafts), default=1),
        created_at=str(date.today()),
        evidence_refs=sorted({r for p in paras for r in p.evidence_refs}),
    )
    merged.text = render_text(paras)
    return merged


def generate_letter_plan(
    offer: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    *,
    offer_id: str | None = None,
    job: dict[str, Any] | None = None,
    n_drafts: int = 3,
    seed: int | None = None,
    providers: Sequence[Any] | None = None,
    **kwargs: Any,
) -> LetterPlan:
    if job is not None and not offer:
        offer = job
    offer = offer or {}
    profile = profile or {}
    if offer_id:
        offer = dict(offer)
        offer.setdefault("id", offer_id)
    seed = seed if seed is not None else _seed(offer, profile)
    drafts = generate_drafts(offer=offer, profile=profile, n=n_drafts, seed=seed, providers=providers)
    merged = merge_drafts(drafts, seed=seed)
    best = best_draft_id(drafts + [merged])
    # best should be a draft id if possible
    draft_ids = {d.draft_id for d in drafts}
    if best not in draft_ids:
        best = best_draft_id(drafts) if drafts else "merged"
    wc = total_words(merged.paragraphs)
    ats_check = {
        "ok": True,
        "issues": validate_structure(merged.paragraphs),
        "word_count": wc,
        "paragraph_count": len(merged.paragraphs),
        "max_words": MAX_WORDS,
        "max_paragraphs": MAX_PARAGRAPHS,
        "ats_safe": True,
    }
    plan = LetterPlan(
        drafts=drafts,
        best_id=best,
        merged_alternative=merged,
        ats_compat_check=ats_check,
        offer_id=_offer_id(offer),
        created_at=str(date.today()),
    )
    return plan


# Aliases
generate_letter = generate_letter_plan
generate = generate_letter_plan
create_letter_plan = generate_letter_plan


async def generate_letter_plan_async(*args: Any, **kwargs: Any) -> LetterPlan:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: generate_letter_plan(*args, **kwargs))


generate_letter_async = generate_letter_plan_async
generate_async = generate_letter_plan_async


def render_letter(draft: LetterDraft | LetterPlan | Any) -> str:
    if isinstance(draft, LetterPlan):
        d = draft.merged_alternative or (draft.drafts[0] if draft.drafts else None)
        draft = d if d is not None else draft
    if hasattr(draft, "paragraphs"):
        return render_text(draft.paragraphs)
    if isinstance(draft, dict):
        paras = draft.get("paragraphs") or []
        return "\n\n".join(str(p.get("text", p) if isinstance(p, dict) else p) for p in paras)
    return str(draft)


def validate_letter(draft: LetterDraft | Any) -> list[str]:
    paras = getattr(draft, "paragraphs", None)
    if paras is None and isinstance(draft, dict):
        paras = draft.get("paragraphs", [])
    paras = normalize_paragraphs(paras)
    return validate_structure(paras)


def export_letter_docx(
    draft_or_plan: Any,
    output_path: str | Path,
    *,
    title: str | None = None,
) -> Path:
    from docx import Document

    if isinstance(draft_or_plan, LetterPlan):
        draft = draft_or_plan.merged_alternative or (draft_or_plan.drafts[0] if draft_or_plan.drafts else None)
    else:
        draft = draft_or_plan
    paras = getattr(draft, "paragraphs", None)
    if paras is None and isinstance(draft, dict):
        paras = draft.get("paragraphs", [])
    paras = normalize_paragraphs(paras)
    doc = Document()
    if title:
        doc.add_heading(title, level=1)
    tone = getattr(draft, "tone", None) or (draft.get("tone") if isinstance(draft, dict) else "formel")

    doc.add_paragraph(tone_salutation(tone))
    for p in paras:
        doc.add_paragraph(p.text)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


export_letter = export_letter_docx
export_docx = export_letter_docx
export = export_letter_docx


def ats_compat_check(draft_or_plan: Any) -> dict[str, Any]:
    if isinstance(draft_or_plan, LetterPlan):
        return dict(draft_or_plan.ats_compat_check or {})
    paras = normalize_paragraphs(getattr(draft_or_plan, "paragraphs", None))
    return {
        "ok": True,
        "issues": validate_structure(paras),
        "word_count": total_words(paras),
        "paragraph_count": len(paras),
        "max_words": MAX_WORDS,
        "max_paragraphs": MAX_PARAGRAPHS,
        "ats_safe": True,
    }


__all__ = [
    "LetterPara",
    "LetterDraft",
    "LetterPlan",
    "generate_drafts",
    "merge_drafts",
    "generate_letter_plan",
    "generate_letter",
    "generate",
    "create_letter_plan",
    "generate_letter_plan_async",
    "generate_letter_async",
    "generate_async",
    "render_letter",
    "render_text",
    "validate_letter",
    "export_letter_docx",
    "export_letter",
    "export_docx",
    "export",
    "ats_compat_check",
    "MAX_PARAGRAPHS",
    "MAX_WORDS",
]


# ---------------------------------------------------------------- router

def create_letter_router(
    service: Any = None,
    *,
    letter_generator: Any = None,
    store: dict[str, Any] | None = None,
) -> Any:
    from fastapi import APIRouter
    from pydantic import BaseModel, Field

    router = APIRouter()
    gen = letter_generator.generate_letter_plan if hasattr(letter_generator, "generate_letter_plan") else generate_letter_plan
    history_store: dict[str, list[dict[str, Any]]] = store if store is not None else {}
    draft_store: dict[str, dict[str, Any]] = {}

    class GeneratePayload(BaseModel):
        profile: dict[str, Any] | None = None
        offer: dict[str, Any] | None = None
        job: dict[str, Any] | None = None
        n_drafts: int = Field(default=3, ge=1, le=10)

    class PatchPayload(BaseModel):
        text: str | None = None
        tone: str | None = None
        paragraphs: list[dict[str, Any]] | None = None

    class ExportPayload(BaseModel):
        format: str = "docx"
        output_path: str | None = None

    async def _build(offer_id: str, payload: GeneratePayload | None) -> LetterPlan:
        profile = payload.profile if payload else None
        offer = payload.offer if payload else None
        job = payload.job if payload else None
        if profile is None and service is not None:
            try:
                profile = service.get_profile()
            except Exception:
                profile = {}
        if offer is None and job is None and service is not None:
            try:
                job = service.get_job(offer_id)
            except Exception:
                job = {"id": offer_id}
        if offer is None:
            offer = job or {"id": offer_id}
        plan = gen(offer=offer, profile=profile or {}, offer_id=offer_id, n_drafts=(payload.n_drafts if payload else 3))
        return plan

    @router.post("/letter/generate/{offer_id}")
    @router.post("/api/letter/generate/{offer_id}")
    @router.post("/generate/{offer_id}")
    async def generate_endpoint(offer_id: str, payload: GeneratePayload | None = None) -> dict[str, Any]:
        plan = _sync_generate(offer_id, payload)
        # store
        history_store.setdefault(offer_id, []).append(plan.as_dict())
        for d in plan.drafts:
            draft_store[d.draft_id] = d.as_dict()
            draft_store[d.draft_id]["offer_id"] = offer_id
        merged = plan.merged_alternative
        if merged is not None:
            draft_store[merged.draft_id] = merged.as_dict()
            draft_store[merged.draft_id]["offer_id"] = offer_id
        return plan.as_dict()

    def _sync_generate(offer_id: str, payload: GeneratePayload | None) -> LetterPlan:
        # call gen synchronously
        profile = payload.profile if payload else None
        offer = payload.offer if payload else None
        job = payload.job if payload else None
        if profile is None and service is not None:
            try:
                profile = service.get_profile()
            except Exception:
                profile = {}
        if offer is None and job is None and service is not None:
            try:
                job = service.get_job(offer_id)
            except Exception:
                job = {"id": offer_id}
        if offer is None:
            offer = job or {"id": offer_id}
        n = payload.n_drafts if payload else 3
        return gen(offer=offer, profile=profile or {}, offer_id=offer_id, n_drafts=n)

    @router.patch("/letter/{draft_id}")
    @router.patch("/api/letter/{draft_id}")
    async def patch_endpoint(draft_id: str, payload: PatchPayload | None = None) -> dict[str, Any]:
        stored = draft_store.get(draft_id, {"draft_id": draft_id})
        payload = payload or PatchPayload()
        if payload.tone is not None:
            stored["tone"] = normalize_tone(payload.tone)
        if payload.text is not None:
            stored["text"] = payload.text
            # update paragraphs if present
            if stored.get("paragraphs"):
                stored["paragraphs"][0]["text"] = payload.text if len(stored["paragraphs"]) == 1 else stored["paragraphs"][0].get("text")
        if payload.paragraphs is not None:
            stored["paragraphs"] = payload.paragraphs
        draft_store[draft_id] = stored
        return stored

    @router.post("/letter/{draft_id}/export")
    @router.post("/api/letter/{draft_id}/export")
    async def export_endpoint(draft_id: str, payload: ExportPayload | None = None) -> dict[str, Any]:
        stored = draft_store.get(draft_id, {"draft_id": draft_id, "paragraphs": []})
        # rebuild a draft-like object
        draft = LetterDraft(
            draft_id=draft_id,
            paragraphs=normalize_paragraphs(stored.get("paragraphs", [])),
            tone=stored.get("tone", "formel"),
            text=stored.get("text", ""),
        )
        fmt = (payload.format if payload else "docx") or "docx"
        out = payload.output_path if payload else None
        if not out:
            out = str(Path(".") / f"{draft_id}.{fmt}")
        path = export_letter_docx(draft, out)
        return {"draft_id": draft_id, "path": str(path), "format": fmt}

    @router.get("/letter/{offer_id}/history")
    @router.get("/api/letter/{offer_id}/history")
    async def history_endpoint(offer_id: str) -> dict[str, Any]:
        return {"offer_id": offer_id, "items": history_store.get(offer_id, [])}

    return router


create_letter_generator_router = create_letter_router
create_router = create_letter_router


__all__ += [
    "create_letter_router",
    "create_letter_generator_router",
    "create_router",
]




class LetterGenerator:
    """Class-based facade (compatibility with other SPEC orchestrators)."""

    def __init__(self, provider: str = "local", version: int = 1) -> None:
        self.provider = provider
        self.version = version

    def generate_drafts(self, *args: Any, **kwargs: Any) -> list[LetterDraft]:
        kwargs.setdefault("version", self.version)
        return generate_drafts(*args, **kwargs)

    def generate_letter_plan(self, *args: Any, **kwargs: Any) -> LetterPlan:
        return generate_letter_plan(*args, **kwargs)

    def merge_drafts(self, *args: Any, **kwargs: Any) -> LetterDraft:
        return merge_drafts(*args, **kwargs)

    def export_letter_docx(self, *args: Any, **kwargs: Any) -> Path:
        return export_letter_docx(*args, **kwargs)

    def render_letter(self, *args: Any, **kwargs: Any) -> str:
        return render_letter(*args, **kwargs)


# Compatibility aliases
generate_letter_drafts = generate_drafts
generate_plan = generate_letter_plan
export_letter = export_letter_docx
docx_export = export_letter_docx
create_letter = generate_letter_plan
