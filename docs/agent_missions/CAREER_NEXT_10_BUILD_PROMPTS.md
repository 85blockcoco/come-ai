# Côme AI Career — 10 missions Build prêtes à déléguer

Date de préparation : 18 octobre 2026

Base commune vérifiée : `daf8bc3d30e012bb2604bea0d78b8ea6038bccb4`

Les missions 01 à 08 peuvent être lancées en parallèle. La mission 09 commence après disponibilité des commits 01 à 08. La mission 10 commence seulement après création d'un candidat d'intégration par la mission 09.

## Répartition de modèles recommandée

| Mission | Profil de modèle recommandé |
| --- | --- |
| 01 Sources finance | LongCat 2.5 Preview ou GLM, bon usage terminal/réseau |
| 02 Connecteur JobPosting | Kimi ou GLM, rigueur protocoles/parsing |
| 03 Profil PDF/OCR | Kimi, très bon code documentaire et données |
| 04 CV/lettre factuels | LongCat ou Kimi, rédaction multilingue + code |
| 05 Accueil offres du jour | GLM ou MiniMax, full-stack/UI |
| 06 Tableau de suivi | GLM, SQLite/API/UI |
| 07 Entretiens | LongCat, logique produit et contenu multilingue |
| 08 Évaluations qualité | Kimi ou GLM, tests adversariaux |
| 09 Intégration contrôlée | meilleur modèle de code disponible, raisonnement élevé |
| 10 Recette et correction finale | modèle différent de la mission 09 pour une revue indépendante |

---

## PROMPT 01 — Extension vérifiée des sources finance internationales

```text
MISSION_ID = CAREER-NEXT-01
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Tu développes Côme AI dans /Users/comedelavenne/AI-Excel-Agent. Ta base obligatoire est daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Crée toi-même, s'il n'existe pas, le worktree /Users/comedelavenne/AI-Excel-Agent-next-01 et la branche agent/career-next-01 depuis ce SHA exact. Tu es explicitement autorisé à créer ce worktree et cette branche. Ne travaille jamais dans main et ne modifie aucun autre worktree.

OBJECTIF PRODUIT
Augmenter fortement la couverture réelle d'offres internationales utiles, sans ajouter de sources inventées ni confondre un flux ATS joignable avec une provenance officielle. Commence par les huit employeurs déjà documentés comme reliés à un ATS officiel : Doctolib/Greenhouse doctolib, Pigment/Lever pigment, OakNorth/Ashby oaknorth, Monzo/Greenhouse monzo, Thought Machine/Ashby thought-machine, Alan/Ashby alan, Contentsquare/Lever contentsquare, Dataiku/Greenhouse dataiku. Vérifie d'abord les preuves existantes dans les branches et rapports ; effectue ensuite une vérification réseau courte et bornée des pages officielles et flux publics. Si une relation n'est plus démontrable, ne l'active pas et explique précisément pourquoi.

BUILD ATTENDU
- Étendre uniquement career/source_registry.py avec les sources réellement vérifiées.
- Ajouter des tests garantissant identifiants uniques, HTTPS, horodatage, page officielle, fournisseur supporté et absence de source fictive.
- Dédupliquer Doctolib : ne jamais activer simultanément deux boards contenant le même inventaire sans preuve et stratégie de déduplication.
- Réutiliser les connecteurs existants ; ne créer aucun nouveau framework.
- Exécuter une collecte réelle bornée avec scripts/live_source_check.py dans une base temporaire, sans profil/CV/base privée ni clé IA.
- Produire un rapport JSON réduit sans corps complet d'annonce et un rapport Markdown donnant, par source, raw/evaluated/retained/confirmed/to_verify/errors/latence.
- Mesurer le rendement finance et stage de chaque ajout ; une source à rendement nul reste honnêtement signalée.
- Ajouter au moins un test prouvant qu'une offre pertinente située après la 150e ligne d'un gros flux peut être retenue avant la limite globale.

SÉCURITÉ
Ne lis aucun .env, CV, dossier internships, base Career réelle ou secret. Aucun login, CAPTCHA, scraping interdit ou contournement. Respecte timeouts, User-Agent et limites de débit. Aucun formulaire ou candidature envoyé.

VALIDATION
Tests ciblés d'abord, puis suite complète. Aucun skip/xfail ajouté. Vérification navigateur dans une instance jetable : critères finance sélectionnés, clic Explorer, sources/erreurs/annonces/résultats visibles. Conserve une preuve factuelle sans donnée privée. Si un défaut apparaît, ajoute un test rouge puis corrige-le.

LIVRABLES
1. Code et tests.
2. docs/career_intl/REPORT_NEXT_01_SOURCES.md.
3. Rapport JSON réduit du contrôle réel.
4. docs/agent-reports/CAREER-NEXT-01.md avec commandes, sorties réelles, limites, rollback et fichiers modifiés.
5. Un commit unique ou une petite série logique sur agent/career-next-01. Ne merge pas, ne push pas.

Même si une partie existe déjà, tu dois produire une amélioration Build utile et testée ; un rapport sans code n'est pas une livraison suffisante.
```

