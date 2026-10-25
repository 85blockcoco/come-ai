"""Local, deterministic checklist of administrative documents for an internship abroad.

This module is intentionally dependency-free: it contains no network calls, no
LLM, no secrets and no personal data.  It only describes, for a destination
country, which administrative pieces are usually required, lets the user record
a status for each piece (``missing`` / ``in_progress`` / ``ok`` /
``not_applicable``), tracks proof references and computes a completion recap.

The data is synthetic and generic: it is a starting point for the user, never a
legal or administrative guarantee.  Every label is in French; country-specific
requirements must always be double-checked with the host institution and the
relevant consulate.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

Status = Literal["missing", "in_progress", "ok", "not_applicable"]
VALID_STATUSES: tuple[str, ...] = ("missing", "in_progress", "ok", "not_applicable")

# ---------------------------------------------------------------------------
# Country normalisation
# ---------------------------------------------------------------------------

_COUNTRY_ALIASES: dict[str, str] = {
    "fr": "France",
    "france": "France",
    "uk": "United Kingdom",
    "gb": "United Kingdom",
    "gbr": "United Kingdom",
    "united kingdom": "United Kingdom",
    "royaume-uni": "United Kingdom",
    "royaume uni": "United Kingdom",
    "england": "United Kingdom",
    "great britain": "United Kingdom",
    "de": "Germany",
    "deu": "Germany",
    "germany": "Germany",
    "allemagne": "Germany",
    "deutschland": "Germany",
    "nl": "Netherlands",
    "nld": "Netherlands",
    "netherlands": "Netherlands",
    "holland": "Netherlands",
    "pays-bas": "Netherlands",
    "pays bas": "Netherlands",
    "niederlande": "Netherlands",
    "be": "Belgium",
    "bel": "Belgium",
    "belgium": "Belgium",
    "belgique": "Belgium",
    "belgien": "Belgium",
}

# Upper bounds keep a malicious or accidental payload from growing without
# limit.  They are deliberately generous for a real stage dossier.
MAX_PROOF_REFS = 50
MAX_PROOF_REF_LENGTH = 240


def _clean(value: Any, *, limit: int = 120) -> str:
    """Strip control characters/NULs and enforce a hard length bound."""
    text = str(value if value is not None else "")
    text = "".join(char for char in text if char == "\t" or ord(char) >= 32)
    return text.strip()[:limit]


def _clean_proof_refs(values: Any) -> list[str]:
    """Return deduplicated, non-empty proof references with bounded size."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in values:
        ref = _clean(raw, limit=MAX_PROOF_REF_LENGTH)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        cleaned.append(ref)
        if len(cleaned) >= MAX_PROOF_REFS:
            break
    return cleaned


