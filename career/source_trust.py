"""Deterministic trust contract for the official link of a job offer.

The interface used to display one opaque boolean ("Source officielle liée")
computed from source metadata.  This module replaces that boolean with an
explicit, replayable and explainable decision:

``verified``
    The link is proven to be the employer's own source: a known ATS host
    plus a coherent employer, or the employer's own domain matching the
    declared employer.
``unverified``
    The link is usable but nothing ties it to a given employer: it stays a
    *linked* source, never a proven one.
``contradictory``
    The link contradicts the declared employer, the declared provider, or
    imitates the domain of a known provider.
``missing``
    There is no usable official link.

Design rules that the tests enforce:

* no network request is ever performed;
* a source flag is a *claim*, never a proof: the decision always rests on
  observable facts (host, path, local registry);
* every decision carries human readable ``reasons`` -- an empty explanation
  is a bug;
* ``registry_evidence`` is the record that supports the decision; it is set
  if and only if the status is ``verified``;
* the whole decision is replayable: the clock is injectable and no other
  ambient state is read.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from .models import clean_text, normalized_text
from .source_registry import CURATED_SOURCES


TrustStatus = Literal["verified", "unverified", "contradictory", "missing"]
EmployerMatch = Literal["confirmed", "mismatch", "unknown"]
ProviderName = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "employer", "unknown"]

TRUST_STATUSES: tuple[str, ...] = ("verified", "unverified", "contradictory", "missing")
EMPLOYER_MATCHES: tuple[str, ...] = ("confirmed", "mismatch", "unknown")
PROVIDERS: tuple[str, ...] = ("greenhouse", "lever", "ashby", "smartrecruiters", "employer", "unknown")

# Labels proposed for the interface.  The interface is not modified here:
# the labels are only the vocabulary a future integration may reuse.
STATUS_LABELS: dict[str, str] = {
    "verified": "Source officielle vérifiée",
    "unverified": "Source liée, non vérifiée",
    "contradictory": "Source contradictoire",
    "missing": "Source officielle manquante",
}

# Public link shorteners.  They hide the final target, so the target can
# never be proved from the short link alone: no network request is allowed
# here, hence the link stays "unverified" unless the caller already knows
# the final target and passes it explicitly.
SHORTENER_HOSTS: frozenset[str] = frozenset({
    "bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly",
    "rebrand.ly", "shorturl.at", "shorturl.com", "lnkd.in", "s.id", "rb.gy", "t.ly",
    "vk.cc", "youtu.be", "short.io", "clck.ru", "mzl.la", "lnk.to", "urlz.fr",
})

# Multi-label public suffixes.  The list is deliberately small and explicit:
# it only has to separate an employer domain from a board domain.
_MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "co.jp", "or.jp", "ne.jp",
    "co.kr", "com.au", "net.au", "org.au", "co.nz", "net.nz", "co.za", "com.br",
    "com.mx", "com.ar", "com.co", "com.tr", "com.cn", "com.hk", "com.sg", "com.tw",
    "co.in", "net.in", "co.il", "com.pl", "com.ua", "co.ma", "co.id", "com.my",
    "com.ph", "com.vn", "com.pk", "com.sa", "com.eg", "com.ng", "com.pe", "com.cl",
    "co.at", "co.hu", "co.rs", "co.me", "co.cr", "co.th",
})

_IPV4_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_OPAQUE_TOKEN_RE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+|[0-9a-f]{16,})$",
    re.IGNORECASE,
)
# Two characters are enough to be a brand name on its own ("bp", "axa"), but
# a *substring* match on a short name produces false positives ("clever"
# contains "lever"), so containment requires a longer distinctive name.
_MIN_CONTAINMENT_LENGTH = 4


@dataclass(frozen=True)
class AtsProfile:
    """A documented ATS: its official board hosts and its vendor domain."""

    provider: str
    label: str
    board_hosts: frozenset[str]
    vendor_domains: frozenset[str]
    brand_tokens: tuple[str, ...]


ATS_PROFILES: tuple[AtsProfile, ...] = (
    AtsProfile(
        provider="greenhouse",
        label="Greenhouse",
        board_hosts=frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"}),
        vendor_domains=frozenset({"greenhouse.io"}),
        brand_tokens=("greenhouse",),
    ),
    AtsProfile(
        provider="lever",
        label="Lever",
        board_hosts=frozenset({"jobs.lever.co", "jobs.eu.lever.co", "api.lever.co", "api.eu.lever.co"}),
        vendor_domains=frozenset({"lever.co"}),
        brand_tokens=("lever",),
    ),
    AtsProfile(
        provider="ashby",
        label="Ashby",
        board_hosts=frozenset({"jobs.ashbyhq.com", "api.ashbyhq.com"}),
        vendor_domains=frozenset({"ashbyhq.com"}),
        brand_tokens=("ashby", "ashbyhq"),
    ),
    AtsProfile(
        provider="smartrecruiters",
        label="SmartRecruiters",
        board_hosts=frozenset({
            "www.smartrecruiters.com", "careers.smartrecruiters.com",
            "jobs.smartrecruiters.com", "api.smartrecruiters.com",
        }),
        vendor_domains=frozenset({"smartrecruiters.com"}),
        brand_tokens=("smartrecruiters", "smartrecruiter"),
    ),
)

_ATS_BY_PROVIDER: dict[str, AtsProfile] = {profile.provider: profile for profile in ATS_PROFILES}


@dataclass(frozen=True)
class TrustResult:
    """The explicit outcome of one trust decision."""

    status: TrustStatus
    provider: Optional[str]
    canonical_host: Optional[str]
    employer_match: EmployerMatch
    registry_evidence: Optional[str]
    reasons: list[str]
    checked_at: str

    def to_dict(self) -> dict[str, object]:
        """Return the JSON contract exposed to the interface."""

        return {
            "status": self.status,
            "provider": self.provider,
            "canonical_host": self.canonical_host,
            "employer_match": self.employer_match,
            "registry_evidence": self.registry_evidence,
            "reasons": list(self.reasons),
            "checked_at": self.checked_at,
        }


@dataclass(frozen=True)
class RegistryRecord:
    """One curated public-source record, with its provenance."""

    id: str
    provider: str
    company: str
    board_token: str
    public_url: str
    provenance_url: str
    verified_at: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact(text: str) -> str:
    """Fold a name to letters and digits only ("Acme Corp" -> "acmecorp")."""

    return normalized_text(text).replace(" ", "")


def _labels(host: str) -> list[str]:
    return [label for label in host.lower().split(".") if label]


def registrable_domain(host: str) -> str:
    """Return the registrable domain of a host ("careers.acme.co.uk" -> "acme.co.uk")."""

    labels = _labels(host)
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def core_label(host: str) -> str:
    """Return the employer-facing label of a domain ("careers.acme.com" -> "acme")."""

    labels = registrable_domain(host).split(".")
    return labels[0] if len(labels) >= 2 else registrable_domain(host)


def names_match(hint: str, candidate: str) -> bool:
    """Tell whether an employer name and a board/domain name designate the same employer."""

    left = _compact(hint)
    right = _compact(candidate)
    if not left or not right:
        return False
    if left == right:
        return True
    if len(right) >= _MIN_CONTAINMENT_LENGTH and right in left:
        return True
    if len(left) >= _MIN_CONTAINMENT_LENGTH and left in right:
        return True
    return False


def _label_mentions_brand(label: str, brand: str) -> bool:
    """Tell whether a host label names a brand ("greenhouse-jobs" mentions "greenhouse")."""

    parts = [part for part in re.split(r"[-_]", label.lower()) if part]
    return any(part == brand for part in parts)


def _exact_profile(host: str) -> Optional[AtsProfile]:
    for profile in ATS_PROFILES:
        if host in profile.board_hosts:
            return profile
    return None


def _vendor_profile(host: str) -> Optional[AtsProfile]:
    domain = registrable_domain(host)
    for profile in ATS_PROFILES:
        if domain in profile.vendor_domains:
            return profile
    return None


def _impersonated_profile(host: str) -> tuple[Optional[AtsProfile], str]:
    """Detect a host that pretends to be an official host ("boards.greenhouse.io.evil.test")."""

    for profile in ATS_PROFILES:
        # The longest candidate wins: "job-boards.greenhouse.io" is more precise
        # than "greenhouse.io" when a host pretends to be an official one.
        for candidate in sorted(profile.board_hosts | profile.vendor_domains, key=len, reverse=True):
            if host.startswith(f"{candidate}."):
                return profile, candidate
    return None, ""


def _lookalike_brand(host: str) -> tuple[Optional[AtsProfile], str]:
    for profile in ATS_PROFILES:
        for label in _labels(host):
            for brand in profile.brand_tokens:
                if _label_mentions_brand(label, brand):
                    return profile, brand
    return None, ""


def _board_token(profile: AtsProfile, host: str, parts: list[str]) -> Optional[str]:
    """Extract the board token of an ATS URL, per documented URL layout."""

    if not parts:
        return None
    provider = profile.provider
    if provider == "greenhouse":
        if host == "boards-api.greenhouse.io":
            if len(parts) >= 3 and parts[0].lower() == "v1" and parts[1].lower() == "boards":
                return parts[2]
            return None
        return parts[0]
    if provider == "lever":
        if parts[0].lower() == "company":
            return parts[1] if len(parts) > 1 else None
        return parts[0]
    if provider == "ashby":
        if host == "api.ashbyhq.com":
            if len(parts) >= 3 and parts[0].lower() == "posting-api" and parts[1].lower() == "job-board":
                return parts[2]
            return None
        return parts[0]
    if provider == "smartrecruiters":
        if host == "api.smartrecruiters.com":
            if len(parts) >= 3 and parts[0].lower() == "v1" and parts[1].lower() == "companies":
                return parts[2]
            return None
        if host == "www.smartrecruiters.com" and parts[0].lower() == "jobs":
            return parts[1] if len(parts) > 1 else None
        return parts[0]
    return parts[0]


def _is_opaque_token(token: str) -> bool:
    """Tell whether a board token is an opaque identifier rather than a company name."""

    return bool(_OPAQUE_TOKEN_RE.match(token.strip()))


def _registry_records() -> tuple[RegistryRecord, ...]:
    return tuple(
        RegistryRecord(
            id=clean_text(entry.get("id"), limit=200),
            provider=clean_text(entry.get("provider"), limit=60).lower(),
            company=clean_text(entry.get("company"), limit=200),
            board_token=clean_text(entry.get("board_token"), limit=200),
            public_url=clean_text(entry.get("public_url"), limit=2_000),
            provenance_url=clean_text(entry.get("provenance_url"), limit=2_000),
            verified_at=clean_text(entry.get("verified_at"), limit=64),
        )
        for entry in CURATED_SOURCES
    )


_REGISTRY_RECORDS: tuple[RegistryRecord, ...] = _registry_records()
_REGISTRY_BY_BOARD: dict[tuple[str, str], RegistryRecord] = {
    (record.provider, _compact(record.board_token)): record
    for record in _REGISTRY_RECORDS
    if record.provider in _ATS_BY_PROVIDER and record.board_token
}
_REGISTRY_BY_COMPANY: dict[tuple[str, str], RegistryRecord] = {
    (record.provider, _compact(record.company)): record
    for record in _REGISTRY_RECORDS
    if record.provider in _ATS_BY_PROVIDER and record.company
}
_VENDOR_DOMAINS: frozenset[str] = frozenset(
    domain for profile in ATS_PROFILES for domain in profile.vendor_domains
)
_REGISTRY_BY_EMPLOYER_DOMAIN: dict[str, RegistryRecord] = {}
for _record in _REGISTRY_RECORDS:
    if _record.provider not in _ATS_BY_PROVIDER or not _record.provenance_url:
        continue
    _provenance_host = urllib.parse.urlsplit(_record.provenance_url).hostname or ""
    _provenance_domain = registrable_domain(_provenance_host.lower())
    if not _provenance_domain or _provenance_domain in _VENDOR_DOMAINS:
        continue
    _REGISTRY_BY_EMPLOYER_DOMAIN.setdefault(_provenance_domain, _record)


def _result(
    status: str,
    provider: Optional[str],
    canonical_host: Optional[str],
    employer_match: str,
    registry_evidence: Optional[str],
    reasons: list[str],
    checked_at: str,
) -> TrustResult:
    """Build a result and enforce the invariants of the contract."""

    if status not in TRUST_STATUSES:
        raise ValueError(f"Statut de confiance inconnu : {status}")
    if employer_match not in EMPLOYER_MATCHES:
        raise ValueError(f"Correspondance employeur inconnue : {employer_match}")
    # A supporting record exists exactly when the decision is a proof.
    if status != "verified":
        registry_evidence = None
    return TrustResult(
        status=status,  # type: ignore[arg-type]
        provider=provider,
        canonical_host=canonical_host,
        employer_match=employer_match,  # type: ignore[arg-type]
        registry_evidence=registry_evidence,
        reasons=list(reasons),
        checked_at=checked_at,
    )


def _ats_decision(
    profile: AtsProfile,
    host: str,
    token: Optional[str],
    hint: str,
    reasons: list[str],
) -> tuple[str, str, Optional[str]]:
    """Decide an ATS-hosted link; return (status, employer_match, evidence)."""

    board_record = _REGISTRY_BY_BOARD.get((profile.provider, _compact(token))) if token else None
    if board_record is not None:
        reasons.append(
            f"Board enregistré dans le registre curaté : {board_record.id} "
            f"(entreprise « {board_record.company} », vérifié le {board_record.verified_at})."
        )
        if hint and not names_match(hint, board_record.company):
            reasons.append(
                f"Le board « {board_record.board_token} » appartient à « {board_record.company} », "
                f"pas à l'employeur annoncé « {hint} » : incohérence."
            )
            return "contradictory", "mismatch", None
        reasons.append(
            f"L'employeur « {board_record.company} » est rattaché à ce board par le registre curaté."
        )
        return "verified", "confirmed", board_record.id

    if hint:
        company_record = _REGISTRY_BY_COMPANY.get((profile.provider, _compact(hint)))
        if company_record is not None and company_record.board_token:
            reasons.append(
                f"L'employeur « {hint} » est enregistré chez {profile.label} sous le board "
                f"« {company_record.board_token} », pas « {token or '—'} » : incohérence."
            )
            return "contradictory", "mismatch", None
        if token and not _is_opaque_token(token):
            if names_match(hint, token):
                reasons.append(
                    f"Jeton de board « {token} » cohérent avec l'employeur annoncé « {hint} »."
                )
                reasons.append(
                    f"Preuve : « registry:{profile.provider}:{token} » (domaine {profile.label} officiel "
                    "+ jeton de board cohérent avec l'employeur)."
                )
                return "verified", "confirmed", f"registry:{profile.provider}:{token}"
            reasons.append(
                f"Jeton de board « {token} » sans lien avec l'employeur annoncé « {hint} » : incohérence."
            )
            return "contradictory", "mismatch", None
        if token:
            reasons.append(
                f"Jeton de board « {token} » opaque : il ne permet pas de confirmer l'employeur « {hint} »."
            )
        else:
            reasons.append(
                f"Aucun jeton de board lisible dans l'URL : l'employeur « {hint} » ne peut pas être confirmé."
            )
        return "unverified", "unknown", None

    reasons.append(
        f"Le lien pointe sur un domaine {profile.label} officiel, mais aucun élément ne le rattache "
        "à un employeur : le lien reste lié, non vérifié."
    )
    return "unverified", "unknown", None


def _employer_decision(host: str, hint: str, reasons: list[str]) -> tuple[str, str, Optional[str]]:
    """Decide a link hosted on the employer's own domain."""

    domain = registrable_domain(host)
    record = _REGISTRY_BY_EMPLOYER_DOMAIN.get(domain)
    if record is not None:
        reasons.append(
            f"Domaine employeur attesté par le registre curaté : {record.id} "
            f"(entreprise « {record.company} », vérifié le {record.verified_at})."
        )
        if hint and not names_match(hint, record.company):
            reasons.append(
                f"Le domaine « {domain} » appartient à « {record.company} », pas à l'employeur "
                f"annoncé « {hint} » : incohérence."
            )
            return "contradictory", "mismatch", None
        return "verified", "confirmed", record.id

    label = core_label(host)
    reasons.append(f"Domaine d'employeur : {domain} (hôte observé : {host}).")
    if hint:
        if names_match(hint, label):
            reasons.append(f"Le domaine « {label} » correspond à l'employeur annoncé « {hint} ».")
            reasons.append(
                f"Preuve : « registry:employer:{domain} » (domaine de l'employeur ; "
                "aucun enregistrement curaté ne couvre ce domaine)."
            )
            return "verified", "confirmed", f"registry:employer:{domain}"
        reasons.append(
            f"Le domaine « {label} » ne correspond pas à l'employeur annoncé « {hint} » : incohérence."
        )
        return "contradictory", "mismatch", None
    reasons.append(
        "Aucun indice d'employeur fourni : le domaine n'est rattaché à aucune preuve d'employeur."
    )
    return "unverified", "unknown", None


