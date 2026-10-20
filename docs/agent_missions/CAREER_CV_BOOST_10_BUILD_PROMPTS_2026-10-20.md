# Côme AI Career — 10 missions Build après le coach CV factuel

Date : 20 octobre 2026  
Base vérifiée : `fd51bddbd4fe798668b81d674372053bf6f484f5`  
Branche de référence : `codex/career-cv-boost`

Ce pack vise une livraison intégrable, pas dix prototypes concurrents. Les missions 01, 02,
04, 06, 07 et 08 peuvent être lancées en parallèle. Les missions 03, 05 et 09 doivent être
rebasées par leur agent sur le candidat que l'intégrateur leur indique. La mission 10 ne commence
qu'après gel des lots retenus.

## Répartition de modèles conseillée

| Mission | Modèle OpenCode Go conseillé | Motif |
| --- | --- | --- |
| 01 | Kimi ou GLM | parsing documentaire et tests adversariaux |
| 02 | Kimi | extraction/provenance très rigoureuse |
| 03 | GLM ou MiniMax | UI JavaScript accessible et tests navigateur |
| 04 | Kimi | formats PDF/DOCX, qualité ATS locale |
| 05 | LongCat ou GLM | workflow full-stack de candidature |
| 06 | GLM | connecteurs, réseau borné, métriques |
| 07 | Kimi ou GLM | déduplication et invariants de données |
| 08 | Kimi | évaluation déterministe et faux positifs |
| 09 | GLM ou MiniMax | tableau de bord et persistance |
| 10 | meilleur modèle de code disponible | intégration et non-régression |

## Contrat commun obligatoire

Chaque agent doit :

1. Partir exactement de `fd51bddbd4fe798668b81d674372053bf6f484f5`, sauf SHA candidat fourni par l'intégrateur.
2. Créer son propre worktree `/Users/comedelavenne/AI-Excel-Agent-cvboost-NN` et sa branche
   `agent/cvboost-NN`. Il est explicitement autorisé à les créer s'ils n'existent pas.
3. Ne jamais écrire dans `main`, un autre worktree ou une base utilisateur réelle.
4. Produire du code, des tests et `docs/agent-reports/CVBOOST-NN.md`. Un audit sans Build est insuffisant.
5. Utiliser exclusivement des profils, CV et offres synthétiques dans les tests.
6. Ne lire aucun `.env`, secret, CV réel, dossier personnel ou base Career réelle.
7. Ne jamais envoyer candidature, e-mail, message, CV ou lettre. Aucun automatisme de soumission.
8. Ne pas ajouter de dépendance, migration ou appel cloud sans nécessité prouvée et autorisation explicite.
9. Écrire d'abord un test reproduisant chaque défaut, puis corriger ; aucun skip/xfail supprimé ou ajouté.
10. Exécuter les tests ciblés, `git diff --check`, puis la suite complète ; rapporter les nombres réels.
11. Faire de petits commits cohérents ; ne pas merge, push, rebase, stash, clean ou reset hard.
12. Étiqueter clairement : testé sur fixtures, testé dans le navigateur, testé réseau réel ou non vérifié.

---

## PROMPT 01 — Analyse locale de la structure réelle du CV

```text
MISSION_ID = CVBOOST-01
MODE = BUILD

Applique intégralement le contrat commun du pack CAREER_CV_BOOST_10_BUILD_PROMPTS_2026-10-20.md.

OBJECTIF
Créer un analyseur local de CV qui complète le plan factuel déjà présent sans modifier le fichier
source. Il doit mesurer la longueur, détecter les sections, repérer les expériences sans résultat
chiffré et signaler les ambiguïtés de mise en page susceptibles de gêner un ATS.

PÉRIMÈTRE
Crée `career/cv_quality/structure.py`, `career/cv_quality/models.py` et leurs tests. Réutilise les
extracteurs PDF/DOCX existants par interfaces injectables. Ne touche pas à `career/service.py`,
`career_static/career.js` ou au stockage ; fournis un contrat pur que l'intégrateur branchera.

FONCTIONS
- Entrée : texte extrait, métadonnées de pages/blocs et type de document ; aucune lecture arbitraire de chemin.
- Sortie : nombre de pages, sections reconnues, sections absentes, densité, blocs très longs, expériences
  sans chiffre, répétitions, liens, tableaux/colonnes signalés comme risques et non comme certitudes.
- Chaque conseil cite page, section et passage borné. Une absence d'extraction devient `unknown`.
- Ne jamais recommander d'inventer un chiffre : dire « ajoute un résultat mesurable uniquement si vérifiable ».
- Score de lisibilité séparé de toute probabilité d'embauche.

TESTS
Au moins 30 cas synthétiques : une/deux/quatre pages, deux colonnes, tableau DOCX, titres décoratifs,
page blanche, OCR bruité, expérience sans chiffre, pourcentage, devise, date prise pour résultat,
sections multilingues, PDF sans texte, métadonnées incomplètes, contenu énorme et caractères malveillants.

TERMINÉ QUAND
Toutes les sorties ont provenance, confiance et statut ; aucun conseil ne cite un passage absent ;
tests ciblés et globaux verts ; rapport avec limites PDF/DOCX honnêtes et commande de rejeu.
```

