# SPEC-046 — intégration adaptée dans la candidate

Source: `agent/spec-046-ats-guide-human` / `726930428b33387de2b4d395e422a26d23751e34`.

Le lot brut a passé ses 54 tests en 4,82 s lors de la revue Codex. L'intégration conserve les guides humains et la détection locale des neuf plateformes, avec les adaptations suivantes:

- Une source non vérifiée par le sérialiseur Career ne fournit aucun `apply_url`, même sur un domaine ATS reconnu.
- Un nom de source ne prouve pas la plateforme d'un domaine inconnu.
- Les chemins et ancres de formulaire ne sont pas inventés. Le champ publié `applyUrl`, lorsqu'il existe dans le matériel source, est utilisé uniquement sur le même hôte et la même offre; sinon le lien officiel est conservé.
- Les liens non HTTPS, locaux, à caractères de contrôle (y compris encodés), avec identifiants ou avec une redirection vers un autre hôte sont refusés.
- Durée et besoin de compte sont explicitement indicatifs; aucun formulaire réel n'a été lu. Les guides n'émettent aucune requête réseau et ne soumettent aucune candidature.

La [documentation officielle Lever](https://github.com/lever/postings-api) distingue `hostedUrl` de `applyUrl`; le matériel publié est préféré à une URL reconstruite.

Les fixtures unitaires qui représentent une source vérifiée portent maintenant une preuve synthétique explicite. Le test HTTP d'import manuel conserve un lien de candidature vide: une API d'import ne peut pas s'attribuer cette preuve. Les assertions de raccourcis devinés ont été remplacées par des assertions de provenance et de conservation de l'identité de l'offre.

Validation exécutée:

- Nouvelle campagne avant adaptation: 15 échecs / 48 réussites, dont les garde-fous de destination et l'absence de lien pour source non vérifiée.
- Après adaptation: `python -m pytest tests/test_career_ats_guide.py -q` — **63 passed en 3,95 s**.
- `ruff check career/ tests/test_career_ats_guide.py` — vert; `git diff --check` — vert.

La reconnaissance statique d'une plateforme n'est pas une validation réelle de son formulaire, de la nécessité d'un compte ou de sa durée.