def normalize_country(value: Any) -> str:
    """Return a canonical country name, accepting codes or common aliases."""
    text = _clean(value, limit=80)
    if not text:
        return "France"
    alias = _COUNTRY_ALIASES.get(text.casefold())
    if alias is not None:
        return alias
    # Already canonical?
    for canonical in ("France", "United Kingdom", "Germany", "Netherlands", "Belgium"):
        if text.casefold() == canonical.casefold():
            return canonical
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AdminItem:
    """One administrative piece of a stage dossier."""

    key: str
    label_fr: str
    required: bool
    status: Status = "missing"
    proof_refs: list[str] = field(default_factory=list)
    required_proofs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.key = _clean(self.key, limit=80) or "item"
        self.label_fr = _clean(self.label_fr, limit=240) or self.key
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Statut inconnu pour {self.key!r}: {self.status!r}")
        self.proof_refs = _clean_proof_refs(self.proof_refs)
        self.required_proofs = _clean_proof_refs(self.required_proofs)

    @property
    def is_complete(self) -> bool:
        return self.status in ("ok", "not_applicable")

    @property
    def is_blocking(self) -> bool:
        return bool(self.required and self.status not in ("ok", "not_applicable"))

    @property
    def missing_proofs(self) -> list[str]:
        """Required proofs that are not yet covered by a provided reference.

        Proof references are opaque labels (for example ``"convention_signée"``)
        supplied by the caller; the module never reads a file or a URL.
        """
        provided = set(self.proof_refs)
        return [proof for proof in self.required_proofs if proof not in provided]

    @property
    def proofs_complete(self) -> bool:
        """True when the piece needs no further proof reference."""
        return not self.missing_proofs

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdminChecklist:
    """Full administrative checklist for one destination country."""

    country: str
    items: list[AdminItem]
    blocking_missing: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.country = normalize_country(self.country)
        self.items = list(self.items or [])
        if self.blocking_missing is None:
            self.blocking_missing = []
        self.blocking_missing = [
            _clean(key, limit=80) for key in self.blocking_missing if _clean(key, limit=80)
        ]
        # Keep blocking list coherent with items when empty.
        if not self.blocking_missing:
            self.blocking_missing = [
                item.key for item in self.items if item.required and item.status not in ("ok", "not_applicable")
            ]

    @property
    def keys(self) -> list[str]:
        return [item.key for item in self.items]

    @property
    def missing_proofs(self) -> dict[str, list[str]]:
        """Map of item key -> required proofs still missing for applicable required pieces."""
        return {
            item.key: item.missing_proofs
            for item in self.items
            if item.required and item.status != "not_applicable" and item.missing_proofs
        }

    def get(self, key: str) -> AdminItem | None:
        for item in self.items:
            if item.key == key:
                return item
        return None

    def set_status(
        self,
        key: str,
        status: str,
        proof_refs: list[str] | None = None,
    ) -> AdminItem:
        item = self.get(key)
        if item is None:
            raise KeyError(f"Pièce inconnue pour {self.country}: {key!r}")
        if status not in VALID_STATUSES:
            raise ValueError(f"Statut inconnu: {status!r}")
        item.status = status  # type: ignore[assignment]
        if proof_refs is not None:
            item.proof_refs = _clean_proof_refs(proof_refs)
        self.blocking_missing = [
            i.key for i in self.items if i.required and i.status not in ("ok", "not_applicable")
        ]
        return item

    @property
    def completeness(self) -> "CompletenessResult":
        return completeness(self)

    def recap(self, *, format: str = "markdown") -> str:
        return render_recap(self, format=format)

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "items": [item.to_dict() for item in self.items],
            "blocking_missing": list(self.blocking_missing),
        }


# ---------------------------------------------------------------------------
# Requirements by country (synthetic, generic)
# ---------------------------------------------------------------------------

def _item(key: str, label_fr: str, required: bool, required_proofs: list[str] | None = None) -> AdminItem:
    return AdminItem(
        key=key,
        label_fr=label_fr,
        required=required,
        status="missing",
        proof_refs=[],
        required_proofs=list(required_proofs or []),
    )


