# NAGe — backlog des 200 missions vers l'outil final

Date de cadrage : 2026-11-02. Ce document est un backlog de développement, pas un
registre de missions terminées. Une mission ne devient « done » qu'après un commit,
un test ciblé reproductible et une vérification du parcours concerné. Les données de
test sont synthétiques ; aucune candidature n'est envoyée automatiquement.

## Règles communes

- Chaque mission doit rester atomique, réversible et limitée à un worktree.
- Chaque mission conserve la provenance, les inconnues et les avertissements.
- Toute action externe (candidature, mail, upload, partage) reste manuelle et confirmée.
- Les tests ciblés sont obligatoires avant toute intégration ; la suite complète est une étape séparée.
- Les missions qui touchent `main` sont interdites dans leur branche de travail.

## Lot A — socle produit et navigation (FINAL-001 à FINAL-020)

- FINAL-001 — Cartographier tous les écrans accessibles depuis le lanceur — dépend de rien — preuve : inventaire de routes et screenshot synthétique.
- FINAL-002 — Définir une route canonique unique `/app` pour les modules visibles — dépend de FINAL-001 — preuve : redirections testées sans perte de hash.
- FINAL-003 — Supprimer les liens de navigation historiques non fonctionnels — dépend de FINAL-002 — preuve : test DOM sans lien mort.
- FINAL-004 — Ajouter un registre de modules affichant nom, statut et route — dépend de FINAL-002 — preuve : fixture de registre validée.
- FINAL-005 — Ajouter un sélecteur de thème professionnel vert — dépend de FINAL-001 — preuve : préférence persistée et accessible au clavier.
- FINAL-006 — Créer le shell responsive commun — dépend de FINAL-002 — preuve : snapshots 390, 768 et 1440 px.
- FINAL-007 — Uniformiser les états de chargement — dépend de FINAL-006 — preuve : chaque liste expose `aria-busy` et skeleton.
- FINAL-008 — Uniformiser les erreurs et boutons de reprise — dépend de FINAL-006 — preuve : panne réseau synthétique récupérable.
- FINAL-009 — Ajouter une barre de contexte avec titre, retour et aide — dépend de FINAL-006 — preuve : navigation clavier complète.
- FINAL-010 — Ajouter un indicateur de sauvegarde locale — dépend de FINAL-006 — preuve : état enregistré, en cours, échoué.
- FINAL-011 — Créer la page d'accueil orientée prochaine action — dépend de FINAL-004 — preuve : aucun module vide sans explication.
- FINAL-012 — Ajouter une recherche globale locale — dépend de FINAL-004 — preuve : résultats avec route et provenance.
- FINAL-013 — Ajouter une palette de raccourcis clavier — dépend de FINAL-012 — preuve : test clavier synthétique.
- FINAL-014 — Ajouter un centre de notifications non intrusif — dépend de FINAL-008 — preuve : notification de succès et d'erreur testées.
- FINAL-015 — Garantir le contraste WCAG AA des composants — dépend de FINAL-006 — preuve : audit automatisé sans violation bloquante.
- FINAL-016 — Garantir le focus visible après chaque changement de vue — dépend de FINAL-006 — preuve : scénario Playwright.
- FINAL-017 — Ajouter une page de préférences générales — dépend de FINAL-005 — preuve : sauvegarde et réinitialisation.
- FINAL-018 — Ajouter un mode données synthétiques de démonstration — dépend de FINAL-011 — preuve : seed isolé et bouton d'effacement.
- FINAL-019 — Ajouter un export de diagnostic non personnel — dépend de FINAL-014 — preuve : archive sans secret ni document personnel.
- FINAL-020 — Documenter le lanceur exact et les ports supportés — dépend de FINAL-001 — preuve : quickstart rejouable sur machine neuve.

## Lot B — Career et découverte des stages (FINAL-021 à FINAL-040)