## PROMPT 02 — Connecteur générique des pages officielles JobPosting

```text
MISSION_ID = CAREER-NEXT-02
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Base obligatoire : daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Crée /Users/comedelavenne/AI-Excel-Agent-next-02 sur agent/career-next-02 depuis cette base. La création est autorisée et requise. Aucun travail dans main ou dans les worktrees d'autres agents.

OBJECTIF
Ajouter une nouvelle voie légale de couverture pour les banques, assureurs et institutions qui n'utilisent pas Greenhouse/Lever/Ashby/SmartRecruiters : lecture bornée de pages carrière officielles contenant des objets schema.org JobPosting en JSON-LD. Il ne s'agit pas d'un crawler général.

PÉRIMÈTRE EXCLUSIF
Crée un package nouveau career/connectors/jobposting_jsonld.py et ses tests. Limite à une accroche minimale dans le registre de connecteurs existant. Ne modifie pas source_registry.py : utilise uniquement des sources synthétiques dans les tests et documente le contrat que l'intégrateur pourra ensuite employer.

CONTRAT
- URL HTTPS exacte fournie par un registre approuvé ; aucun suivi libre de liens.
- Hôte strictement identique à l'hôte autorisé ; redirects inter-hôtes refusés.
- GET uniquement, taille maximale, timeout, User-Agent, nombre de pages et nombre d'offres bornés.
- Parse uniquement script[type='application/ld+json'] et @type JobPosting, y compris @graph et tableaux.
- Champs : title, hiringOrganization, jobLocation, employmentType, datePosted, validThrough, description, identifier, url/directApply si officiel.
- HTML normalisé par le mécanisme central existant ; scripts/styles supprimés.
- Provenance champ par champ ; inconnu reste inconnu.
- Refus des URL credential-bearing, javascript/data/file, hôtes inattendus, JSON excessif ou récursif, doublons et structures malformées.
- Horloge et transport injectables ; aucun réseau dans les tests.

TESTS ADVERSARIAUX
Au moins 25 cas : objet unique, @graph, tableau, multilingue, organisation manquante, lieu multiple, remote, contrat ambigu, date absente, validThrough expirée, duplicate identifier, duplicate URL, HTML/script, JSON-LD invalide, profondeur excessive, payload trop grand, redirect interdit, hôte différent, URL relative, URL dangereuse, offre senior, offre sans lien officiel, CDI intitulé stage, deux offres valides sur même page, page sans JobPosting, réseau bloqué. Zéro offre dangereuse importée.

INTÉGRATION
Retourne le même contrat commun que les connecteurs ATS. Réutilise qualification, admission, déduplication et classement existants. Ne code pas de recherche Google/Bing et n'invente aucune page de banque réelle.

VALIDATION/LIVRAISON
Tests rouges puis verts, tests ciblés, suite complète, diff-check, scan de secrets. Rapport docs/career_intl/REPORT_NEXT_02_JOBPOSTING.md avec architecture, limites et exemple synthétique. Rapport agent dans docs/agent-reports/CAREER-NEXT-02.md. Commit sur ta branche ; aucun merge/push.
```

## PROMPT 03 — Import de CV PDF/DOCX et profil approuvable excellent

