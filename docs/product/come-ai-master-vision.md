# Côme IA — Vision Maître Consolidée (Révisée)

## Statut
Vision produit consolidée — architecture et détails techniques à confirmer  
**Portendue**: Côme IA dans sa globalité — tous les domaines fonctionnels couplés  
**Ambition**: Assistant personnel intelligent, proactif, multimodal, multiplateforme et hautement autonome, capable de centraliser et d'automatiser la majorité des activités numériques quotidiennes de son utilisateur.

---

## Mission
Côme IA doit devenir un assistant personnel intelligent capable de comprendre profondément son utilisateur, d'apprendre ses préférences, de mémoriser les informations pertinentes, d'anticiper ses besoins et d'exécuter le plus grand nombre possible de tâches numériques — sans que Career Explorer soit la finalité unique du produit. Il doit constituer une interface centrale entre l'utilisateur et son environnement numérique, afin de remplacer ou de réunir les fonctions de nombreux outils actuellement utilisés séparément. L'utilisateur doit pouvoir lui confier des objectifs complets sans devoir détailler chaque opération intermédiaire.

### Philosophie fondamentale
Côme IA doit :
- Être disponible en permanence
- Conserver un contexte personnel évolutif et contrôlable
- Minimiser les interventions nécessaires de l'utilisateur
- Être proactif sans devenir envahissant
- Apprendre les habitudes et préférences sans les considérer comme immuables
- Pouvoir utiliser plusieurs modèles d'IA et outils spécialisés (locaux et distants)
- Produire des résultats précis, concrets, fiables et immédiatement utilisables
- Communiquer sans jugement, avec franchise et personnalisation
- Respecter les décisions, les autorisations et la confidentialité de son utilisateur
- Rester contrôlable, auditable et réversible
- Présenter une expérience utilisateur haut de gamme sur toutes les plateformes

### Philosophie exclue
- **Career Explorer n'est pas la finalité unique** du produit — c'est un module important mais parmi d'autres
- Toutes les fonctionnalités ne servent pas obligatoirement Career Explorer
- L'architecture ne se résume pas à un serveur domestique ouvert

---

## Objectifs de réussite (progression vers)
1. Le point d'entrée principal pour l'organisation personnelle sur toutes les plateformes
2. L'assistant de référence pour les études et la production académique
3. Un copilote automatisé pour la recherche de stages et les candidatures (module Career)
4. Un outil de gestion des communications (mails, messages)
5. Un assistant de mobilité (trajets, transports)
6. Un moteur de production de documents et d'analyses (Excel, finance, présentations)
7. Une mémoire personnelle consultable et intelligente, transverse à tous les domaines
8. Un projet technique professionnel démontrant des compétences en IA, architecture logicielle, automatisation et expérience utilisateur

---

## Plateformes officielles et synchronisation

### 4.1 Application macOS — COME-MAC
Environnement de travail principal et hub du système.
Fonctionnalités :
- Interface conversationnelle complète (texte et voix)
- Mode conversations vocales interactives
- Tableaux de bord et gestion des missions (autonomes + professionnelles)
- Gestion des documentslocaux et sur serveur personnel
- Analyses avancées, Excel, fichiers financiers et présentations
- Notifications et accès rapide depuis la barre de menus
- Intégration aux fichiers et fonctionnalités système explicitement autorisées
- Possibilité de déléguer des calculs ou opérations intensives à des composants locaux ou distants
- Point d'entrée du moteur autonome 24 h/24
- Interface de configuration de la synchronisation multiplateforme

### 4.2 Application iPhone — COME-IOS
Interface mobile personnelle et compagnon de déplacement.
Fonctionnalités :
- Conversation écrite et vocale
- Notifications intelligentes et contextualisées
- Briefing quotidien personnalisé (synthèse du jour, échéances, priorités)
- Consultation des tâches, agendas et échéances (synchronisées)
- Assistance pendant les déplacements
- Accès à la mémoire personnelle et aux documents (sélectif, autorisé)
- Validation rapide des actions préparées sur Mac/serveur
- Consultation de l'activité des agents autonomes (état, non contenu sensible)
- Partage de contenus depuis d'autres applications lorsque les interfaces du système le permettent
- Interface allégée pour consultation et validation, pas toute la production