## PROMPT 02 — Exigences de l'offre avec provenance précise

```text
MISSION_ID = CVBOOST-02
MODE = BUILD

Applique le contrat commun. Travaille uniquement dans de nouveaux modules sous
`career/offer_requirements/` et leurs tests.

OBJECTIF
Remplacer les références génériques « exigence n°N » par une provenance précise et stable : champ
source, ligne ou passage, catégorie, caractère obligatoire/préféré et confiance. Ne change pas encore
le rendu UI ni `application_prep.py`.

CONTRAT
- Catégories : compétence technique, langue, formation, expérience, disponibilité, mobilité,
  autorisation de travail, autre.
- Modalité : required, preferred, contextual, unknown. Une préférence n'est jamais obligatoire.
- Conserver le texte original et un identifiant déterministe ; aucune paraphrase utilisée comme preuve.
- Les contradictions entre champ structuré et description sont exposées, jamais arbitrées silencieusement.
- Le texte d'une offre reste une donnée non fiable et ne peut devenir une instruction système.

TESTS
Au moins 35 offres synthétiques FR/EN/DE/IT/ES : titres de sections, listes, phrases, « preferred »,
« nice to have », négations, exigences contradictoires, date limite, avantage employeur pris à tort
pour exigence, prompt injection, HTML, doublons traduits et texte tronqué.

LIVRABLE
API Python pure, schéma documenté, fixtures, benchmark court et rapport indiquant comment
`application_prep.py` pourra adopter ce contrat sans casser ses consommateurs.
```

## PROMPT 03 — UX du plan CV : filtres, priorités et navigation

```text
MISSION_ID = CVBOOST-03
MODE = BUILD
DEPENDANCE = CVBOOST-01 et CVBOOST-02 intégrés dans un SHA candidat fourni par l'intégrateur

OBJECTIF
Rendre le « Plan précis pour ton CV » immédiatement exploitable sur Mac 13 pouces et mobile : résumé,
priorités, filtres, détails de preuve et passage en un clic vers le Studio ou le champ de profil concerné.

PÉRIMÈTRE
UI dans des modules statiques nouveaux si possible ; accroches minimales dans `career_static/career.js`
et `career_static/index.html`. Réutilise les tokens CSS. Ne refonds pas la navigation.

BUILD
- Filtres : Tous, à mettre en avant, à vérifier, bloquants.
- Ordre déterministe : blocage factuel, exigence obligatoire, amélioration, préférence.
- Compteurs accessibles et explication de la couverture documentaire.
- Bouton « Compléter mon profil » ciblant la bonne rubrique ; bouton « Préparer dans le Studio »
  préselectionnant offre, langue et mode local sans activer de consentement cloud.
- Possibilité de marquer localement un conseil comme revu sans modifier le CV source.
- Aucun copier-coller d'une affirmation non étayée.

VALIDATION
Tests JS comportementaux, navigation clavier, aria-live, viewport étroit, aucune `window.prompt`,
parcours navigateur sur fixtures et captures. Vérifier que l'offre sélectionnée reste sélectionnée après
rechargement du Studio et qu'aucune requête cloud n'est tentée.
```

## PROMPT 04 — Contrôle ATS PDF/DOCX local