```text
MISSION_ID = CAREER-NEXT-03
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Base : daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Crée /Users/comedelavenne/AI-Excel-Agent-next-03, branche agent/career-next-03. Tu as l'autorisation explicite de créer le worktree. Ne lis aucune vraie donnée personnelle : fixtures synthétiques uniquement.

OBJECTIF UTILISATEUR
Rendre l'import du profil très simple : déposer un PDF ou DOCX, obtenir une extraction locale de qualité, voir exactement la source de chaque information, corriger et approuver champ par champ. Rien d'extrait n'est automatiquement un fait confirmé.

ARCHITECTURE
Travaille principalement dans de nouveaux modules sous career/profile_ingest/ et tests associés. Réutilise LocalVisionOCR, les parseurs existants et le stockage candidate_profile ; n'introduis pas une deuxième base mémoire. Accroches service/router/UI minimales et clairement listées. Ne migre pas personal_profile dans ce lot.

FONCTIONS
- PDF texte natif, DOCX et image/PDF scanné via OCR local détecté ; aucune installation système.
- Détection page par page : texte natif prioritaire, OCR uniquement si nécessaire.
- Extraction structurée : identité, coordonnées, liens, formations, expériences, compétences, langues, certifications, mobilité, disponibilité.
- Chaque valeur candidate porte document opaque, page, passage, méthode, confiance technique et statut proposed/approved/rejected/edited.
- Détection des doublons et contradictions sans arbitrage automatique.
- Aperçu, édition, approbation/rejet individuel, approbation groupée uniquement après action explicite.
- Suppression et export local des candidats ; fichiers source conservés avec permissions privées.
- Ne jamais journaliser le texte du CV, l'adresse, l'e-mail ou le téléphone.
- Limites de taille/page/temps et messages compréhensibles.

QUALITÉ
Fixtures synthétiques difficiles : CV deux colonnes, accents, anglais/français, dates chevauchantes, titre décoratif, tableau DOCX, PDF sans texte, OCR bruité, e-mail/LinkedIn, diplôme ambigu, compétences dans description mais pas dans rubrique, page blanche. Mesure précision champ par champ sur vérité de référence ; sépare extraction exacte, à vérifier et absente.

UI
Construis un parcours accessible en trois écrans maximum : importer, vérifier les propositions, confirmer le profil. Aucun champ ne disparaît silencieusement. Affiche provenance et confiance sans jargon. Teste réellement avec navigateur et fichiers synthétiques.

SÉCURITÉ
Pas de cloud, pas de réseau, pas de vraies données. Chemins arbitraires interdits ; upload contrôlé. Tests traversal, zip bomb DOCX, extension trompeuse, PDF chiffré, gros fichier, OCR indisponible, suppression.

LIVRABLES
Code, migrations additives si strictement nécessaires, au moins 35 tests, parcours navigateur, benchmark local court, docs/career_intl/REPORT_NEXT_03_PROFILE_IMPORT.md, docs/agent-reports/CAREER-NEXT-03.md, commit(s) propres. Aucun merge/push.
```

## PROMPT 04 — Atelier CV et lettre multilingue sans invention