def check_trust(
    url: str,
    *,
    employer_hint: str | None = None,
    declared_provider: str | None = None,
    final_url: str | None = None,
    clock: Callable[[], str] | None = None,
) -> TrustResult:
    """Return the trust decision for one official link.

    ``employer_hint`` is the employer the link is supposed to point to.
    ``declared_provider`` is the provider claimed by the offer metadata: it
    is checked against the observed host, never trusted as a proof.
    ``final_url`` is the already resolved target of a shortened link: it is
    supplied by the caller because this module never performs a request.
    ``clock`` makes the decision replayable.
    """

    checked_at = (clock or _utc_now)()
    hint = clean_text(employer_hint, limit=200)
    declared = clean_text(declared_provider, limit=60).lower()
    raw = clean_text(url, limit=2_000)

    if not raw:
        return _result(
            "missing", None, None, "unknown", None,
            ["Aucune URL officielle n'est fournie : la source n'est pas liée."],
            checked_at,
        )

    parsed = urllib.parse.urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return _result(
            "missing", None, None, "unknown", None,
            [f"URL officielle inexploitable (« {raw[:120]} ») : seule une URL http(s) peut être une source."],
            checked_at,
        )
    if parsed.username or parsed.password:
        return _result(
            "missing", None, None, "unknown", None,
            ["URL officielle porteuse d'identifiants : elle n'est jamais utilisée comme source."],
            checked_at,
        )
    try:
        port = parsed.port
    except ValueError:
        return _result(
            "missing", None, None, "unknown", None,
            ["URL officielle inexploitable : le port n'est pas valide."],
            checked_at,
        )

    host = parsed.hostname.lower().rstrip(".")
    canonical_host = host[4:] if host.startswith("www.") else host

    if host in SHORTENER_HOSTS:
        target = clean_text(final_url, limit=2_000)
        if not target:
            return _result(
                "unverified", "unknown", canonical_host, "unknown", None,
                [
                    f"URL raccourcie ({host}) : la cible finale n'est pas résolue localement.",
                    "Un lien raccourci ne peut pas être vérifié sans requête réseau : il reste lié, non vérifié.",
                ],
                checked_at,
            )
        resolved = check_trust(target, employer_hint=hint, declared_provider=declared, clock=clock)
        target_host = urllib.parse.urlsplit(target).hostname or ""
        reasons = [
            f"URL raccourcie ({host}) résolue vers « {target_host} » (cible fournie par l'appelant)."
        ] + list(resolved.reasons)
        return _result(
            resolved.status, resolved.provider, resolved.canonical_host, resolved.employer_match,
            resolved.registry_evidence, reasons, checked_at,
        )

    parts = [part for part in (parsed.path or "").split("/") if part]
    reasons: list[str] = []

    if _IPV4_RE.match(host):
        return _result(
            "unverified", "unknown", canonical_host, "unknown", None,
            [f"Hôte « {host} » : une adresse IP ne désigne pas une source officielle."],
            checked_at,
        )

    profile = _exact_profile(host)
    official_host = profile is not None
    provider: Optional[str] = profile.provider if profile else None

    if profile is None:
        impersonated, impersonated_host = _impersonated_profile(host)
        if impersonated is not None:
            reasons.append(
                f"Le lien imite le domaine officiel « {impersonated_host} » de {impersonated.label} : "
                f"l'hôte réel « {host} » n'est pas contrôlé par {impersonated.label} : contradiction."
            )
            return _result(
                "contradictory", impersonated.provider, canonical_host, "unknown", None, reasons, checked_at,
            )
        profile = _vendor_profile(host)
        if profile is not None:
            provider = profile.provider
            reasons.append(
                f"Hôte « {host} » sous le domaine du fournisseur {profile.label}, "
                "mais l'hôte de board n'est pas un domaine officiel documenté."
            )
        else:
            lookalike, brand = _lookalike_brand(host)
            if lookalike is not None:
                reasons.append(
                    f"Le domaine « {host} » mentionne « {brand} » mais n'est pas le domaine officiel de "
                    f"{lookalike.label} : le lien reste non vérifié."
                )
                reasons.append(
                    "Un domaine ressemblant à un fournisseur connu ne prouve jamais une source officielle."
                )
                return _result(
                    "unverified", "unknown", canonical_host, "unknown", None, reasons, checked_at,
                )

    if profile is not None:
        token = _board_token(profile, host, parts)
        if official_host:
            reasons.append(f"Domaine {profile.label} officiel : {host}.")
        status, employer_match, evidence = _ats_decision(profile, host, token, hint, reasons)
    else:
        provider = "employer"
        status, employer_match, evidence = _employer_decision(host, hint, reasons)

    if declared and declared in _ATS_BY_PROVIDER:
        if provider == declared:
            reasons.append(f"Source déclarée « {declared} » cohérente avec le fournisseur observé.")
        elif provider in _ATS_BY_PROVIDER:
            reasons.append(
                f"Source déclarée « {declared} » alors que le lien pointe chez « {provider} » : incohérence."
            )
            status = "contradictory"
        else:
            reasons.append(
                f"Source déclarée « {declared} » non confirmée par le lien : "
                "une source déclarée ne constitue jamais une preuve."
            )

    if scheme == "http" and status == "verified":
        reasons.append("Lien non chiffré (http) : il ne peut pas être considéré comme vérifié.")
        status = "unverified"

    if port not in {None, 80, 443} and status == "verified":
        reasons.append(
            f"Port non standard ({port}) : un lien de publication officielle n'utilise pas de port dédié."
        )
        status = "unverified"

    return _result(status, provider, canonical_host, employer_match, evidence, reasons, checked_at)


def status_label(status: str) -> str:
    """Return the interface label of a status (empty string when unknown)."""

    return STATUS_LABELS.get(status, "")
