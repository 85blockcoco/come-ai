# Feature Specification: Venture Capital Revision Coach

**Feature Branch**: `004-venture-capital-revision`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "Des centaines de nouvelles missions à intégrer au spec-kit, avec pour priorité de vraiment m'aider à réviser mes cours en VENTURE CAPITAL."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Daily active-recall session (Priority: P1)

L'étudiant ouvre une session de révision quotidienne. Le système lui propose
des cartes de rappel actif issues de **ses propres notes de cours** et du
socle VC original, dans un ordre adapté à sa maîtrise. Il répond de mémoire,
s'auto-évalue, et la carte revient au bon moment (répétition espacée).

**Why this priority**: C'est la boucle d'apprentissage la plus rentable pour un
examen : rappel actif + espacement. Sans elle, les autres fonctions ne servent
qu'à consulter passivement.

**Independent Test**: Avec un jeu de 20 cartes synthétiques, une session de
10 minutes doit proposer des cartes dues, enregistrer les réponses, replanifier
les cartes et afficher un bilan honnête (vues / acquises / à revoir).

**Acceptance Scenarios**:

1. **Given** un jeu de cartes VC avec des échéances, **When** l'étudiant lance
   une session, **Then** seules les cartes dues (ou nouvelles) sont proposées,
   dans un ordre déterministe et explicable.
2. **Given** une réponse auto-évaluée « à revoir », **When** la session se
   termine, **Then** la carte est replanifiée à court terme et le bilan indique
   le nombre exact de cartes restant à consolider.
3. **Given** une session interrompue, **When** l'étudiant la reprend,
   **Then** aucune réponse déjà enregistrée n'est perdue.

---

### User Story 2 - Venture Capital formula lab (Priority: P1)

L'étudiant s'entraîne sur les calculs qui tombent en examen : pre-money /
post-money, dilution, option pool, cap table, liquidation waterfall, IRR,
MOIC, TVPI, DPI, RVPI, J-curve. Chaque exercice attend une réponse numérique
ou un tableau, puis affiche la correction **étape par étape** et diagnostique
l'erreur (formule, ordre des opérations, convention).

**Why this priority**: Les calculs VC sont la principale source d'erreurs
évitables en examen. Un cours compris mais mal calculé ne rapporte pas les
points.

**Independent Test**: Avec 10 drills synthétiques, le système doit accepter
une réponse exacte, refuser une réponse fausse avec une explication, et
produire la même correction déterministe pour les mêmes entrées.

**Acceptance Scenarios**:

1. **Given** un drill « pre-money 8 M€, investment 2 M€ », **When** l'étudiant
   répond 10 M€, **Then** la correction confirme le post-money et détaille la
   formule.
2. **Given** un drill de dilution avec option pool, **When** l'étudiant oublie
   d'inclure l'option pool avant le calcul, **Then** le diagnostic identifie
   l'étape manquante et montre le tableau corrigé.
3. **Given** une réponse non numérique, **When** l'étudiant valide, **Then**
   le système refuse proprement sans perdre l'état de l'exercice.

---

### User Story 3 - Case-study studio (Priority: P1)

L'étudiant travaille des cas VC réalistes et originaux : seed round, Series A,
down round, liquidation preference, anti-dilution, exit waterfall. Pour chaque
cas, il répond à des questions guidées, puis compare sa réponse à une grille
de correction et à un raisonnement modèle.

**Why this priority**: Les examens VC évaluent le jugement et la structuration,
pas seulement la formule. Le case method force la révision active.

**Independent Test**: Un cas seed round doit produire 5 questions guidées, une
grille de notation, un corrigé et un score explicable, sans jamais inventer de
fait absent de l'énoncé.

**Acceptance Scenarios**:

1. **Given** un cas avec des données chiffrées, **When** l'étudiant soumet ses
   réponses, **Then** chaque point de la grille est évalué séparément.
2. **Given** une réponse qui utilise un fait absent de l'énoncé, **When** elle
   est évaluée, **Then** le système la signale comme non justifiée.
3. **Given** un cas de down round, **When** l'étudiant calcule le waterfall,
   **Then** la correction montre l'ordre de priorité des actionnaires.

---

### User Story 4 - Mock exam and oral defense (Priority: P2)

L'étudiant passe un examen blanc chronométré mêlant QCM, calculs et questions
ouvertes, puis un oral simulé avec questions de relance. Le système note,
identifie les topics fragiles et propose une séance de rattrapage.

**Why this priority**: L'examen final combine pression, temps et explication
orale. S'entraîner dans ces conditions réduit l'écart entre révision et
performance.