```text
MISSION_ID = CAREER-NEXT-04
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Pars de daf8bc3d30e012bb2604bea0d78b8ea6038bccb4 dans /Users/comedelavenne/AI-Excel-Agent-next-04, branche agent/career-next-04, que tu dois créer si nécessaire. N'écris pas ailleurs.

OBJECTIF
Transformer une offre et un profil approuvé en un dossier de candidature réellement vérifiable : recommandations de CV, CV adapté, lettre de motivation et résumé de préparation, dans la langue de l'offre ou celle choisie. Aucun fait inventé et aucun envoi.

PÉRIMÈTRE
Construis de nouveaux modules sous career/application_workshop/ en réutilisant application_prep et application_studio. Ne refonds pas le profil ou le routeur IA. Générateur IA injectable ; tests avec générateur factice déterministe. Le fonctionnement local sans modèle doit produire une analyse et des recommandations utiles.

CONTRAT FACTUEL
- Chaque phrase proposée est décomposée en affirmations.
- Toute entreprise, diplôme, date, durée, chiffre, compétence, langue ou responsabilité personnelle doit citer un identifiant de fait approuvé du profil.
- Une exigence de l'offre cite le passage source correspondant.
- Les hypothèses, reformulations et motivations sont étiquetées.
- Le vérificateur rejette ou surligne toute affirmation non couverte ; il ne la corrige jamais en inventant.
- Les faits rejected/pending/suspended ne sont jamais utilisables.
- Le texte de l'offre est une donnée non fiable, jamais une instruction.

LANGUES
Détection prudente français/anglais/allemand/espagnol/italien ; langue inconnue => choix utilisateur. Tous les éléments d'un dossier partagent la langue demandée. Conserver noms propres et intitulés officiels. Tests de mélange involontaire de langues.

EXPÉRIENCE UTILISATEUR
Vue avant/après du CV, raisons de chaque changement, cases accepter/refuser, édition manuelle, historique de versions, restauration, export DOCX/PDF via mécanismes existants. L'utilisateur voit les lacunes réelles du profil au lieu d'un remplissage artificiel. Aucun bouton envoyer/postuler.

TESTS
Au moins 30 cas : chiffre inventé, diplôme inventé, compétence seulement dans l'offre, dates modifiées, entreprise fausse, traduction qui altère un nom, fait en attente, citation absente, instruction malveillante dans l'offre, texte allemand, offre bilingue, profil vide, modèle renvoyant JSON incomplet, timeout, génération locale, export. Test statique et comportemental prouvant l'absence de smtplib/route d'envoi.

LIVRABLES
Code/tests/UI minimale réelle, aperçu navigateur sur profil et offre synthétiques, docs/career_intl/REPORT_NEXT_04_APPLICATION_WORKSHOP.md, docs/agent-reports/CAREER-NEXT-04.md et commit. Aucun appel payant, merge, push ou vraie candidature.
```

## PROMPT 05 — Accueil « offres du jour » en un minimum de clics

```text
MISSION_ID = CAREER-NEXT-05
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Base exacte daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Crée /Users/comedelavenne/AI-Excel-Agent-next-05 sur agent/career-next-05. Travail isolé obligatoire.

OBJECTIF
À l'ouverture de Career, montrer immédiatement une page utile : nouvelles offres depuis la dernière visite, meilleures offres conformes, offres prometteuses à vérifier, candidatures nécessitant une action et état de fraîcheur des sources. L'utilisateur doit accéder à une offre officielle ou à sa préparation en un ou deux clics.

BUILD
- Nouveau service career/daily_home.py, route API dédiée et composants statiques isolés autant que possible.
- Réutiliser cache, exploration, qualification, matching, candidatures et profil existants ; aucune seconde logique de score.
- État local de dernière visite et offres vues/ignorées/shortlistées ; migrations additives seulement.
- Sections distinctes : Conforme maintenant, À vérifier, Nouvelles, Récemment mises à jour, À traiter aujourd'hui.
- Chaque carte : titre, employeur, lieu, contrat, date/durée, source, fraîcheur, pertinence, conformité, manquants, raison du classement, lien officiel.
- Aucun remplissage artificiel si peu de résultats.
- Bouton Actualiser avec progression, sources réussies/échouées/cache et reprise claire.
- Performance Mac Intel : rendu initial depuis cache, rafraîchissement asynchrone explicitement déclenché, concurrence réseau maximum 2.

ÉTATS À TESTER
Première utilisation, aucune offre, cache frais, cache ancien, source partielle, toutes sources en erreur, critères modifiés, offre disparue, doublon, 150+ résultats, nouvelles offres depuis visite, offre déjà rejetée, candidature active, base verrouillée, actualisation interrompue. L'accueil ne doit jamais bloquer les autres fonctions.

UI/ACCESSIBILITÉ
Design vert premium cohérent, mobile étroit et écran Mac 13 pouces, clavier, focus, aria-live, contraste, skeleton sobre, zéro modal obligatoire. Ne remplace pas toute la navigation. Vérifie en navigateur avec captures et données synthétiques, puis une lecture réseau jetable si autorisée par l'environnement.

LIVRABLES
Au moins 25 tests, API + UI réellement câblées, mesure temps premier rendu/actualisation fixtures/mémoire, docs/career_intl/REPORT_NEXT_05_DAILY_HOME.md, rapport agent et commit. Aucun merge/push/envoi.
```