- FINAL-021 — Définir le modèle canonique d'une offre — dépend de FINAL-004 — preuve : schéma validé avec champs inconnus explicites.
- FINAL-022 — Ajouter l'identifiant stable d'offre et d'employeur — dépend de FINAL-021 — preuve : doublons synthétiques regroupés.
- FINAL-023 — Normaliser `internship`, `intern`, `stage` et variantes — dépend de FINAL-021 — preuve : fixtures FR/EN/DE/ES.
- FINAL-024 — Extraire début, durée et date de fin sans inventer le jour — dépend de FINAL-021 — preuve : 30 cas dont mois ambigus.
- FINAL-025 — Détecter les langues exigées et préférées — dépend de FINAL-021 — preuve : obligatoire/préférée/inconnue séparées.
- FINAL-026 — Calculer la fin d'un stage à partir d'un début et d'une durée — dépend de FINAL-024 — preuve : mois calendaires et cas bissextiles.
- FINAL-027 — Détecter les contradictions entre texte et champs structurés — dépend de FINAL-024 — preuve : statut `contradictory` conservé.
- FINAL-028 — Conserver le texte source et son emplacement — dépend de FINAL-021 — preuve : chaque fait possède une citation.
- FINAL-029 — Vérifier la fraîcheur d'une offre — dépend de FINAL-028 — preuve : âge et niveau de confiance affichés.
- FINAL-030 — Vérifier la provenance employeur/ATS officielle — dépend de FINAL-028 — preuve : domaines ressemblants refusés.
- FINAL-031 — Ajouter connecteur Greenhouse synthétique — dépend de FINAL-030 — preuve : import hors ligne.
- FINAL-032 — Ajouter connecteur Lever synthétique — dépend de FINAL-030 — preuve : import hors ligne.
- FINAL-033 — Ajouter connecteur Ashby synthétique — dépend de FINAL-030 — preuve : import hors ligne.
- FINAL-034 — Ajouter connecteur SmartRecruiters synthétique — dépend de FINAL-030 — preuve : import hors ligne.
- FINAL-035 — Ajouter import manuel CSV contrôlé — dépend de FINAL-021 — preuve : colonnes inconnues signalées.
- FINAL-036 — Ajouter déduplication par URL canonique — dépend de FINAL-022 — preuve : résultat avant/après mesuré.
- FINAL-037 — Ajouter déduplication par titre, employeur et période — dépend de FINAL-036 — preuve : faux positifs couverts.
- FINAL-038 — Ajouter couverture par pays et famille finance — dépend de FINAL-021 — preuve : métriques séparées live/synthétique.
- FINAL-039 — Ajouter bouton « vérifier maintenant » sans envoi externe — dépend de FINAL-029 — preuve : confirmation humaine.
- FINAL-040 — Construire la carte offre avec source, dates, langue et inconnues — dépend de FINAL-025 — preuve : parcours navigateur complet.

## Lot C — profil, éligibilité et matching (FINAL-041 à FINAL-060)

- FINAL-041 — Modéliser le profil approuvé minimal — dépend de FINAL-021 — preuve : aucun fait non approuvé utilisé.
- FINAL-042 — Importer un CV en zone locale contrôlée — dépend de FINAL-041 — preuve : fichier synthétique seulement.
- FINAL-043 — Extraire formation, niveau et dates — dépend de FINAL-042 — preuve : extraction avec citations.
- FINAL-044 — Distinguer BBA/Bac+4/M1/M2/MBA — dépend de FINAL-043 — preuve : matrice de qualification.
- FINAL-045 — Rendre le niveau de diplôme configurable — dépend de FINAL-044 — preuve : filtre conservant les offres moins accessibles.
- FINAL-046 — Extraire autorisation de travail sans inférence — dépend de FINAL-041 — preuve : inconnu séparé de non-conforme.
- FINAL-047 — Extraire expérience et secteur financier — dépend de FINAL-043 — preuve : faits approuvables un par un.
- FINAL-048 — Extraire langues du profil — dépend de FINAL-043 — preuve : niveau et source séparés.
- FINAL-049 — Comparer requis et préférés — dépend de FINAL-045 — preuve : groupes satisfied/missing/unknown.
- FINAL-050 — Produire un verdict d'éligibilité explicable — dépend de FINAL-049 — preuve : chaque score a des raisons.
- FINAL-051 — Refuser le score si un critère critique est inconnu — dépend de FINAL-050 — preuve : blocker visible.
- FINAL-052 — Ajouter score de compatibilité modifiable — dépend de FINAL-050 — preuve : poids persistés et affichés.
- FINAL-053 — Ajouter score de qualité de preuve — dépend de FINAL-028 — preuve : URL/citation influencent la confiance.
- FINAL-054 — Ajouter score de fraîcheur — dépend de FINAL-029 — preuve : vieillissement déterministe.
- FINAL-055 — Ajouter classement global explicable — dépend de FINAL-052 — preuve : ordre stable.
- FINAL-056 — Ajouter filtre « accessible dès Bac+4 » — dépend de FINAL-045 — preuve : BBA prioritaire, M2/MBA conservés.
- FINAL-057 — Ajouter filtre période janvier 2027 et six mois — dépend de FINAL-024 — preuve : aucun critère inconnu classé conforme.
- FINAL-058 — Ajouter comparaison de deux offres — dépend de FINAL-055 — preuve : tableau des écarts.
- FINAL-059 — Ajouter explication « pourquoi cette offre » — dépend de FINAL-055 — preuve : trois raisons maximum et sources.
- FINAL-060 — Tester le matching sur 100 offres synthétiques — dépend de FINAL-055 — preuve : rapport précision/rappels manuel.

