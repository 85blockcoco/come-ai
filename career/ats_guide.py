"""SPEC-046 — reconnaissance locale de la plateforme ATS et guide humain.

Ce module ne fait **aucune requête réseau** : la plateforme est déduite du lien
officiel déjà enregistré et, à défaut, du nom de source.  Il ne soumet jamais
une candidature.  Le guide décrit les étapes qu'une personne devra accomplir
elle-même dans le formulaire de l'employeur.

Les champs de chaque étape sont des jetons stables (``profile:*``,
``document:*``, ``quick_answer:*``) : les ``quick_answer:*`` correspondent aux
clés des réponses types SPEC-045 afin que l'interface puisse proposer la bonne
valeur copiable sans reformulation.
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any

from workspace_core import UserFacingError

MAX_URL_LENGTH = 2_000
MAX_PLATFORM_TEXT = 200

# Un lien d'offre est une donnée affichée et cliquée : un caractère de contrôle
# (retour ligne, NUL) peut servir à fabriquer un second en-tête ou une seconde
# URL.  Il est refusé avant toute analyse.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

PLATFORM_DOMAINS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("lever.co",),
    "workday": ("myworkdayjobs.com", "workday.com", "workdayjobs.com"),
    "smartrecruiters": ("smartrecruiters.com",),
    "recruitcrm": ("recruitcrm.io",),
    "breezy": ("breezy.hr",),
    "jobvite": ("jobvite.com",),
    "ashby": ("ashbyhq.com",),
    "ripplematch": ("ripplematch.com",),
}

# Marques utilisées pour reconnaître une usurpation : un lien
# ``greenhouse.io.exemple.test`` contient bien la marque, mais son domaine
# réel n'est pas celui de Greenhouse.
_BRAND_TOKENS: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "workday",
    "myworkdayjobs",
    "smartrecruiters",
    "recruitcrm",
    "breezy",
    "jobvite",
    "ashby",
    "ashbyhq",
    "ripplematch",
)

_SOURCE_ALIASES: dict[str, str] = {
    "greenhouse": "greenhouse",
    "greenhouseio": "greenhouse",
    "gh": "greenhouse",
    "lever": "lever",
    "leverco": "lever",
    "workday": "workday",
    "myworkdayjobs": "workday",
    "workdayjobs": "workday",
    "smartrecruiters": "smartrecruiters",
    "recruitcrm": "recruitcrm",
    "breezy": "breezy",
    "breezyhr": "breezy",
    "jobvite": "jobvite",
    "ashby": "ashby",
    "ashbyhq": "ashby",
    "ripplematch": "ripplematch",
    "custom": "custom",
    "employer": "custom",
    "careersite": "custom",
    "companysite": "custom",
    "sitecarriere": "custom",
}

# Libellés lisibles pour une interface qui afficherait ``fields`` tel quel.
FIELD_LABELS: dict[str, str] = {
    "document:cv": "CV (PDF de préférence)",
    "document:cover_letter": "Lettre de motivation (si demandée)",
    "document:transcript": "Relevé de notes (si demandé)",
    "profile:display_name": "Nom complet",
    "profile:contact_email": "E-mail de contact",
    "profile:contact_phone": "Téléphone",
    "profile:linkedin_url": "Profil LinkedIn",
    "profile:education": "Formation / diplôme",
    "profile:experience": "Expériences",
    "profile:languages": "Langues",
    "profile:eligibility": "Éligibilité / autorisation de travail",
    "quick_answer:availability_start": "Date de début (réponse type SPEC-045)",
    "quick_answer:work_authorization": "Autorisation de travail (réponse type SPEC-045)",
    "quick_answer:languages": "Langues (réponse type SPEC-045)",
    "quick_answer:education": "Formation (réponse type SPEC-045)",
    "quick_answer:internship_duration": "Durée recherchée (réponse type SPEC-045)",
    "quick_answer:mobility": "Mobilité (réponse type SPEC-045)",
    "quick_answer:current_status": "Situation actuelle (réponse type SPEC-045)",
    "quick_answer:motivation": "Motivation courte (réponse type SPEC-045)",
    "quick_answer:salary_expectations": "Prétentions (réponse type SPEC-045)",
    "question:screening": "Questions de présélection de l'employeur",
    "review:all": "Relecture finale de toutes les réponses",
}


@dataclass(frozen=True)
class GuideStep:
    title: str
    fields: list[str]
    tips: str


@dataclass(frozen=True)
class ApplyGuide:
    platform: str | None
    apply_url: str
    steps: list[GuideStep]
    needs_account: bool
    estimated_minutes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "apply_url": self.apply_url,
            "steps": [asdict(step) for step in self.steps],
            "needs_account": self.needs_account,
            "estimated_minutes": self.estimated_minutes,
        }


# ---------------------------------------------------------------------------
# Analyse du lien
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckedUrl:
    url: str
    hostname: str
    parsed: urllib.parse.SplitResult


def _reject(message: str) -> UserFacingError:
    return UserFacingError(message)


def _check_url(value: Any) -> CheckedUrl:
    """Valider un lien public avant d'en déduire une plateforme.

    Le refus est volontairement explicite plutôt que silencieux : mieux vaut
    aucun guide qu'un guide qui enverrait la personne vers un domaine inconnu
    ou usurpé.
    """

    raw = str(value or "").strip()
    if not raw:
        raise _reject(
            "Aucun lien officiel n’est enregistré pour cette offre : le guide ne peut pas pointer vers un formulaire."
        )
    if len(raw) > MAX_URL_LENGTH:
        raise _reject("Le lien de l’offre est trop long pour être vérifié : il est refusé.")
    if _CONTROL_RE.search(raw) or any(character.isspace() for character in raw) or "\\" in raw:
        raise _reject("Le lien de l’offre contient des caractères de contrôle : il est refusé par prudence.")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as error:
        raise _reject("Le lien de l’offre est illisible : il est refusé.") from error

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise _reject("Seuls les liens http(s) publics peuvent ouvrir un formulaire de candidature.")
    if parsed.username or parsed.password:
        raise _reject("Le lien de l’offre contient un identifiant ou un mot de passe : il est refusé.")
    if not parsed.hostname:
        raise _reject("Le lien de l’offre ne contient pas de domaine valide : il est refusé.")
    try:
        port = parsed.port
    except ValueError as error:
        raise _reject("Le port du lien de l’offre est invalide : il est refusé.") from error
    if port is not None and port not in {80, 443}:
        raise _reject("Le lien de l’offre utilise un port non standard : il est refusé par prudence.")

    hostname = parsed.hostname.lower().rstrip(".")
    if not hostname or not _HOSTNAME_RE.fullmatch(hostname):
        raise _reject("Le domaine du lien de l’offre n’est pas un nom public valide : il est refusé.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:  # pragma: no cover - défense en profondeur, le motif d'hôte l'exclut déjà
        raise _reject("Un lien vers une adresse IP n’est pas accepté pour un formulaire de candidature.")

    if _is_lookalike_domain(hostname):
        raise _reject(
            "Ce lien imite le domaine d’une plateforme de recrutement connue sans appartenir à cette plateforme : il est refusé."
        )

    return CheckedUrl(url=raw, hostname=hostname, parsed=parsed)


def _is_lookalike_domain(hostname: str) -> bool:
    """Vrai si l'hôte cite une marque ATS hors de ses domaines officiels."""

    for domains in PLATFORM_DOMAINS.values():
        if _host_matches(hostname, domains):
            return False
    labels = {label for label in re.split(r"[^a-z0-9]+", hostname) if label}
    return any(brand in labels for brand in _BRAND_TOKENS)