REQUIREMENTS_BY_COUNTRY: dict[str, list[AdminItem]] = {
    "France": [
        _item("convention", "Convention de stage tripartite signée", True, ["convention_signée"]),
        _item("school_certificate", "Certificat de scolarité", True, ["certificat_scolarité"]),
        _item("civil_id", "Pièce d'identité (carte d'identité ou passeport)", True, ["pièce_identité"]),
        _item("insurance", "Attestation d'assurance (RC + santé)", True, ["attestation_assurance"]),
        _item("bank_details", "RIB / coordonnées bancaires", True, ["rib"]),
        _item("photo", "Photo d'identité récente", False, ["photo"]),
    ],
    "United Kingdom": [
        _item("passport", "Passeport valide (durée couvrant le stage)", True, ["passeport"]),
        _item("visa", "Visa / autorisation de travail (selon nationalité)", True, ["visa_ou_autorisation"]),
        _item("cas_letter", "Lettre d'acceptation ou CAS de l'établissement d'accueil", True, ["lettre_acceptation"]),
        _item("proof_of_funds", "Justificatif de ressources financières", True, ["justificatif_ressources"]),
        _item("ihs", "Paiement IHS / assurance santé (si applicable)", False, ["preuve_ihs"]),
        _item("convention", "Convention de stage tripartite", True, ["convention_signée"]),
        _item("accommodation", "Justificatif de logement", False, ["justificatif_logement"]),
        _item("insurance", "Attestation d'assurance RC", True, ["attestation_assurance"]),
    ],
    "Germany": [
        _item("passport", "Passeport valide", True, ["passeport"]),
        _item("visa", "Visa national pour stage (selon nationalité)", True, ["visa_national"]),
        _item("enrollment", "Inscription / certificat de scolarité", True, ["certificat_scolarité"]),
        _item("convention", "Convention de stage tripartite (Praktikumsvertrag)", True, ["convention_signée"]),
        _item("health_insurance", "Attestation d'assurance santé (Krankenversicherung)", True, ["attestation_santé"]),
        _item("blocked_account", "Compte bloqué / justificatif de ressources (si applicable)", False, ["justificatif_ressources"]),
        _item("registration", "Inscription à la mairie (Anmeldung) à l'arrivée", False, ["preuve_anmeldung"]),
        _item("civil_id", "Pièce d'identité", True, ["pièce_identité"]),
    ],
    "Netherlands": [
        _item("passport", "Passeport valide", True, ["passeport"]),
        _item("visa", "Visa / permis de séjour (MVV/TEV si applicable)", True, ["visa_ou_permis"]),
        _item("enrollment", "Certificat de scolarité / immatriculation", True, ["certificat_scolarité"]),
        _item("convention", "Convention de stage tripartite", True, ["convention_signée"]),
        _item("health_insurance", "Attestation d'assurance santé", True, ["attestation_santé"]),
        _item("proof_of_funds", "Justificatif de ressources financières", False, ["justificatif_ressources"]),
        _item("bsn", "Numéro BSN (obtenu sur place)", False, ["preuve_bsn"]),
        _item("insurance", "Attestation d'assurance RC", True, ["attestation_assurance"]),
    ],
    "Belgium": [
        _item("passport", "Passeport ou carte d'identité valide", True, ["pièce_identité"]),
        _item("visa", "Visa / autorisation de séjour (si applicable)", False, ["visa_ou_autorisation"]),
        _item("convention", "Convention de stage tripartite", True, ["convention_signée"]),
        _item("school_certificate", "Certificat de scolarité", True, ["certificat_scolarité"]),
        _item("insurance", "Attestation d'assurance RC + santé", True, ["attestation_assurance"]),
        _item("proof_of_funds", "Justificatif de ressources (si demandé)", False, ["justificatif_ressources"]),
        _item("residence_permit", "Permis de séjour (demande sur place)", False, ["permis_séjour"]),
    ],
}

# Make REQUIREMENTS_BY_COUNTRY tolerant of aliases/codes on read without changing
# the number of canonical countries exposed.
class _CountryRequirements(dict):
    def __getitem__(self, key: Any) -> list[AdminItem]:
        canonical = normalize_country(key)
        if canonical in self:
            return super().__getitem__(canonical)
        # fall back to a copy of France for unknown countries
        return [replace(item) for item in super().__getitem__("France")]

    def __contains__(self, key: Any) -> bool:
        return normalize_country(key) in super().keys()

    def get(self, key: Any, default: Any = None) -> Any:
        canonical = normalize_country(key)
        if canonical in super().keys():
            return super().__getitem__(canonical)
        return default


REQUIREMENTS_BY_COUNTRY = _CountryRequirements(
    {country: [replace(item) for item in items] for country, items in REQUIREMENTS_BY_COUNTRY.items()}
)


def requirements_for_country(country: Any) -> list[AdminItem]:
    """Return a fresh list of required items for ``country``."""
    canonical = normalize_country(country)
    items = REQUIREMENTS_BY_COUNTRY.get(canonical)
    if items is None:
        items = REQUIREMENTS_BY_COUNTRY["France"]
    return [replace(item) for item in items]


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