## Lot D — CV et diagnostic ATS (FINAL-061 à FINAL-080)

- FINAL-061 — Définir le CV source immuable — dépend de FINAL-042 — preuve : hash et copie originale conservés.
- FINAL-062 — Ajouter extraction texte PDF — dépend de FINAL-061 — preuve : PDF textuel et erreurs explicites.
- FINAL-063 — Ajouter extraction DOCX — dépend de FINAL-061 — preuve : paragraphes et tableaux testés.
- FINAL-064 — Détecter PDF image-only — dépend de FINAL-062 — preuve : avertissement OCR, aucune invention.
- FINAL-065 — Ajouter diagnostic de lisibilité ATS — dépend de FINAL-062 — preuve : score et raisons.
- FINAL-066 — Détecter colonnes, tableaux et polices à risque — dépend de FINAL-065 — preuve : fixtures documentaires.
- FINAL-067 — Extraire les mots-clés d'une offre — dépend de FINAL-028 — preuve : termes cités.
- FINAL-068 — Comparer mots-clés CV/offre — dépend de FINAL-067 — preuve : couverture et gaps.
- FINAL-069 — Ajouter variantes de CV par famille finance — dépend de FINAL-068 — preuve : variante versionnée.
- FINAL-070 — Empêcher la modification automatique de l'original — dépend de FINAL-061 — preuve : test d'intégrité du hash.
- FINAL-071 — Ajouter édition guidée d'une section — dépend de FINAL-069 — preuve : diff avant/après.
- FINAL-072 — Ajouter validation des dates du CV — dépend de FINAL-071 — preuve : contradictions bloquantes.
- FINAL-073 — Ajouter validation des coordonnées — dépend de FINAL-071 — preuve : secrets et données sensibles masqués dans les logs.
- FINAL-074 — Ajouter aperçu PDF local — dépend de FINAL-071 — preuve : rendu contrôlé.
- FINAL-075 — Ajouter export DOCX local — dépend de FINAL-071 — preuve : ZIP validé et texte retrouvé.
- FINAL-076 — Ajouter nomenclature de fichiers — dépend de FINAL-074 — preuve : nom déterministe et sûr.
- FINAL-077 — Ajouter historique des variantes — dépend de FINAL-069 — preuve : restauration non destructive.
- FINAL-078 — Ajouter approbation humaine avant export — dépend de FINAL-077 — preuve : export refusé si version modifiée.
- FINAL-079 — Ajouter comparaison CV original/variant — dépend de FINAL-077 — preuve : lignes ajoutées/supprimées.
- FINAL-080 — Recette CV complète sur document synthétique — dépend de FINAL-078 — preuve : parcours navigateur sans données personnelles.

## Lot E — lettres de motivation (FINAL-081 à FINAL-100)

