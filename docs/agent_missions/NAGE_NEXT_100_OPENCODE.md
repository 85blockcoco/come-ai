# Mission OpenCode — NAGE NEXT 100

Côme autorise la préparation et l’exécution de 100 missions utiles avec quatre
workers simultanés, sous les limites de coût et de fichiers ci-dessous.

## Priorités

1. Meilleures offres internationales en finance, BBA/Bac+4 prioritaire,
   janvier 2027 au plus tôt et six mois minimum; M2/MBA restent visibles.
2. Meilleur CV et meilleure lettre pour chaque offre, uniquement à partir de
   faits approuvés, avec relecture et export.
3. IA cohérente, fiable, pratique et améliorable par Dev Kit et Spec Kit.

## Coordination

Lis COORDINATION.md et messages/agent_note.md. Préserve les changements locaux.
Codex a livré le panneau Spec Kit sur `codex/nage-consolidation-20261030`.
Son checkout est :
`/Users/comedelavenne/Documents/Codex/2026-10-25/codex-op-ration-v3-stable-consolidation/candidate`.

Ne modifie jamais ce checkout ni `/Users/comedelavenne/NAGE-release`.
Réserve à Codex `devkit/**`, `desktop_static/**` et leurs tests jusqu’au handoff
explicite de ces fichiers. Une mission les nécessitant passe en attente de
coordination; prends la suivante. Aucune modification de main.

## Backlog de 100 missions

Prépare dix lots de dix missions concrètes :

A. Sources officielles internationales et fraîcheur.
B. Qualification : dates, durée, langues, contrats et diplôme.
C. Classement expliqué et shortlist pertinente.
D. Profil approuvé, preuves et import de CV.
E. Adaptation factuelle du CV et variantes métier.
F. Lettres de motivation ciblées et langues.
G. Dossier de candidature, exports et formulaires.
H. Entretiens, suivi et relances préparées.
I. Fiabilité de l’IA, mémoire utile et récupération après erreur.
J. Recettes utilisateur, accessibilité, performances et régressions.

Inspecte d’abord les travaux existants. Réutilise ce qui est livré et validé.
Ne fabrique pas 100 fonctionnalités artificielles : remplace les travaux déjà
couverts par des manques prouvés. Une branche livrée n’est pas nécessairement
intégrée ou utilisable. Pour chaque mission, documente le résultat utilisateur,
les fichiers autorisés, dépendances, critères d’acceptation et tests ciblés.

## Quatre workers simultanés

- Un worktree, une branche et une mission active par worker.
- Quatre périmètres de fichiers distincts, verrouillés par le coordinateur.
- Un fichier partagé n’a jamais deux écrivains.
- Les dépendances repartent de la dernière base validée de leur chaîne.
- Deux tentatives maximum par mission; en cas de blocage, conserver le rapport
  et poursuivre une mission indépendante.
- Pas de fusion massive et pas de suite complète pendant le travail parallèle.

## Quota et données

Vérifie les modèles disponibles et leur coût. Utilise uniquement un modèle
dont le coût courant est vérifié nul. Ne suppose pas le quota OpenCode Go
disponible. Aucun fallback payant, achat ou fournisseur facturable. Arrête les
relances répétées lorsqu’un fournisseur est épuisé.

Aucune candidature, aucun CV, email ou message envoyé automatiquement.
Aucune donnée personnelle dans le dépôt ou les fixtures. Ne lis ni clés API
ni fichiers .env. Aucune protection désactivée, aucun test supprimé ou affaibli,
aucun reset destructif, force-push, suppression de worktrees ou écrasement.

## Preuves et livraison

Chaque mission fournit branche, SHA complet, fichiers, commandes exécutées,
durée, nombres de tests réussis/échoués/ignorés et recette HTTP/navigateur
lorsque pertinente. Distingue les statuts : spécifiée, en cours, bloquée,
livrée sur branche, intégrée, vérifiée dans l’application. Une déclaration
done d’un worker ne justifie pas les deux derniers statuts.

Publie maintenant le backlog puis lance les quatre premières missions
indépendantes à plus forte valeur. Publie leurs identifiants et worktrees dans
ta note. Après chaque lot validé, pousse les branches et transmets à Codex les
SHA, tests et conflits. La convergence finale sur main et la modification de
l’application Bureau restent coordonnées séparément.