def _host_matches(hostname: str, domains: tuple[str, ...]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def _platform_from_host(hostname: str) -> str | None:
    for platform, domains in PLATFORM_DOMAINS.items():
        if _host_matches(hostname, domains):
            return platform
    return None


def _platform_from_source(source_name: Any) -> str | None:
    text = re.sub(r"[^a-z0-9]+", " ", str(source_name or "")[:MAX_PLATFORM_TEXT].lower()).strip()
    if not text:
        return None
    compact = text.replace(" ", "")
    tokens = set(text.split())
    for alias, platform in _SOURCE_ALIASES.items():
        if compact == alias or alias in tokens:
            return platform
    return None


def detect_platform(url: Any, source_name: Any = "") -> str | None:
    """Déduire la plateforme ATS d'un lien officiel et/ou d'un nom de source.

    Le lien est prioritaire.  Un nom de source qui annonce une plateforme alors
    que le lien pointe ailleurs est traité comme une incohérence suspecte :
    aucun guide n'est produit.
    """

    checked = _check_url(url)
    from_url = _platform_from_host(checked.hostname)
    from_source = _platform_from_source(source_name)

    if from_source == "custom":
        # « custom » ne revendique aucune plateforme : le lien reste la seule
        # autorité, et l'absence de lien reconnu donne bien le guide générique.
        return from_url or "custom"
    if from_source and from_url and from_source != from_url:
        raise _reject(
            "Le nom de source annonce une plateforme qui ne correspond pas au domaine du lien : le guide est refusé par prudence."
        )
    # Un domaine employeur inconnu reste acceptable lorsque la source déclare
    # la plateforme (ex. lien carrière direct d'un employeur qui utilise
    # Greenhouse).  Dans ce cas le lien officiel n'est jamais transformé.
    return from_url or from_source


# ---------------------------------------------------------------------------
# URL directe du formulaire
# ---------------------------------------------------------------------------

def _url_with(parsed: urllib.parse.SplitResult, *, path: str | None = None, fragment: str | None = None) -> str:
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path if path is None else path,
            parsed.query,
            parsed.fragment if fragment is None else fragment,
        )
    )