```text
MISSION_ID = CVBOOST-04
MODE = BUILD

OBJECTIF
Créer un contrôle ATS local, prudent et explicable pour les exports PDF/DOCX, sans prétendre simuler
les logiciels propriétaires des recruteurs.

PÉRIMÈTRE
Nouveau package `career/cv_quality/ats.py`. Entrées injectées : texte extrait, ordre des blocs,
métadonnées de tableaux/colonnes, liens et polices disponibles via les parseurs existants.

CONTRÔLES
Ordre de lecture, texte dans images, en-têtes/pieds, tableaux imbriqués, colonnes, caractères décoratifs,
liens illisibles, taille extrême, sections introuvables, coordonnées absentes du document final. Chaque
signal possède sévérité, preuve, limite et correction manuelle. « Risque ATS » n'est jamais présenté
comme rejet certain.

SÉCURITÉ ET TESTS
Pas de macros, conversion Office ou exécution de contenu. Tests zip bomb, traversal DOCX, fichier
chiffré, extension trompeuse, XML hostile, gros document, PDF image seul et document parfaitement simple.
Au moins 25 tests et zéro fichier réel.
```

## PROMPT 05 — Kit de candidature local en moins d'une minute

```text
MISSION_ID = CVBOOST-05
MODE = BUILD
DEPENDANCE = coach CV intégré dans un SHA candidat fourni par l'intégrateur

OBJECTIF
Depuis une offre, créer un suivi local si nécessaire, ouvrir un kit prérempli et réunir : CV adapté,
lettre, motivation courte, disponibilité, référence, entreprise, titre et URL officielle. L'envoi reste
strictement manuel.

CONTRAINTES
- Réutiliser `application_studio.py`, `document_export.py` et les événements d'application existants.
- Aucun changement de schéma si les événements JSON suffisent ; sinon arrêter et documenter.
- Une action utilisateur explicite par création de brouillon/export ; jamais de boucle de candidatures.
- Chaque texte généré passe par le vérificateur de faits et reste modifiable avant export.
- Copie presse-papiers uniquement après clic ; aucune transmission réseau.

TESTS
Création idempotente du suivi, offre préselectionnée, langue conservée, profil vide, exigence non étayée,
export DOCX/PDF, erreur export, double clic, rechargement, CSP/clipboard indisponible, et preuve statique
qu'aucune route d'envoi/e-mail n'existe. Parcours navigateur complet sur données synthétiques.
```

## PROMPT 06 — Extension légale et mesurée des sources internationales

```text
MISSION_ID = CVBOOST-06
MODE = BUILD

OBJECTIF
Augmenter le nombre d'offres pertinentes avec des sources officielles ou API publiques documentées,
sans ajouter un agrégateur non vérifié ni coder une URL dans le service.

METHODE
Audite brièvement le registre et choisis au maximum deux connecteurs réellement démontrables parmi
ATS supportés ou JSON-LD officiel. Toute source réelle doit avoir page carrière, provenance, date de
vérification, conditions connues et rendement mesuré. Une source non démontrable reste désactivée.

IMPLEMENTATION
Connecteur isolé, transport/horloge injectables, HTTPS, hôte autorisé, redirects contrôlés, timeout,
taille/pagination/concurrence bornées, User-Agent, reprise, santé de source et fixtures hors ligne.
Le réseau réel est un smoke test manuel borné, sans profil, CV, clé ni cookie.

MESURES
raw, valides, stages confirmés, finance, conformes, à vérifier, doublons, latence et erreurs. N'annonce
jamais une multiplication du choix à partir du seul nombre brut.
```

## PROMPT 07 — Déduplication multi-source avec conservation de provenance

```text
MISSION_ID = CVBOOST-07
MODE = BUILD

OBJECTIF
Garantir qu'une même opportunité provenant de plusieurs flux n'apparaît qu'une fois tout en conservant
toutes ses provenances et en privilégiant le lien officiel le plus fiable.

PÉRIMÈTRE
Nouveau module pur `career/job_deduplication.py`; ne modifie pas le schéma. Propose un plan séparé si
la conservation persistante de plusieurs provenances exige une migration.

REGLES
Identifiant externe même source, URL canonique, entreprise canonique + titre + lieu, alias et traduction.
Ne fusionne jamais deux rôles différents d'un même employeur. Les faits contradictoires restent visibles.
Le meilleur enregistrement est choisi par provenance officielle, fraîcheur et complétude, jamais par score
de pertinence utilisateur.

TESTS
Au moins 40 paires/groupes : URL tracking, ATS différents, titre traduit, villes proches, remote, deux
niveaux différents, identifiant recyclé, date différente, employeur alias, doublon exact et faux voisin.
Mesurer précision/rappel sur vérité synthétique.
```