- FINAL-081 — Définir le contrat lettre multilingue — dépend de FINAL-040 — preuve : français/anglais/allemand/espagnol.
- FINAL-082 — Générer une structure de lettre factuelle — dépend de FINAL-081 — preuve : faits cités uniquement.
- FINAL-083 — Ajouter choix de ton — dépend de FINAL-081 — preuve : formal/dynamic/concise contrôlé.
- FINAL-084 — Ajouter champ faits utilisateur — dépend de FINAL-082 — preuve : longueur et avertissements.
- FINAL-085 — Ajouter vérification de couverture — dépend de FINAL-082 — preuve : score et gaps.
- FINAL-086 — Ajouter détecteur d'affirmation non prouvée — dépend de FINAL-085 — preuve : suggestion « à compléter ».
- FINAL-087 — Ajouter adaptation à la langue de l'offre — dépend de FINAL-025 — preuve : langue inconnue ne déclenche pas de traduction automatique.
- FINAL-088 — Ajouter aperçu éditable — dépend de FINAL-082 — preuve : modification invalide l'approbation.
- FINAL-089 — Ajouter approbation liée au contenu — dépend de FINAL-088 — preuve : empreinte recalculée.
- FINAL-090 — Ajouter export Markdown local — dépend de FINAL-089 — preuve : cible serveur imposée.
- FINAL-091 — Ajouter export DOCX local — dépend de FINAL-089 — preuve : document ouvrable.
- FINAL-092 — Ajouter export PDF local — dépend de FINAL-089 — preuve : rendu vérifié.
- FINAL-093 — Ajouter modèles de paragraphes sans hallucination — dépend de FINAL-082 — preuve : texte source obligatoire.
- FINAL-094 — Ajouter suggestions de personnalisation — dépend de FINAL-085 — preuve : suggestions jamais appliquées sans clic.
- FINAL-095 — Ajouter historique des versions de lettre — dépend de FINAL-089 — preuve : restauration et audit.
- FINAL-096 — Ajouter effacement des brouillons — dépend de FINAL-095 — preuve : suppression locale confirmée.
- FINAL-097 — Ajouter téléchargement sûr des exports — dépend de FINAL-090 — preuve : traversal et symlink refusés.
- FINAL-098 — Ajouter test trois interactions — dépend de FINAL-089 — preuve : offer → generate → approve/export manuel.
- FINAL-099 — Ajouter revue accessibilité de l'éditeur — dépend de FINAL-088 — preuve : clavier et lecteur d'écran.
- FINAL-100 — Recette lettre complète en quatre langues — dépend de FINAL-097 — preuve : 16 scénarios synthétiques.

## Lot F — shortlist, dossier et candidatures contrôlées (FINAL-101 à FINAL-120)

- FINAL-101 — Ajouter shortlist persistante — dépend de FINAL-055 — preuve : redémarrage conserve les choix.
- FINAL-102 — Ajouter note personnelle locale — dépend de FINAL-101 — preuve : note non envoyée.
- FINAL-103 — Ajouter statut découvert/shortlist/prêt/suivi — dépend de FINAL-101 — preuve : transitions validées.
- FINAL-104 — Ajouter dossier par offre — dépend de FINAL-103 — preuve : CV, lettre, preuves et checklist.
- FINAL-105 — Ajouter checklist de candidature — dépend de FINAL-104 — preuve : items cochables et auditables.
- FINAL-106 — Ajouter préremplissage ATS — dépend de FINAL-104 — preuve : champs suggérés avec source.
- FINAL-107 — Ajouter détection du formulaire ATS — dépend de FINAL-106 — preuve : guide humain si inconnu.
- FINAL-108 — Ajouter aperçu du payload sans envoi — dépend de FINAL-106 — preuve : JSON visible et local.
- FINAL-109 — Ajouter validation email/URL avant action — dépend de FINAL-108 — preuve : blocage des domaines non confirmés.
- FINAL-110 — Ajouter confirmation explicite avant tout upload — dépend de FINAL-108 — preuve : aucune requête sans clic.
- FINAL-111 — Ajouter bouton « ouvrir l'offre » dans le même flux — dépend de FINAL-101 — preuve : pas de perte de contexte.
- FINAL-112 — Ajouter suivi d'action manuelle — dépend de FINAL-110 — preuve : horodatage local et note.
- FINAL-113 — Ajouter relance planifiée sans envoi automatique — dépend de FINAL-112 — preuve : rappel uniquement.
- FINAL-114 — Ajouter export dossier ZIP — dépend de FINAL-104 — preuve : archive sans chemin client.
- FINAL-115 — Ajouter import d'une réponse recruteur — dépend de FINAL-112 — preuve : texte local et source.
- FINAL-116 — Ajouter journal d'audit des décisions — dépend de FINAL-103 — preuve : append-only et lisible.
- FINAL-117 — Ajouter suppression complète d'une candidature — dépend de FINAL-116 — preuve : données liées supprimées.
- FINAL-118 — Ajouter tableau de bord candidature — dépend de FINAL-103 — preuve : compte cohérent.
- FINAL-119 — Ajouter recette « stage en 3 interactions » — dépend de FINAL-110 — preuve : vidéo/screenshot synthétique.
- FINAL-120 — Vérifier absence de soumission HTTP automatique — dépend de FINAL-110 — preuve : test réseau bloquant.