### 4.3 Application web — COME-WEB
Interface web d'accès au navigateur, partageant la même identité, mémoire et missions que les autres interfaces.
Fonctionnalités :
- Conversations (historique et mémoire communs)
- Agenda et organisation (synchronisé)
- Candidatures et projets (module Career visible mais pas exclusif)
- Production documentaire (extraction depuis n'importe quelle interface)
- Administration des automatisations (règles de déclenchement, permissions)
- Paramétrage personnel et sécurité (identique aux autres interfaces)
- Accès distant sécurisé au serveur personnel

---

## Exigence MP-001 : Identité utilisateur commune
Les trois interfaces doivent accéder à une identité utilisateur unique, avec préférences et mémoire partagées mais adaptées à la capacité d'affichage de chaque appareil.

## Exigence MP-002 : Continuité de conversation
Une conversation commencée sur Mac doit pouvoir être reprise sur iPhone ou sur le web, avec conservation du contexte et de la mémoire pertinente.

## Exigence MP-003 : Visibilité des missions
Une mission en cours (qu'elle soit professionnelle extraite d'offres ou autonome programmée) doit rester visible depuis tous les appareils, avec adaptation du niveau de détail.

## Exigence MP-004 : Synchronisation des données
Les données doivent être synchronisées avec gestion des conflits et des déconnexions, avec politique de conservation configurable par catégorie (mémoire, missions, documents, préférences).

## Exigence MP-005 : Capacités spécifiques par appareil
Chaque appareil peut posséder des capacités spécifiques sans fragmenter l'expérience globale — par exemple, la production Excel est privilégiée sur Mac, la consultation rapide sur iPhone, l'administration sur web.

---

## Interaction multimodale
- Texte ou voix, en alternant naturellement sur n'importe quelle interface
- Reconnaissance vocale sur appareil ou via services connectés (avec autorisation)
- Synthèse vocale naturelle, adaptation du style de parole
- Conversations vocales interactives, possibilité de reprendre par écrit
- Adaptation de la longueur et du détail des réponses selon l'appareil et le contexte
- Compréhension des références à un contexte déjà connu (mémoire personnelle cross-session)
- Exploitation des documents et images transmis via n'importe quelle interface
- Commandes vocales autorisées pour déclencher des missions (Niveau 2 ou 3 d'autonomie)
- **L'écoute permanente ou l'activation par mot-clé constitue une fonctionnalité distincte**, soumise aux possibilités techniques et à une activation explicite et configurable par l'utilisateur

---

## Présence permanente et autonomie (AUTONOMIE 24h/24)

### Moteur autonome persistant
Côme IA doit disposer d'un service d'exécution persistant, indépendant de l'ouverture des interfaces, capable d :
- Exécuter des tâches programmées et des missions autorisées en arrière-plan
- Réagir à des événements provenant des services connectés (mails, capteurs, calendriers)
- Poursuivre les missions autorisées (Niveaux 2 et 3 d'autonomie) en arrière-plan
- Surveiller les échéances et les événements pertinents (déadlines, relances, perturbations)
- Détecter les changements nécessitant une action (nouveau mail urgent, modification d'agenda, trajet perturbé)
- Poursuivre les prochains briefings (quotidiens, hebdomadaires, à la relance)
- Envoyer des notifications pertinentes et personnalisées sur les appareils de l'utilisateur
- Suspendre ou reprendre desmissions avec état persistant
- Gérer les erreurs, les délais et les interruptions, avec notification à l'utilisateur

### Architecture d'autonomie hybride
- **Serveur permanent à domicile** : disponible en permanence, hébergement local ou dédié, contient la mémoire personnelle, les missions en cours, les automatisations configurées
- **Accès distant sécurisé** : depuis iPhone, web, n'importe où, avec authentification forte et chiffrement des transmissions
- **Modèles locaux et distants selon les besoins** : tâches légères et sensibles sur le Mac/local, calculs intensifs ou modèles spécialisés à distance, basculement configurable par catégorie
- **Mode dégradé** : si le serveur ou la connexion est unavailable, les fonctions locales continuent sur la base des données en cache, avec reconnexion transparente

### Quatre niveaux d'autonomie (représentés sur toutes les interfaces)
- **Niveau 0 — Assistance** : conseil et recommandation sur toute interface
- **Niveau 1 — Préparation** : recherche et production sans action externe engageante, sur toute interface
- **Niveau 2 — Exécution approuvée** : réalisation après validation de l'utilisateur, depuis n'importe quelle interface
- **Niveau 3 — Délégation préautorisée** : exécution autonome d'actions dans un cadre explicite, limité et révocable, configuré par catégorie (mails, calendriers, documents, transports, candidatures)

Les permissions doivent pouvoir être différentes pour les mails, les calendriers, les documents, les transports et les candidatures. Le système doit prévenir les doublons, les exécutions répétées et les actions irréversibles non autorisées.

---

## Mémoire et connaissance personnelle (Côme Memory)

La mémoire personnelle doit être un composant majeur du produit, transversal à tous les domaines, et non une simple conservation des conversations, ni un module uniquement dédié à Career.

### Catégories principales (transversales)
- Mémoire de profil (compétences, préférences générales)
- Mémoire des préférences de communication (ton, format, fréquence)
- Mémoire des habitudes et routines (quotidiennes, hebdomadaires)
- Mémoire académique (cours, supports, révisions, mémoire de fin d'études)
- Mémoire professionnelle (projets, réalisations, compétences validées)
- Mémoire des projets (personnels et professionnels)
- Mémoire relationnelle (interactions sociales, contextes connus)
- Mémoire des événements (échéances, rendez-vous, anniversaires)
- Mémoire des engagements futurs (missions, objectifs)
- Mémoire des documents et connaissances (extraits, extractions, références)
- Mémoire des trajets et mobilité (historique, préférences itinéraires)

### Constitution du profil personnel (transversal)
- Parcours scolaire et professionnel (vue synthèse sur toutes interfaces)
- Objectifs et ambitions (à court, moyen, long terme)
- Préférences de communication (par plateforme)
- Routines et contraintes habituelles (par appareil)
- Méthodes de travail efficaces (par contexte)
- Préférences documentaires (templates, formats favoris)
- Horaires habituels (par fuseau, par activité)
- Déplacements récurrents (itinéraires favoris, transports habituels)
- Engagements et échéances (par catégorie : personnelles, professionnelles, académiques)
- Compétences et connaissances (niveau, origine, date d'acquisition)
- Exigences propres aux différentes tâches (par domaine d'application)

La mémoire doit distinguer les informations confirmées des déductions et hypothèses, avec niveau de confiance associé.

### Gestion et transparence (transversale)
L'utilisateur doit pouvoir, sur n'importe quelle interface :
- Consulter ce que Côme IA sait de lui (par catégorie)
- Voir l'origine d'une information (source, date, confiance)
- Corriger les informations erronées (par catégorie)
- Définir les informations à conserver (durées de conservation par catégorie)
- Supprimer un souvenir ou une catégorie (avec confirmation)
- Désactiver certains mécanismes d'apprentissage (par catégorie)
- Exporter ses données (par catégorie, format)
- Définir des durées de conservation (par catégorie, policy)
- Révoquer l'accès à un service ou une source (par catégorie)

L'accès à une information ne signifie pas automatiquement qu'elle doit être stockée indéfiniment ou sur toutes les plateformes.

---

## Domaines fonctionnels (structure transversale)

Chaque domaine ci-dessous s'applique sur toutes les plateformes, avec interface adaptée.

### 1. Organisation et productivité
- Planification intelligente des journées et semaines (toutes plates-formes)
- Calendriers synchronisés (identité commune, MP-001 à MP-005)
- Gestion des tâches (création, suivi, rappel, sur n'importe quelle interface)
- Détection des deadlines (toutes sources, unifiées)
- Rappels contextualisés (par appareil, par préférence)
- Routines personnelles (configurables par utilisateur)
- Replanification dynamique (moteur autonome, niveau 3)
- Briefings quotidiens et hebdomadaires (synthèse, adaptée à l'appareil)
- Identification et hiérarchisation des priorités (par contexte, par niveau d'autonomie autorisé)

### 2. Études et apprentissage
- Compréhension des cours (tous formats : PDF, présentations, notes)
- Importation et analyse de supports (transfert depuis n'importe quelle source)
- Création de fiches de révision (adaptée au type de cours)
- Quiz et examens blancs (génération, correction partielle)
- Suivi de progression (par cours, par compétence, visualisation cross-appareil)
- Explications pédagogiques personnalisées (par style d'apprentissage)
- Aide aux exercices et aux devoirs (guidage, pas remplacement)
- Analyse financière et tableurs (module Finance, pas uniquement Career)
- Recherche documentaire (mémoire, thèse, articles, pas seulement Career)
- Accompagnement méthodologique et rédactionnel du mémoire de fin d'études (transversal)
- Traçabilité des sources et respect des consignes académiques applicables

### 3. Carrière et candidatures (module spécialisé)
- Importation du profil professionnel (vue synthétique, pas exhaustive Career-only)
- Recherche automatisée d'offres de stage et d'emploi (module Career)
- Déduplication des annonces (moteur commun, pas seulement Career)
- Vérification des critères d'éligibilité (par programme, pas uniquement)
- Score de compatibilité explicable (par offre, par compétence, transparent)
- Recherche sur les entreprises (base élargie, pas seulement recrutement)
- Génération de CV adaptés aux annonces (module Production documentaire)
- Optimisation de la lisibilité ATS (outil, pas seulement pour Career)
- Personnalisation des lettres de motivation (modèle, adaptation)
- Préparation des formulaires de candidature (synthèse des qualifications)
- Suivi des candidatures (statut, échéances, relances, sur toutes interfaces)
- Gestion des relances (moteur autonome, niveaux d'autonomie)
- Préparation aux entretiens (questions, préparation, simulacres)
- Historique et statistiques des candidatures (tableaux de bord, visualisation)

**Distinction** : Ce module est spécialisé mais pas exclusif — d'autres domaines (communication, mobilité) peuvent aussi traiter les aspects "candidature" selon le contexte.

### 4. Mails et communications
- Connexion aux comptes autorisés (IMAP, Exchange, autres, avec consentement explicite)
- Tri et catégorisation (règles configurables, par préférence)
- Résumés intelligents (par importance, par contexte, résumé court/détaillé selon appareil)
- Détection des messages importants (règles heuristiques, apprentissage utilisateur)
- Préparation de réponses ( brouillon, suggestions, pas envoi automatique sans niveau 2)
- Extraction des tâches et rendez-vous (de n'importe quel mail, pas seulement candidatures)
- Création de rappels (synchronisation avec agenda, par catégorie)
- Suivi des échanges (historique, ponts non lus, par compte)
- Propositions de relances (moteur autonome, selon règles utilisateur)
- Envois uniquement selon les règles d'autorisation définies (Niveaux 1/2/3 d'autonomie)

### 5. Transport et mobilité
- Recherche de trajets (SNCF, TGV MAX, transports urbains, selon accès disponibles)
- Comparaison des itinéraires (temps, coût, confort, préférences utilisateur)
- Gestion des horaires (synchronisation avec agendas, mises à jour en temps réel)
- Suivi des perturbations (alertes proactives, suggestions d'itinéraires alternatifs)
- Alerte pour les correspondances (temps minimum, contexte historique)
- Prise en compte des contraintes d'agenda (conflits détectés, réplanification suggérée)
- Préparation de réservations lorsque les services le permettent (validation explicite engageante)
- Validation explicite des achats ou réservations engageantes (Niveau 2 exigé)
- Intégration des informations de mobilité dans les briefings quotidiens

### 6. Conseiller personnel
- Conversations sur les sujets de la vie quotidienne (toutes plates-formes)
- Comparaison d'options (multi-critères, adaptation au profil)
- Aide à la décision (présentation des options, incertitudes explicites)
- Recommandations adaptées au profil (mémoire personnelle, préférences)
- Réponses concrètes et sans jugement (ton configurable, frame de référence)
- Présentation explicite des incertitudes (niveau de confiance, limites connues)
- Liberté de personnaliser le ton et le degré de franchise (paramétrable par utilisateur)
- **Limites de sûreté pour les usages dangereux ou illégitimes** (toujours explicites, jamais franchies sans autorisation explicite)
- Ne pas agir à l'insu de l'utilisateur (toute action engageante nécessite validation selon les niveaux d'autonomie configurés)

### 7. Création et analyse documentaire
- Production et modification de fichiers Excel (formules, calculs, modèles financiers)
- Formules, calculs et modèles financiers (pas uniquement liés aux carrières)
- Analyse de données (tout type de jeu de données, visualisation)
- Production de graphiques et de présentations (modèles variés, pas seulement portfolio carrière)
- Conception de CV (module, mais pas uniquement pour candidatures Career)
- Production de documents Word et PDF (templates variés, usage général)
- Notes intelligentes (prise de lien avec mémoire personnelle)
- Gestion et recherche dans les documents (par mots-clés, par provenance, traverses interfaces)
- Exportation dans des formats standard et modifiables (PDF, DOCX, ODT, selon besoin)

### 8. Architecture cible (hybride auto-hébergée)

**Côme Core** : raisonnement, sélection des modèles selon besoin, basculement local/distanciel.

**Côme Memory** : connaissance personnelle et récupération du contexte, stockée sur serveur personnel, accessible transversalement.

**Côme Watch** : événements, tâches programmées, détection des changements et proactivité, sur serveur maison + accès distant.

**Côme Agents** : planification, délégation, exécution et vérification des missions (Niveaux 0-3 d'autonomie), répartis entre local et distant selon catégories de permissions.

**Côme Connect** : intégration aux outils et services externes, avec autorisations explicites par catégorie.

**Côme Identity** : authentification, permissions et gestion des secrets, avec identité commune MP-001.

**Côme Sync** : synchronisation des données et continuité entre appareils, politique de conservation par catégorie, gestion des conflits.

**Côme Studio** : production et manipulation de documents, sur chaque appareil selon capacités.

**Côme Apps** : applications macOS, iOS et web, interfaces adaptées aux capacités de chaque plateforme.

Ces composants définissent des responsabilités logiques. Leur implémentation — locale, distante, hybride — sera déterminée après audit complet de l'application existante et architecture du serveur personnel.

### 9. Sécurité et fiabilité (principles Constitution adaptés)
- Authentification et contrôle d'accès (identité commune, permissions par catégorie)
- Chiffrement approprié des données (transit au repos, par catégorie de sensibilité)
- Gestion sécurisée des secrets (stockage local, jamais en clair sur interfaces externes)
- Autorisations limitées par domaine et par niveau d'autonomie (Niveaux 0-3)
- Journalisation des actions (par catégorie, conservé selon policy utilisateur, accessible pour révision)
- Protection contre les contenus malveillants provenant de sources externes (filtres, confirmations)
- Confirmation des actions sensibles (Niveau 2 minimum pour tout engagement)
- Annulation lorsque techniquement possible (tout engagement Niveau 2+ doit pouvoir être annulé)
- Sauvegardes et restauration (par catégorie, politique configurables)
- Supervision des coûts et quotas des services IA (visibilité sur dépenses, seuils configurables)
- Disponibilité 24h/24 avec mode dégradé (serveur maison + cache local)

---

## Critères d'acceptation (revisés, transverses)
| Identifiant | Condition vérifiable | Portée |
|---|---|---|
| MP-001 | Une conversation créée sur Mac peut être reprise sur iPhone et sur le web | Synchronisation identité |
| MP-002 | Une mission reste consultable depuis plusieurs appareils | Visibilité cross-platform |
| VO-001 | L'utilisateur peut envoyer une demande vocale et recevoir une réponse audio sur les plateformes compatibles | Multimodal |
| VO-002 | Une conversation peut alterner texte et voix sans perdre son contexte | Mémoire contextuelle |
| AUT-001 | Une mission programmée peut se déclencher alors que les trois interfaces sont fermées | Moteur autonome (Niveaux 2-3) |
| AUT-002 | Une mission interrompue possède un état persistant et peut être reprise ou signalée en échec | État persistant, serveur maison |
| AUT-003 | Une action externe non autorisée est bloquée et inscrite dans le journal approprié | Contrôle d'autorisations |
| MEM-001 | L'utilisateur peut voir et corriger une information personnelle mémorisée | Transparence, par catégorie |
| MEM-002 | La suppression d'une information entraîne sa disparition des mécanismes de récupération concernés, selon la politique de rétention documentée | Gestion données, par catégorie |
| PRO-001 | Un événement pertinent peut déclencher une proposition d'action contextualisée | Intelligence proactive |
| PRO-002 | Une automatisation peut être suspendue ou désactivée par l'utilisateur | Contrôle utilisateur, Niveaux autonomie |
| SEC-001 | Les identifiants et secrets des services connectés ne sont pas exposés dans les journaux ou réponses des agents | Sécurité opérative |
| SEC-002 | Les transferts de données entre Mac, serveur personnel, iPhone et web sont explicitement autorisés par catégorie | Flux de données autorisés |
| QUA-001 | Toute nouvelle fonctionnalité possède des tests et des conditions explicites de non-régression | Qualité globale |

---

## Décisions architecturales validées
- **Plateformes** : Mac, iPhone et web avec synchronisation identité commune (MP-001 à MP-005)
- **Interaction** : Texte et voix, multimodale, adaptée à chaque interface
- **Mémoire** : Personnelle, contrôlable, transversale à tous les domaines, stockée sur serveur personnel
- **Proactivité** : Présente 24h/24 via moteur autonome, architecture hybride maison+distant
- **Autonomie** : Quatre niveaux configurables par catégorie (mails, calendriers, documents, transports, candidatures)
- **Architecture** : Serveur permanent à domicile + accès distant sécurisé + modèles locaux/distants selon besoins
- **Sécurité** : Principes Constitution adaptés, pas Career-only,適用 sur tout le produit

**Prochaine décision architecturale** : Infrastructure du serveur personnel — choix technologie, critères de sélection, politique de déploiement progressif.

---

## Domaines non-exclusifs de Côme IA (pas uniquement Career)

Pour éviter la dérive Career-first constatée, les domaines suivants sont présents dans le produit dans leur globalité, indépendamment de Career Explorer :

1. **Productivité générale** — organisation, tâches, routines (transverses)
2. **Académique et études** — cours, mémoire, examens (transverses, module dédié)
3. **Finance et documents** — Excel, analyse, présentations (transverses)
4. **Mobilité et transports** — trajets, réservations (transverses)
5. **Communications** — mails, messages, relances (transverses)
6. **Conseiller personnel** — vie quotidienne, décisions (transverses)
7. **Production documentaire** — variée, pas seulement CV/lettres de motivation

Chaque domaine possède sa propre roadmap de consolidation, indépendamment de Career. L'objectif n'est pas de faire de Côme IA un assistant "tout-en-un" mais de centraliser là où l'utilisateur le souhaite, avec transparence sur ce qui appartient à quel domaine.

---

## Séquence d'implémentation recommandée (vision d'ensemble)
1. **Consolidation de l'existant** — Toutes les fonctionnalités présentes vérifiées, testées, intégrées
2. **Stabilisation des interfaces** — Expérience cohérente entre Mac, iPhone, web
3. **Mémoire personnelle avancée** — Structure transversale, gestion_confiance, accès par catégorie
4. **Intelligence et orchestration** — Moteur autonome, prise de décision, niveaux d'autonomie
5. **Proactivité et missions persistantes** — Détection événements, déclenchements, état persistant
6. **Synchronisation multiplateforme** — Identité commune, synchronisation, gestion conflits
7. **Académique et productivité** — Domaines non-Career consolidés et testés
8. **Connecteurs, transports et communications** — Intégrations externes, autorisations explicites
9. **Production documentaire** — Variée, modèles variés, export formats standards
10. **Sécurité, performance et qualité** — Surveillance, coût, non-régression, stabilisation

L'ordre réel pourra être modifié après étude des dépendances réelles et de la valeur apportée par chaque domaine.

---

## Provenance de cette vision
| Claim | Source | Quote | Offset |
|-------|--------|-------|--------|
| Vision portée globale | présente document | "Portée: Côme IA dans sa globalité — tous les domaines fonctionnels couplés" | h1 |
| Career n'est pas finalité unique | présente document | "Career Explorer n'est pas la finalité unique du produit" | h2 Philosophie exclue |
| Architecture hybride | présente document | "Serveur permanent à domicile + accès distant sécurisé + modèles locaux/distants selon besoins" | section 8 |
| Distinction domaines | présente document | "Chaque domaine possède sa propre roadmap de consolidation, indépendamment de Career" | fin de section Domaines non-exclusifs |