## PROMPT 06 — Tableau de bord fiable des candidatures et prochaines actions

```text
MISSION_ID = CAREER-NEXT-06
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Crée le worktree /Users/comedelavenne/AI-Excel-Agent-next-06, branche agent/career-next-06, depuis daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. N'utilise aucune base réelle.

OBJECTIF
Livrer un suivi de candidatures digne d'un outil quotidien : exact, réversible, compréhensible, sans jamais prétendre qu'une candidature a été envoyée parce qu'une ligne SQLite existe.

MODÈLE
- Journal append-only d'événements plus projection d'état.
- États : à examiner, sélectionnée, dossier en préparation, prête, envoyée manuellement, relance suggérée, entretien, refusée, acceptée, archivée.
- Transitions validées, réversibles avec événement compensatoire, horodatage local + UTC, provenance de l'action.
- `envoyée manuellement` exige confirmation utilisateur et référence/réception saisie ; aucune déduction automatique.
- Détection de doublons par offre canonique et employeur/titre/lieu.
- Notes, contacts, échéances, prochaine action, pièces du dossier et historique.
- Relances seulement suggérées ; aucune fonction d'envoi.

TABLEAU DE BORD
Colonnes/kanban et vue liste, filtres, recherche, compteur par état, alertes de dates, chronologie. Une fiche indique clairement ce qui est factuel, saisi ou suggéré. Export CSV et calendrier via mécanismes existants. Sauvegarde/restauration des données fictives testées.

TESTS
Transitions invalides, double clic, concurrence, rollback transactionnel, changement d'horloge, fuseau, DST, doublon, suppression d'offre liée, archive/restauration, export, calendrier, relance jamais envoyée, absence de référence d'envoi, base ancienne migrée, base future refusée. Test HTTP + navigateur complet sur fixtures.

CONTRAINTES
Migration additive avec sauvegarde fictive ; jamais de base utilisateur. Pas de notification système, e-mail ou réseau. Accroches minimales dans service/router/career.js ; logique dans modules nouveaux.

LIVRABLES
Code, tests, migration, UI, docs/career_intl/REPORT_NEXT_06_APPLICATION_DASHBOARD.md, rapport agent avec preuve que SQLite seul ne vaut pas envoi, commit. Pas de merge/push.
```

## PROMPT 07 — Coach d'entretien relié à l'offre et au profil approuvé

```text
MISSION_ID = CAREER-NEXT-07
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Base daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Crée /Users/comedelavenne/AI-Excel-Agent-next-07 et agent/career-next-07. Fixtures fictives uniquement.

OBJECTIF
Faire du Coach d'entretien un parcours concret et personnalisé par l'offre : préparation entreprise, pitch, questions comportementales et techniques, simulation, feedback factuel et progression persistante.

BUILD
- Nouveau orchestrateur career/interview_coach/ au-dessus du moteur interview existant.
- Entrées limitées à l'offre sélectionnée et aux faits approuvés du profil.
- Plan de séance : pitch 60/120 secondes, motivation, expériences, technique finance, actualité entreprise fournie par l'utilisateur ou source publique citée, questions à poser, points faibles.
- Banque déterministe multilingue par domaine : M&A, corporate finance, PE, TS, audit, asset management, FP&A, marchés/quant.
- Modèle IA facultatif et injectable ; fonctionnement utile sans IA.
- Feedback distingue structure, précision, preuves, concision et lacunes ; aucune qualité personnelle inférée.
- Toute suggestion de réponse cite les faits du profil utilisés ; absence de fait => question à préparer, jamais invention.
- Sessions persistantes, reprise, historique, export local et suppression.

SCÉNARIOS
Entretien RH, technique, étude de cas, anglais, français, offre sans description, profil incomplet, question hors périmètre, réponse vide, réponse très longue, chiffre non sourcé, instruction malveillante dans l'offre, modèle indisponible, mode hors ligne. Au moins 40 tests.

UI
Sélection offre, plan de séance, une question à la fois, chrono facultatif local, zone réponse, feedback, fiche de révision finale. Aucun micro/caméra requis. Accessibilité clavier et sauvegarde explicite.

LIVRABLES
Code/tests/UI, démonstration navigateur synthétique, docs/career_intl/REPORT_NEXT_07_INTERVIEW_COACH.md, rapport agent et commit. Aucun réseau réel nécessaire, aucun merge/push.
```