## Lot G — sourcing international et intelligence métier (FINAL-121 à FINAL-140)

- FINAL-121 — Définir les familles finance prioritaires — dépend de FINAL-038 — preuve : M&A, CIB, PE, VC, marchés, risk, corp fin.
- FINAL-122 — Ajouter mapping synonymes métier — dépend de FINAL-121 — preuve : FR/EN et acronymes.
- FINAL-123 — Ajouter couverture géographique configurable — dépend de FINAL-038 — preuve : pays et villes séparés.
- FINAL-124 — Ajouter score de diversité des sources — dépend de FINAL-038 — preuve : métrique sans gonflement.
- FINAL-125 — Ajouter quotas de fréquence par source — dépend de FINAL-030 — preuve : simulation 429.
- FINAL-126 — Ajouter reprise après timeout — dépend de FINAL-125 — preuve : backoff déterministe.
- FINAL-127 — Ajouter cache de connecteur — dépend de FINAL-125 — preuve : TTL et invalidation.
- FINAL-128 — Ajouter détection d'offre expirée — dépend de FINAL-024 — preuve : statut et raison.
- FINAL-129 — Ajouter détection d'offre retirée — dépend de FINAL-029 — preuve : source inaccessible séparée.
- FINAL-130 — Ajouter rapport de couverture quotidien — dépend de FINAL-124 — preuve : sortie locale exportable.
- FINAL-131 — Ajouter import d'offres en allemand — dépend de FINAL-023 — preuve : dates et langues.
- FINAL-132 — Ajouter import d'offres en espagnol — dépend de FINAL-023 — preuve : dates et langues.
- FINAL-133 — Ajouter import d'offres en italien — dépend de FINAL-023 — preuve : dates et langues.
- FINAL-134 — Ajouter classification contrat stage/alternance — dépend de FINAL-023 — preuve : inconnus conservés.
- FINAL-135 — Ajouter détection rémunération — dépend de FINAL-028 — preuve : devise et intervalle séparés.
- FINAL-136 — Ajouter détection télétravail/présentiel — dépend de FINAL-028 — preuve : localisation non inventée.
- FINAL-137 — Ajouter détection durée minimale — dépend de FINAL-024 — preuve : six mois distinct de date de fin.
- FINAL-138 — Ajouter alertes contradictions offre — dépend de FINAL-027 — preuve : blocker lisible.
- FINAL-139 — Ajouter classement par utilité utilisateur — dépend de FINAL-055 — preuve : critères modifiables.
- FINAL-140 — Recette 500 offres synthétiques multilingues — dépend de FINAL-139 — preuve : déduplication et métriques.

## Lot H — apprentissage, devoirs et documents (FINAL-141 à FINAL-160)

