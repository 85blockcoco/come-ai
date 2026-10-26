"""Static ATS platform detection and a human application guide (SPEC-046).

This module never performs network I/O and never submits an application.  It
only recognises a handful of public applicant-tracking systems from a job URL
or source name, then lays out the human steps a person should expect.

Every URL is validated before it is shown back to the user.  A link carrying
control characters, credentials, an internal host, or a non-HTTP scheme is
refused instead of being rendered as a clickable target.
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any

from workspace_core import UserFacingError

PLATFORMS: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "workday",
    "smartrecruiters",
    "recruitcrm",
    "breezy",
    "jobvite",
    "ashby",
    "ripplematch",
    "custom",
)

# Field keys shared with the quick answers (SPEC-045).  Keeping the vocabulary
# closed means the UI can prefetch an answer for every expected field.
QUICK_ANSWER_FIELDS: frozenset[str] = frozenset(
    {
        "full_name",
        "email",
        "phone",
        "location",
        "linkedin_url",
        "portfolio_url",
        "cv_file",
        "cover_letter",
        "work_authorization",
        "availability",
        "start_date",
        "salary_expectation",
        "screening_answers",
        "motivation",
        "education_history",
        "work_history",
    }
)


class UnsafeApplyURLError(UserFacingError):
    """The job link cannot be shown or opened safely."""


@dataclass(frozen=True, slots=True)
class GuideStep:
    """One human step in an external application form."""

    title: str
    fields: list[str]
    tips: str


@dataclass(frozen=True, slots=True)
class ApplyGuide:
    """What the person will face after clicking "apply"."""

    platform: str | None
    apply_url: str
    steps: list[GuideStep]
    needs_account: bool
    estimated_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Suffix matching is done on a labelled host: ``evil-greenhouse.io`` is not a
# match, while ``boards.greenhouse.io`` and ``greenhouse.io`` are.
_PLATFORM_HOST_SUFFIXES: dict[str, tuple[str, ...]] = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("lever.co",),
    "workday": ("myworkdayjobs.com", "myworkday.com", "workday.com"),
    "smartrecruiters": ("smartrecruiters.com",),
    "recruitcrm": ("recruitcrm.io",),
    "breezy": ("breezy.hr",),
    "jobvite": ("jobvite.com",),
    "ashby": ("ashbyhq.com",),
    "ripplematch": ("ripplematch.com",),
}

_SOURCE_ALIASES: dict[str, str] = {
    "greenhouse": "greenhouse",
    "greenhouse io": "greenhouse",
    "lever": "lever",
    "lever co": "lever",
    "workday": "workday",
    "my workday jobs": "workday",
    "myworkdayjobs": "workday",
    "workday myworkdayjobs": "workday",
    "smartrecruiters": "smartrecruiters",
    "smart recruiters": "smartrecruiters",
    "recruitcrm": "recruitcrm",
    "recruit crm": "recruitcrm",
    "breezy": "breezy",
    "breezy hr": "breezy",
    "jobvite": "jobvite",
    "ashby": "ashby",
    "ashbyhq": "ashby",
    "ripplematch": "ripplematch",
    "ripple match": "ripplematch",
    "custom": "custom",
    "career site": "custom",
    "company site": "custom",
    "in house": "custom",
    "in-house": "custom",
    "manual": "",
}

_INTERNAL_SUFFIXES: tuple[str, ...] = (
    ".local",
    ".localhost",
    ".internal",
    ".intranet",
    ".lan",
    ".home",
    ".localdomain",
    ".test.internal",
)

_RESERVED_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)

# Characters which must never reach an href or a browser address bar.
_FORBIDDEN_URL_CHARACTERS = frozenset('<>"\'`{}|\\^ ')
_FORBIDDEN_ENCODED = ("%00", "%0a", "%0d", "%3c", "%3e", "%22", "%27", "%60")


def _clean(value: Any, *, limit: int = 2_000) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _normalized_source(source_name: Any) -> str:
    text = _clean(source_name, limit=120).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _host_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith(f".{suffix}")


def _platform_from_host(host: str) -> str | None:
    for platform, suffixes in _PLATFORM_HOST_SUFFIXES.items():
        if any(_host_matches(host, suffix) for suffix in suffixes):
            return platform
    return None


def _platform_from_source(source_name: Any) -> str | None:
    alias = _SOURCE_ALIASES.get(_normalized_source(source_name))
    if alias:
        return alias
    return None


def detect_platform(url: Any, source_name: Any = "") -> str | None:
    """Recognise an ATS from a static URL host or a source label.

    The URL wins over the source label because it is the direct evidence of
    where the person will land.  An unrecognised public URL returns ``None``;
    only an explicit "custom/company site" label yields ``"custom"``.
    """

    raw = _clean(url)
    if raw:
        try:
            host = (urllib.parse.urlsplit(raw).hostname or "").lower().rstrip(".")
        except ValueError:
            host = ""
        if host:
            platform = _platform_from_host(host)
            if platform:
                return platform
    return _platform_from_source(source_name)


def _validate_apply_url(url: Any) -> str:
    """Return a safe absolute HTTP(S) URL or raise a user-facing refusal."""

    raw = _clean(url)
    if not raw:
        return ""
    lowered = raw.lower()
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise UnsafeApplyURLError(
            "Le lien de candidature contient des caractères de contrôle et ne peut pas être ouvert."
        )
    if any(character in _FORBIDDEN_URL_CHARACTERS for character in raw):
        raise UnsafeApplyURLError(
            "Le lien de candidature contient des caractères interdits et ne peut pas être ouvert."
        )
    if any(character in lowered for character in _FORBIDDEN_ENCODED):
        raise UnsafeApplyURLError(
            "Le lien de candidature contient un encodage suspect et ne peut pas être ouvert."
        )
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as error:
        raise UnsafeApplyURLError("Le lien de candidature est invalide.") from error
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeApplyURLError(
            "Seuls les liens http:// et https:// peuvent être ouverts."
        )
    if not parsed.netloc or not parsed.hostname:
        raise UnsafeApplyURLError("Le lien de candidature est invalide.")
    if parsed.username or parsed.password:
        raise UnsafeApplyURLError(
            "Le lien de candidature ne doit pas contenir d’identifiant ni de mot de passe."
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise UnsafeApplyURLError("Le port du lien de candidature est invalide.") from error
    if port not in {None, 80, 443}:
        raise UnsafeApplyURLError("Le lien de candidature utilise un port non standard.")

    host = parsed.hostname.lower().rstrip(".")
    if not host or host in _RESERVED_HOSTS or host.endswith(_INTERNAL_SUFFIXES):
        raise UnsafeApplyURLError(
            "Le lien de candidature pointe vers un hôte interne et ne peut pas être ouvert."
        )
    if not host.isascii():
        raise UnsafeApplyURLError("Le lien de candidature utilise un domaine non reconnu.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        raise UnsafeApplyURLError(
            "Le lien de candidature utilise une adresse IP et ne peut pas être ouvert."
        )
    if "." not in host or host.startswith(".") or ".." in host:
        raise UnsafeApplyURLError(
            "Le lien de candidature ne correspond pas à un domaine public valide."
        )
    labels = host.split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise UnsafeApplyURLError("Le lien de candidature contient un domaine invalide.")
    if len(labels[-1]) < 2:
        raise UnsafeApplyURLError("Le lien de candidature contient un domaine invalide.")
    return raw


def _append_path(url: str, suffix: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(suffix):
        path = f"{path}{suffix}"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _direct_apply_url(platform: str, url: str) -> str:
    """Best-effort direct form URL for the platforms with a stable pattern."""

    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if platform == "greenhouse":
        # Greenhouse opens the embedded form on the ``#app`` fragment.
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "app"))
    if platform == "lever":
        return _append_path(url, "/apply")
    if platform == "workday":
        return _append_path(url, "/apply")
    if platform == "smartrecruiters":
        query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if key != "oga"]
        query.append(("oga", "true"))
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
        )
    if platform in {"recruitcrm", "breezy", "jobvite"}:
        return _append_path(url, "/apply")
    if platform == "ashby":
        return _append_path(url, "/application")
    return url


def _job_value(job: Any, key: str) -> Any:
    if isinstance(job, dict):
        return job.get(key)
    return getattr(job, key, None)


def _step(title: str, fields: tuple[str, ...], tips: str) -> GuideStep:
    unknown = set(fields) - QUICK_ANSWER_FIELDS
    if unknown:  # pragma: no cover - guards future template edits
        raise ValueError(f"Unknown quick-answer field(s): {sorted(unknown)}")
    return GuideStep(title=title, fields=list(fields), tips=tips)


def _platform_template(platform: str) -> tuple[bool, int, list[GuideStep]]:
    """The human checklist for each recognised platform."""

    if platform == "greenhouse":
        return (
            False,
            12,
            [
                _step(
                    "Importer le CV",
                    ("cv_file", "full_name", "email", "phone"),
                    "Greenhouse préremplit le profil à partir du CV ; relis chaque champ avant de continuer.",
                ),
                _step(
                    "Compléter le profil",
                    ("location", "linkedin_url", "portfolio_url"),
                    "Les liens sont facultatifs mais aident le recruteur à retrouver tes preuves.",
                ),
                _step(
                    "Répondre aux questions de présélection",
                    ("work_authorization", "availability", "start_date", "salary_expectation"),
                    "Réutilise tes réponses courtes ; ne laisse pas une question obligatoire vide.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("screening_answers", "motivation"),
                    "Greenhouse demande un envoi explicite : rien n’est transmis automatiquement.",
                ),
            ],
        )
    if platform == "lever":
        return (
            False,
            10,
            [
                _step(
                    "Choisir le CV et le profil",
                    ("cv_file", "full_name", "email", "phone"),
                    "Lever accepte un CV PDF ou DOCX ; l’import peut remplir les champs de base.",
                ),
                _step(
                    "Compléter les liens",
                    ("linkedin_url", "portfolio_url", "location"),
                    "Vérifie que les liens s’ouvrent et correspondent bien à ton profil public.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "start_date", "salary_expectation", "screening_answers"),
                    "Lever affiche parfois des questions personnalisées par offre : réponds factuellement.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("motivation",),
                    "Relis la pièce jointe et le message avant de cliquer sur « Submit application ».",
                ),
            ],
        )
    if platform == "workday":
        return (
            True,
            25,
            [
                _step(
                    "Créer un compte candidat",
                    ("email", "full_name"),
                    "Workday exige un compte ; utilise une adresse que tu consultes souvent.",
                ),
                _step(
                    "Importer le CV",
                    ("cv_file",),
                    "L’auto-remplissage Workday est imparfait : contrôle ensuite chaque section.",
                ),
                _step(
                    "Compléter l’historique",
                    ("phone", "location", "work_history", "education_history"),
                    "Saisis les dates au mois près et évite les trous inexpliqués.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date", "salary_expectation"),
                    "Certaines questions sont éliminatoires ; relis-les avant de valider.",
                ),
                _step(
                    "Relire et soumettre",
                    ("screening_answers", "motivation"),
                    "Workday demande souvent une deuxième confirmation ; vérifie le récapitulatif.",
                ),
            ],
        )
    if platform == "smartrecruiters":
        return (
            False,
            12,
            [
                _step(
                    "Importer le CV",
                    ("cv_file", "full_name", "email", "phone"),
                    "Le formulaire peut préremplir le profil depuis le CV ; corrige les erreurs de parsing.",
                ),
                _step(
                    "Compléter le profil",
                    ("location", "linkedin_url", "portfolio_url"),
                    "SmartRecruiters conserve ton profil pour les offres suivantes du même employeur.",
                ),
                _step(
                    "Répondre au questionnaire",
                    ("work_authorization", "availability", "start_date", "screening_answers"),
                    "Les questions varient par employeur ; réponds sans copier une réponse générique.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("motivation", "cover_letter"),
                    "La lettre est souvent facultative mais peut être lue par le recruteur.",
                ),
            ],
        )
    if platform == "recruitcrm":
        return (
            False,
            10,
            [
                _step(
                    "Renseigner l’identité",
                    ("full_name", "email", "phone", "location"),
                    "Recruit CRM ouvre un formulaire court ; vérifie l’adresse e-mail avant l’envoi.",
                ),
                _step(
                    "Joindre le CV",
                    ("cv_file", "linkedin_url"),
                    "Un PDF lisible est préférable ; évite les fichiers protégés par mot de passe.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date", "salary_expectation"),
                    "Reste cohérent avec les dates de ton CV.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("screening_answers",),
                    "Le recruteur reçoit une fiche synthétique : relis-la avant validation.",
                ),
            ],
        )
    if platform == "breezy":
        return (
            False,
            8,
            [
                _step(
                    "Renseigner le profil",
                    ("full_name", "email", "phone", "location"),
                    "Breezy HR demande peu de champs ; le CV reste la pièce principale.",
                ),
                _step(
                    "Joindre le CV",
                    ("cv_file", "linkedin_url", "portfolio_url"),
                    "Tu peux ajouter un lien public si le poste demande des exemples de travail.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date", "screening_answers"),
                    "Certaines offres ajoutent un questionnaire ; réponds étape par étape.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("motivation",),
                    "Breezy confirme l’envoi par e-mail : garde ce message comme preuve.",
                ),
            ],
        )
    if platform == "jobvite":
        return (
            True,
            15,
            [
                _step(
                    "Créer ou retrouver le compte",
                    ("email", "full_name"),
                    "Jobvite peut demander un compte ; note le mot de passe pour suivre la candidature.",
                ),
                _step(
                    "Importer le CV",
                    ("cv_file", "phone", "location"),
                    "L’import remplit le profil mais oublie parfois les expériences les plus anciennes.",
                ),
                _step(
                    "Compléter le profil",
                    ("linkedin_url", "work_history", "education_history"),
                    "Vérifie la chronologie et les intitulés de poste.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date", "salary_expectation"),
                    "Les réponses sont visibles par l’employeur ; reste factuel.",
                ),
                _step(
                    "Relire et soumettre",
                    ("screening_answers", "motivation"),
                    "Jobvite affiche un récapitulatif final : contrôle chaque section.",
                ),
            ],
        )
    if platform == "ashby":
        return (
            False,
            10,
            [
                _step(
                    "Renseigner le profil",
                    ("full_name", "email", "phone", "location"),
                    "Ashby propose un formulaire court et un import de CV.",
                ),
                _step(
                    "Joindre le CV",
                    ("cv_file", "linkedin_url", "portfolio_url"),
                    "Le CV doit rester lisible par un parseur : pas de colonnes ni de texte dans les images.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date", "salary_expectation"),
                    "Ashby affiche parfois des questions conditionnelles ; relis-les avant de valider.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("screening_answers", "motivation"),
                    "Tu peux relire ta candidature avant l’envoi manuel.",
                ),
            ],
        )
    if platform == "ripplematch":
        return (
            True,
            12,
            [
                _step(
                    "Se connecter à RippleMatch",
                    ("email", "full_name"),
                    "La plateforme demande un compte pour transmettre la candidature à l’employeur.",
                ),
                _step(
                    "Vérifier le profil",
                    ("phone", "location", "education_history", "work_history"),
                    "RippleMatch réutilise ton profil : mets-le à jour avant de postuler.",
                ),
                _step(
                    "Joindre le CV",
                    ("cv_file", "linkedin_url"),
                    "Un CV daté et lisible évite un rejet automatique.",
                ),
                _step(
                    "Répondre aux questions",
                    ("work_authorization", "availability", "start_date"),
                    "Vérifie les critères d’éligibilité avant de consommer une candidature.",
                ),
                _step(
                    "Vérifier et envoyer",
                    ("motivation",),
                    "La candidature part chez l’employeur après ta confirmation explicite.",
                ),
            ],
        )
    return (
        True,
        15,
        [
            _step(
                "Ouvrir le site carrière de l’entreprise",
                (),
                "Formulaire maison : vérifie que le domaine correspond bien à l’entreprise avant de saisir des données.",
            ),
            _step(
                "Préparer les pièces",
                ("cv_file", "cover_letter"),
                "Garde un PDF nommé clairement ; évite les documents protégés ou scannés en image.",
            ),
            _step(
                "Préparer les réponses récurrentes",
                (
                    "full_name",
                    "email",
                    "phone",
                    "location",
                    "work_authorization",
                    "availability",
                    "start_date",
                    "salary_expectation",
                ),
                "Réutilise tes réponses courtes, puis adapte la motivation à cette offre précise.",
            ),
            _step(
                "Remplir et relire",
                ("screening_answers", "motivation"),
                "Rien n’est envoyé automatiquement : tu gardes le contrôle de la soumission finale.",
            ),
        ],
    )


def human_apply_guide(job: Any) -> ApplyGuide:
    """Build an honest, offline guide for applying to ``job``.

    ``job`` may be a dictionary or an object exposing the same names.  A
    suspicious URL raises :class:`UnsafeApplyURLError`; an unknown public URL
    yields a generic guide with ``platform=None``.
    """

    official_url = _clean(_job_value(job, "official_url"))
    fallback_url = _clean(_job_value(job, "apply_url") or _job_value(job, "url"))
    raw_url = official_url or fallback_url
    safe_url = _validate_apply_url(raw_url)
    source_name = _clean(_job_value(job, "source_name"), limit=120)
    platform = detect_platform(safe_url, source_name)

    if platform is None:
        steps = _generic_steps(safe_url)
        return ApplyGuide(
            platform=None,
            apply_url=safe_url,
            steps=steps,
            needs_account=True,
            estimated_minutes=20,
        )

    needs_account, estimated_minutes, steps = _platform_template(platform)
    apply_url = _direct_apply_url(platform, safe_url) if safe_url else ""
    if not safe_url:
        steps = [
            _step(
                "Retrouver le lien officiel",
                (),
                "Aucun lien n’est enregistré pour cette offre : ouvre la fiche source avant de postuler.",
            ),
            *steps,
        ]
    return ApplyGuide(
        platform=platform,
        apply_url=apply_url,
        steps=steps,
        needs_account=needs_account,
        estimated_minutes=estimated_minutes,
    )


def _generic_steps(safe_url: str) -> list[GuideStep]:
    if safe_url:
        opening_tip = (
            "Plateforme non reconnue : ouvre le lien officiel et vérifie que le domaine correspond "
            "à l’entreprise avant de saisir des données."
        )
    else:
        opening_tip = (
            "Aucun lien officiel n’est enregistré : retrouve la fiche source avant de postuler."
        )
    return [
        _step("Vérifier le lien officiel", (), opening_tip),
        _step(
            "Préparer les pièces",
            ("cv_file", "cover_letter"),
            "Garde un CV PDF lisible et une lettre adaptée à cette offre précise.",
        ),
        _step(
            "Préparer les réponses récurrentes",
            (
                "full_name",
                "email",
                "phone",
                "location",
                "work_authorization",
                "availability",
                "start_date",
                "salary_expectation",
            ),
            "Réutilise tes réponses courtes ; ne devine jamais une information administrative.",
        ),
        _step(
            "Remplir et relire",
            ("screening_answers", "motivation"),
            "La plateforme est inconnue : lis chaque question et garde la soumission finale manuelle.",
        ),
        _step(
            "Envoyer manuellement",
            (),
            "Aucune candidature n’est soumise par cet outil ; tu cliques toi-même sur le bouton final.",
        ),
    ]


__all__ = [
    "PLATFORMS",
    "QUICK_ANSWER_FIELDS",
    "ApplyGuide",
    "GuideStep",
    "UnsafeApplyURLError",
    "detect_platform",
    "human_apply_guide",
]
