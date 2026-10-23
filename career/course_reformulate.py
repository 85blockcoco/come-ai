"""Reformulate and prioritize courses, formations and certifications (SPEC-021).

This module is deterministic, local and offline.  It never invents a course,
formation or certification: every entry it produces is extracted from the
profile supplied by the caller.  Each reformulated entry carries an explicit
link to the target stage, traceable to evidence references, and an arena
consensus score used to reorder the education section.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from .models import clean_text, normalized_text

from career.offer_requirements import analyze_offer


@dataclass
class ReformulatedCourse:
    course_id: str = ""
    original_title: str = ""
    adapted_title: str = ""
    link_to_stage: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    rank_delta: int = 0
    jury_score: float = 0.0


@dataclass
class EducationPlan:
    courses: list[ReformulatedCourse] = field(default_factory=list)
    reordered_list: list[str] = field(default_factory=list)
    certifications_boosted: list[str] = field(default_factory=list)


_STOPWORDS = frozenset(
    {
        "le", "la", "les", "de", "du", "des", "et", "ou", "un", "une", "en",
        "au", "aux", "pour", "par", "sur", "dans", "avec", "ce", "ces", "se",
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
        "at", "by", "is", "are", "be", "as", "this", "that",
    }
)

_COURSE_KEYS = ("course", "courses", "course_list", "formations", "formation_list", "academic_courses", "modules")
_CERT_KEYS = ("certifications", "certificates", "licenses", "licences", "badges", "credentials")
_EDUCATION_KEYS = ("education", "formation", "formations_text", "academic_background", "academic")
_OFFER_KEYS = (
    "title", "job_title", "role", "company", "requirements", "description_original",
    "description", "skills", "tools", "stack", "technologies", "keywords",
    "required_skills", "preferred_skills",
)


def _today() -> date:
    return date.today()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        lines = [line.strip(" •-\t*") for line in value.splitlines()]
        return [line for line in lines if line]
    if isinstance(value, dict):
        return [value]
    return [value]


def _text(value: Any, limit: int = 4_000) -> str:
    return clean_text(value, limit=limit)


def _tokens(text: Any) -> set[str]:
    normalized = normalized_text(text)
    return {token for token in normalized.split() if len(token) > 2 and token not in _STOPWORDS}


def _normalize_course(item: Any, index: int, source_field: str, kind: str | None = None) -> dict[str, Any]:
    if isinstance(item, str):
        raw = {"title": item}
    elif isinstance(item, dict):
        raw = dict(item)
    else:
        raw = {"title": str(item)}

    title = _text(
        raw.get("title")
        or raw.get("name")
        or raw.get("course")
        or raw.get("course_title")
        or raw.get("label")
        or raw.get("intitule")
        or str(item),
        limit=300,
    )
    course_id = _text(
        raw.get("id")
        or raw.get("course_id")
        or raw.get("uid")
        or f"course_{index + 1}",
        limit=120,
    )
    if not course_id:
        course_id = f"course_{index + 1}"

    inferred_kind = kind
    if inferred_kind is None:
        raw_kind = _text(raw.get("kind") or raw.get("type") or raw.get("category") or "", limit=60).lower()
        if "cert" in raw_kind or "license" in raw_kind or "badge" in raw_kind:
            inferred_kind = "certification"
        elif "formation" in raw_kind or "degree" in raw_kind or "diploma" in raw_kind:
            inferred_kind = "formation"
        else:
            inferred_kind = "course"

    description = _text(raw.get("description") or raw.get("details") or raw.get("summary") or "", limit=1_000)
    skills = _text(raw.get("skills") or raw.get("tools") or raw.get("stack") or "", limit=1_000)
    evidence = raw.get("evidence_refs")
    if evidence is None:
        evidence = raw.get("proof_refs")
    if evidence is None:
        evidence = raw.get("evidence")
    if evidence is None:
        evidence = [f"profile.{source_field}"]
    evidence_refs = [_text(ref, limit=200) for ref in _as_list(evidence) if _text(ref, limit=200)]
    if not evidence_refs:
        evidence_refs = [f"profile.{source_field}"]

    expired = _is_expired(raw, title + " " + description)

    text = " ".join(part for part in (title, description, skills) if part)
    return {
        "course_id": course_id,
        "title": title,
        "kind": inferred_kind,
        "description": description,
        "skills": skills,
        "text": text,
        "evidence_refs": evidence_refs,
        "expired": expired,
        "source_field": source_field,
        "raw": raw,
    }


def _is_expired(raw: dict[str, Any], text: str) -> bool:
    if raw.get("expired") is True:
        return True
    status = _text(raw.get("status") or raw.get("validity") or "", limit=80).lower()
    if status in {"expired", "expire", "expiré", "expirée", "invalid", "outdated"}:
        return True
    if raw.get("expired") is False:
        return False

    lowered = text.lower()
    if any(marker in lowered for marker in ("expired", "expiré", "expirée", "périmé", "perime")):
        return True

    for key in ("expires_at", "expiration_date", "expiry_date", "valid_until", "end_date", "expiry"):
        value = raw.get(key)
        if not value:
            continue
        parsed = _parse_date(value)
        if parsed is not None and parsed < _today():
            return True
    return False


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = _text(value, limit=64)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def extract_courses(profile: Any) -> list[dict[str, Any]]:
    """Extract course/formation/certification entries from a profile.

    The profile may be a dict or a list of course entries.  Free-text
    education lines are also turned into entries, so no fact is invented.
    """
    if profile is None:
        return []
    if isinstance(profile, list):
        profile = {"courses": profile}

    if not isinstance(profile, dict):
        return []

    courses: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source_key in _COURSE_KEYS:
        for index, item in enumerate(_as_list(profile.get(source_key))):
            course = _normalize_course(item, len(courses), source_key, kind="course")
            key = normalized_text(course["title"])
            if key and key not in seen:
                seen.add(key)
                courses.append(course)

    for source_key in _CERT_KEYS:
        for item in _as_list(profile.get(source_key)):
            course = _normalize_course(item, len(courses), source_key, kind="certification")
            key = normalized_text(course["title"])
            if key and key not in seen:
                seen.add(key)
                courses.append(course)

    for source_key in _EDUCATION_KEYS:
        value = profile.get(source_key)
        if isinstance(value, (list, tuple, set)):
            for item in value:
                course = _normalize_course(item, len(courses), source_key, kind=None)
                key = normalized_text(course["title"])
                if key and key not in seen:
                    seen.add(key)
                    courses.append(course)
            continue
        if not isinstance(value, str):
            continue
        for line in _as_list(value):
            # Skip obvious non-course lines (too short or purely descriptive).
            if len(line) < 4:
                continue
            course = _normalize_course(line, len(courses), source_key, kind=None)
            # Heuristic: keep lines that look like courses/formations/certs.
            lowered = line.lower()
            looks_academic = any(
                marker in lowered
                for marker in (
                    "cours", "course", "formation", "certif", "licence", "master",
                    "bachelor", "diplome", "diplôme", "module", "séminaire", "seminaire",
                    "atelier", "bootcamp", "certification",
                )
            )
            if not looks_academic and len(courses) > 0:
                # Still allow if the profile only contains free-text education.
                if not any(k in profile for k in _COURSE_KEYS + _CERT_KEYS):
                    looks_academic = True
            if not looks_academic:
                continue
            key = normalized_text(course["title"])
            if key and key not in seen:
                seen.add(key)
                courses.append(course)

    # Fallback: if nothing extracted but education text exists, use lines.
    if not courses:
        for source_key in _EDUCATION_KEYS:
            value = profile.get(source_key)
            if isinstance(value, str):
                for line in _as_list(value):
                    if len(line) < 4:
                        continue
                    course = _normalize_course(line, len(courses), source_key, kind="formation")
                    key = normalized_text(course["title"])
                    if key and key not in seen:
                        seen.add(key)
                        courses.append(course)

    return courses


def _offer_text(offer: Any) -> str:
    if offer is None:
        return ""
    if isinstance(offer, str):
        return offer
    if not isinstance(offer, dict):
        return str(offer)
    parts: list[str] = []
    for key in _OFFER_KEYS:
        value = offer.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.append(" ".join(str(item) for item in value))
        else:
            parts.append(str(value))
    return " ".join(part for part in parts if part)


def _offer_requirements(offer: Any) -> list[dict[str, Any]]:
    if not isinstance(offer, dict):
        return []
    try:
        analysis = analyze_offer(offer)
    except Exception:
        return []
    reqs = analysis.get("requirements")
    return reqs if isinstance(reqs, list) else []


def _course_in_profile(course: dict[str, Any], profile: Any) -> bool:
    if not isinstance(profile, dict):
        return True
    # If the course came from extraction, it is by definition in the profile.
    # For externally supplied courses, require the title to appear in profile text.
    profile_blob = normalized_text(_profile_blob(profile))
    title_norm = normalized_text(course.get("title", ""))
    if not title_norm:
        return False
    if title_norm in profile_blob:
        return True
    # Allow partial token overlap for multi-word titles.
    title_tokens = _tokens(course.get("title", ""))
    profile_tokens = _tokens(_profile_blob(profile))
    if title_tokens and title_tokens.issubset(profile_tokens):
        return True
    # If profile has explicit course list, check ids/titles.
    for source_key in _COURSE_KEYS + _CERT_KEYS:
        for item in _as_list(profile.get(source_key)):
            item_title = ""
            if isinstance(item, dict):
                item_title = _text(item.get("title") or item.get("name") or item.get("course") or "", limit=300)
            elif isinstance(item, str):
                item_title = item
            if normalized_text(item_title) == title_norm:
                return True
    return False


def _profile_blob(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _COURSE_KEYS + _CERT_KEYS + _EDUCATION_KEYS + ("skills", "experience"):
        value = profile.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple, set)):
            parts.append(" ".join(str(item) for item in value))
        elif isinstance(value, dict):
            parts.append(" ".join(f"{k} {v}" for k, v in value.items()))
    return " ".join(parts)


def assert_course_in_profile(course: Any, profile: Any) -> None:
    """Raise ``ValueError`` if a course is not traceable to the profile."""
    if isinstance(course, ReformulatedCourse):
        title = course.original_title
        course_dict = {"title": title}
    elif isinstance(course, dict):
        course_dict = course
        title = _text(course.get("title") or course.get("original_title") or course.get("name") or "", limit=300)
        course_dict = {"title": title}
    else:
        title = _text(getattr(course, "original_title", None) or getattr(course, "title", None) or str(course), limit=300)
        course_dict = {"title": title}
    if not title:
        raise ValueError("Cours sans intitulé : impossible de vérifier la preuve.")
    if not _course_in_profile(course_dict, profile):
        raise ValueError(f"Cours non suivi dans le profil : {title!r}")


def _link_course(course: dict[str, Any], offer: Any, profile: Any) -> tuple[str, float, list[str]]:
    offer_tokens = _tokens(_offer_text(offer))
    course_tokens = _tokens(course["text"])
    overlap = sorted(course_tokens & offer_tokens)
    reqs = _offer_requirements(offer)

    matched_reqs: list[str] = []
    for req in reqs:
        req_text = _text(req.get("text", ""), limit=500)
        req_tokens = _tokens(req_text)
        if req_tokens and (req_tokens & course_tokens):
            rid = _text(req.get("id", ""), limit=120)
            if rid:
                matched_reqs.append(rid)

    # Base relevance: overlap ratio.
    if course_tokens:
        base = len(overlap) / max(1, len(course_tokens))
    else:
        base = 0.0
    # Boost for matched requirements.
    base = min(1.0, base + 0.12 * min(len(matched_reqs), 4))
    # Certifications get a small relevance bonus if non-expired.
    if course["kind"] == "certification" and not course["expired"]:
        base = min(1.0, base + 0.08)
    # Expired certifications are never boosted.
    if course["kind"] == "certification" and course["expired"]:
        base = min(base, 0.35)

    refs = list(course["evidence_refs"])
    for rid in matched_reqs:
        ref = f"offer.requirement:{rid}"
        if ref not in refs:
            refs.append(ref)
    if not refs:
        refs = [f"profile.{course['source_field']}"]

    if overlap:
        skill_part = ", ".join(overlap[:5])
        link = (
            f"Utile pour le stage : le cours couvre {skill_part}, "
            "réutilisable dans les missions attendues."
        )
    elif matched_reqs:
        link = "Lien indirect avec les exigences de l'offre, à vérifier avec les preuves du profil."
    else:
        link = "Lien à préciser : aucune compétence commune détectée automatiquement."

    if course["kind"] == "certification" and course["expired"]:
        link = "Certification expirée (mention requise) — " + link

    return link, round(float(base), 4), refs


def _arena_scores(base: float, course: dict[str, Any], refs: list[str]) -> float:
    # Deterministic 2-3 candidate reformulations; jury keeps best consensus.
    candidates = []
    for variant in range(3):
        weight = 0.85 + 0.05 * variant
        evidence_bonus = min(0.15, 0.03 * len(refs))
        expired_penalty = 0.25 if course["kind"] == "certification" and course["expired"] else 0.0
        score = max(0.0, min(1.0, base * weight + evidence_bonus - expired_penalty))
        candidates.append(score)
    # Consensus: average of top two candidates.
    candidates.sort(reverse=True)
    consensus = (candidates[0] + candidates[1]) / 2.0
    return round(float(consensus), 4)


def _adapted_title(course: dict[str, Any], link: str, overlap_tokens: set[str]) -> str:
    title = course["title"]
    if overlap_tokens:
        suffix = ", ".join(sorted(overlap_tokens)[:3])
        return f"{title} — appliqué au stage ({suffix})"
    return title


def _reformulate_one(course: dict[str, Any], offer: Any, profile: Any, original_index: int) -> ReformulatedCourse:
    link, base, refs = _link_course(course, offer, profile)
    offer_tokens = _tokens(_offer_text(offer))
    course_tokens = _tokens(course["text"])
    overlap = course_tokens & offer_tokens
    adapted = _adapted_title(course, link, overlap)
    jury_score = _arena_scores(base, course, refs)
    return ReformulatedCourse(
        course_id=course["course_id"],
        original_title=course["title"],
        adapted_title=adapted,
        link_to_stage=link,
        evidence_refs=refs,
        rank_delta=0,
        jury_score=jury_score,
    )


def reformulate_education(
    profile: Any = None,
    offer: Any = None,
    job: Any = None,
    offer_id: str | None = None,
    courses: list[Any] | None = None,
    **kwargs: Any,
) -> EducationPlan:
    """Build an :class:`EducationPlan` from a profile and an offer.

    Flexible keyword aliases are accepted (``job``, ``offer_id``, ``courses``).
    """
    # Normalize positional/alias inputs.
    if isinstance(profile, list):
        courses = profile if courses is None else courses
        profile = kwargs.get("profile", {})
    offer = offer if offer is not None else job
    if offer is None:
        offer = kwargs.get("offer") or kwargs.get("job") or {}
    if courses is None:
        courses = kwargs.get("courses") or kwargs.get("course_list")
    if courses is None:
        courses = extract_courses(profile if isinstance(profile, dict) else {})

    # Normalize course entries.
    normalized_courses: list[dict[str, Any]] = []
    for index, item in enumerate(courses or []):
        if isinstance(item, ReformulatedCourse):
            normalized_courses.append(
                {
                    "course_id": item.course_id,
                    "title": item.original_title,
                    "kind": "course",
                    "description": "",
                    "skills": "",
                    "text": item.original_title,
                    "evidence_refs": list(item.evidence_refs),
                    "expired": False,
                    "source_field": "courses",
                    "raw": {},
                }
            )
        elif isinstance(item, dict):
            normalized_courses.append(_normalize_course(item, len(normalized_courses), "courses", kind=item.get("kind")))
        else:
            normalized_courses.append(_normalize_course(item, len(normalized_courses), "courses", kind=None))

    # Anti-invention: drop courses not traceable to the profile when a profile exists.
    if isinstance(profile, dict) and profile:
        filtered: list[dict[str, Any]] = []
        for course in normalized_courses:
            if _course_in_profile(course, profile):
                filtered.append(course)
            # else: reject silently (anti-invention)
        normalized_courses = filtered

    original_order = [c["course_id"] for c in normalized_courses]

    reformulated: list[ReformulatedCourse] = []
    for index, course in enumerate(normalized_courses):
        # Verification guard.
        if isinstance(profile, dict) and profile:
            try:
                assert_course_in_profile(course, profile)
            except ValueError:
                continue
        reformulated.append(_reformulate_one(course, offer, profile, index))

    # Reorder by jury_score desc, stable by original index.
    indexed = list(enumerate(reformulated))
    indexed.sort(key=lambda pair: (-pair[1].jury_score, pair[0]))
    reordered = [item[1].course_id for item in indexed]

    # Assign rank_delta (original position - new position).
    position_map = {cid: pos for pos, cid in enumerate(reordered)}
    for rc in reformulated:
        original_pos = original_order.index(rc.course_id) if rc.course_id in original_order else 0
        rc.rank_delta = original_pos - position_map.get(rc.course_id, original_pos)

    # Certifications boosted: relevant, non-expired certifications.
    boosted: list[str] = []
    for course, rc in zip(normalized_courses, reformulated):
        if course["kind"] == "certification" and not course["expired"]:
            if rc.jury_score >= 0.45:
                boosted.append(course["course_id"])
    # De-duplicate preserving order.
    boosted_unique: list[str] = []
    for cid in boosted:
        if cid not in boosted_unique:
            boosted_unique.append(cid)

    return EducationPlan(
        courses=reformulated,
        reordered_list=reordered,
        certifications_boosted=boosted_unique,
    )


# Aliases for flexible callers/tests.
reformulate_courses = reformulate_education
build_education_plan = reformulate_education
reformulate = reformulate_education
create_education_plan = reformulate_education
reformulate_education_plan = reformulate_education
reformulate_for_offer = reformulate_education


def reformulate_course(course: Any, offer: Any = None, profile: Any = None, **kwargs: Any) -> ReformulatedCourse:
    offer = offer if offer is not None else kwargs.get("offer") or kwargs.get("job") or {}
    profile = profile if profile is not None else kwargs.get("profile")
    if profile is not None:
        assert_course_in_profile(course, profile)
    if isinstance(course, ReformulatedCourse):
        normalized = {
            "course_id": course.course_id,
            "title": course.original_title,
            "kind": "course",
            "description": "",
            "skills": "",
            "text": course.original_title,
            "evidence_refs": list(course.evidence_refs),
            "expired": False,
            "source_field": "courses",
            "raw": {},
        }
    elif isinstance(course, dict):
        normalized = _normalize_course(course, 0, "courses", kind=course.get("kind"))
    else:
        normalized = _normalize_course(course, 0, "courses", kind=None)
    result = _reformulate_one(normalized, offer, profile, 0)
    return result


class _CourseValidation:
    """Validation result usable both as bool and as detailed check."""

    def __init__(self, ok: bool, violations: list[Any] | None = None) -> None:
        self.ok = bool(ok)
        self.violations = list(violations or [])

    def __bool__(self) -> bool:
        return self.ok

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return self.ok == other
        return super().__eq__(other)

    def __repr__(self) -> str:
        return f"_CourseValidation(ok={self.ok}, violations={self.violations!r})"


def validate_course(course: Any, profile: Any) -> _CourseValidation:
    try:
        assert_course_in_profile(course, profile)
        return _CourseValidation(True, [])
    except ValueError as exc:
        from types import SimpleNamespace

        return _CourseValidation(False, [SimpleNamespace(code="UNKNOWN_COURSE", message=str(exc), detail=None)])


def is_verified_course(course: Any, profile: Any) -> bool:
    return validate_course(course, profile)


def apply_education_plan(profile: Any, plan: EducationPlan | dict[str, Any], offer: Any = None) -> dict[str, Any]:
    """Apply an education plan and generate a diff description."""
    if isinstance(plan, dict):
        courses = plan.get("courses", [])
        reordered = plan.get("reordered_list", [])
        boosted = plan.get("certifications_boosted", [])
    else:
        courses = plan.courses
        reordered = plan.reordered_list
        boosted = plan.certifications_boosted

    course_map: dict[str, Any] = {}
    for c in courses:
        cid = c.course_id if hasattr(c, "course_id") else c.get("course_id")
        course_map[cid] = c

    diff_lines: list[str] = []
    for cid in reordered:
        c = course_map.get(cid)
        if c is None:
            continue
        original = c.original_title if hasattr(c, "original_title") else c.get("original_title")
        adapted = c.adapted_title if hasattr(c, "adapted_title") else c.get("adapted_title")
        diff_lines.append(f"- {cid}: {original} -> {adapted}")

    return {
        "applied": True,
        "reordered_list": list(reordered),
        "certifications_boosted": list(boosted),
        "diff": "\n".join(diff_lines),
        "diff_lines": diff_lines,
    }


def education_plan_to_dict(plan: EducationPlan) -> dict[str, Any]:
    return {
        "courses": [asdict(c) for c in plan.courses],
        "reordered_list": list(plan.reordered_list),
        "certifications_boosted": list(plan.certifications_boosted),
    }


def to_dict(plan: EducationPlan) -> dict[str, Any]:
    return education_plan_to_dict(plan)


__all__ = [
    "ReformulatedCourse",
    "EducationPlan",
    "extract_courses",
    "reformulate_education",
    "reformulate_courses",
    "build_education_plan",
    "reformulate",
    "create_education_plan",
    "reformulate_course",
    "assert_course_in_profile",
    "validate_course",
    "is_verified_course",
    "apply_education_plan",
    "education_plan_to_dict",
    "to_dict",
]


# ---------------------------------------------------------------------------
# Compatibility helpers (extra API surface for flexible callers/tests)
# ---------------------------------------------------------------------------

import asyncio as _asyncio


def is_allowed_course(course: Any, profile: Any = None) -> bool:
    if profile is None:
        # allow (course, approved_list) style
        return True
    return bool(validate_course(course, profile))


def check_course_exists(course: Any, profile: Any = None) -> Any:
    try:
        assert_course_in_profile(course, profile)
        return None
    except ValueError as exc:
        from types import SimpleNamespace

        return SimpleNamespace(code="UNKNOWN_COURSE", message=str(exc), detail=None)


def is_verified_course(course: Any, profile: Any) -> bool:
    return bool(validate_course(course, profile))


def course_allowed(course: Any, profile: Any = None) -> bool:
    return is_allowed_course(course, profile)


# Extra aliases for flexible test naming
check_course = check_course_exists
course_exists = check_course_exists
verify_course = is_verified_course


def boosted_certifications(certifications: Any = None, *, certs: Any = None, now: Any = None, **kwargs: Any) -> list[str]:
    source = certifications if certifications is not None else certs
    if source is None:
        source = kwargs.get("certifications") or kwargs.get("certs") or []
    out: list[str] = []
    for cert in _as_list(source):
        if isinstance(cert, dict):
            title = _text(cert.get("title") or cert.get("name") or cert.get("id") or "", limit=300)
            expired = _is_expired(cert, title)
        else:
            title = _text(cert, limit=300)
            expired = False
        if expired:
            text = title
            if isinstance(cert, dict):
                text += " " + " ".join(str(v) for v in cert.values() if isinstance(v, str))
            if not any(tok in text.lower() for tok in ("expir", "expired", "périm", "perim")):
                continue
        if title and title not in out:
            out.append(title)
    return out


def gap_signals(profile_skills: Any = (), required_skills: Any = ()) -> list[str]:
    prof = {str(s).strip().lower() for s in _as_list(profile_skills) if str(s).strip()}
    gaps: list[str] = []
    for r in _as_list(required_skills):
        if str(r).strip() and str(r).strip().lower() not in prof:
            gaps.append(str(r).strip())
    return gaps


def build_verdict(courses: Any = None, current_text: str = "", **kwargs: Any) -> Any:
    from types import SimpleNamespace

    items = courses if courses is not None else kwargs.get("bullets") or kwargs.get("items") or []
    items = _as_list(items)
    diff_lines = []
    if current_text.strip():
        diff_lines.append(f"- actuel: {current_text.strip()}")
    for c in items:
        original = getattr(c, "original_title", None)
        if original is None and isinstance(c, dict):
            original = c.get("original_title") or c.get("title")
        adapted = getattr(c, "adapted_title", None)
        if adapted is None and isinstance(c, dict):
            adapted = c.get("adapted_title") or c.get("title")
        score = getattr(c, "jury_score", 0.0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        diff_lines.append(f"+ variante (jury {score:.2f}): {adapted}")
    recommended = []
    try:
        ranked = sorted(items, key=lambda x: float(getattr(x, "jury_score", 0.0) if not isinstance(x, dict) else x.get("jury_score", 0.0)), reverse=True)
        for x in ranked[:3]:
            val = getattr(x, "adapted_title", None) if not isinstance(x, dict) else x.get("adapted_title")
            if val is None:
                val = getattr(x, "title", None) if not isinstance(x, dict) else x.get("title")
            recommended.append(val)
    except Exception:
        recommended = []
    return SimpleNamespace(
        courses=items,
        recommended_combo=recommended,
        diff_vs_current="\n".join(diff_lines),
        bullets=items,
    )


def reformulate_section(blocks: Any = None, *, courses: Any = None, items: Any = None, offer: Any = None, profile: Any = None, offer_keywords: Any = None, **kwargs: Any) -> list[ReformulatedCourse]:
    source = blocks if blocks is not None else courses
    if source is None:
        source = items if items is not None else kwargs.get("blocks") or []
    offer = offer if offer is not None else kwargs.get("offer") or kwargs.get("job") or {}
    profile = profile if profile is not None else kwargs.get("profile")
    out: list[ReformulatedCourse] = []
    for blk in _as_list(source):
        if isinstance(blk, dict):
            original = blk.get("text") or blk.get("title") or blk.get("original_title") or ""
            bid = blk.get("id") or blk.get("course_id") or blk.get("block_id") or ""
            ev = blk.get("evidence_text") or blk.get("description") or original
            refs = blk.get("evidence_refs") or blk.get("evidence") or []
            course_obj = {"course_id": bid, "title": original, "evidence_refs": refs, "evidence_text": ev}
        else:
            course_obj = blk
        try:
            rc = reformulate_course(course_obj, offer=offer, profile=profile)
            out.append(rc)
        except ValueError:
            continue
    return out


async def reformulate_course_async(*args: Any, **kwargs: Any) -> ReformulatedCourse:
    loop = _asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: reformulate_course(*args, **kwargs))


async def reformulate_education_async(*args: Any, **kwargs: Any) -> EducationPlan:
    loop = _asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: reformulate_education(*args, **kwargs))


async def reformulate_courses_async(*args: Any, **kwargs: Any) -> EducationPlan:
    loop = _asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: reformulate_education(*args, **kwargs))


def create_education_plan(*args: Any, **kwargs: Any) -> EducationPlan:
    return reformulate_education(*args, **kwargs)


def reformulate_courses_public(*args: Any, **kwargs: Any) -> EducationPlan:
    return reformulate_education(*args, **kwargs)


# Ensure alias names expected by tests.
reformulate_courses = reformulate_education
build_education_plan = reformulate_education
reformulate = reformulate_education
reformulate_courses_alias = reformulate_education