**Independent Test**: Un examen de 20 questions doit produire un score, un
temps par question, une liste de topics à revoir et aucune question hors
barème.

**Acceptance Scenarios**:

1. **Given** un examen chronométré, **When** le temps expire, **Then** les
   réponses déjà saisies sont conservées et l'examen est soumis.
2. **Given** un oral simulé, **When** l'étudiant répond, **Then** des relances
   ciblées sont proposées sans révéler la réponse modèle.
3. **Given** un score faible sur un topic, **When** le bilan s'affiche,
   **Then** une séance de rattrapage est proposée avec les cartes et drills
   correspondants.

---

### User Story 5 - Weakness radar and adaptive study plan (Priority: P2)

L'étudiant voit sa maîtrise par topic (forces, fragilités, topics non testés)
et reçoit un plan de révision borné en minutes, priorisé par échéance d'examen
et taux d'erreur.

**Why this priority**: Un étudiant perdu révise ce qu'il aime déjà. Le radar
oriente l'effort vers les points qui rapportent le plus.

**Independent Test**: Avec des résultats synthétiques, le radar doit classer
les topics, exclure les non testés du calcul de maîtrise, et produire un plan
tenant dans la capacité demandée.

**Acceptance Scenarios**:

1. **Given** 5 topics avec des taux d'erreur différents, **When** le radar
   s'affiche, **Then** les topics fragiles sont visibles et justifiés.
2. **Given** une capacité de 60 minutes, **When** le plan est généré,
   **Then** la somme des activités ne dépasse pas 60 minutes.
3. **Given** un topic sans données, **When** le radar s'affiche, **Then** il est
   marqué « non testé », jamais « maîtrisé ».

---

### User Story 6 - Notes-to-deck ingestion with citations (Priority: P2)

L'étudiant importe ses notes de cours (texte, markdown, PDF texte) et le
système propose des cartes et des fiches **ancrées dans ses notes**, avec la
citation exacte. Il approuve ou rejette chaque carte avant qu'elle entre dans
sa révision.

**Why this priority**: Les cours VC ont leurs propres définitions et notations.
Réviser avec les mots du professeur est plus utile qu'un contenu générique.

**Independent Test**: Avec des notes synthétiques contenant 3 définitions, le
système doit proposer 3 cartes citées, aucune carte inventée, et un flux
d'approbation explicite.

**Acceptance Scenarios**:

1. **Given** des notes avec une définition, **When** l'ingestion propose une
   carte, **Then** la citation source est visible et vérifiable.
2. **Given** une note ambiguë, **When** aucune réponse certaine n'est trouvée,
   **Then** la carte est marquée « à compléter », pas inventée.
3. **Given** une carte rejetée, **When** l'étudiant relance l'ingestion,
   **Then** elle n'est pas réintroduite sans action explicite.

---

### User Story 7 - VC lexicon and term-sheet decoder (Priority: P3)

L'étudiant consulte un lexique VC FR/EN et décode les clauses d'un term sheet
(liquidation preference, anti-dilution, board, drag-along, tag-along,
pro-rata). Chaque clause est expliquée en langage clair avec son effet
économique.

**Why this priority**: Le vocabulaire est une barrière d'entrée ; le décodage
des clauses relie la théorie au deal réel.

**Independent Test**: Un term sheet synthétique de 10 clauses doit produire
10 explications, 10 effets économiques et 0 clause inventée.

**Acceptance Scenarios**:

1. **Given** une clause de liquidation preference 1x non participating,
   **When** elle est décodée, **Then** l'explication distingue le remboursement
   du partage du residual.
2. **Given** un terme inconnu, **When** l'étudiant le cherche, **Then** le
   système répond « non documenté » au lieu d'inventer.

---

### User Story 8 - Progress report and exam readiness (Priority: P3)

L'étudiant exporte un rapport de progression : topics couverts, cartes dues,
taux de réussite, erreurs récurrentes, cas travaillés, examens blancs et
prochaines actions. Le rapport est lisible hors ligne et ne contient aucune
donnée personnelle inutile.

**Why this priority**: Un rapport honnête permet de décider quoi réviser la
veille de l'examen, sans fausse confiance.

**Independent Test**: Un rapport généré depuis des données synthétiques doit
contenir les sections attendues, des chiffres cohérents et aucune donnée
personnelle.

**Acceptance Scenarios**:

1. **Given** des sessions et des examens synthétiques, **When** le rapport est
   généré, **Then** chaque chiffre est recalculable depuis les données.
2. **Given** un topic non testé, **When** le rapport s'affiche, **Then** il est
   listé comme non testé, pas comme acquis.

---

### Edge Cases