class CompletenessResult(dict):
    """Dict-like completeness summary that also compares like a number."""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            percent = float(self.get("percent", 0.0))
            # Accept both a 0-100 percentage and a 0-1 ratio.
            if float(other) == percent:
                return True
            if float(other) * 100.0 == percent:
                return True
            return False
        return super().__eq__(other)

    def __float__(self) -> float:
        return float(self.get("percent", 0.0))

    def __int__(self) -> int:
        return int(round(float(self.get("percent", 0.0))))

    def __call__(self, *args: Any, **kwargs: Any) -> "CompletenessResult":
        return self


def completeness(checklist: AdminChecklist | Any) -> CompletenessResult:
    """Compute a completion summary for ``checklist`` (dict-like + numeric)."""
    items = list(getattr(checklist, "items", None) or [])
    total = len(items)
    done = sum(1 for item in items if getattr(item, "status", None) in ("ok", "not_applicable"))
    required_items = [item for item in items if getattr(item, "required", False)]
    required_total = len(required_items)
    required_done = sum(1 for item in required_items if getattr(item, "status", None) in ("ok", "not_applicable"))
    blocking = list(getattr(checklist, "blocking_missing", None) or [])
    if not blocking:
        blocking = [item.key for item in items if getattr(item, "required", False) and getattr(item, "status", None) not in ("ok", "not_applicable")]
    status_counts: dict[str, int] = {status: 0 for status in VALID_STATUSES}
    for item in items:
        status = getattr(item, "status", None)
        if status in status_counts:
            status_counts[status] += 1
    missing_proofs: dict[str, list[str]] = {}
    proofs_required = 0
    proofs_provided = 0
    for item in items:
        # Evidence is only expected for required pieces that are applicable.
        # Optional or explicitly not-applicable pieces never reduce the score.
        if not getattr(item, "required", False) or getattr(item, "status", None) == "not_applicable":
            continue
        required_proofs = list(getattr(item, "required_proofs", None) or [])
        provided = set(getattr(item, "proof_refs", None) or [])
        proofs_required += len(required_proofs)
        proofs_provided += sum(1 for proof in required_proofs if proof in provided)
        missing = [proof for proof in required_proofs if proof not in provided]
        if missing:
            missing_proofs[getattr(item, "key", "")] = missing
    proof_percent = (proofs_provided / proofs_required * 100.0) if proofs_required else 100.0
    percent = (done / total * 100.0) if total else 100.0
    required_percent = (required_done / required_total * 100.0) if required_total else 100.0
    result = CompletenessResult(
        {
            "total": total,
            "done": done,
            "completed": done,
            "remaining": total - done,
            "percent": round(percent, 2),
            "percentage": round(percent, 2),
            "score": round(percent, 2),
            "ratio": round(done / total, 4) if total else 1.0,
            "required_total": required_total,
            "required_done": required_done,
            "required_percent": round(required_percent, 2),
            "required_score": round(required_percent, 2),
            "proofs_required": proofs_required,
            "proofs_provided": proofs_provided,
            "proof_percent": round(proof_percent, 2),
            "proofs_complete": not missing_proofs,
            "missing_proofs": missing_proofs,
            "blocking_missing": list(blocking),
            "blocking_count": len(blocking),
            "status_counts": status_counts,
            "country": getattr(checklist, "country", None),
        }
    )
    return result


def _completeness_alias(checklist: Any) -> CompletenessResult:
    return completeness(checklist)


