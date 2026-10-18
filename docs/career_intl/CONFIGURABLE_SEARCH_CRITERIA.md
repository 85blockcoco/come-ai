# Critères configurables de recherche Career

Cette livraison remplace le mois fixe par des critères persistés dans le brief Career :

- Contrats sélectionnés par défaut : stage, CDD, CDI et VIE.
- Débuts sélectionnés par défaut : janvier, février et mars. « Premier trimestre » agit comme raccourci de sélection, sans critère distinct enregistré.
- Durée minimale de stage par défaut : six mois.
- Un stage dont la date de début ou la durée manque reste « à vérifier ». Une fourchette qui chevauche le minimum reste également à vérifier.
- Les dates de début passées, les dates limites passées, les annonces clôturées, les contrats non sélectionnés et les offres seniors sont exclues.
- Les contradictions (par exemple un titre de stage avec un CDI explicite) restent « à vérifier » ; elles ne sont pas transformées en offre conforme.
- Les contrats CDD, CDI et VIE sélectionnés n'héritent pas du seuil de durée propre aux stages. Une date de début et une source officielle vérifiée restent nécessaires pour le statut « conforme ».

Les critères sont validés, sauvegardés par `CareerService.update_stage_search`, renvoyés par l'API existante et réutilisés par le classement et les connecteurs. Les faits d'offre manquants ne sont jamais inventés. Les règles de provenance et les garde-fous de confidentialité n'ont pas été modifiés.

Le champ existant `study_level` désigne toujours le niveau réel du candidat utilisé par le matching. La préférence distincte `education_preference` décrit uniquement le niveau demandé par l'offre : Bachelor et Master 1 sont prioritaires, les offres Master 2 restent à considérer, et les niveaux absents ou ambigus restent à vérifier. Cette préférence est un départage souple entre offres de pertinence équivalente : elle ne filtre pas automatiquement une offre et ne déclare jamais le diplôme, l'admissibilité ou les notes du candidat.

L'analyse académique renvoie les passages exacts de l'annonce qui justifient son verdict. Un « Master » non précisé, une combinaison de diplômes ambiguë, une simple compétence comme « master Python » ou une mention de note/GPA ne deviennent pas une qualification personnelle.