- Notes vides, notes dans une autre langue, notes contenant plusieurs définitions contradictoires.
- Formule applicable seulement sous conditions (ex. liquidation preference participating avec cap).
- Down round avec plusieurs classes d'actions et option pool.
- Réponse numérique avec unités différentes (k€, M€, %).
- Examen interrompu, temps expiré, réponse partielle.
- Carte déjà approuvée puis note source modifiée.
- Topic sans aucune donnée de performance.
- Mode hors-ligne ou serveur local indisponible.
- Import d'un PDF scanné sans texte exploitable.
- Contenu protégé par le droit d'auteur : ne jamais recopier un manuel ou un slide sans droit.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Le système MUST proposer une session de rappel actif composée de cartes dues et de nouvelles cartes, dans un ordre déterministe.
- **FR-002**: Le système MUST enregistrer pour chaque carte la réponse, l'auto-évaluation, la date et la prochaine échéance.
- **FR-003**: Le système MUST replanifier une carte selon une règle de répétition espacée explicite et testable.
- **FR-004**: Le système MUST reprendre une session interrompue sans perte de réponses.
- **FR-005**: Le système MUST proposer des drills de calcul VC avec énoncé, réponse attendue, unité et correction étape par étape.
- **FR-006**: Le système MUST couvrir au minimum : pre/post-money, dilution, option pool, cap table, liquidation waterfall, IRR, MOIC, TVPI, DPI, RVPI.
- **FR-007**: Le système MUST diagnostiquer une erreur de calcul par catégorie (formule, ordre, unité, donnée manquante) lorsque c'est possible.
- **FR-008**: Le système MUST refuser une réponse non numérique sans perdre l'état du drill.
- **FR-009**: Le système MUST proposer des cas VC originaux avec énoncé, questions guidées, grille et corrigé.
- **FR-010**: Le système MUST évaluer chaque critère de la grille séparément.
- **FR-011**: Le système MUST signaler toute réponse qui s'appuie sur un fait absent de l'énoncé.
- **FR-012**: Le système MUST proposer un examen blanc chronométré mêlant plusieurs formats.
- **FR-013**: Le système MUST conserver les réponses saisies quand le temps expire.
- **FR-014**: Le système MUST calculer un score par topic et un score global explicables.
- **FR-015**: Le système MUST proposer un oral simulé avec questions de relance, sans révéler la réponse modèle.
- **FR-016**: Le système MUST afficher un radar de maîtrise par topic.
- **FR-017**: Le système MUST distinguer « non testé » de « maîtrisé ».
- **FR-018**: Le système MUST générer un plan de révision borné par une capacité en minutes.
- **FR-019**: Le système MUST prioriser le plan par échéance d'examen, taux d'erreur et cartes dues.
- **FR-020**: Le système MUST importer des notes texte/markdown/PDF texte fournies par l'étudiant.
- **FR-021**: Le système MUST citer la source exacte de chaque carte issue de notes.
- **FR-022**: Le système MUST marquer « à compléter » toute carte non certaine, sans invention.
- **FR-023**: Le système MUST exiger une approbation explicite avant d'ajouter une carte au deck actif.
- **FR-024**: Le système MUST conserver un lexique VC FR/EN avec définitions originales.
- **FR-025**: Le système MUST décoder les clauses d'un term sheet synthétique et expliquer leur effet économique.
- **FR-026**: Le système MUST répondre « non documenté » pour un terme absent du lexique.
- **FR-027**: Le système MUST produire un rapport de progression lisible hors ligne.
- **FR-028**: Le système MUST recalculer chaque chiffre du rapport depuis les données stockées.
- **FR-029**: Le système MUST stocker les données d'apprentissage hors du dépôt, dans un espace local dédié.
- **FR-030**: Le système MUST fonctionner sans réseau pour les sessions, drills, cas et examens.
- **FR-031**: Le système MUST ne jamais envoyer de notes, réponses ou données personnelles à un service externe.
- **FR-032**: Le système MUST conserver la langue des notes et permettre FR/EN pour l'interface.
- **FR-033**: Le système MUST exposer les topics, cartes, drills et cas via une interface stable et documentée.
- **FR-034**: Le système MUST valider les entrées et renvoyer des erreurs lisibles, sans trace technique brute.
- **FR-035**: Le système MUST journaliser localement les sessions et erreurs sans secret ni donnée sensible.
- **FR-036**: Le système MUST permettre de supprimer toutes les données VC locales avec confirmation.
- **FR-037**: Le système MUST distinguer contenu original, contenu importé et contenu à vérifier.
- **FR-038**: Le système MUST ne jamais recopier un manuel, un slide ou un examen protégé sans droit explicite.
- **FR-039**: Le système MUST fournir un mode « révision rapide » de 10 minutes et un mode « session longue » de 45 minutes.
- **FR-040**: Le système MUST fournir un mode « veille d'examen » centré sur les topics fragiles et les cartes dues.
- **FR-041**: Le système MUST expliquer pourquoi une carte ou un drill est proposé.
- **FR-042**: Le système MUST mesurer la couverture du programme VC (topics vus / topics du plan).
- **FR-043**: Le système MUST produire des statistiques de rétention à 1 jour, 7 jours et 30 jours.
- **FR-044**: Le système MUST gérer les unités k€/M€/% et refuser les incohérences manifestes.
- **FR-045**: Le système MUST proposer une correction alternative quand plusieurs conventions sont acceptables.
- **FR-046**: Le système MUST permettre à l'étudiant de marquer un contenu comme « ambigu » ou « à vérifier avec le cours ».
- **FR-047**: Le système MUST conserver l'historique des versions d'une carte approuvée.
- **FR-048**: Le système MUST permettre l'export du deck en JSON et Markdown.
- **FR-049**: Le système MUST permettre l'import d'un deck JSON valide sans écraser le deck existant.
- **FR-050**: Le système MUST fournir une procédure de reprise après interruption (session, examen, import).