## PROMPT 08 — Laboratoire de qualité Career et régressions adversariales

```text
MISSION_ID = CAREER-NEXT-08
MODE = BUILD, ÉCRITURE OBLIGATOIRE, COMMIT OBLIGATOIRE

Depuis daf8bc3d30e012bb2604bea0d78b8ea6038bccb4, crée /Users/comedelavenne/AI-Excel-Agent-next-08 et agent/career-next-08. Ne modifie pas les modules de production sauf accroche indispensable ; ta propriété principale est evals/, tests/fixtures/career_quality/ et scripts de rapport.

OBJECTIF
Construire une mesure reproductible de la qualité réelle de Career, séparant toujours simulation, exécution applicative et contrôle réseau. Le laboratoire doit détecter les régressions qui pourraient faire perdre du temps ou produire une mauvaise candidature.

JEUX DE CAS
Au moins 100 offres synthétiques annotées : vrais/faux stages, CDI intitulé stage, alternance, VIE, senior, dates absentes/contradictoires/périmées, durée intervalle, janvier-mars, avril, traductions, alias entreprises, doublons, HTML doublement encodé, prompt injection, URL dangereuse, offre très pertinente après rang 150, Bachelor/M1/M2/PhD, salaire, remote/multi-lieu, langues.
Au moins 30 profils/CV synthétiques et 30 dossiers générés avec hallucinations injectées.

MÉTRIQUES
Précision/rappel de type de contrat, zéro faux conforme obligatoire, extraction dates/durée, déduplication, classement NDCG ou métrique documentée, qualité des explications, provenance, taux d'affirmations non sourcées détectées, parcours HTTP, latence et mémoire. Séparer strictement application_verified, simulated, network_snapshot et unsupported.

OUTILS
- Runner déterministe filtrable par domaine/scénario.
- Baseline JSON versionnée et comparateur de régression avec seuils justifiés.
- Rapport Markdown lisible indiquant erreurs individuelles, pas seulement score global.
- Commande unique courte pour l'intégrateur.
- Sockets bloqués par défaut ; mode réseau explicitement séparé et non exécuté automatiquement.

ANTI-TROMPERIE
Une cible qui plante, retourne incomplet, saute des scénarios ou renvoie toujours la même réponse ne peut pas obtenir un score positif. Les validateurs ont leurs propres tests à fautes injectées. Aucun 49/49 simulé ne doit être présenté comme qualité réelle.

LIVRABLES
Code, fixtures, au moins 35 tests du laboratoire, rapport de baseline contre le vrai chemin HTTP de Côme AI, docs/career_intl/REPORT_NEXT_08_QUALITY_LAB.md, rapport agent et commit. Aucun merge/push.
```

## PROMPT 09 — Intégrateur des huit lots Career