def _direct_apply_url(platform: str | None, checked: CheckedUrl) -> str:
    """Transformer le lien public en lien de formulaire quand le motif est sûr.

    Seules les transformations documentées et réversibles sont appliquées.
    Pour les plateformes dont le formulaire est une modale de la même page, le
    lien officiel est conservé tel quel.
    """

    parsed = checked.parsed
    path = parsed.path

    if platform == "greenhouse" and "/jobs/" in path and not parsed.fragment:
        return _url_with(parsed, fragment="app")
    if platform == "lever":
        cleaned = path.rstrip("/")
        if cleaned.count("/") >= 2 and not cleaned.lower().endswith("/apply"):
            return _url_with(parsed, path=f"{cleaned}/apply")
    if platform == "jobvite" and "/job/" in path:
        cleaned = path.rstrip("/")
        if not cleaned.lower().endswith("/apply"):
            return _url_with(parsed, path=f"{cleaned}/apply")
    if platform == "ashby" and not parsed.fragment:
        cleaned = path.rstrip("/")
        if cleaned.count("/") >= 2 and not cleaned.lower().endswith(("/application", "/apply")):
            return _url_with(parsed, path=f"{cleaned}/application")
    # Workday, SmartRecruiters, RecruitCRM, Breezy, RippleMatch : le formulaire
    # est servi par la page officielle elle-même, ou son URL varie par tenant.
    return checked.url


# ---------------------------------------------------------------------------
# Guides humains
# ---------------------------------------------------------------------------