- FINAL-141 — Définir espace de cours local — dépend de FINAL-006 — preuve : séparation par matière.
- FINAL-142 — Importer PDF de cours — dépend de FINAL-062 — preuve : pagination et citations.
- FINAL-143 — Importer DOCX de cours — dépend de FINAL-063 — preuve : titres et tableaux.
- FINAL-144 — Importer XLSX de devoir — dépend de FINAL-061 — preuve : feuilles, formules et styles détectés.
- FINAL-145 — Construire index de recherche local — dépend de FINAL-142 — preuve : résultat avec page/source.
- FINAL-146 — Ajouter mode question-réponse cité — dépend de FINAL-145 — preuve : réponse refusée si aucune preuve.
- FINAL-147 — Ajouter générateur d'exercices — dépend de FINAL-146 — preuve : niveau et correction séparés.
- FINAL-148 — Ajouter correction guidée pas à pas — dépend de FINAL-147 — preuve : indice sans réponse forcée.
- FINAL-149 — Ajouter vérification contre corrigé — dépend de FINAL-148 — preuve : écarts expliqués.
- FINAL-150 — Ajouter suivi des notions — dépend de FINAL-149 — preuve : progression persistante.
- FINAL-151 — Ajouter révisions espacées — dépend de FINAL-150 — preuve : calendrier local.
- FINAL-152 — Ajouter plan d'étude quotidien — dépend de FINAL-151 — preuve : minutes et priorités.
- FINAL-153 — Ajouter calcul financier avec unités — dépend de FINAL-146 — preuve : signes et conventions affichés.
- FINAL-154 — Ajouter validation formules Excel — dépend de FINAL-144 — preuve : erreurs listées sans écraser l'original.
- FINAL-155 — Ajouter export corrigé annoté — dépend de FINAL-149 — preuve : copie dérivée, original intact.
- FINAL-156 — Ajouter citation de cellule Excel — dépend de FINAL-154 — preuve : feuille/cellule reproduite.
- FINAL-157 — Ajouter détection données manquantes — dépend de FINAL-144 — preuve : inconnue distincte de zéro.
- FINAL-158 — Ajouter mode examen sans solution immédiate — dépend de FINAL-147 — preuve : correction différée.
- FINAL-159 — Ajouter synthèse de révision — dépend de FINAL-150 — preuve : sources et lacunes.
- FINAL-160 — Recette devoir PDF+Word+Excel synthétique — dépend de FINAL-155 — preuve : trois formats vérifiés.

## Lot I — intelligence centrale, mémoire et fiabilité (FINAL-161 à FINAL-180)

- FINAL-161 — Définir contrat de contexte minimal — dépend de FINAL-041 — preuve : seuls faits approuvés transmis.
- FINAL-162 — Ajouter sélection d'outil explicable — dépend de FINAL-161 — preuve : outil et raison affichés.
- FINAL-163 — Ajouter plan multi-étapes visible — dépend de FINAL-162 — preuve : étapes, statut, reprise.
- FINAL-164 — Ajouter consentement par action sensible — dépend de FINAL-163 — preuve : consentement non contournable.
- FINAL-165 — Ajouter validation de sortie structurée — dépend de FINAL-162 — preuve : schema et erreurs.
- FINAL-166 — Ajouter récupération après erreur modèle — dépend de FINAL-165 — preuve : fallback local ou blocage clair.
- FINAL-167 — Interdire fallback payant implicite — dépend de FINAL-166 — preuve : test de fournisseur interdit.
- FINAL-168 — Ajouter budget et compteur de tokens — dépend de FINAL-166 — preuve : seuil et arrêt.
- FINAL-169 — Ajouter mode fournisseur indisponible — dépend de FINAL-166 — preuve : expérience lisible.
- FINAL-170 — Ajouter mémoire avec oubli sélectif — dépend de FINAL-161 — preuve : suppression vérifiable.
- FINAL-171 — Ajouter recherche dans la mémoire — dépend de FINAL-170 — preuve : provenance de chaque résultat.
- FINAL-172 — Ajouter chiffrement local des secrets applicatifs — dépend de FINAL-170 — preuve : secrets absents des logs.
- FINAL-173 — Ajouter redaction automatique des logs — dépend de FINAL-172 — preuve : clés, emails et tokens masqués.
- FINAL-174 — Ajouter audit des permissions — dépend de FINAL-164 — preuve : matrice lecture/écriture/partage.
- FINAL-175 — Ajouter tests adversariaux de prompt injection — dépend de FINAL-165 — preuve : outil sensible bloqué.
- FINAL-176 — Ajouter tests de contradiction — dépend de FINAL-165 — preuve : réponse prudente.
- FINAL-177 — Ajouter reprise après interruption — dépend de FINAL-163 — preuve : job relancé sans doublon.
- FINAL-178 — Ajouter idempotence des tâches — dépend de FINAL-177 — preuve : même entrée, même résultat.
- FINAL-179 — Ajouter journal de provenance inter-modules — dépend de FINAL-161 — preuve : identifiant de trace.
- FINAL-180 — Recette adversariale centrale — dépend de FINAL-179 — preuve : rapport synthétique reproductible.