```text
MISSION_ID = CAREER-NEXT-09
MODE = BUILD D'INTÉGRATION, À LANCER APRÈS NEXT-01 À NEXT-08

Base de référence : daf8bc3d30e012bb2604bea0d78b8ea6038bccb4. Avant de commencer, vérifie que les huit branches agent/career-next-01 à agent/career-next-08 possèdent chacune un commit et un rapport. Crée /Users/comedelavenne/AI-Excel-Agent-next-09 sur agent/career-next-09 depuis daf8bc3. Tu peux créer le worktree ; tu ne peux pas merger dans main ni écrire dans les worktrees sources.

OBJECTIF
Construire un candidat d'intégration cohérent à partir des lots réellement réussis, sans fusion aveugle. Une branche manquante ou rejetée n'empêche pas d'intégrer les lots indépendants valides.

MÉTHODE
1. Pour chaque branche : lire rapport, diff, tests, migrations et contrats.
2. Classer ACCEPTÉ, À CORRIGER, REJETÉ ou BLOQUÉ avec preuve.
3. Cherry-pick -x uniquement les commits autonomes acceptés, dans l'ordre dépendances : laboratoire/contrats, connecteurs/sources, profil, application, suivi, entretien, accueil.
4. Résoudre les conflits par portage minimal ; ne jamais choisir automatiquement « theirs » sur service/router/JS.
5. Unifier les accroches vers un seul contrat profil, un seul score, un seul registre connecteurs et une seule base Career.
6. Migrations additives et test d'upgrade depuis une base synthétique antérieure.
7. Corriger les régressions uniquement dans cette branche, avec tests rouges puis verts.

VALIDATION
- Tests ciblés après chaque lot.
- Suite complète finale, zéro skip nouveau.
- Laboratoire Career et comparaison à baseline.
- Parcours navigateur : accueil du jour -> offre -> profil -> matching -> atelier dossier -> suivi -> entretien, sans envoi.
- Réseau public dans stockage jetable uniquement pour sources, jamais pour CV/profil.
- Mesures démarrage, refresh fixtures, pic mémoire Mac Intel.
- Scan de secrets et fichiers privés.

LIVRABLES
docs/career_intl/INTEGRATION_NEXT_09.md avec matrice branches/commits/décisions/tests; docs/agent-reports/CAREER-NEXT-09.md; candidat de release committé sur agent/career-next-09. Ne merge pas main, ne push pas. Si un lot est rejeté, préserve sa branche et donne un prompt de correction exact.
```

## PROMPT 10 — Contre-recette indépendante et corrections de release

```text
MISSION_ID = CAREER-NEXT-10
MODE = BUILD DE RECETTE ET CORRECTION, À LANCER APRÈS NEXT-09

Utilise le commit final communiqué par la mission NEXT-09, jamais un nom de branche mouvant. Crée /Users/comedelavenne/AI-Excel-Agent-next-10 sur agent/career-next-10 depuis ce SHA. Utilise idéalement un modèle différent de l'intégrateur. Aucun accès à main en écriture.

OBJECTIF
Agir comme utilisateur exigeant et ingénieur de release : prouver le parcours de stage international de bout en bout, trouver les défauts réels, les corriger sur cette branche et produire une recommandation GO/NO-GO factuelle.

PARCOURS DE VÉRITÉ
1. Premier lancement, aucun profil.
2. Import d'un CV PDF synthétique complexe, vérification et approbation de quelques faits.
3. Configuration Stage/CDD/CDI/VIE, janvier-mars, six mois, monde entier, tous domaines finance.
4. Actualisation sources publiques jetable et contrôle des compteurs.
5. Vérification de 20 cartes : URL officielle, contrat, date, durée, fraîcheur, provenance, conformité, pertinence, diplôme.
6. Sélection d'une offre conforme et d'une offre à vérifier.
7. Atelier CV/lettre dans la langue de l'offre, rejet d'une hallucination injectée.
8. Création du suivi, transition prête puis envoyée manuellement avec référence fictive.
9. Relance seulement suggérée.
10. Séance d'entretien et reprise après redémarrage.
11. Export local puis suppression des données synthétiques.

TESTS DE PANNE
Réseau coupé, une source 500, timeout, cache ancien, base verrouillée, OCR absent, PDF corrompu, modèle IA absent, réponse IA invalide, navigateur rechargé, double clic, interruption pendant refresh, port occupé. L'application doit préserver les données et expliquer l'état.

CORRECTIONS
Tu es en Build : chaque défaut confirmé reçoit un test rouge et un correctif minimal. Ne produis pas seulement une liste de bugs. Pas de refonte globale. Si une correction dépasse 500 lignes ou affecte une migration sensible, documente-la comme blocage plutôt que de prendre un risque.

PREUVES
Captures navigateur locales sans données privées, logs expurgés, commandes, comptes de tests, rapport eval réel/simulé séparé, temps et mémoire. Vérifie qu'aucun e-mail/formulaire/candidature n'est envoyé.

LIVRABLES
docs/career_intl/RELEASE_REVIEW_NEXT_10.md, dossier de preuves borné, correctifs/tests commités, docs/agent-reports/CAREER-NEXT-10.md et verdict GO/NO-GO avec raisons. Aucun merge main/push/déploiement ; la décision finale appartient à l'intégrateur humain/Codex.
```