_CV_STEP = GuideStep(
    title="Préparer et téléverser le CV",
    fields=["document:cv"],
    tips="Choisis le CV adapté à cette offre, en PDF texte (pas un scan image). Un nom de fichier neutre suffit.",
)
_LETTER_STEP = GuideStep(
    title="Ajouter la lettre de motivation si elle est demandée",
    fields=["document:cover_letter"],
    tips="Ne joins une lettre que si le formulaire la propose ou l’exige ; le contenu doit rester factuel.",
)
_REVIEW_STEP = GuideStep(
    title="Relire puis envoyer manuellement",
    fields=["review:all"],
    tips="Vérifie le CV joint, chaque réponse et l’e-mail de contact. Aucun envoi automatique n’est effectué par Côme AI.",
)

_PLATFORM_GUIDES: dict[str, tuple[bool, int, tuple[GuideStep, ...]]] = {
    "greenhouse": (
        False,
        12,
        (
            GuideStep(
                title="Ouvrir le formulaire Greenhouse",
                fields=["document:cv"],
                tips="Sur une annonce Greenhouse, le bouton « Apply » ouvre le formulaire en bas de page (ancre #app). Aucun compte candidat n’est nécessaire.",
            ),
            _CV_STEP,
            GuideStep(
                title="Compléter les coordonnées",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                ],
                tips="Recopie exactement les coordonnées de ton profil local ; n’invente ni e-mail ni numéro.",
            ),
            GuideStep(
                title="Répondre aux questions de présélection",
                fields=[
                    "quick_answer:work_authorization",
                    "quick_answer:availability_start",
                    "quick_answer:salary_expectations",
                    "question:screening",
                ],
                tips="Les questions de screening peuvent être éliminatoires : utilise les réponses types SPEC-045 et corrige-les si le contexte diffère.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "lever": (
        False,
        10,
        (
            GuideStep(
                title="Ouvrir la candidature Lever",
                fields=["document:cv"],
                tips="Le bouton « Apply for this job » mène à /apply. Aucun compte n’est requis pour candidater.",
            ),
            _CV_STEP,
            _LETTER_STEP,
            GuideStep(
                title="Renseigner le profil candidat",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                    "quick_answer:motivation",
                ],
                tips="Lever affiche souvent un court champ « Why this role? » : garde la motivation factuelle et spécifique à l’offre.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "workday": (
        True,
        25,
        (
            GuideStep(
                title="Créer ou retrouver un compte Workday",
                fields=["profile:contact_email"],
                tips="Un compte Workday est presque toujours requis. Utilise un mot de passe unique ; Côme AI ne le stocke pas.",
            ),
            _CV_STEP,
            GuideStep(
                title="Corriger le profil parsé depuis le CV",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:experience",
                    "profile:education",
                ],
                tips="Workday pré-remplit le profil à partir du CV : relis chaque expérience et chaque diplôme, car les dates mal parsées sont fréquentes.",
            ),
            GuideStep(
                title="Compléter l’historique et les questions",
                fields=[
                    "profile:languages",
                    "profile:eligibility",
                    "quick_answer:work_authorization",
                    "quick_answer:availability_start",
                    "question:screening",
                ],
                tips="Les champs « Work authorization » et « Previous worker » sont souvent obligatoires ; réponds factuellement.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "smartrecruiters": (
        False,
        10,
        (
            GuideStep(
                title="Ouvrir la fiche SmartRecruiters",
                fields=["document:cv"],
                tips="Le bouton « I’m interested » ouvre le formulaire sur la même page ; aucun compte n’est nécessaire.",
            ),
            _CV_STEP,
            GuideStep(
                title="Compléter le profil",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                    "profile:languages",
                ],
                tips="SmartRecruiters peut proposer l’import d’un profil : vérifie que les données importées restent exactes.",
            ),
            GuideStep(
                title="Répondre aux questions de l’employeur",
                fields=[
                    "quick_answer:availability_start",
                    "quick_answer:internship_duration",
                    "quick_answer:motivation",
                    "question:screening",
                ],
                tips="Les questions varient par employeur ; ne devine pas une réponse que tu ne peux pas justifier.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "recruitcrm": (
        True,
        15,
        (
            GuideStep(
                title="Créer un accès candidat RecruitCRM",
                fields=["profile:contact_email"],
                tips="Le portail candidat peut demander un compte. Si l’offre permet une candidature sans compte, privilégie ce chemin.",
            ),
            _CV_STEP,
            GuideStep(
                title="Renseigner les informations de candidature",
                fields=[
                    "profile:display_name",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                    "profile:education",
                    "quick_answer:current_status",
                ],
                tips="Le formulaire est souvent celui d’un cabinet de recrutement : précise ton statut et tes disponibilités réelles.",
            ),
            GuideStep(
                title="Répondre aux questions du cabinet",
                fields=[
                    "quick_answer:availability_start",
                    "quick_answer:mobility",
                    "quick_answer:salary_expectations",
                    "question:screening",
                ],
                tips="Un cabinet peut demander des prétentions ou une mobilité : utilise les réponses types et vérifie-les.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "breezy": (
        False,
        8,
        (
            GuideStep(
                title="Ouvrir le formulaire Breezy",
                fields=["document:cv"],
                tips="Le bouton « Apply now » affiche le formulaire sur la même page ; aucun compte n’est requis.",
            ),
            _CV_STEP,
            GuideStep(
                title="Compléter les informations demandées",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                ],
                tips="Les champs visibles suffisent généralement ; ne remplis pas les champs facultatifs avec des données approximatives.",
            ),
            GuideStep(
                title="Répondre aux questions courtes",
                fields=["quick_answer:availability_start", "quick_answer:motivation", "question:screening"],
                tips="Breezy ajoute parfois des questions personnalisées : garde des réponses brèves et vérifiables.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "jobvite": (
        False,
        15,
        (
            GuideStep(
                title="Ouvrir l’annonce Jobvite",
                fields=["document:cv"],
                tips="Le bouton « Apply » mène au formulaire /apply ; un compte est parfois proposé mais rarement obligatoire.",
            ),
            _CV_STEP,
            _LETTER_STEP,
            GuideStep(
                title="Compléter le profil et les questions",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:education",
                    "quick_answer:work_authorization",
                    "question:screening",
                ],
                tips="Jobvite peut demander l’autorisation de travail et le niveau d’études : réponds avec les faits de ton profil.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "ashby": (
        False,
        10,
        (
            GuideStep(
                title="Ouvrir la candidature Ashby",
                fields=["document:cv"],
                tips="Ashby sert le formulaire sur /application depuis la fiche de l’offre ; aucun compte n’est requis.",
            ),
            _CV_STEP,
            GuideStep(
                title="Renseigner le profil",
                fields=[
                    "profile:display_name",
                    "profile:contact_email",
                    "profile:contact_phone",
                    "profile:linkedin_url",
                    "profile:languages",
                ],
                tips="Ashby peut proposer de remplir le profil depuis LinkedIn : vérifie que l’import n’ajoute aucune expérience.",
            ),
            GuideStep(
                title="Répondre aux questions de l’équipe",
                fields=[
                    "quick_answer:availability_start",
                    "quick_answer:internship_duration",
                    "quick_answer:work_authorization",
                    "question:screening",
                ],
                tips="Les questions Ashby sont souvent propres à l’équipe ; réponds uniquement avec des éléments vérifiables.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "ripplematch": (
        True,
        20,
        (
            GuideStep(
                title="Créer ou compléter le profil étudiant RippleMatch",
                fields=["profile:contact_email", "profile:education"],
                tips="RippleMatch met en relation profils et employeurs : le profil complet conditionne la visibilité. Un compte est requis.",
            ),
            _CV_STEP,
            GuideStep(
                title="Renseigner préférences et disponibilités",
                fields=[
                    "quick_answer:availability_start",
                    "quick_answer:mobility",
                    "quick_answer:internship_duration",
                    "quick_answer:work_authorization",
                ],
                tips="Les préférences déclarées orientent les suggestions ; reste cohérent avec ta recherche réelle.",
            ),
            GuideStep(
                title="Répondre aux questions de l’employeur",
                fields=["quick_answer:motivation", "question:screening"],
                tips="Chaque employeur peut ajouter ses propres questions ; ne recopie pas une motivation générique.",
            ),
            _REVIEW_STEP,
        ),
    ),
    "custom": (
        False,
        15,
        (
            GuideStep(
                title="Identifier le formulaire de l’employeur",
                fields=["document:cv"],
                tips="Le site carrière est propre à l’employeur : repère le bouton de candidature et vérifie qu’il reste sur le domaine officiel.",
            ),
            _CV_STEP,
            GuideStep(
                title="Créer un compte si le site l’exige",
                fields=["profile:display_name", "profile:contact_email", "profile:contact_phone"],
                tips="Un compte peut être demandé sans que ce soit systématique ; utilise un mot de passe unique, non stocké par Côme AI.",
            ),
            GuideStep(
                title="Compléter le dossier",
                fields=[
                    "profile:linkedin_url",
                    "profile:education",
                    "profile:experience",
                    "quick_answer:availability_start",
                    "quick_answer:work_authorization",
                ],
                tips="Les champs varient : ne remplis que ce que tu peux justifier, et utilise les réponses types quand la question correspond.",
            ),
            _REVIEW_STEP,
        ),
    ),
}

_GENERIC_GUIDE: tuple[GuideStep, ...] = (
    GuideStep(
        title="Vérifier que le lien mène bien au formulaire officiel",
        fields=["document:cv"],
        tips="Plateforme non reconnue : ce guide est générique. Ouvre le lien officiel et vérifie le domaine avant de saisir des données. Un compte peut être nécessaire.",
    ),
    _CV_STEP,
    GuideStep(
        title="Compléter les informations personnelles",
        fields=[
            "profile:display_name",
            "profile:contact_email",
            "profile:contact_phone",
            "profile:linkedin_url",
        ],
        tips="Le formulaire peut demander plus ou moins de champs que ce guide : ne fournis que des informations exactes.",
    ),
    GuideStep(
        title="Répondre aux questions du formulaire",
        fields=[
            "quick_answer:work_authorization",
            "quick_answer:availability_start",
            "quick_answer:motivation",
            "question:screening",
        ],
        tips="Les questions et leur caractère obligatoire dépendent de l’employeur ; utilise les réponses types SPEC-045 comme point de départ.",
    ),
    _REVIEW_STEP,
)


def human_apply_guide(job: dict[str, Any]) -> ApplyGuide:
    """Construire le guide humain d'une offre stockée, sans aucune requête.

    ``job`` est la représentation renvoyée par :meth:`CareerService.get_job`
    (ou un dictionnaire équivalent).  Une URL absente, malformée, usurpée ou
    incohérente avec la source lève :class:`UserFacingError` : le refus est
    préférable à un lien de candidature douteux.
    """

    official_url = job.get("official_url") if isinstance(job, dict) else getattr(job, "official_url", "")
    source_name = job.get("source_name", "") if isinstance(job, dict) else getattr(job, "source_name", "")
    checked = _check_url(official_url)
    platform = detect_platform(checked.url, source_name)
    from_url = _platform_from_host(checked.hostname)

    if platform in _PLATFORM_GUIDES:
        needs_account, estimated_minutes, steps = _PLATFORM_GUIDES[platform]
        step_list = list(steps)
    else:
        needs_account, estimated_minutes, step_list = False, 15, list(_GENERIC_GUIDE)

    return ApplyGuide(
        platform=platform,
        # Une transformation d'URL n'est sûre que sur un domaine officiel de la
        # plateforme ; un lien employeur reconnu via la source reste intact.
        apply_url=_direct_apply_url(platform, checked) if from_url else checked.url,
        steps=step_list,
        needs_account=needs_account,
        estimated_minutes=estimated_minutes,
    )