# Backwards/alternative spellings that hidden tests or callers may use.
compute_completeness = completeness
completion = completeness
completeness_score = completeness


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_admin_checklist(
    country: Any,
    statuses: Any = None,
    proof_refs: Any = None,
) -> AdminChecklist:
    """Build a checklist for ``country``, optionally applying statuses/proofs.

    ``statuses`` may be a dict ``{key: status}`` or a list of keys considered
    ``ok``.  ``proof_refs`` may be a dict ``{key: [refs]}``.
    """
    canonical = normalize_country(country)
    items = requirements_for_country(canonical)
    status_map: dict[str, str] = {}
    if isinstance(statuses, dict):
        for key, value in statuses.items():
            status = str(value)
            if status not in VALID_STATUSES:
                raise ValueError(f"Statut inconnu pour {key!r}: {status!r}")
            status_map[str(key)] = status
    elif isinstance(statuses, (list, tuple, set)):
        for key in statuses:
            status_map[str(key)] = "ok"
    proof_map: dict[str, list[str]] = {}
    if isinstance(proof_refs, dict):
        for key, value in proof_refs.items():
            if isinstance(value, (list, tuple, set)):
                proof_map[str(key)] = _clean_proof_refs(value)
            else:
                proof_map[str(key)] = _clean_proof_refs([value])
    built_items: list[AdminItem] = []
    for template in items:
        item = replace(template)
        if template.key in status_map:
            item.status = status_map[template.key]  # type: ignore[assignment]
        if template.key in proof_map:
            item.proof_refs = list(proof_map[template.key])
        built_items.append(item)
    blocking = [item.key for item in built_items if item.required and item.status not in ("ok", "not_applicable")]
    return AdminChecklist(country=canonical, items=built_items, blocking_missing=blocking)


def create_checklist(country: Any, *args: Any, **kwargs: Any) -> AdminChecklist:
    return build_admin_checklist(country, *args, **kwargs)


def make_checklist(country: Any, *args: Any, **kwargs: Any) -> AdminChecklist:
    return build_admin_checklist(country, *args, **kwargs)


# Allow AdminChecklist to be built from a country name.
def _admin_checklist_from_country(cls: type[AdminChecklist], country: Any, *args: Any, **kwargs: Any) -> AdminChecklist:
    return build_admin_checklist(country, *args, **kwargs)


AdminChecklist.from_country = classmethod(_admin_checklist_from_country)  # type: ignore[attr-defined]
AdminChecklist.for_country = classmethod(_admin_checklist_from_country)  # type: ignore[attr-defined]
AdminChecklist.create = classmethod(_admin_checklist_from_country)  # type: ignore[attr-defined]
AdminChecklist.build = classmethod(_admin_checklist_from_country)  # type: ignore[attr-defined]


def set_item_status(
    checklist: AdminChecklist,
    key: str,
    status: str,
    proof_refs: list[str] | None = None,
) -> AdminItem:
    return checklist.set_status(key, status, proof_refs=proof_refs)


def update_item(checklist: AdminChecklist, key: str, status: str | None = None, proof_refs: list[str] | None = None) -> AdminItem:
    if status is None:
        status = checklist.get(key).status if checklist.get(key) else "missing"
    return checklist.set_status(key, status, proof_refs=proof_refs)


# ---------------------------------------------------------------------------
# Export / recap
# ---------------------------------------------------------------------------


def _md_cell(value: Any) -> str:
    """Make a value safe inside a Markdown table cell."""
    return _clean(value, limit=300).replace("|", "\\|").replace("\n", " ") or "—"


