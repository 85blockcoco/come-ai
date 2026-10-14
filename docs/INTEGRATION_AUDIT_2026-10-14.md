# Audit vérifié d’intégration — 14 octobre 2026

## Protection avant modification

Main réel initial : `ed8a6b9962b9c9b24088ea2597aa910c6fec80bb`.
19 worktrees inspectés ; checkpoint privé `.devkit/integration/20261014T082203Z`
(bundle de toutes les références, inventaire, 81 fichiers sources/documents
non commités autorisés). Secrets, bases et gros fichiers non lus/non copiés,
laissés intacts. Aucun reset, clean, rebase ou suppression.

Six rapports/script non suivis de main conservés. `checklist_codex.sh` inspecté
mais non exécuté aveuglément : mémoire legacy cible, routes comptées par chemin
sans méthode, assertions historiques. Les instructions handoff de rebase
Nemotron et de suppression de branches ne sont pas suivies : contradictoires
avec le choix B et la préservation des worktrees dirty. Gates retenus : tests
ciblés, diagnostic DevKit isolé, empreinte, vrai navigateur et données fictives.

## Livraisons vérifiées à l’ouverture

| Lot | Révision/état Git constaté | Décision |
| --- | --- | --- |
| Noyau main, MiMo, Step5, evals | ed8a6b9, suivis propres ; 6 documents non suivis | Déjà intégrés. Evals simulées ne prouvent pas qualité réelle. |
| PCE | feature/personal-context-engine, 8864b47 + QA dirty | Source personnelle unique, copie profile-core ; original intact. |
| Profil V5 prototype | feature/profile-integration-v1, ed8a6b9 + non commité | Façade à adapter, pas merge des routes/store contournant PCE. |
| Nemotron | feature/nemotron-memory, 1b570dd + 2 fichiers dirty | Référence conservée ; aucune migration/base réelle inspectée. |
| Catalogue Career | fc041f067ff00fffe8ab8ecf69c672d1b2155cc4, propre | Isolé, 4160 lignes ≠ stages. 23 A incluent EURES sans URL et alternance. |
| Sources overnight | f70d61b5c7a5abecefc545691649e866d581d4e1, propre | Requalification individuelle, pas import global des 32 flux. |
| Study Coach | b89a3095ea1a0a40b25cadc19f419debf4d3dac2, propre | 82 tests rejoués ; pas UI V5/PDF réel démontré à l’ouverture. |
| Career source | a146769 + 6 fichiers dirty | Préservés ; moteur Explorer développé dans copie distincte. |
| Control Center / Noveria | 7def985 + fichiers nouveaux | Conservés, non intégrés. Noveria 16 succès/8 échecs antérieurs, pas validation complète. |

## Recommandations confrontées au code

| Gravité | Preuve constatée | Action/gate |
| --- | --- | --- |
| P0 confidentialité | Diagnostic PCE exposait snapshots privés before/after ; prototype adapter contournait edit/forget | Metadata-only, façade méthodes publiques + QA oubli ; tests synthétiques. |
| P0 endpoints | Prototype profil sans Origin/body limit, export pack/1 non conforme | Gardes lecture/écriture, import pending individuel, export/1 distinct du pack. |
| P0 métier Career | Graduate/contrat permanent ou ingénierie via boilerplate financier admis ; dates connues écrasables | Classification indépendante du score, métadonnées contrat, préservation, régressions avant fusion. |
| P1 exactitude | Ville/région/pays devenait pays inconnu et échappait au filtre | Pays uniquement reconnu depuis texte explicite ; multi-villes conservées. |
| P1 Study | IDs globaux mélangent cours ; réponse future saute question ; writes non atomiques ; schedules orphelins | Isolation IDs, ordre et transaction unique, suppression limitée au cours. |
| P1 documents | Study cherchait UUID en texte et catégorie cours vs general V5 ; test PDF avec faux store | Résolution opaque et PDF synthétique réellement importé/indexé/exercé. |
| P1 gouvernance | Rebase/suppression proposés par handoffs malgré worktrees dirty | Refus ; inventaire et sauvegarde, intégrations sélectives. |
| P2 couverture | Sources obsolètes, Wise non attesté, géographie fausse, doublons logiques/classification lexicalement fragile | Aucun merge catalogue massif ; sources officielles individuellement attestées. |

PCE est l’unique vérité personnelle. FTS documentaire conserve un rôle distinct.
Aucune table legacy réelle lue, supprimée ou migrée ; accord utilisateur requis
avant migration sensible. Architecture/mapping : PERSONAL_MEMORY_ARCHITECTURE.md.
Pas de nouveau smoke test cloud, ni dépense, ni secret lu, ni profil réel importé.
Auto-amélioration maintenue expérimentale : génération/tests isolés, pas
auto-déploiement critique. Performance des fournisseurs non requalifiée ici.