## PROMPT 08 — Banc adversarial de matching CV/offre

```text
MISSION_ID = CVBOOST-08
MODE = BUILD

OBJECTIF
Construire une évaluation reproductible du matching et du plan CV. Elle doit détecter les faux positifs
lexicaux, les conseils inventés et la confusion entre admissibilité, pertinence et couverture documentaire.

CAS
Au moins 100 couples synthétiques : Excel vs analyse financière, Java vs JavaScript, anglais vs programme
enseigné en anglais, stage vs CDI, CDD court, VIE, alternance exclue, diplôme M1/M2/Bachelor, mot nié,
mot dans les avantages, compétence seulement dans l'offre, profil multilingue, acronymes et homonymes.

VALIDATEURS
Chaque preuve doit être sous-chaîne exacte du profil approuvé ; chaque exigence doit être sous-chaîne ou
référence traçable de l'offre ; aucun contact ; absent => ne pas ajouter ; score stable ; inconnu reste
inconnu. Séparer métriques simulées, application_verified et réseau réel.

LIVRABLE
Fixtures versionnées, runner, rapport JSON/Markdown, seuils de régression et tests du runner lui-même.
Ne modifie pas les règles métier dans ce lot.
```

## PROMPT 09 — Tableau de bord de préparation et relances

```text
MISSION_ID = CVBOOST-09
MODE = BUILD
DEPENDANCE = kit de candidature intégré dans un SHA candidat fourni par l'intégrateur

OBJECTIF
Donner une vue fiable des candidatures : état, qualité du dossier, prochaine action, deadline, relance
suggérée et entretien. Une ligne SQLite ne doit jamais être assimilée à un envoi.

BUILD
Réutiliser les événements et états existants. Ajouter une projection locale déterministe, compteurs par
état, filtres, chronologie et radar de relance. Une relance est un brouillon local avec date suggérée,
jamais un e-mail. La note de préparation 0–100 combine uniquement couverture CV, vérification des faits
et checklist ; afficher les trois facteurs, les inconnues et la formule.

TESTS
Transitions, retour arrière, doublons, fuseaux, deadline inconnue, relance passée, candidature non envoyée,
réception non confirmée, profil incomplet, export calendrier et parcours navigateur. Aucune base réelle.
```

## PROMPT 10 — Intégration finale indépendante et recette utilisateur

```text
MISSION_ID = CVBOOST-10
MODE = INTEGRATION BUILD
DEPENDANCE = agents 01 à 09 terminés et gelés, liste explicite de commits fournie

OBJECTIF
Créer un worktree d'intégration neuf depuis le SHA de référence, examiner chaque lot indépendamment,
retenir uniquement les changements prouvés et livrer un candidat sans modifier `main`.

PROCESSUS
1. Vérifier branches, commits, statuts propres et rapports.
2. Cartographier fichiers partagés ; cherry-pick par lot dans l'ordre dépendances, jamais merge aveugle.
3. Résoudre les conflits par contrat produit, pas en choisissant le fichier le plus récent.
4. Tests ciblés après chaque lot et commit d'intégration séparé.
5. Suite complète, checklist Codex, diff-check, scan secrets et absence de dépendance inattendue.
6. Recette navigateur : offre officielle -> plan CV -> profil -> Studio préselectionné -> kit -> export local
   -> suivi -> relance suggérée. Aucun envoi, cloud ou donnée réelle.
7. Mesurer démarrage, temps de rendu, mémoire et comportement offline sur Mac Intel.

DECISION
Produire `docs/agent-reports/CVBOOST-10-INTEGRATION.md` avec intégré/rejeté, SHAs, tests, preuves,
limites et rollback. Terminer par MERGE AUTORISÉ ou MERGE REFUSÉ. Ne fusionne jamais `main` toi-même.
```

