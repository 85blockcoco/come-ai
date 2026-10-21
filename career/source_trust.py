"""Deterministic trust contract for official Career source links.

The Career interface displays a "Source officielle liée" badge that used to be
derived from a single opaque metadata flag.  This module replaces that flag
with an explicit, explainable contract: every decision states which provider
was recognised, which canonical host was seen, whether the employer agrees,
which local registry entry corroborates the link, and why the decision was
taken.

Everything here is pure and offline:

* no network call, no DNS, no HTTP client;
* no filesystem access, no database, no private preference;
* the clock is injected, so the same input always yields the same verdict.

The module deliberately refuses to treat any single source flag as proof.
A metadata claim ("this offer says it is official") is accepted as an input
but never changes the verdict: only structural evidence (a canonical ATS
host, an employer-owned domain, a local registry entry) can raise a link to
``verified``.

The four statuses are:

``verified``
    A known provider (or an employer-owned domain) *and* a proven employer
    agreement.  The link is proven official for that employer.
``unverified``
    The domain is linked to something plausible but nothing proves the link
    is the employer's own page (unknown board, secondary vendor host, short
    link, look-alike domain, no employer context at all).
``contradictory``
    An inconsistency was detected: a deceptive host that impersonates a
    vendor, or a known provider board that belongs to another employer.
``missing``
    No URL at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal
import unicodedata
import urllib.parse

from .source_registry import CURATED_SOURCES


TrustStatus = Literal["verified", "unverified", "contradictory", "missing"]
EmployerMatch = Literal["confirmed", "mismatch", "unknown"]

STATUS_VERIFIED: TrustStatus = "verified"
STATUS_UNVERIFIED: TrustStatus = "unverified"
STATUS_CONTRADICTORY: TrustStatus = "contradictory"
STATUS_MISSING: TrustStatus = "missing"

# The interface differentiates the three usable states (constraint 3 of the
# mission).  The labels are plain text: the module never renders HTML.
STATUS_LABELS: dict[str, str] = {
    STATUS_VERIFIED: "Source officielle vérifiée",
    STATUS_UNVERIFIED: "Source liée, non vérifiée",
    STATUS_CONTRADICTORY: "Source contradictoire",
    STATUS_MISSING: "Source officielle absente",
}

MAX_REDIRECT_HOPS = 5
MAX_URL_LENGTH = 2_000


@dataclass(frozen=True)
class ProviderSpec:
    """One known applicant-tracking vendor and the hosts it actually serves."""

    name: str
    domain: str
    canonical_hosts: frozenset[str]
    brand: str
    token_query_param: str = ""


# Only hosts that really serve public job postings are canonical.  A vendor
# owns more hosts than that (API hosts, embed hosts, marketing sites); those
# are reported as secondary hosts and never grant a "verified" status.
PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        name="greenhouse",
        domain="greenhouse.io",
        canonical_hosts=frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"}),
        brand="greenhouse",
        token_query_param="for",
    ),
    ProviderSpec(
        name="lever",
        domain="lever.co",
        canonical_hosts=frozenset({"jobs.lever.co", "jobs.eu.lever.co"}),
        brand="lever",
    ),
    ProviderSpec(
        name="ashby",
        domain="ashbyhq.com",
        canonical_hosts=frozenset({"jobs.ashbyhq.com"}),
        brand="ashby",
    ),
    ProviderSpec(
        name="smartrecruiters",
        domain="smartrecruiters.com",
        canonical_hosts=frozenset({"careers.smartrecruiters.com", "jobs.smartrecruiters.com"}),
        brand="smartrecruiters",
    ),
)

PROVIDERS_BY_NAME: dict[str, ProviderSpec] = {spec.name: spec for spec in PROVIDERS}

# Link shorteners hide the real destination: the module can never prove such a
# link is official unless the caller supplies the resolved target locally.
SHORTENER_HOSTS: frozenset[str] = frozenset({
    "bit.ly", "t.co", "tinyurl.com", "cutt.ly", "rebrand.ly", "s.id", "lnkd.in",
    "ow.ly", "buff.ly", "is.gd", "rb.gy", "tiny.cc", "soo.gd", "shorturl.at",
    "shorte.st", "t.ly", "clck.ru", "v.gd", "tiny.one", "urlz.fr", "goo.gl",
    "shorturl.com", "trib.al", "db.tt", "qr.ae", "short.io",
})

# Host labels that never identify an employer on their own.
GENERIC_LABELS: frozenset[str] = frozenset({
    "www", "web", "site", "jobs", "job", "career", "careers", "recruit",
    "recruiting", "recruitment", "rh", "talent", "talents", "work", "workplace",
    "hire", "hiring", "join", "joinus", "portal", "people", "team", "home",
    "en", "fr", "de", "es", "it", "nl", "eu", "us", "uk", "ch", "be", "at",
    "pt", "se", "no", "dk", "fi", "pl", "cz", "ca", "au", "jp", "cn", "in",
    "br", "mx", "global", "company", "corp", "inc", "ltd", "llc", "ag", "gmbh",
    "holding", "holdings", "group", "groups",
})

# Legal forms and connectives are dropped before comparing two names: they
# carry no identity ("Acme Corp" == "Acme", "Qube Research & Technologies" ==
# "Qube Research and Technologies").
LEGAL_NOISE: frozenset[str] = frozenset({
    "corp", "corporation", "inc", "incorporated", "ltd", "limited", "llc",
    "llp", "plc", "sa", "sas", "sarl", "spa", "ag", "gmbh", "bv", "nv", "co",
    "company",
})
CONNECTIVES: frozenset[str] = frozenset({"and", "et", "the", "of", "und", "for", "fur"})

# Multi-part public suffixes, kept small and explicit: the module never
# performs a network lookup (no PSL download) and only needs to recognise the
# employer domain, not to resolve every suffix in the world.
MULTI_PART_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "co.jp", "ne.jp",
    "or.jp", "co.kr", "co.nz", "co.za", "co.in", "com.au", "net.au", "org.au",
    "com.br", "com.mx", "com.ar", "com.tr", "com.cn", "com.sg", "com.hk",
    "com.tw", "co.il", "co.id", "co.th",
})

# Top-level labels are never an employer identity.
TOP_LEVEL_LABELS: frozenset[str] = frozenset({
    "com", "net", "org", "io", "co", "fr", "de", "es", "it", "nl", "be", "ch",
    "at", "uk", "eu", "us", "ca", "au", "jp", "cn", "in", "br", "mx", "ru",
    "se", "no", "dk", "fi", "pl", "cz", "pt", "ie", "nz", "za", "kr", "sg",
    "hk", "tw", "il", "tr", "ae", "info", "biz", "dev", "app", "ai", "jobs",
    "example", "test", "invalid", "localhost",
})


@dataclass(frozen=True)
class TrustResult:
    """The explainable outcome of one source-link check."""

    status: TrustStatus
    provider: str | None
    canonical_host: str | None
    employer_match: EmployerMatch
    registry_evidence: str | None
    reasons: list[str]
    checked_at: str

    @property
    def label(self) -> str:
        """Human readable label the interface can show as-is."""
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_official(self) -> bool:
        return self.status == STATUS_VERIFIED

    def to_dict(self) -> dict[str, object]:
        """The JSON contract of the mission, exactly."""
        return {
            "status": self.status,
            "provider": self.provider,
            "canonical_host": self.canonical_host,
            "employer_match": self.employer_match,
            "registry_evidence": self.registry_evidence,
            "reasons": list(self.reasons),
            "checked_at": self.checked_at,
        }


def check_trust(
    url: str,
    *,
    employer_hint: str | None = None,
    registry: Iterable[Mapping[str, str]] | None = None,
    redirects: Mapping[str, str] | None = None,
    claimed_official: bool = False,
    clock: Callable[[], str] | None = None,
) -> TrustResult:
    """Grade one source link without any network access.

    ``url``
        The link to grade.  An empty value yields the ``missing`` status.
    ``employer_hint``
        The employer the link is supposed to belong to (company name).
    ``registry``
        Local evidence entries (``registry:<provider>:<token>``).  Defaults to
        the curated registry of the product.
    ``redirects``
        Locally known redirections, used to follow a short link to its final
        target without touching the network.
    ``claimed_official``
        A metadata claim ("the source says this is official").  It is never a
        proof: it is reported in the reasons and changes nothing.
    ``clock``
        ISO 8601 clock, injected so the decision stays reproducible.
    """
    checked_at = _now(clock)
    raw = _clean(url)
    if not raw:
        return TrustResult(
            status=STATUS_MISSING,
            provider=None,
            canonical_host=None,
            employer_match="unknown",
            registry_evidence=None,
            reasons=["Aucune URL de source officielle n’est fournie."],
            checked_at=checked_at,
        )

    reasons: list[str] = []
    entries = _registry_entries(registry)
    target, hops = _resolve_redirects(raw, redirects or {})
    for source, destination in hops:
        reasons.append(f"Redirection locale résolue : « {source} » → « {destination} ».")

    parsed = urllib.parse.urlsplit(target)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        reasons.append(f"Le schéma « {scheme or 'absent'} » n’est pas http(s) : ce lien ne peut pas identifier une source officielle.")
        return _result(STATUS_UNVERIFIED, "unknown", None, "unknown", None, reasons, checked_at, claimed_official)

    host = _host(parsed)
    if not host:
        reasons.append("L’URL ne contient aucun nom de domaine exploitable.")
        return _result(STATUS_UNVERIFIED, "unknown", None, "unknown", None, reasons, checked_at, claimed_official)

    if parsed.username or parsed.password:
        reasons.append("L’URL contient un identifiant ou un mot de passe : elle n’est pas retenue comme preuve.")
        return _result(STATUS_UNVERIFIED, "unknown", host, "unknown", None, reasons, checked_at, claimed_official)

    vendor = _impersonated_vendor(host)
    if vendor:
        reasons.append(
            f"Le domaine « {host} » imite le fournisseur « {vendor} » alors qu’il ne lui appartient pas : contradiction."
        )
        return _result(STATUS_CONTRADICTORY, "unknown", host, "unknown", None, reasons, checked_at, claimed_official)

    if _is_shortener(host):
        reasons.append(f"Le lien est un raccourcisseur (« {host} ») : la destination réelle n’est pas prouvée par ce module.")
        return _result(STATUS_UNVERIFIED, "unknown", host, "unknown", None, reasons, checked_at, claimed_official)

    spec, relation = _provider_for_host(host)
    if spec is not None:
        return _grade_provider(spec, relation, parsed, host, employer_hint, entries, reasons, checked_at, claimed_official)
    return _grade_plain_host(host, employer_hint, entries, reasons, checked_at, claimed_official)


def check_offer_trust(
    offer: Mapping[str, object],
    *,
    employer_hint: str | None = None,
    registry: Iterable[Mapping[str, str]] | None = None,
    redirects: Mapping[str, str] | None = None,
    claimed_official: bool = False,
    clock: Callable[[], str] | None = None,
) -> TrustResult:
    """Grade the official link carried by an offer mapping.

    The employer hint defaults to the company written on the offer.  The
    mapping is only read, never modified.
    """
    payload = offer if isinstance(offer, Mapping) else {}
    url = payload.get("official_url") or payload.get("apply_url") or ""
    hint = employer_hint if employer_hint is not None else payload.get("company")
    claim = claimed_official or bool(payload.get("source_verified"))
    return check_trust(
        str(url or ""),
        employer_hint=str(hint) if hint else None,
        registry=registry,
        redirects=redirects,
        claimed_official=claim,
        clock=clock,
    )


# --- provider hosts ---------------------------------------------------------


def _provider_for_host(host: str) -> tuple[ProviderSpec | None, str]:
    """Return the vendor owning ``host`` and how the host relates to it."""
    for spec in PROVIDERS:
        if host in spec.canonical_hosts:
            return spec, "canonical"
        if host.endswith(f".{spec.domain}"):
            return spec, "vendor_subdomain"
    return None, "none"


def _impersonated_vendor(host: str) -> str | None:
    """Return the vendor whose identity the host structurally claims.

    Two shapes are detected, both of them impersonations:

    * the vendor domain is embedded in a domain the vendor does not own
      (``boards.greenhouse.io.evil.example``, ``notgreenhouse.io``);
    * the vendor brand is the left-most label of someone else's domain
      (``greenhouse.evil.example``).
    """
    for spec in PROVIDERS:
        if host == spec.domain or host.endswith(f".{spec.domain}"):
            continue
        if f".{spec.domain}" in host or host.startswith(f"{spec.domain}."):
            return spec.name
        labels = host.split(".")
        if len(labels) >= 3 and labels[0] == spec.brand:
            return spec.name
    return None


def _is_shortener(host: str) -> bool:
    return host in SHORTENER_HOSTS or _registrable_domain(host) in SHORTENER_HOSTS


# --- employer agreement -----------------------------------------------------


def _employer_agreement(candidate: str, hint: str) -> str:
    """Compare a candidate identity with the expected employer.

    Returns ``match`` (same employer), ``compatible`` (same employer with a
    loose slug: the board token extends the name without a shared word
    boundary) or ``mismatch`` (a different employer).
    """
    candidate_core = _core(candidate)
    hint_core = _core(hint)
    if not candidate_core or not hint_core:
        return "compatible" if candidate_core or hint_core else "mismatch"
    if candidate_core == hint_core:
        return "match"
    shorter, longer = sorted((candidate_core, hint_core), key=len)
    if len(shorter) < 3:
        # Too short to conclude: an abbreviation may hide the real name.
        return "compatible"
    if longer.startswith(shorter):
        remainder = longer[len(shorter):]
        if _is_word_suffix(remainder, _words(hint)) or _is_word_suffix(remainder, _words(candidate)):
            return "match"
    if shorter in longer:
        # The slug extends the name without any shared word boundary: the two
        # may still be the same employer, so no contradiction is claimed.
        return "compatible"
    return "mismatch"


def _is_word_suffix(remainder: str, words: tuple[str, ...]) -> bool:
    """True when ``remainder`` is the concatenation of a suffix of ``words``."""
    for index in range(len(words)):
        if "".join(words[index:]) == remainder:
            return True
    return False


# --- grading ----------------------------------------------------------------


def _grade_provider(
    spec: ProviderSpec,
    relation: str,
    parsed: urllib.parse.SplitResult,
    host: str,
    employer_hint: str | None,
    entries: list[Mapping[str, str]],
    reasons: list[str],
    checked_at: str,
    claimed_official: bool,
) -> TrustResult:
    """Grade a link served by a known applicant-tracking vendor."""
    token = _board_token(spec, parsed)
    evidence = _registry_evidence(entries, spec, token, host)

    if relation == "canonical":
        reasons.append(f"« {host} » est un hôte de board public de {spec.name}.")
    else:
        reasons.append(f"« {host} » est un hôte secondaire de {spec.name}, pas un hôte de board public : l’officialité n’est pas prouvée.")

    if evidence is not None:
        reasons.append(f"Preuve locale : la source « {evidence.get('id', '')} » atteste ce board pour « {evidence.get('company', '')} ».")
    elif token:
        reasons.append(f"Board « {token} » sur {host} : aucune entrée du registre local ne l’attribue.")

    company = _clean(evidence.get("company", "")) if evidence else ""
    hint = _clean(employer_hint or "")
    employer_match: EmployerMatch = "unknown"
    if hint and company:
        agreement = _employer_agreement(company, hint)
        if agreement == "mismatch":
            employer_match = "mismatch"
            reasons.append(f"Le board appartient à « {company} » alors que l’employeur attendu est « {hint} » : contradiction.")
        else:
            employer_match = "confirmed"
    elif hint and token:
        agreement = _employer_agreement(token, hint)
        if agreement == "match":
            employer_match = "confirmed"
            reasons.append(f"Le board « {token} » correspond à l’employeur attendu « {hint} ».")
        elif agreement == "compatible":
            employer_match = "unknown"
            reasons.append(f"Le board « {token} » est compatible avec « {hint} » sans le prouver : l’employeur reste à confirmer.")
        else:
            employer_match = "mismatch"
            reasons.append(f"Le board « {token} » de {spec.name} ne correspond pas à l’employeur attendu « {hint} » : contradiction.")
    elif evidence:
        employer_match = "confirmed"
        reasons.append(f"L’attribution du board à « {company} » est prouvée par le registre local.")
    else:
        reasons.append("Aucun élément local ne rattache ce board à un employeur : la cohérence employeur reste à établir.")

    if employer_match == "mismatch":
        status: TrustStatus = STATUS_CONTRADICTORY
    elif relation != "canonical":
        status = STATUS_UNVERIFIED
    elif employer_match == "confirmed":
        status = STATUS_VERIFIED
    else:
        status = STATUS_UNVERIFIED

    return _result(status, spec.name, host, employer_match, _evidence_id(evidence), reasons, checked_at, claimed_official)


def _grade_plain_host(
    host: str,
    employer_hint: str | None,
    entries: list[Mapping[str, str]],
    reasons: list[str],
    checked_at: str,
    claimed_official: bool,
) -> TrustResult:
    """Grade a link that is not served by a known vendor."""
    domain = _registrable_domain(host)
    candidates = _domain_candidates(domain)
    evidence = _registry_evidence_for_host(entries, host)
    hint = _clean(employer_hint or "")

    if evidence is not None:
        reasons.append(f"Preuve locale : la source « {evidence.get('id', '')} » atteste ce domaine pour « {evidence.get('company', '')} ».")

    employer_match: EmployerMatch = "unknown"
    company = _clean(evidence.get("company", "")) if evidence else ""
    if hint and company:
        agreement = _employer_agreement(company, hint)
        if agreement == "mismatch":
            employer_match = "mismatch"
            reasons.append(f"Le domaine « {host} » appartient à « {company} » alors que l’employeur attendu est « {hint} » : contradiction.")
        else:
            employer_match = "confirmed"
    elif hint:
        best = "mismatch"
        for candidate in candidates:
            agreement = _employer_agreement(candidate, hint)
            if agreement == "match":
                best = "match"
                break
            if agreement == "compatible" and best == "mismatch":
                best = "compatible"
        if best == "match":
            employer_match = "confirmed"
            reasons.append(f"Le domaine « {domain} » correspond à l’employeur attendu « {hint} ».")
        elif best == "compatible":
            employer_match = "unknown"
            reasons.append(f"Le domaine « {domain} » est compatible avec « {hint} » sans le prouver : l’employeur reste à confirmer.")
        else:
            reasons.append(f"Le domaine « {host} » ne correspond pas à l’employeur attendu « {hint} » et n’est rattaché à aucun employeur connu.")
    elif evidence:
        employer_match = "confirmed"
        reasons.append(f"L’attribution du domaine à « {company} » est prouvée par le registre local.")
    else:
        reasons.append(f"Le domaine « {host} » n’est ni un fournisseur d’emploi connu ni un domaine d’employeur attesté.")

    if employer_match == "mismatch":
        status: TrustStatus = STATUS_CONTRADICTORY
    elif employer_match == "confirmed":
        status = STATUS_VERIFIED
        reasons.append("La page est servie par un domaine d’employeur cohérent avec l’offre.")
    else:
        status = STATUS_UNVERIFIED

    provider = "employer" if employer_match == "confirmed" or (evidence is not None) else "unknown"
    return _result(status, provider, host, employer_match, _evidence_id(evidence), reasons, checked_at, claimed_official)


def _result(
    status: TrustStatus,
    provider: str | None,
    canonical_host: str | None,
    employer_match: EmployerMatch,
    registry_evidence: str | None,
    reasons: list[str],
    checked_at: str,
    claimed_official: bool,
) -> TrustResult:
    """Build the final result; the reasons are never empty."""
    if claimed_official:
        reasons.append(
            "La mention « source officielle » portée par la source est une déclaration, pas une preuve : elle n’a pas été utilisée."
        )
    if not reasons:
        reasons.append("Aucun élément de preuve disponible : la décision reste au plus bas niveau de confiance.")
    return TrustResult(
        status=status,
        provider=provider,
        canonical_host=canonical_host,
        employer_match=employer_match,
        registry_evidence=registry_evidence,
        reasons=reasons,
        checked_at=checked_at,
    )


# --- registry ---------------------------------------------------------------


def _registry_entries(registry: Iterable[Mapping[str, str]] | None) -> list[Mapping[str, str]]:
    source = CURATED_SOURCES if registry is None else registry
    return [entry for entry in source if isinstance(entry, Mapping)]


def _registry_evidence(
    entries: list[Mapping[str, str]],
    spec: ProviderSpec,
    token: str,
    host: str,
) -> Mapping[str, str] | None:
    """Find the local entry that attests this board, if any."""
    if not token:
        return None
    wanted = _core(token)
    for entry in entries:
        if _clean(entry.get("provider", "")).lower() != spec.name:
            continue
        entry_token = _clean(entry.get("board_token") or entry.get("company_identifier") or "")
        if not entry_token or _core(entry_token) != wanted:
            continue
        entry_host = _host(urllib.parse.urlsplit(_clean(entry.get("public_url", ""))))
        if entry_host and entry_host != host and entry_host not in spec.canonical_hosts:
            continue
        return entry
    return None


def _registry_evidence_for_host(entries: list[Mapping[str, str]], host: str) -> Mapping[str, str] | None:
    """Find the local entry that attests this employer domain, if any."""
    domain = _registrable_domain(host)
    for entry in entries:
        entry_host = _host(urllib.parse.urlsplit(_clean(entry.get("public_url", ""))))
        if not entry_host:
            continue
        if entry_host == host or _registrable_domain(entry_host) == domain:
            return entry
    return None


def _evidence_id(entry: Mapping[str, str] | None) -> str | None:
    if entry is None:
        return None
    identifier = _clean(entry.get("id", ""))
    return identifier or None


# --- identifiers ------------------------------------------------------------


def _board_token(spec: ProviderSpec, parsed: urllib.parse.SplitResult) -> str:
    """Extract the board identifier carried by the URL, if any."""
    path = urllib.parse.unquote(parsed.path or "")
    segments = [segment for segment in path.split("/") if segment]
    if spec.token_query_param and segments and segments[0] == "embed":
        query = urllib.parse.parse_qs(parsed.query or "")
        values = query.get(spec.token_query_param) or []
        if values:
            candidate = _clean(values[0])
            if candidate:
                return candidate
    if not segments:
        return ""
    candidate = _clean(segments[0])
    if len(candidate) < 2 or not any(character.isalpha() for character in candidate):
        return ""
    return candidate


def _domain_candidates(domain: str) -> list[str]:
    """Labels of the host that may identify an employer."""
    labels = [label for label in domain.split(".") if label]
    labels.reverse()
    candidates: list[str] = []
    for label in labels:
        if label in GENERIC_LABELS or label in TOP_LEVEL_LABELS:
            continue
        candidates.append(label)
    return candidates


def _registrable_domain(host: str) -> str:
    """Best-effort registrable domain, computed locally without any lookup."""
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _words(value: str) -> tuple[str, ...]:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    cleaned = "".join(character if character.isalnum() else " " for character in decomposed)
    return tuple(word for word in cleaned.split() if word)


def _core(value: str) -> str:
    """Identity of a name, without legal forms and connectives."""
    return "".join(
        word for word in _words(value)
        if word not in LEGAL_NOISE and word not in CONNECTIVES
    )


def _host(parsed: urllib.parse.SplitResult) -> str:
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return ""
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        pass
    return hostname


def _clean(value: object) -> str:
    return str(value or "").replace("\x00", "").strip()[:MAX_URL_LENGTH]


# --- redirects and clock ----------------------------------------------------


def _resolve_redirects(raw: str, redirects: Mapping[str, str]) -> tuple[str, list[tuple[str, str]]]:
    """Follow locally known redirections, without any network access."""
    hops: list[tuple[str, str]] = []
    current = raw
    seen = {raw}
    for _ in range(MAX_REDIRECT_HOPS):
        target = _lookup_redirect(current, redirects)
        if not target:
            break
        destination = _clean(target)
        if not destination or destination in seen:
            break
        seen.add(destination)
        hops.append((current, destination))
        current = destination
    return current, hops


def _lookup_redirect(url: str, redirects: Mapping[str, str]) -> str:
    if not redirects:
        return ""
    if url in redirects:
        return _clean(redirects[url])
    parsed = urllib.parse.urlsplit(url)
    key = f"{parsed.hostname or ''}{parsed.path or ''}".rstrip("/").lower()
    for candidate, target in redirects.items():
        candidate_parsed = urllib.parse.urlsplit(_clean(candidate))
        candidate_key = f"{candidate_parsed.hostname or ''}{candidate_parsed.path or ''}".rstrip("/").lower()
        if candidate_key and candidate_key == key:
            return _clean(target)
    return ""


def _now(clock: Callable[[], str] | None) -> str:
    if clock is not None:
        return _clean(clock())
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "EmployerMatch",
    "GENERIC_LABELS",
    "PROVIDERS",
    "PROVIDERS_BY_NAME",
    "ProviderSpec",
    "SHORTENER_HOSTS",
    "STATUS_LABELS",
    "STATUS_CONTRADICTORY",
    "STATUS_MISSING",
    "STATUS_UNVERIFIED",
    "STATUS_VERIFIED",
    "TrustResult",
    "TrustStatus",
    "check_offer_trust",
    "check_trust",
]