### Key Entities

- **CourseTopic**: un thème du programme VC (ex. cap table, term sheet), avec code, titre FR/EN, prérequis et poids d'examen.
- **Concept**: une notion atomique rattachée à un topic, avec définition originale et source.
- **Flashcard**: question, réponse attendue, topic, source, état d'approbation, historique de versions.
- **ReviewEvent**: réponse d'une session, auto-évaluation, date, durée, prochaine échéance.
- **FormulaDrill**: énoncé, variables, unité, réponse, étapes de correction, catégories d'erreur.
- **CaseStudy**: contexte, données chiffrées, questions, grille, corrigé, faits autorisés.
- **ExamSession**: composition, réponses, temps, score, topics évalués.
- **MasteryRecord**: topic, nombre d'essais, réussites, erreurs, dernière activité, statut.
- **StudyPlan**: capacité, activités ordonnées, justification, échéance.
- **NoteSource**: document importé, extrait, citation, date, statut d'approbation.
- **GlossaryEntry**: terme FR/EN, définition, exemple, source.
- **ProgressReport**: période, couverture, rétention, erreurs, prochaines actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 90 % des sessions de 10 minutes proposent au moins 8 cartes réellement dues ou nouvelles.
- **SC-002**: Une session interrompue reprend avec 100 % des réponses déjà enregistrées.
- **SC-003**: 100 % des drills affichent une correction étape par étape et une unité explicite.
- **SC-004**: 100 % des cas possèdent une grille, un corrigé et une liste de faits autorisés.
- **SC-005**: Un examen blanc de 20 questions produit un score recalculable et un temps total à ±1 seconde.
- **SC-006**: Le radar distingue « non testé » de « maîtrisé » dans 100 % des cas.
- **SC-007**: Un plan de 60 minutes ne dépasse jamais 60 minutes de contenu planifié.
- **SC-008**: 100 % des cartes issues de notes affichent une citation source vérifiable.
- **SC-009**: Aucune carte non certaine n'est ajoutée sans le statut « à compléter ».
- **SC-010**: Le lexique couvre au moins 120 termes VC au terme du programme.
- **SC-011**: Le rapport de progression contient 100 % des sections attendues et des chiffres recalculables.
- **SC-012**: Les sessions, drills, cas et examens fonctionnent sans réseau.
- **SC-013**: Aucune donnée personnelle n'est écrite dans le dépôt.
- **SC-014**: 80 % des topics du programme sont couverts par au moins 10 cartes et 3 drills.
- **SC-015**: L'étudiant peut expliquer, après une session, pourquoi chaque activité lui a été proposée.

## Assumptions

- L'étudiant dispose de ses notes de cours et du programme officiel ; le système ne les remplace pas.
- Le contenu VC de base est original ou fourni par l'étudiant ; aucun manuel protégé n'est recopié.
- L'usage principal est un Mac local, sans dépendance cloud ; le mode hors-ligne est la norme.
- Les calculs utilisent des conventions explicites (k€/M€, pourcentages, ordre des opérations) et documentent les alternatives.
- La langue principale est le français ; les termes VC restent disponibles en anglais.
- Les données d'apprentissage sont stockées hors du dépôt, dans un espace local dédié.
- Le système ne remplace ni le cours ni le professeur : il organise la révision et vérifie la compréhension.
- Les examens blancs sont des exercices originaux, pas des annales copiées.