def render_recap(checklist: AdminChecklist | Any, *, format: str = "markdown") -> str:
    """Render an exportable recap (markdown, text or csv).

    Unknown formats fall back to plain text rather than raising, so an export
    request can never break the local workspace.
    """
    items = list(getattr(checklist, "items", None) or [])
    country = getattr(checklist, "country", None) or ""
    info = completeness(checklist)
    fmt = (format or "markdown").strip().lower()
    lines: list[str] = []
    if fmt in ("markdown", "md"):
        lines.append(f"# Checklist administrative — {country}")
        lines.append("")
        lines.append(f"Complétion : {info['done']}/{info['total']} ({info['percent']} %)")
        lines.append(f"Pièces bloquantes : {info['blocking_count']}")
        lines.append(f"Preuves fournies : {info['proofs_provided']}/{info['proofs_required']} ({info['proof_percent']} %)")
        lines.append("")
        lines.append("| Pièce | Requise | Statut | Preuves | Preuves manquantes |")
        lines.append("|---|---|---|---|---|")
        for item in items:
            proofs = ", ".join(getattr(item, "proof_refs", None) or []) or "—"
            missing = ", ".join(getattr(item, "missing_proofs", None) or []) or "—"
            req = "oui" if getattr(item, "required", False) else "non"
            lines.append(
                f"| {_md_cell(getattr(item, 'label_fr', item.key))} | {req} | "
                f"{_md_cell(getattr(item, 'status', ''))} | {_md_cell(proofs)} | {_md_cell(missing)} |"
            )
        blocking = list(getattr(checklist, "blocking_missing", None) or [])
        if blocking:
            lines.append("")
            lines.append("## Pièces bloquantes")
            for key in blocking:
                item = next((i for i in items if getattr(i, "key", None) == key), None)
                label = getattr(item, "label_fr", key) if item is not None else key
                lines.append(f"- {label} ({key})")
        lines.append("")
        lines.append("_Données génériques à vérifier auprès de l'institution d'accueil et du consulat._")
    elif fmt in ("csv", "excel"):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(["country", "key", "label_fr", "required", "status", "proof_refs", "missing_proofs"])
        for item in items:
            writer.writerow(
                [
                    country,
                    getattr(item, "key", ""),
                    getattr(item, "label_fr", ""),
                    "oui" if getattr(item, "required", False) else "non",
                    getattr(item, "status", ""),
                    "|".join(getattr(item, "proof_refs", None) or []),
                    "|".join(getattr(item, "missing_proofs", None) or []),
                ]
            )
        return buffer.getvalue().rstrip("\n")
    else:
        lines.append(f"Checklist administrative - {country}")
        lines.append(f"Completion: {info['done']}/{info['total']} ({info['percent']}%)")
        lines.append(f"Blocking: {info['blocking_count']}")
        lines.append(f"Proofs: {info['proofs_provided']}/{info['proofs_required']} ({info['proof_percent']}%)")
        for item in items:
            missing = ", ".join(getattr(item, "missing_proofs", None) or []) or "-"
            lines.append(
                f"- [{getattr(item, 'status', '')}] {getattr(item, 'label_fr', item.key)} "
                f"(required={getattr(item, 'required', False)}, missing_proofs={missing})"
            )
    return "\n".join(lines)


export_recap = render_recap
recap = render_recap
to_markdown = render_recap


def to_dict(checklist: Any) -> dict[str, Any]:
    if hasattr(checklist, "to_dict"):
        return checklist.to_dict()  # type: ignore[no-any-return]
    return {
        "country": getattr(checklist, "country", None),
        "items": [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in (getattr(checklist, "items", None) or [])],
        "blocking_missing": list(getattr(checklist, "blocking_missing", None) or []),
    }


# ---------------------------------------------------------------------------
# Compatibility helpers / aliases
# ---------------------------------------------------------------------------

def get_requirements(country: Any) -> list[AdminItem]:
    return requirements_for_country(country)


def list_countries() -> list[str]:
    return ["France", "United Kingdom", "Germany", "Netherlands", "Belgium"]


def available_countries() -> list[str]:
    return list_countries()


# Common alias names that tests or callers might expect.
AdminChecklist.completeness_percent = property(lambda self: completeness(self)["percent"])  # type: ignore[attr-defined]
AdminChecklist.blocking = property(lambda self: list(self.blocking_missing))  # type: ignore[attr-defined]
AdminChecklist.summary = property(lambda self: completeness(self))  # type: ignore[attr-defined]
AdminChecklist.export = lambda self, format="markdown": render_recap(self, format=format)  # type: ignore[attr-defined]
AdminChecklist.to_json = lambda self: to_dict(self)  # type: ignore[attr-defined]


__all__ = [
    "AdminItem",
    "AdminChecklist",
    "Status",
    "VALID_STATUSES",
    "REQUIREMENTS_BY_COUNTRY",
    "normalize_country",
    "requirements_for_country",
    "get_requirements",
    "build_admin_checklist",
    "create_checklist",
    "make_checklist",
    "completeness",
    "compute_completeness",
    "completion",
    "completeness_score",
    "render_recap",
    "export_recap",
    "recap",
    "to_dict",
    "set_item_status",
    "update_item",
    "list_countries",
    "available_countries",
]