## Lot J — qualité, performance, déploiement et preuve finale (FINAL-181 à FINAL-200)

- FINAL-181 — Définir budgets de latence par route — dépend de FINAL-020 — preuve : tableau mesuré.
- FINAL-182 — Mesurer pipeline sur 150 offres — dépend de FINAL-181 — preuve : p50/p95 et code HTTP.
- FINAL-183 — Mesurer pipeline sur 1 000 offres — dépend de FINAL-181 — preuve : p50/p95 et mémoire.
- FINAL-184 — Optimiser requêtes SQLite du Career — dépend de FINAL-182 — preuve : plan SQL avant/après.
- FINAL-185 — Ajouter index validés par mesure — dépend de FINAL-184 — preuve : migration réversible.
- FINAL-186 — Tester concurrence de lecture — dépend de FINAL-184 — preuve : aucune corruption.
- FINAL-187 — Tester conflit d'écriture shortlist — dépend de FINAL-101 — preuve : résolution déterministe.
- FINAL-188 — Tester migration ancienne base — dépend de FINAL-185 — preuve : backup et rollback.
- FINAL-189 — Ajouter healthcheck local — dépend de FINAL-020 — preuve : dépendances et statut.
- FINAL-190 — Ajouter logs structurés corrélables — dépend de FINAL-179 — preuve : request-id sans donnée sensible.
- FINAL-191 — Ajouter rapport de recette automatisé — dépend de FINAL-189 — preuve : succès/échecs/blocages séparés.
- FINAL-192 — Ajouter test de démarrage à froid — dépend de FINAL-189 — preuve : port et routes principales.
- FINAL-193 — Ajouter test de persistance après redémarrage — dépend de FINAL-188 — preuve : shortlist et brouillons retrouvés.
- FINAL-194 — Ajouter test de sauvegarde/restauration locale — dépend de FINAL-188 — preuve : hash identique.
- FINAL-195 — Ajouter vérification des dépendances vulnérables — dépend de FINAL-189 — preuve : rapport daté.
- FINAL-196 — Ajouter test de licence des dépendances — dépend de FINAL-195 — preuve : liste approuvée.
- FINAL-197 — Construire une image de démonstration synthétique — dépend de FINAL-191 — preuve : lancement documenté.
- FINAL-198 — Exécuter recette navigateur Career complète — dépend de FINAL-119 — preuve : screenshots et logs.
- FINAL-199 — Préparer diff exact de convergence vers `main` — dépend de FINAL-191 — preuve : liste de commits et rollback.
- FINAL-200 — Gate finale « outil montrable avec fierté » — dépend de FINAL-198 — preuve : checklist signée, risques résiduels et décision merge.

## Ordre recommandé

1. `FINAL-001` à `FINAL-020` pour stabiliser le shell et la navigation.
2. `FINAL-021` à `FINAL-060` pour rendre Career fiable et réellement exploitable.
3. `FINAL-061` à `FINAL-120` pour CV, lettres et candidature humaine en trois interactions.
4. `FINAL-141` à `FINAL-160` pour l'apprentissage et les devoirs.
5. `FINAL-161` à `FINAL-180` pour l'intelligence centrale et les garde-fous.
6. `FINAL-181` à `FINAL-200` pour la performance, la recette et la préparation de `main`.

Les missions peuvent être parallélisées uniquement quand leurs fichiers et données
de test sont disjoints. Les lots de migration, de sécurité, de navigation et de
validation finale restent séquentiels.
